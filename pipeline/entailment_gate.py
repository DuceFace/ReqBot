#!/usr/bin/env python3
"""Step D.6: Production description-grounding entailment gate (WP-35.4).

Input:  requirements_enriched.jsonl (Step D.5) — or requirements_normalized.jsonl
        if Step D.5 was skipped/failed; whatever pipeline/run_pipeline.py's
        index_path currently points to when this step runs.
Output:
  - {doc_key}_requirements_gated.jsonl — same schema as the input. A
    requirement is NEVER dropped by this step. If its description fails
    either check below, only the description field is cleared (set to "");
    source_quote, domain_tags, requirement_type, and everything else pass
    through unchanged.
  - {doc_key}_description_gate_failures.jsonl — one record per rejected
    description: requirement_id, chunk_id, error (list — one or both of
    "description_not_grounded"/"description_fabricated_obligation"),
    support_prob (if the entailment check ran and contributed), the
    rejected description text, and the original record (raw), mirroring
    pipeline/parse_and_normalize.py's *_normalization_failures.jsonl
    durable-failure-reason pattern.

Wires together two independently-built, independently-validated checks:

- WP-35.2's calibrated MiniCheck entailment threshold (general fabricated
  content — description asserts facts source_quote doesn't support).
- WP-35.3's deterministic modality-fabrication check, defined in this module
  (MODAL_MARKERS / ACTION_VERB_FORMS / is_fabricated_obligation below —
  moved here from eval/modality_fabrication_check.py, which now imports
  from here instead, mirroring how eval/harvest_description_grounding_
  candidates.py already imports normalize_text from pipeline/
  parse_and_normalize.py: pipeline/ holds the canonical production logic,
  eval/ scripts reuse it for validation reporting).

Either check rejecting is enough to reject the description (OR, not AND):
they catch different fabrication shapes, and WP-35.3 exists specifically
because WP-35.2's entailment score has no signal for a factual/definitional
quote reframed as an imperative it never states (docs/PHASE35_REQUIREMENTS.md
§1, Gap 2) — requiring both checks to agree would silently reopen exactly
that gap. See docs/PHASE35_REQUIREMENTS.md's WP-35.4 section for the full
"reject" semantics decision (clear description, never drop the requirement)
and why this is a separate step from Step D.5 rather than folded into it.

MiniCheck is an optional dependency (pyproject.toml's `grounding-check`
extra — its GitHub install pulls torch/transformers/datasets/openai/pyarrow,
a heavy footprint not needed for basic ingestion). If it isn't installed,
the entailment check is skipped (logged, not fatal — same "pipeline
continues" precedent Step D.5 already established for its own LLM call) but
the modality-fabrication check still runs — it has no extra dependencies
beyond what the base install already includes, so there's no reason to lose
that coverage just because the heavier check is unavailable.

A description that is a byte-identical copy of its own source_quote is
short-circuited past MiniCheck entirely (_is_exact_match, WP-36.1) — see
that function's docstring for why (WP-35.5 found MiniCheck scores this
shape inconsistently, sometimes below threshold, despite zero possible
fabrication in a verbatim copy).
"""

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.artifact_resolver import doc_key_from_requirements_path  # noqa: E402
from pipeline.parse_and_normalize import normalize_text  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WP-35.3: deterministic modality/obligation-fabrication check.
# Moved here from eval/modality_fabrication_check.py (WP-35.4) so it's real
# production logic, not just an eval script. See that module's own (thinner,
# now import-only) docstring, and docs/PHASE35_REQUIREMENTS.md's WP-35.3
# Findings for the full fixture-by-fixture design rationale.
# ---------------------------------------------------------------------------

# Interchangeable modality markers — express obligation without naming the
# action. Substituting among these restates existing modality, not new
# content (WP-35.3 Scope: "will"/"must"/"shall"/"is required to" function
# interchangeably in DoD/NIST regulatory writing).
MODAL_MARKERS = [
    "shall", "must", "will", "are to", "is to", "is responsible for",
    "required to", "required", "requires", "require",
]

