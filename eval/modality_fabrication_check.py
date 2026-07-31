#!/usr/bin/env python3
"""
eval/modality_fabrication_check.py — WP-35.3 obligation/modality-fabrication check

Cheap, deterministic (no LLM) secondary check for the failure mode WP-34.4's
spike found (Codex review, PR #164) and the entailment score alone can't
catch: a description that is fully grounded in source_quote's *facts* while
still inventing an obligation/imperative the quote never actually asserts —
e.g. a glossary definition reframed as "Implement X to ensure Y...".

Deliberately NOT simple obligation-vocabulary presence/absence checking —
docs/PHASE35_REQUIREMENTS.md's WP-35.3 section verified against this repo's
own eval/entailment_spike.py fixtures that the naive version gets both
directions wrong:

- Under-catches if checked as "quote already contains *some* obligation
  word, so any obligation word in description is fine": afpd_definition_
  reframed_as_imperative's quote already contains "ensure" (a purpose
  clause, "...to ensure its availability...", not an actor being commanded),
  but "Implement" — a distinct verb naming a specific new action — is
  fabricated wholesale.
- Over-catches if checked as strict per-word set difference: dodi_nsa_
  approved_crypto is a real "will" -> "must" modal-verb substitution,
  confirmed faithful in WP-34.4; a literal per-word match false-positives
  on this and other legitimate near-synonym paraphrases.

Design (see docs/PHASE35_REQUIREMENTS.md WP-35.3 Findings for full rationale
and the fixture-by-fixture walkthrough that produced it):

- MODAL_MARKERS: words/phrases that express "this is obligatory" without
  naming the action itself (shall/must/will/are to/is responsible for/
  required(-to)). These are treated as one interchangeable class — DoD/NIST
  regulatory writing routinely paraphrases between them (WP-35.3 Scope) —
  so a description substituting one for another isn't new content.
- ACTION_VERBS: words that name a specific act to be performed (implement/
  establish/maintain/enforce/ensure). Each is distinct, not a synonym for
  the others. Introducing one that has no counterpart anywhere in the quote
  invents a *specific new action*, not just a modality restatement.
- "ensure" is ambiguous between an ACTION_VERB (a governing command: "must
  ensure X") and a purpose-clause connective ("...to ensure X", explaining
  *why* something happens rather than commanding it). An action verb
  immediately preceded by a bare infinitive "to " is treated as a purpose
  clause, not a governing obligation — this applies to any ACTION_VERB, not
  just "ensure", since the same infinitive construction has the same
  non-finite grammatical role regardless of which verb follows it.
- The actual check: a description "fabricates" an obligation if it
  introduces an ACTION_VERB (in a governing, non-purpose-clause sense) with
  no counterpart in the quote, AND the quote itself asserts no obligation of
  its own at all (no MODAL_MARKER, no governing ACTION_VERB). If the quote
  already asserts *some* obligation, substituting or adding an action-verb
  synonym is treated as a paraphrase of an already-obligatory sentence, not
  a new fabricated command — matching every real paraphrase fixture found
  (will->must, support->maintain alongside an existing "must", etc.).

Non-goals (docs/PHASE35_REQUIREMENTS.md WP-35.3): not a general grammar/mood
classifier. This is a narrow, targeted check for the specific pattern found,
not an attempt to parse arbitrary sentence structure.
"""

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.parse_and_normalize import normalize_text  # noqa: E402

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
# a separate vocabulary, per WP-35.3 Scope ("reusing the cybersecurity
# profile's own obligation_verbs list... rather than inventing a separate
# vocabulary").
#
# Each base form maps to its attested surface inflections (third-person
# singular, past/participle, gerund) — source quotes routinely state a
# governing action in third-person-singular present tense ("The ISSO
# maintains access logs"), and a faithful description that normalizes this
# to imperative form ("Maintain access logs") must not be treated as
# introducing a new action just because the exact surface string differs
# (Gemini review, PR #168: exact-match regex missed "maintains"/"enforces").
# A small closed set per verb, not a general morphological engine — matches
# this WP's own "narrow, targeted check" Non-Goal; these five verbs' English
# inflections are fixed and few, no stemming logic needed.
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
# something else happens (Codex review, PR #168: "Personnel have a
# responsibility to maintain records" -> "Maintain records" was wrongly
# treated as fabricated because "to maintain" was discarded as a purpose
# clause). A short closed list, not a general parse — matches this WP's own
# "narrow, targeted check" Non-Goal.
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
    any restatement/paraphrase of it (a new or substituted action verb, or a
    different modal marker); there's nothing further to check once the quote
    already carries an obligation, matching every real paraphrase fixture
    found (will->must, support->maintain alongside an existing "must", etc.).

    Originally checked only for a newly introduced ACTION_VERB — missed the
    case where a neutral, non-obligatory quote is reframed as a command
    purely via a new MODAL_MARKER with no action-verb change at all (e.g.
    "Encryption transforms data" -> "Encryption must transform data";
    Codex review, PR #168).

    A missing/None source_quote or description can't assert or fabricate
    anything — pass through as not-fabricated rather than crash in
    normalize_text() (Gemini review, PR #168).
    """
    if not source_quote or not description:
        return False
    if _has_governing_obligation(source_quote):
        return False
    return _has_governing_obligation(description)


def _load_gold(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="WP-35.3 modality-fabrication check validation")
    parser.add_argument(
        "--gold", default=str(_ROOT / "eval" / "gold_description_grounding.jsonl"),
        help="Path to WP-35.1's labeled dataset (default: eval/gold_description_grounding.jsonl)",
    )
    args = parser.parse_args()

    records = _load_gold(Path(args.gold))

    modality = [r for r in records if r["label"] == "fabricated_modality"]
    other_fabricated = [r for r in records if r["label"].startswith("fabricated_") and r["label"] != "fabricated_modality"]
    faithful = [r for r in records if r["label"] == "faithful"]

    def flagged(r: dict) -> bool:
        return is_fabricated_obligation(r["source_quote"], r["description"])

    modality_results = [(r, flagged(r)) for r in modality]
    other_fabricated_results = [(r, flagged(r)) for r in other_fabricated]
    faithful_results = [(r, flagged(r)) for r in faithful]

    caught = sum(1 for _, f in modality_results if f)
    fp_on_faithful = sum(1 for _, f in faithful_results if f)
    fp_on_other_fabricated = sum(1 for _, f in other_fabricated_results if f)

    lines = [
        "# WP-35.3 Modality-Fabrication Check — Validation Against WP-35.1's Dataset",
        "",
        "Generated by `eval/modality_fabrication_check.py`. See "
        "`docs/PHASE35_REQUIREMENTS.md`'s WP-35.3 section for the full design "
        "rationale (why naive vocabulary presence gets both directions wrong, "
        "and how MODAL_MARKERS/ACTION_VERBS/purpose-clause handling fix it).",
        "",
        f"**Fabricated-modality (should be CAUGHT):** {len(modality)} examples, "
        f"{caught} caught ({caught}/{len(modality)})",
        f"**Faithful (should NOT be flagged):** {len(faithful)} examples, "
        f"{fp_on_faithful} false positives ({fp_on_faithful}/{len(faithful)})",
        f"**Other fabricated subtypes (citation/fragment/other — not this "
        f"check's job, informational only):** {len(other_fabricated)} examples, "
        f"{fp_on_other_fabricated} incidentally flagged",
        "",
        "## Fabricated-modality detail",
        "",
    ]
    for r, f in modality_results:
        verdict = "caught" if f else "**MISSED**"
        lines.append(f"### {r['requirement_id']} ({r['source']}) — {verdict}")
        lines.append(f"- QUOTE: {r['source_quote']!r}")
        lines.append(f"- DESC: {r['description']!r}")
        lines.append("")

    lines.append("## False positives on faithful records")
    lines.append("")
    fps = [(r, f) for r, f in faithful_results if f]
    if not fps:
        lines.append("None.")
    else:
        for r, _ in fps:
            lines.append(f"### {r['requirement_id']} ({r['source']})")
            lines.append(f"- QUOTE: {r['source_quote']!r}")
            lines.append(f"- DESC: {r['description']!r}")
            lines.append(f"- NOTES: {r.get('notes', '')}")
            lines.append("")

    out_dir = _ROOT / "eval" / "spike_results" / "wp_35_3"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    results_json = {
        "modality": [dict(r, flagged=f) for r, f in modality_results],
        "faithful_false_positives": [dict(r, flagged=f) for r, f in fps],
        "other_fabricated": [dict(r, flagged=f) for r, f in other_fabricated_results],
    }
    (out_dir / "results.json").write_text(json.dumps(results_json, indent=2) + "\n", encoding="utf-8")

    print(f"Caught {caught}/{len(modality)} fabricated_modality; "
          f"{fp_on_faithful}/{len(faithful)} false positives on faithful. "
          f"Report: {out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
