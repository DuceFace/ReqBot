#!/usr/bin/env python3
"""Step D.5: Enrich normalized requirements with description, domain_tags, and requirement_type.

Input:  requirements_normalized.jsonl (from Step D)
Output: requirements_enriched.jsonl — same schema, with enrichment fields populated.

This step is optional and deferrable. It can be re-run with any model without
re-running the ingestion pipeline (Steps A-D). Enrichment is keyed by requirement_id
so re-runs are safe and incremental — already-enriched requirements are skipped.
"""

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

import requests

# Ensure repo root is on sys.path when run as a standalone script from pipeline/
# (matches core/ask.py's precedent) -- needed for the core.profiles import below.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.profiles import default_profile
from pipeline.parse_and_normalize import _is_dangling_clause

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Only used as a fallback default for process_batch()/process_single() when called
# directly without a profile (run(), the real Step D.5 entry point, always passes
# profile["domain_tags"]/["requirement_types"] explicitly instead -- WP-33.1).
# Derived from core.profiles rather than hardcoded so there's exactly one place
# that defines the cybersecurity vocabulary, not a second copy that can drift.
VALID_DOMAIN_TAGS = default_profile()["domain_tags"]
VALID_REQUIREMENT_TYPES = default_profile()["requirement_types"]

_VALID_TAGS_STR = ", ".join(VALID_DOMAIN_TAGS)
_VALID_TYPES_STR = ", ".join(VALID_REQUIREMENT_TYPES)

ENRICH_BATCH_PROMPT_TEMPLATE = """You are enriching cybersecurity compliance requirements with classification metadata.

For each requirement below, return metadata. Return ONLY a valid JSON array with exactly {n} objects \
(one per requirement, in the same order as listed).

Each object must have these keys:
- "description": One precise sentence summarizing what must be done. Preserve technical terms, control \
IDs, system names, and numerical thresholds exactly as they appear. Max 120 words. Use "" if the source \
text is self-explanatory.
- "domain_tags": Array of 1-3 tags from this list ONLY: {valid_tags}. Use single most relevant if unsure.
- "requirement_type": One of: {valid_types}

Return ONLY the JSON array. No markdown code fences. No text before or after the array.

Requirements:
{requirements}"""

ENRICH_SINGLE_PROMPT_TEMPLATE = """You are enriching a cybersecurity compliance requirement with classification metadata.

Requirement text (verbatim):
{source_quote}

Reference: {source_ref}

Return ONLY a valid JSON object with these keys:
- "description": One precise sentence summarizing what must be done. Preserve technical terms, control \
IDs, system names, and numerical thresholds exactly as they appear. Max 120 words. Use "" if the source \
text is self-explanatory.
- "domain_tags": Array of 1-3 tags from this list ONLY: {valid_tags}. Use single most relevant if unsure.
- "requirement_type": One of: {valid_types}

Return ONLY the JSON object. No markdown code fences. No other text."""


def call_ollama(
    prompt: str,
    model: str,
    base_url: str,
    timeout: int = 120,
    max_retries: int = 3,
) -> str:
    """Call the Ollama generate API with exponential backoff for transient errors."""
    url = f"{base_url}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 4096,
        },
    }

    attempt = 0
    while attempt <= max_retries:
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()["response"]
        except requests.RequestException as e:
            attempt += 1
            if attempt > max_retries:
                log.error("Ollama request failed after %d retries: %s", max_retries, e)
                raise
            backoff = 2 ** attempt
            log.warning(
                "Ollama request failed (%s) — retrying in %ds (attempt %d/%d)",
                e, backoff, attempt, max_retries,
            )
            time.sleep(backoff)


def _extract_json_array(raw: str) -> list | None:
    """Extract a JSON array from raw LLM response text."""
    text = raw.strip()
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Find outermost [ ... ] with string-aware bracket counting
    start = text.find("[")
    if start != -1:
        depth = 0
        in_string = False
        escape_next = False
        end = None
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is not None:
            try:
                result = json.loads(text[start:end + 1])
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

    return None