# Verbs that name a specific act. Each base form is distinct — not
# interchangeable with each other or with a MODAL_MARKER. Reuses
# profiles/cybersecurity.json's own obligation_verbs list (minus the ones
# that are really modality markers, not action verbs) rather than inventing
# a separate vocabulary, per WP-35.3 Scope.
#
# Each base form maps to its attested surface inflections (third-person
# singular, past/participle, gerund) — source quotes routinely state a
# governing action in third-person-singular present tense ("The ISSO
# maintains access logs"), and a faithful description that normalizes this
# to imperative form ("Maintain access logs") must not be treated as
# introducing a new action just because the exact surface string differs
# (Gemini review, PR #168). A small closed set per verb, not a general
# morphological engine — matches this WP's own "narrow, targeted check"
# Non-Goal; these five verbs' English inflections are fixed and few.
ACTION_VERB_FORMS = {
    "implement": ["implement", "implements", "implemented", "implementing"],
    "establish": ["establish", "establishes", "established", "establishing"],
    "maintain": ["maintain", "maintains", "maintained", "maintaining"],
    "enforce": ["enforce", "enforces", "enforced", "enforcing"],
    "ensure": ["ensure", "ensures", "ensured", "ensuring"],
}
ACTION_VERBS = list(ACTION_VERB_FORMS)

# Nouns that take an obligation-bearing infinitive complement ("a
# responsibility/duty/obligation/requirement to VERB") — the "to VERB" here
# is the obligation itself, not a purpose/goal clause explaining why
# something else happens (Codex review, PR #168). A short closed list, not
# a general parse — matches this WP's own "narrow, targeted check" Non-Goal.
OBLIGATION_COMPLEMENT_NOUNS = ["responsibility", "duty", "obligation", "requirement"]


def _is_infinitive_purpose_clause(text: str, verb_start: int) -> bool:
    """True if the verb at verb_start is a non-governing bare infinitive
    ("...to ensure X", explaining why, not commanding who) rather than a
    governing infinitive complement.

    Two constructions look identical (a literal "to VERB") but are not: a
    genuine purpose clause vs. an infinitive governed by a modal marker that
    itself ends in "to" ("required to VERB", "are to VERB" — Gemini review,
    PR #168) or by an obligation-bearing noun (OBLIGATION_COMPLEMENT_NOUNS,
    "a responsibility to VERB" — Codex review, PR #168). In both exception
    cases the "to" is part of what asserts the obligation, not a separate
    infinitive-of-purpose construction, so the verb is governing.
    """
    prefix = text[:verb_start]
    if not re.search(r"\bto\s+$", prefix):
        return False
    for marker in MODAL_MARKERS:
        if marker.endswith("to") and re.search(r"\b" + re.escape(marker) + r"\s+$", prefix):
            return False
    for noun in OBLIGATION_COMPLEMENT_NOUNS:
        if re.search(r"\b" + re.escape(noun) + r"\s+to\s+$", prefix):
            return False
    return True


def _governing_action_verbs_in(text: str) -> set[str]:
    """ACTION_VERBS base forms present in text as a governing (non-infinitive)
    verb, matched via any attested surface inflection (see ACTION_VERB_FORMS).
    Results are keyed by base form regardless of which inflection matched, so
    "The ISSO maintains X" (quote) and "Maintain X" (description) compare
    equal — a tense/person normalization, not a new action."""
    normalized = normalize_text(text)
    found = set()
    for base, forms in ACTION_VERB_FORMS.items():
        for form in forms:
            matched = False
            for m in re.finditer(r"\b" + re.escape(form) + r"\b", normalized):
                if _is_infinitive_purpose_clause(normalized, m.start()):
                    continue
                found.add(base)
                matched = True
                break
            if matched:
                break
    return found


def _has_modal_marker(text: str) -> bool:
    normalized = normalize_text(text)
    return any(re.search(r"\b" + re.escape(m) + r"\b", normalized) for m in MODAL_MARKERS)


def _has_governing_obligation(text: str) -> bool:
    """True if text asserts some obligation of its own — a MODAL_MARKER, or
    a governing (non-purpose-clause) ACTION_VERB."""
    return _has_modal_marker(text) or bool(_governing_action_verbs_in(text))


def is_fabricated_obligation(source_quote: str, description: str) -> bool:
    """True if description asserts an obligation source_quote never states.

    Fires when source_quote asserts no obligation of its own at all (no
    MODAL_MARKER, no governing ACTION_VERB) but description does — via
    either mechanism. A quote that already asserts *some* obligation permits
    any restatement/paraphrase of it; there's nothing further to check once
    the quote already carries an obligation.

    A missing/None source_quote or description can't assert or fabricate
    anything — pass through as not-fabricated rather than crash in
    normalize_text().
    """
    if not source_quote or not description:
        return False
    if _has_governing_obligation(source_quote):
        return False
    return _has_governing_obligation(description)


# ---------------------------------------------------------------------------
# WP-35.2: calibrated MiniCheck entailment threshold.
# ---------------------------------------------------------------------------

