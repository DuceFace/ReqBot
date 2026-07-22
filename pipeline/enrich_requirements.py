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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

VALID_DOMAIN_TAGS = [
    "access-control",
    "authentication-and-identity",
    "audit-and-logging",
    "configuration-management",
    "contingency-and-recovery",
    "data-protection-and-encryption",
    "incident-response",
    "maintenance",
    "media-protection",
    "network-security",
    "personnel-security",
    "physical-security",
    "privacy",
    "risk-management",
    "security-assessment",
    "supply-chain-security",
    "system-integrity",
    "training-and-awareness",
]

VALID_REQUIREMENT_TYPES = [
    "policy",
    "technical-control",
    "procedural-control",
    "assessment",
    "guidance",
]

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