def _extract_json_object(raw: str) -> dict | None:
    """Extract a JSON object from raw LLM response text."""
    text = raw.strip()
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Find outermost { ... } with string-aware bracket counting
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape_next = False
        end = None
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is not None:
            try:
                result = json.loads(text[start:end + 1])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    return None


def _validate_enrichment(
    raw: dict,
    valid_domain_tags: list[str] | None = None,
    valid_requirement_types: list[str] | None = None,
) -> dict:
    """Validate and clean a single enrichment result dict.

    Always returns a dict with all three enrichment keys — invalid/missing
    values are normalized to empty string / empty list rather than raising.
    """
    if valid_domain_tags is None:
        from core.profiles import default_profile as _dp
        valid_domain_tags = _dp()["domain_tags"]
    if valid_requirement_types is None:
        from core.profiles import default_profile as _dp
        valid_requirement_types = _dp()["requirement_types"]
    description = str(raw.get("description", "")).strip()

    raw_tags = raw.get("domain_tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    domain_tags = [t.strip().lower() for t in raw_tags if isinstance(t, str)]
    domain_tags = [t for t in domain_tags if t in valid_domain_tags]

    req_type = str(raw.get("requirement_type", "")).strip().lower()
    if req_type not in valid_requirement_types:
        req_type = ""

    return {
        "description": description,
        "domain_tags": domain_tags,
        "requirement_type": req_type,
    }


def _build_batch_requirements_text(batch: list[dict]) -> str:
    """Format a batch of requirements for the enrichment prompt."""
    lines = []
    for i, req in enumerate(batch, 1):
        ref = req.get("source_ref", "") or ""
        quote = req.get("source_quote", "")
        ref_part = f"Ref: {ref} | " if ref else ""
        lines.append(f"[{i}] {ref_part}{json.dumps(quote)}")
    return "\n".join(lines)


def _enrich_batch(
    batch: list[dict],
    model: str,
    ollama_url: str,
    timeout: int,
    valid_tags_str: str = _VALID_TAGS_STR,
    valid_types_str: str = _VALID_TYPES_STR,
    valid_domain_tags: list[str] = VALID_DOMAIN_TAGS,
    valid_requirement_types: list[str] = VALID_REQUIREMENT_TYPES,
) -> list[dict] | None:
    """Enrich a batch of requirements via a single LLM call.

    Returns a list of validated enrichment dicts (same length as batch),
    or None if the LLM response could not be parsed or had wrong count.
    Falls back to None so the caller can try individual calls.
    """
    prompt = ENRICH_BATCH_PROMPT_TEMPLATE.format(
        n=len(batch),
        valid_tags=valid_tags_str,
        valid_types=valid_types_str,
        requirements=_build_batch_requirements_text(batch),
    )

    try:
        raw = call_ollama(prompt, model, ollama_url, timeout)
    except requests.RequestException as e:
        log.warning("Batch LLM call failed: %s", e)
        return None

    parsed = _extract_json_array(raw)
    if parsed is None:
        log.debug("Batch response: failed to parse JSON array (%d chars)", len(raw))
        return None

    if len(parsed) != len(batch):
        log.debug(
            "Batch response: expected %d objects, got %d — falling back to individual calls",
            len(batch), len(parsed),
        )
        return None

    return [
        _validate_enrichment(item, valid_domain_tags, valid_requirement_types)
        if isinstance(item, dict)
        else _validate_enrichment({}, valid_domain_tags, valid_requirement_types)
        for item in parsed
    ]


def _enrich_single(
    req: dict,
    model: str,
    ollama_url: str,
    timeout: int,
    valid_tags_str: str = _VALID_TAGS_STR,
    valid_types_str: str = _VALID_TYPES_STR,
    valid_domain_tags: list[str] = VALID_DOMAIN_TAGS,
    valid_requirement_types: list[str] = VALID_REQUIREMENT_TYPES,
) -> dict | None:
    """Enrich a single requirement via a dedicated LLM call.

    Returns a validated enrichment dict, or None on failure.
    """
    prompt = ENRICH_SINGLE_PROMPT_TEMPLATE.format(
        source_quote=req.get("source_quote", ""),
        source_ref=req.get("source_ref", "") or "unknown",
        valid_tags=valid_tags_str,
        valid_types=valid_types_str,
    )

    try:
        raw = call_ollama(prompt, model, ollama_url, timeout)
    except requests.RequestException as e:
        log.warning("Single LLM call failed for %s: %s", req.get("requirement_id"), e)
        return None

    parsed = _extract_json_object(raw)
    if parsed is None:
        log.debug("Single response: failed to parse JSON object for %s", req.get("requirement_id"))
        return None

    return _validate_enrichment(parsed, valid_domain_tags, valid_requirement_types)


# WP-39.2: parent-stem reconstruction. Deterministic, no LLM/network calls -- kept as a
# fully separate code path from the enrichment functions above so it can run (and must
# run) independently of whether the LLM-calling enrichment below succeeds, fails, or is
# skipped entirely (see apply_parent_stem_reconstruction()'s docstring and its call site
# in run_pipeline.py).
#
# Candidacy and lookup signals below were calibrated directly against the 18 known
# FRAGMENT examples from eval/audit_wp39_1/ (docs/PHASE39_REQUIREMENTS.md's WP-39.1
# Findings), not assumed from the WP-39.2 scope doc's text alone -- implementation-time
# calibration found three real gaps beyond what PR #184's review already caught:
#   1. The scope doc's step-1 signal ("preceding same-chunk record contains a colon")
#      misses 2 of the 10 cheap wins (REQ-c62e41aaf181, REQ-9700722b04cd) -- both
#      dangling_clause fragments whose real antecedent record has no colon at all (one
#      is an unfinished clause with no terminal punctuation; the other is a case where
#      the fragment's own text is already a verbatim substring of the preceding record).
#      Both are handled by _extract_stem_from_record_text()'s two conditions below.
#   2. A blind "fall back to parent_header_text whenever steps 1-2 find nothing" (the
#      scope doc's literal step 3) also fires for the 3 STEM_NEVER_EXTRACTED examples,
#      which must get no parent_stem at all -- confirmed one of them
#      (REQ-4aeeff50f15b) has a parent_header_text that doesn't even match its own
#      chunk's actual section (an upstream ancestry-tracking mismatch, not something
#      fixable here). Gated instead on _is_dangling_clause() -- the existing, narrowly
#      calibrated WP-38.2 predicate that (per its own docstring) uniquely flags
#      REQ-1b1071c8d317 among all 18 examples and zero false positives against 284 real
#      corpus records.
#   3. A naive cross-chunk (step 2) lookup using only Step C's own extracted records
#      misses REQ-cf527f39c8d7: its true stem ("b. Oversee their respective Component's
#      PPSM program to:") was never extracted as a Step C record at all -- present only
#      in the previous chunk's raw_text. Fixed with a raw_text fallback -- but an
#      unconstrained version of that fallback produces a real false positive: DODI
#      5200.44 chunk 24 (unrelated to chunk 25's REQ-8105d9acb410) ends with its own,
#      completely different section's colon-terminated header ("...the Director,
#      DIA:"), which would get misattached without a gate. Gated on the target's own
#      chunk visibly opening mid-enumeration (starts directly with a list marker) --
#      true for both REQ-cf527f39c8d7's chunk and REQ-48f549669bb2's, false for
#      REQ-8105d9acb410's (which opens with a fresh, self-contained governing sentence)
#      -- but "opens with *some* marker" alone isn't enough either: DODI 5200.48
#      chunk 64 opens with "a." (its own fresh list, item one), which matches a bare
#      marker check just as well as "(7)" does. Narrowed further to exclude markers
#      that are themselves a sequence's first value ("1"/"a"/"i") -- a real list
#      continuing from the previous chunk never restarts at its own beginning.
#   4. The raw_text colon fallback (gap 3 above) has its own false positive: a list
#      item's own body text can contain a URL ("...registry at https://pnp.cert.
#      smil.mil/pnp...") whose "https:" colon isn't a list-intro colon at all, and
#      sits between the target and the real stem line in REQ-cf527f39c8d7's own
#      chunk 12. _find_first_real_colon() below skips "://" specifically so the scan
#      keeps walking back to the real stem.
_LIST_MARKER_RE = re.compile(r"^\(?([a-zA-Z0-9]{1,3})[.)]\s")
_FIRST_MARKER_VALUES = {"1", "a", "A", "i", "I"}
_LEADING_DASH_RE = re.compile(r"^-\s*")
_MAX_CANDIDATE_WORDS = 20


def _find_first_real_colon(text: str) -> int:
    """Index of the first ':' that isn't a URL scheme delimiter ("https://" etc.), or
    -1 if none -- see gap 4 in the module-level note above."""
    start = 0
    while True:
        idx = text.find(":", start)
        if idx == -1 or text[idx:idx + 3] != "://":
            return idx
        start = idx + 1


def _is_reconstruction_candidate(source_quote: str) -> bool:
    """Candidacy heuristic for parent-stem reconstruction -- deliberately NOT a reuse of
    Step D's rejection predicates (_is_orphaned_list_item()/_is_dangling_clause() were
    checked directly against all 10 cheap-win examples during WP-39.1 and only flag 1 of
    10; they're precision-first "safe to delete" checks, a different and narrower
    question than "short enough to plausibly benefit from more context"). False
    positives here just mean an unhelpful parent_stem gets attached to an
    already-complete quote -- cheap, unlike Step D's rejection risk -- so this is
    deliberately permissive.
    """
    stripped = (source_quote or "").strip()
    if not stripped:
        return False
    if _LIST_MARKER_RE.match(stripped):
        return True
    if len(stripped.split()) <= _MAX_CANDIDATE_WORDS:
        return True
    return _is_dangling_clause(stripped)


def _extract_stem_from_record_text(text: str) -> str | None:
    """Given a candidate antecedent record's (or raw_text line's) full text, return the
    usable stem substring, or None if it doesn't qualify as a stem at all.

    Two conditions, both calibrated against real examples (see the module-level note
    above): a colon anywhere -- not necessarily as the last character, since Step C
    sometimes merges a stem with its first sibling item into one combined quote
    (REQ-48f549669bb2) -- truncates to up-through-the-first-colon; no terminal sentence
    punctuation at all (a comma-joined clause Step C split from its own continuation,
    e.g. REQ-c62e41aaf181's antecedent) is used as-is.
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    colon_idx = _find_first_real_colon(stripped)
    if colon_idx != -1:
        return stripped[: colon_idx + 1].strip()
    if stripped[-1] not in ".!?":
        return stripped
    return None


def _stem_from_candidate(candidate_text: str, target: str) -> str | None:
    """Check one candidate antecedent record's text against both stem-validity
    conditions (see _extract_stem_from_record_text()'s docstring for the first; the
    second is REQ-9700722b04cd's case -- Step C sometimes extracts an overlapping/
    redundant pair where the fragment's text is already a verbatim tail of the
    preceding record, which itself ends in ordinary terminal punctuation so the first
    condition doesn't catch it -- the preceding record already carries full context)."""
    candidate = (candidate_text or "").strip()
    if not candidate:
        return None
    stem = _extract_stem_from_record_text(candidate)
    if stem:
        return stem
    if target and target in candidate:
        return candidate
    return None


def _find_same_chunk_stem(quote: str, chunk_id: int, step_c_by_chunk: dict[int, list[dict]]) -> str | None:
    """Reconstruction lookup step 1: walk backward through this chunk's Step C records,
    matched to the target by exact (stripped) quote text since Step D recomputes
    requirement_id and doesn't preserve Step C's own IDs, for the nearest preceding one
    that qualifies as a stem.

    Walks past sibling list items, not just the immediate predecessor: a deep item like
    "(4)" following "(1)-(3)" has 3 sibling items directly before it, each ending in
    ordinary terminal punctuation (not a colon) -- only checking the immediate
    predecessor missed 4 of the 10 cheap wins during calibration (REQ-626b98fef9aa,
    REQ-3097aa5d306c, REQ-c6d23854cd0b, and their cross-chunk analog, before this fix).
    """
    records = step_c_by_chunk.get(chunk_id) or []
    target = quote.strip()
    idx = next(
        (i for i, rec in enumerate(records) if (rec.get("source_quote") or "").strip() == target),
        None,
    )
    if idx is None:
        return None
    for rec in reversed(records[:idx]):
        stem = _stem_from_candidate(rec.get("source_quote"), target)
        if stem:
            return stem
    return None


def _find_cross_chunk_stem(
    chunk_id: int,
    step_c_by_chunk: dict[int, list[dict]],
    chunks_by_id: dict[int, dict],
) -> str | None:
    """Reconstruction lookup step 2: the immediately preceding chunk (same document,
    sequential chunk_id), for the confirmed CROSS_CHUNK_SPLIT cases.

    Only attempted when this chunk's own raw_text visibly opens mid-enumeration -- starts
    directly with a list marker that isn't itself a sequence's first value ("1"/"a"/"i")
    -- see gap 3 in the module-level note above for the false positive this gate exists
    to prevent (and why "opens with *some* marker" alone isn't a tight enough check).
    """
    chunk = chunks_by_id.get(chunk_id)
    if not chunk:
        return None
    # raw_text lines are dash-prefixed ("- (7)  Communicate...") -- strip that before
    # checking for a list marker, or every chunk's opening line fails this gate.
    opening = _LEADING_DASH_RE.sub("", (chunk.get("raw_text") or "").lstrip())
    match = _LIST_MARKER_RE.match(opening)
    if not match or match.group(1) in _FIRST_MARKER_VALUES:
        return None

    prev_chunk_id = chunk_id - 1
    prev_records = step_c_by_chunk.get(prev_chunk_id) or []
    for rec in reversed(prev_records):
        stem = _extract_stem_from_record_text(rec.get("source_quote"))
        if stem:
            return stem

    # Fall back to the previous chunk's raw_text directly -- REQ-cf527f39c8d7's real
    # stem ("b. Oversee their respective Component's PPSM program to:") was never
    # extracted as its own Step C record at all, only present in raw_text.
    prev_chunk = chunks_by_id.get(prev_chunk_id)
    if not prev_chunk:
        return None
    for line in reversed((prev_chunk.get("raw_text") or "").split("\n")):
        line = _LEADING_DASH_RE.sub("", line.strip())
        if not line or ":" not in line:
            continue
        stem = _extract_stem_from_record_text(line)
        if stem:
            return re.sub(r"\s+", " ", stem)
    return None


def _find_heading_stem(quote: str, chunk_id: int, chunks_by_id: dict[int, dict]) -> str | None:
    """Reconstruction lookup step 3: fall back to parent_header_text -- covers
    HEADING_IS_SUBJECT at zero additional engineering cost, since that field already
    exists on every chunk record today.

    Gated on _is_dangling_clause() (the existing, narrowly-calibrated WP-38.2 bare-
    copula predicate) rather than firing unconditionally whenever steps 1-2 fail: an
    ungated fallback also fires for STEM_NEVER_EXTRACTED examples, which must get no
    parent_stem at all (see module-level note above).
    """
    if not _is_dangling_clause(quote):
        return None
    chunk = chunks_by_id.get(chunk_id)
    if not chunk:
        return None
    header = (chunk.get("parent_header_text") or "").strip()
    return header or None


def _load_reconstruction_sources(norm_path: Path) -> tuple[dict[int, list[dict]], dict[int, dict]]:
    """Load this document's Step C output (grouped by chunk_id, preserving extraction
    order) and chunk records (raw_text/parent_header_text keyed by chunk_id) -- the two
    on-disk artifacts reconstruction needs beyond what's already in the normalized
    records. Missing files degrade to empty dicts (reconstruction becomes a no-op for
    that document, not a hard failure)."""
    from core.artifact_resolver import doc_key_from_requirements_path
    doc_key = doc_key_from_requirements_path(norm_path)
    doc_dir = norm_path.parent

    step_c_by_chunk: dict[int, list[dict]] = {}
    step_c_path = doc_dir / f"{doc_key}_extracted_requirements.jsonl"
    if step_c_path.exists():
        with open(step_c_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                cid = rec.get("chunk_id")
                if cid is not None:
                    step_c_by_chunk.setdefault(cid, []).append(rec)

    chunks_by_id: dict[int, dict] = {}
    chunks_path = doc_dir / f"{doc_key}_chunks.jsonl"
    if chunks_path.exists():
        with open(chunks_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                cid = rec.get("chunk_id")
                if cid is not None:
                    chunks_by_id[cid] = rec

    return step_c_by_chunk, chunks_by_id


def reconstruct_parent_stem(
    req: dict,
    step_c_by_chunk: dict[int, list[dict]],
    chunks_by_id: dict[int, dict],
) -> str | None:
    """Run the full 3-step reconstruction lookup for one normalized requirement record,
    falling through to None (leave empty) rather than guessing."""
    quote = (req.get("source_quote") or "").strip()
    chunk_id = req.get("chunk_id")
    if not quote or chunk_id is None:
        return None
    if not _is_reconstruction_candidate(quote):
        return None
    return (
        _find_same_chunk_stem(quote, chunk_id, step_c_by_chunk)
        or _find_cross_chunk_stem(chunk_id, step_c_by_chunk, chunks_by_id)
        or _find_heading_stem(quote, chunk_id, chunks_by_id)
    )


def apply_parent_stem_reconstruction(norm_jsonl: str) -> None:
    """WP-39.2: deterministically attach parent_stem/embedding_text to fragment-shaped
    requirements, in place, on Step D's own normalized output file.

    Writes directly into *_requirements_normalized.jsonl -- the artifact resolver's
    lowest, always-present tier -- rather than only inside the enrichment (Step D.5)
    output. That placement is what makes reconstruction survive both --skip-enrichment
    and an Ollama/enrichment failure: *_requirements_enriched.jsonl is never created at
    all in either case, so anything that only lived there would be lost exactly when
    this most needs to survive. See this function's call site in run_pipeline.py (called
    unconditionally, before the skip-enrichment check and outside the LLM call's
    try/except) and run()'s own call below (for anyone invoking this module standalone).

    Pure and offline -- no Ollama, no network. Idempotent: safe to call more than once
    on the same file, since it always recomputes the same values from the same on-disk
    Step C/chunk artifacts.
    """
    norm_path = Path(norm_jsonl).resolve()
    reqs: list[dict] = []
    with open(norm_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                reqs.append(json.loads(line))

    step_c_by_chunk, chunks_by_id = _load_reconstruction_sources(norm_path)

    changed = False
    for req in reqs:
        stem = reconstruct_parent_stem(req, step_c_by_chunk, chunks_by_id) or ""
        embedding_text = f"{stem}\n{req.get('source_quote', '')}".strip() if stem else ""
        if req.get("parent_stem") != stem or req.get("embedding_text") != embedding_text:
            changed = True
        req["parent_stem"] = stem
        req["embedding_text"] = embedding_text

    if changed:
        with open(norm_path, "w", encoding="utf-8") as f:
            for req in reqs:
                f.write(json.dumps(req, ensure_ascii=False) + "\n")


def run(
    norm_jsonl: str,
    output_dir: str,
    *,
    model: str = "llama3.1:8b-instruct-q4_K_M",
    ollama_url: str = "http://localhost:11434",
    timeout: int = 120,
    batch_size: int = 10,
    max_reqs: int | None = None,
    profile: dict | None = None,
) -> str:
    """Enrich normalized requirements with description, domain_tags, and requirement_type.

    Callable interface for in-process use by run_pipeline.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        norm_jsonl:   Path to requirements_normalized.jsonl from Step D.
        output_dir:   Directory to write requirements_enriched.jsonl into.
        model:        Ollama model name for enrichment.
        ollama_url:   Ollama API base URL.
        timeout:      Per-request LLM timeout in seconds.
        batch_size:   Requirements per LLM call (default 10). Falls back to
                      individual calls if batch response cannot be parsed.
        max_reqs:     Limit enrichment to first N unenriched requirements (testing).
        profile:      Validated profile dict from core.profiles.load_profile().
                      When None, the cybersecurity default profile is loaded.

    Returns:
        Path to the requirements_enriched.jsonl file that was written (str).
    """
    if profile is None:
        from core.profiles import default_profile as _default_profile
        profile = _default_profile()

    # WP-39.2: deterministic, offline -- kept independent of the LLM-calling code
    # below, not shared error handling. run_pipeline.py already calls this
    # unconditionally before invoking run() at all (so it also survives
    # --skip-enrichment, which skips this whole function); called again here so
    # anyone invoking enrich_requirements.py standalone gets the same guarantee.
    # Idempotent, so the redundant call on the run_pipeline.py path is harmless.
    apply_parent_stem_reconstruction(norm_jsonl)

    valid_domain_tags: list[str] = profile["domain_tags"]
    valid_requirement_types: list[str] = profile["requirement_types"]
    valid_tags_str = ", ".join(valid_domain_tags)
    valid_types_str = ", ".join(valid_requirement_types)
    norm_path = Path(norm_jsonl).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Anchored suffix strip, not a broad .replace() — a PDF whose own stem
    # happens to contain "_requirements_normalized" (e.g.
    # "policy_requirements_normalized_v1.pdf") would otherwise have that
    # substring collapsed everywhere it appears, producing an enriched
    # filename whose doc_key no longer matches the real *_chunks.jsonl file
    # and silently breaking context indexing downstream (WP-24.3 review).
    from core.artifact_resolver import doc_key_from_requirements_path
    stem = doc_key_from_requirements_path(norm_path)
    enriched_path = out_dir / f"{stem}_requirements_enriched.jsonl"

    # Load all normalized requirements
    reqs: list[dict] = []
    with open(norm_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                reqs.append(json.loads(line))
    log.info("Loaded %d requirements from %s", len(reqs), norm_path)

    # Load existing enriched requirements keyed by requirement_id (resume cache).
    # Only treat a cached record as "done" if:
    #   1. It has at least one non-empty enrichment field (failed runs must be retried), AND
    #   2. It was enriched by the same model currently in use (R-2.2 fix).
    # Switching --enrichment-model must not silently preserve the old model's output.
    #
    # Non-default profiles bypass cache entirely: enrichment_profile is not written to
    # output records until WP-20.4, so a non-cybersecurity enrichment record has no
    # profile marker and would be mis-identified as "cybersecurity" on the next default
    # run (rec.get("enrichment_profile", "cybersecurity") defaults all unmarked records).
    enriched_by_id: dict[str, dict] = {}
    if enriched_path.exists():
        if profile["name"] != "cybersecurity":
            log.info(
                "Non-default profile '%s': bypassing enrichment cache "
                "(enrichment_profile not written to records until WP-20.4)",
                profile["name"],
            )
        else:
            skipped_model_mismatch = 0
            with open(enriched_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            rid = rec.get("requirement_id")
                            if not rid:
                                continue
                            has_enrichment = rec.get("description") or rec.get("domain_tags") or rec.get("requirement_type")
                            if not has_enrichment:
                                continue
                            # If enrichment_model is recorded, require it to match.
                            # Records without enrichment_model (pre-WP-2 cache) are treated
                            # as model-unknown and will be re-enriched.
                            cached_model = rec.get("enrichment_model")
                            if cached_model != model:
                                skipped_model_mismatch += 1
                                continue
                            enriched_by_id[rid] = rec
                        except json.JSONDecodeError:
                            pass
            if skipped_model_mismatch:
                log.info(
                    "Skipped %d cached enrichments (model changed) — will re-enrich with %s",
                    skipped_model_mismatch, model,
                )
            log.info(
                "Loaded %d successfully-enriched requirements from cache (%s)",
                len(enriched_by_id), enriched_path,
            )

    # Requirements that still need enrichment (not yet successfully enriched)
    to_enrich = [req for req in reqs if req["requirement_id"] not in enriched_by_id]

    if max_reqs is not None:
        to_enrich = to_enrich[:max_reqs]

    if not to_enrich:
        log.info("All %d requirements already enriched — writing enriched JSONL", len(reqs))
        # Still write/update the enriched file to reflect any newly normalized reqs
        with open(enriched_path, "w", encoding="utf-8") as f:
            for req in reqs:
                record = enriched_by_id.get(req["requirement_id"], req)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return str(enriched_path)

    log.info(
        "Enriching %d requirements (batch_size=%d, model=%s)",
        len(to_enrich), batch_size, model,
    )

    # Verify Ollama connectivity
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Cannot reach Ollama at {ollama_url}: {e}") from e

    enriched_count = 0
    failed_count = 0
    pipeline_start = time.time()
    processed = 0

    for batch_start in range(0, len(to_enrich), batch_size):
        batch = to_enrich[batch_start:batch_start + batch_size]

        batch_results = _enrich_batch(
            batch, model, ollama_url, timeout,
            valid_tags_str=valid_tags_str,
            valid_types_str=valid_types_str,
            valid_domain_tags=valid_domain_tags,
            valid_requirement_types=valid_requirement_types,
        )

        if batch_results is not None:
            # Batch succeeded
            for req, enrichment in zip(batch, batch_results):
                enriched_req = {**req, **enrichment, "enrichment_model": model}
                enriched_by_id[req["requirement_id"]] = enriched_req
                enriched_count += 1
            processed += len(batch)
            log.info(
                "Batch %d-%d: enriched %d (total %d/%d)",
                batch_start + 1, batch_start + len(batch),
                len(batch), processed, len(to_enrich),
            )
        else:
            # Batch failed — fall back to individual calls
            log.info(
                "Batch %d-%d: falling back to individual calls",
                batch_start + 1, batch_start + len(batch),
            )
            for req in batch:
                result = _enrich_single(
                    req, model, ollama_url, timeout,
                    valid_tags_str=valid_tags_str,
                    valid_types_str=valid_types_str,
                    valid_domain_tags=valid_domain_tags,
                    valid_requirement_types=valid_requirement_types,
                )
                processed += 1
                if result is not None:
                    enriched_req = {**req, **result, "enrichment_model": model}
                    enriched_by_id[req["requirement_id"]] = enriched_req
                    enriched_count += 1
                else:
                    # Do NOT add to enriched_by_id — leave absent so the cache
                    # check above treats it as unenriched on the next run.
                    failed_count += 1
                log.info(
                    "Req %s (%d/%d): %s",
                    req.get("requirement_id", "?"),
                    processed, len(to_enrich),
                    "enriched" if result else "FAILED (kept original)",
                )

    elapsed = time.time() - pipeline_start
    log.info(
        "Enrichment done in %.1fs: %d enriched, %d failed (will retry on next run)",
        elapsed, enriched_count, failed_count,
    )

    # Write enriched JSONL preserving original ordering from norm_path
    with open(enriched_path, "w", encoding="utf-8") as f:
        for req in reqs:
            record = enriched_by_id.get(req["requirement_id"], req)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.info("Wrote %s", enriched_path)

    return str(enriched_path)


def _positive_int(value: str) -> int:
    """Argparse type: integer that must be > 0."""
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: '{value}'")
    if iv <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return iv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich normalized requirements with description, domain_tags, and requirement_type"
    )
    parser.add_argument(
        "norm_jsonl",
        type=str,
        help="Path to requirements_normalized.jsonl from Step D",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: same directory as input)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3.1:8b-instruct-q4_K_M",
        help="Ollama model for enrichment (default: llama3.1:8b-instruct-q4_K_M)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama API base URL",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_int,
        default=120,
        help="Per-request LLM timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=10,
        help="Requirements per LLM call (default: 10); falls back to individual on parse failure",
    )
    parser.add_argument(
        "--max-reqs",
        type=_positive_int,
        default=None,
        help="Limit enrichment to first N unenriched requirements (for testing)",
    )
    args = parser.parse_args()

    norm_path = Path(args.norm_jsonl).resolve()
    if not norm_path.exists():
        log.error("Input file not found: %s", norm_path)
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve() if args.output_dir else norm_path.parent

    try:
        run(
            str(norm_path),
            str(out_dir),
            model=args.model,
            ollama_url=args.ollama_url,
            timeout=args.timeout,
            batch_size=args.batch_size,
            max_reqs=args.max_reqs,
        )
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