# support_prob threshold below which a description is rejected as not
# entailed by its source_quote. Chosen by sweeping thresholds against
# eval/gold_description_grounding.jsonl's independent (wp_35_1_harvest)
# partition: 87.5% catch rate (7/8), 5.4% false-positive rate (5/92) — the
# highest catch rate among thresholds with FP rate <= 10%. See
# eval/spike_results/wp_35_2/report.md for the full sweep table and
# per-subtype breakdown.
#
# PROVISIONAL, not a confident production calibration (carried forward
# explicitly, not silently dropped): only 8 independent fabricated examples
# existed to sweep against, and the narrowest catch at this threshold has a
# margin of just 0.0079 (eval/spike_results/wp_35_2/report.md's
# margin_analysis). Revisit if/when a larger independent fabricated-
# description dataset becomes available.
DESCRIPTION_ENTAILMENT_THRESHOLD = 0.85

# The exact MiniCheck checkpoint the threshold above was calibrated against.
# Not exposed as a CLI/config option — swapping models would silently
# invalidate this threshold (same reasoning QUOTE_GROUNDING_THRESHOLD in
# parse_and_normalize.py already applies to its own fixed threshold).
MINICHECK_MODEL = "flan-t5-large"


def _load_minicheck_scorer():
    """Load the MiniCheck scorer, or return None if minicheck isn't installed
    (pyproject.toml's `grounding-check` extra — see module docstring)."""
    try:
        from minicheck.minicheck import MiniCheck
    except ImportError:
        return None
    t0 = time.time()
    scorer = MiniCheck(model_name=MINICHECK_MODEL)
    log.info("Loaded MiniCheck (%s) in %.1fs", MINICHECK_MODEL, time.time() - t0)
    return scorer


def _score_entailment(scorer, pairs: list[tuple[str, str]]) -> list[float]:
    """Score a batch of (source_quote, description) pairs. Returns support_prob
    per pair (0.0-1.0), same order as pairs. Empty input returns []  without
    calling the scorer (MiniCheck's own batching has no defined behavior for
    an empty batch and there's nothing useful to score anyway)."""
    if not pairs:
        return []
    docs = [p[0] for p in pairs]
    claims = [p[1] for p in pairs]
    _pred_label, raw_prob, _, _ = scorer.score(docs=docs, claims=claims)
    return [round(float(p), 4) for p in raw_prob]


# ---------------------------------------------------------------------------
# WP-36.1: exact-match short-circuit ahead of MiniCheck.
#
# WP-35.5's live integration run found MiniCheck scoring a description that
# is a byte-identical copy of its own source_quote inconsistently -- support_prob
# as low as 0.6782 against the 0.85 threshold, despite a verbatim copy being
# unable to introduce fabricated content by definition. Checked against
# eval/gold_description_grounding.jsonl: 77 of 92 wp_35_1_harvest faithful
# records (84%) are this exact shape, and 4 of WP-35.2's original 5 measured
# false positives are this pattern (docs/PHASE36_REQUIREMENTS.md Sec 1). An
# exact match is excluded from the batch sent to MiniCheck entirely (real
# compute saved, not just a discarded score -- same pattern as the existing
# empty-description exclusion below). is_fabricated_obligation() already
# returns False for two identical strings on its own (confirmed directly,
# not assumed), so the modality check needs no matching short-circuit.
# ---------------------------------------------------------------------------

def _is_exact_match(source_quote: str, description: str) -> bool:
    """True if description is a byte-identical copy of source_quote after
    normalize_text() (whitespace collapse + lowercasing) -- the same
    normalization every other check in this file already relies on.

    Literal equality only, not fuzzy/near-match: checked directly against
    eval/gold_description_grounding.jsonl's near-miss records (a dropped
    leading list marker, a trailing period, a "will"/"must" swap) -- none of
    those are caught by this comparison, so they still reach MiniCheck as
    intended (docs/PHASE36_REQUIREMENTS.md's WP-36.1 Findings).

    A missing/None source_quote or description can't be an exact match of
    anything -- pass through as not-exact rather than crash in
    normalize_text(), mirroring is_fabricated_obligation()'s own guard.
    """
    if not source_quote or not description:
        return False
    return normalize_text(source_quote) == normalize_text(description)


# ---------------------------------------------------------------------------
# Step D.6 orchestration
# ---------------------------------------------------------------------------

def run(enriched_jsonl: str, output_dir: str) -> str:
    """Run the description-grounding gate over a Step D/D.5 output file.

    Args:
        enriched_jsonl: Path to requirements_enriched.jsonl (Step D.5) or
                         requirements_normalized.jsonl (Step D, if D.5 was
                         skipped/failed) — whichever the caller currently
                         considers authoritative.
        output_dir:      Directory to write the gated JSONL and failures
                         JSONL into.

    Returns:
        Path to the written {doc_key}_requirements_gated.jsonl (str).
    """
    in_path = Path(enriched_jsonl).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    doc_key = doc_key_from_requirements_path(in_path)
    gated_path = out_dir / f"{doc_key}_requirements_gated.jsonl"
    failures_path = out_dir / f"{doc_key}_description_gate_failures.jsonl"

    reqs: list[dict] = []
    with open(in_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                reqs.append(json.loads(line))
    log.info("Loaded %d requirements from %s", len(reqs), in_path)

    # Only records with a real description have anything to check — an
    # empty description ("" — the enrichment prompt's own "source text was
    # self-explanatory" sentinel, or a Step D.5 call that failed outright
    # and left the field as Step C set it) asserts nothing, so it can't
    # fabricate anything either.
    checkable = [(i, r) for i, r in enumerate(reqs) if (r.get("description") or "").strip()]

    # WP-36.1: an exact copy can't be fabricated by definition -- skip it
    # before MiniCheck ever sees it rather than trusting the model to score
    # it correctly (see module comment above _is_exact_match for why).
    scoreable = [
        (i, r) for i, r in checkable
        if not _is_exact_match(r.get("source_quote") or "", r["description"])
    ]

    support_probs: dict[int, float] = {}
    scorer = _load_minicheck_scorer()
    if scorer is None:
        log.warning(
            "minicheck not installed — entailment check skipped (install with: "
            "pip install -e '.[grounding-check]'). Modality-fabrication check "
            "still runs (no extra dependencies)."
        )
    else:
        # Scoring can fail for reasons that have nothing to do with the check
        # itself (missing NLTK resource, OOM, a transient model-load error) —
        # caught here, not left to propagate out of run(), so a scoring
        # failure degrades to "entailment skipped" the same way an
        # uninstalled minicheck does, rather than losing the deterministic
        # modality-fabrication check too (Codex review, PR #169: the caller
        # in run_pipeline.py catches any exception from run() by falling
        # back to the completely ungated file, which would silently discard
        # the free/dependency-free check along with the one that failed).
        try:
            pairs = [(r.get("source_quote") or "", r["description"]) for _, r in scoreable]
            scores = _score_entailment(scorer, pairs)
            support_probs = {idx: score for (idx, _), score in zip(scoreable, scores)}
        except Exception as e:
            log.warning(
                "MiniCheck scoring failed (%s) — entailment check skipped for this run. "
                "Modality-fabrication check still runs.", e,
            )

    failures: list[dict] = []
    rejected_count = 0
    for idx, req in checkable:
        errors = []
        support_prob = support_probs.get(idx)
        if support_prob is not None and support_prob < DESCRIPTION_ENTAILMENT_THRESHOLD:
            errors.append("description_not_grounded")
        if is_fabricated_obligation(req.get("source_quote") or "", req["description"]):
            errors.append("description_fabricated_obligation")

        if errors:
            rejected_count += 1
            failure_record = {
                "requirement_id": req.get("requirement_id", "UNKNOWN"),
                "chunk_id": req.get("chunk_id"),
                "error": errors,
                "rejected_description": req["description"],
                "raw": req,
            }
            if support_prob is not None:
                failure_record["support_prob"] = support_prob
            failures.append(failure_record)
            reqs[idx] = {**req, "description": ""}

    with open(gated_path, "w", encoding="utf-8") as f:
        for req in reqs:
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
    log.info(
        "Wrote %s (%d requirements, %d description(s) rejected)",
        gated_path, len(reqs), rejected_count,
    )

    with open(failures_path, "w", encoding="utf-8") as f:
        for failure in failures:
            f.write(json.dumps(failure, ensure_ascii=False) + "\n")
    if failures:
        log.info("Wrote %s (%d rejected description(s))", failures_path, len(failures))

    return str(gated_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Step D.6: description-grounding entailment gate"
    )
    parser.add_argument(
        "enriched_jsonl", type=str,
        help="Path to requirements_enriched.jsonl (Step D.5) or requirements_normalized.jsonl (Step D)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory (default: same directory as input)",
    )
    args = parser.parse_args()

    in_path = Path(args.enriched_jsonl).resolve()
    if not in_path.exists():
        log.error("Input file not found: %s", in_path)
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve() if args.output_dir else in_path.parent
    run(str(in_path), str(out_dir))


if __name__ == "__main__":
    main()
