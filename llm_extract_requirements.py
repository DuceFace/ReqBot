#!/usr/bin/env python3
"""Step C: Extract cybersecurity requirements from text chunks using a local LLM.

Input:  chunks.jsonl (from Step B)
Output:
  - raw_responses.jsonl  — one line per chunk: {chunk_id, model, prompt_hash, raw_response, timestamp}
  - extracted_requirements.jsonl — one line per requirement:
        {chunk_id, requirement_id, description, source_ref, domain_tags, requirement_type, source_quote}
  - parse_failures.jsonl — chunks whose LLM response could not be parsed

This step is nondeterministic. It calls a local Ollama model and isolates all
LLM interaction. Raw responses are always logged before parsing so that
Step D can be rerun without re-calling the LLM.
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
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

PROMPT_TEMPLATE = """You are a requirements extraction system for cybersecurity and compliance documents.

Your task: extract only ACTIONABLE REQUIREMENTS from the text below. A requirement is something an organization MUST DO — it implies obligation, mandate, or necessity.

DO extract:
- Statements that express obligation or mandate, including but not limited to: shall, must, required to, ensure, implement, establish, maintain, enforce, or equivalent language (e.g., "is responsible for", "will", "are to") when used as a mandate
- Technical controls an organization needs to implement
- Policies or procedures an organization must define or follow
- Security measures that are mandated or strongly recommended

DO NOT extract:
- Definitions or glossary entries
- Document change logs or errata (e.g., "Change X to Y")
- Tables of contents or section headings
- Cross-references to other controls or documents (e.g., "Related controls: AC-2, IA-1")
- General background, context, or informational text
- Summaries of what a document covers

Return ONLY a valid JSON array. No markdown code fences. No text before or after the array.
If there are no actionable requirements in the text, return an empty array: []

Each element must be a JSON object with exactly these keys:
- "source_quote": (REQUIRED) The exact verbatim quote from the text that establishes this requirement (under 500 characters). Copy the text word-for-word — do not paraphrase or summarize. If you cannot find an exact verbatim quote for a requirement, do NOT include that requirement in the output.
- "source_ref": The document-specific locator for this requirement (e.g., "AC-4", "Section 5.2.1", "Para 3.4.1") or "" if none is visible in the text. This is a traceability label, not a semantic tag — copy it exactly as written, do not infer or construct it.
- "domain_tags": An array of 1-3 tags from this list ONLY: access-control, authentication-and-identity, audit-and-logging, configuration-management, contingency-and-recovery, data-protection-and-encryption, incident-response, maintenance, media-protection, network-security, personnel-security, physical-security, privacy, risk-management, security-assessment, supply-chain-security, system-integrity, training-and-awareness. If unsure, choose the single most relevant tag.
- "requirement_type": One of these (with definitions):
  * "policy" — a high-level organizational policy or directive
  * "technical-control" — a specific technical measure to implement in a system
  * "procedural-control" — a process, procedure, or practice humans must follow
  * "assessment" — a requirement to evaluate, test, audit, or monitor
  * "guidance" — a recommendation that is not strictly mandatory
- "description": A single precise sentence summarizing what must be done. Preserve the exact subject, verb, and object of the obligation. Keep all technical terms, control identifiers, system names, numerical thresholds, and acronyms exactly as they appear in the source. Do NOT generalize or paraphrase. Maximum 120 words. May be "" if the source_quote is self-explanatory.
  GOOD: "Systems must enforce multi-factor authentication using PIV cards for all privileged access to CUI systems."
  GOOD: "Organizations must review and update system account lists within 24 hours of personnel termination per AC-2(3)."
  BAD: "Organizations must implement authentication controls." (too vague — lost PIV, MFA, CUI, and privileged access specifics)
  BAD: "Ensure proper security measures are in place." (meaningless — no subject, no object, no specifics)
{source_ref_hints}
Text:
{chunk_text}"""


def compute_prompt_hash(prompt: str) -> str:
    """SHA-256 hash of the prompt for deduplication/caching."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


# Compiled patterns for pre-scan source ref detection (P3).
# Order matters: more specific patterns first.
_SOURCE_REF_PATTERNS = [
    # NIST/DoD/STIG control IDs: AC-3, AC-3(4), IA-5(1), CCI-000366, CM-8(3)(a)
    # - \d+ (no cap) handles 6-digit STIG CCIs (CCI-000366)
    # - (?:\([a-zA-Z0-9]+\))* allows multiple/lettered sub-parts: CM-8(3)(a)
    # - Trailing (?!\w) instead of \b so closing ')' is included in the match
    re.compile(r"\b[A-Z]{2,4}-\d+(?:\([a-zA-Z0-9]+\))*(?!\w)"),
    # Explicit section references: Section 5, Section 5.2.1, Sec. 3.4
    # * (not +) so top-level "Section 5" is captured, not just multi-segment refs
    re.compile(r"\b(?:Section|Sec\.)\s+\d+(?:\.\d+)*", re.IGNORECASE),
    # Paragraph references: Para 3, Para 3.4.1, Paragraph 2.1
    re.compile(r"\b(?:Para(?:graph)?)\s+\d+(?:\.\d+)*", re.IGNORECASE),
    # Numbered hierarchy refs with 3+ segments: 4.2.1, 3.1.2.5
    # Note: this is a dragnet — it also captures IP addresses and version strings.
    # The LLM is expected to ignore clearly non-ref values (e.g. 192.168.1.1).
    re.compile(r"\b\d+\.\d+(?:\.\d+)+\b"),
]
_MAX_HINT_REFS = 20  # cap to avoid bloating the prompt


def scan_source_refs(text: str) -> list[str]:
    """Regex-scan chunk text for candidate source references.

    Returns a deduplicated, sorted list of up to _MAX_HINT_REFS candidate
    ref strings found in the text. These are injected into the LLM prompt
    as hints to improve source_ref accuracy on the extracted requirements.
    """
    candidates: set[str] = set()
    for pattern in _SOURCE_REF_PATTERNS:
        for match in pattern.finditer(text):
            candidates.add(match.group().strip())
            if len(candidates) >= _MAX_HINT_REFS:
                break
        if len(candidates) >= _MAX_HINT_REFS:
            break
    return sorted(candidates)


def call_ollama(
    prompt: str,
    model: str,
    base_url: str,
    timeout: int = 120,
    max_retries: int = 3,
) -> str:
    """Call the Ollama generate API with exponential backoff for transient errors.

    Args:
        prompt: The full prompt string.
        model: Ollama model name (e.g., "llama3.1:8b").
        base_url: Ollama API base URL.
        timeout: Request timeout in seconds.
        max_retries: Number of retries before giving up (default: 3).

    Returns:
        The raw text response from the model.

    Raises:
        requests.RequestException: After all retries are exhausted.
    """
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
            backoff = 2 ** attempt  # 2s, 4s, 8s
            log.warning(
                "Ollama request failed (%s) — retrying in %ds (attempt %d/%d)",
                e, backoff, attempt, max_retries,
            )
            time.sleep(backoff)


def extract_json_array(raw_response: str) -> list[dict] | None:
    """Attempt to extract a JSON array from a raw LLM response.

    Tries multiple strategies in order:
    1. Strip markdown code fences and parse directly
    2. Find the outermost [ ... ] with bounded (non-greedy) matching
    3. Try line-by-line brace-counting to find the array boundaries

    Returns None if no valid JSON array can be extracted.
    """
    text = raw_response.strip()

    # Strategy 1: Strip markdown fences
    text_clean = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text_clean = re.sub(r"```\s*$", "", text_clean, flags=re.MULTILINE)
    text_clean = text_clean.strip()

    try:
        result = json.loads(text_clean)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Strategy 2: Find outermost brackets with bracket-counting
    start_idx = text.find("[")
    if start_idx != -1:
        depth = 0
        end_idx = None
        in_string = False
        escape_next = False
        for i in range(start_idx, len(text)):
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
                    end_idx = i
                    break

        if end_idx is not None:
            candidate = text[start_idx:end_idx + 1]
            try:
                result = json.loads(candidate)
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

    # Strategy 3: Handle truncated JSON arrays (LLM hit token limit)
    # Find the last complete JSON object boundary and close the array
    if start_idx is not None and start_idx != -1:
        array_content = text[start_idx:]
        # Find the last "}," or "}" that ends a complete object
        last_obj_end = None
        for pattern in ["},", "}\n"]:
            idx = array_content.rfind(pattern)
            if idx != -1:
                candidate_end = idx + 1  # include the }
                if last_obj_end is None or candidate_end > last_obj_end:
                    last_obj_end = candidate_end
        # Also try just "}" at end of a line
        idx = array_content.rfind("}")
        if idx != -1 and (last_obj_end is None or idx > last_obj_end):
            last_obj_end = idx + 1

        if last_obj_end is not None:
            truncated = array_content[:last_obj_end] + "]"
            try:
                result = json.loads(truncated)
                if isinstance(result, list):
                    log.warning(
                        "Recovered %d objects from truncated JSON array",
                        len(result),
                    )
                    return result
            except json.JSONDecodeError:
                pass

    return None


def validate_requirement(req: dict) -> dict | None:
    """Validate and clean a single requirement dict.

    Returns the cleaned dict or None if invalid.
    """
    if not isinstance(req, dict):
        return None

    description = req.get("description", "").strip()
    source_ref = req.get("source_ref", "").strip()
    source_quote = req.get("source_quote", "").strip()
    req_type = req.get("requirement_type", "").strip().lower()

    # Must have verbatim evidence — requirements without source_quote are fabricated
    if not source_quote:
        return None

    # Validate and filter domain tags
    raw_tags = req.get("domain_tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    domain_tags = [t.strip().lower() for t in raw_tags if isinstance(t, str)]
    domain_tags = [t for t in domain_tags if t in VALID_DOMAIN_TAGS]

    # If LLM gave no valid tags, leave empty — Step D can handle it
    # Validate requirement type
    if req_type not in VALID_REQUIREMENT_TYPES:
        req_type = ""

    return {
        "description": description,
        "source_ref": source_ref,
        "domain_tags": domain_tags,
        "requirement_type": req_type,
        "source_quote": source_quote,
    }


def process_chunk(
    chunk: dict,
    model: str,
    base_url: str,
    timeout: int,
) -> tuple[dict, list[dict], dict | None]:
    """Process a single chunk through the LLM.

    Returns:
        (raw_record, valid_requirements, failure_record_or_none)
    """
    chunk_id = chunk["chunk_id"]
    chunk_text = chunk["text"]

    # P3: pre-scan for candidate source refs and inject as LLM hints
    ref_candidates = scan_source_refs(chunk_text)
    if ref_candidates:
        source_ref_hints = (
            "\nCandidate source references found in this text "
            "(use these for the \"source_ref\" field where applicable): "
            + ", ".join(ref_candidates)
            + "\n"
        )
    else:
        source_ref_hints = ""

    prompt = PROMPT_TEMPLATE.format(chunk_text=chunk_text, source_ref_hints=source_ref_hints)
    prompt_hash = compute_prompt_hash(prompt)
    timestamp = datetime.now(timezone.utc).isoformat()

    raw_record = {
        "chunk_id": chunk_id,
        "model": model,
        "prompt_hash": prompt_hash,
        "raw_response": "",
        "timestamp": timestamp,
    }

    # Call LLM
    try:
        raw_response = call_ollama(prompt, model, base_url, timeout)
        raw_record["raw_response"] = raw_response
    except requests.RequestException as e:
        log.error("Chunk %d: Ollama request failed: %s", chunk_id, e)
        raw_record["raw_response"] = f"ERROR: {e}"
        failure = {
            "chunk_id": chunk_id,
            "error": f"ollama_request_failed: {e}",
            "raw_response": raw_record["raw_response"],
        }
        return raw_record, [], failure

    # Parse response
    parsed = extract_json_array(raw_response)
    if parsed is None:
        log.warning(
            "Chunk %d: Failed to parse JSON from response (%d chars)",
            chunk_id, len(raw_response),
        )
        failure = {
            "chunk_id": chunk_id,
            "error": "json_parse_failed",
            "raw_response_preview": raw_response[:500],
        }
        return raw_record, [], failure

    # Validate individual requirements
    valid_reqs = []
    for item in parsed:
        cleaned = validate_requirement(item)
        if cleaned:
            cleaned["chunk_id"] = chunk_id
            valid_reqs.append(cleaned)

    if not parsed and not valid_reqs:
        # Empty array is valid (chunk had no requirements)
        log.debug("Chunk %d: No requirements found (empty array)", chunk_id)

    return raw_record, valid_reqs, None


def append_jsonl(record: dict, file_handle) -> None:
    """Append a single JSON record to an open file handle."""
    file_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    file_handle.flush()


def run(
    chunks_jsonl: str,
    output_dir: str,
    *,
    model: str = "llama3.1:8b",
    ollama_url: str = "http://192.168.90.100:11434",
    timeout: int = 120,
    max_chunks: int | None = None,
    start_chunk: int = 0,
) -> str:
    """Extract requirements from chunks JSONL using a local LLM.

    Callable interface for in-process use by run_pipeline.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        chunks_jsonl: Path to chunks.jsonl from Step B.
        output_dir:   Directory to write output files into.
        model:        Ollama model name.
        ollama_url:   Ollama API base URL.
        timeout:      Per-request timeout in seconds.
        max_chunks:   Process only first N chunks (for testing).
        start_chunk:  Start from this chunk_id (for resuming).

    Returns:
        Path to the extracted_requirements.jsonl file that was written (str).
    """
    chunks_path = Path(chunks_jsonl).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = chunks_path.stem.replace("_chunks", "")
    raw_path = out_dir / f"{stem}_raw_responses.jsonl"
    reqs_path = out_dir / f"{stem}_extracted_requirements.jsonl"
    fail_path = out_dir / f"{stem}_parse_failures.jsonl"

    chunks = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))

    if start_chunk > 0:
        chunks = [c for c in chunks if c["chunk_id"] >= start_chunk]

    if max_chunks is not None:
        chunks = chunks[:max_chunks]

    cached_hashes: set[str] = set()
    if raw_path.exists():
        with open(raw_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        if ph := rec.get("prompt_hash"):
                            cached_hashes.add(ph)
                    except json.JSONDecodeError:
                        pass
        if cached_hashes:
            log.info(
                "Loaded %d cached prompt hashes — already-processed chunks will be skipped",
                len(cached_hashes),
            )

    log.info("Processing %d chunks with model=%s, ollama=%s", len(chunks), model, ollama_url)

    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        resp.raise_for_status()
        available_models = [m["name"] for m in resp.json().get("models", [])]
        if not any(model in m for m in available_models):
            log.warning("Model '%s' not found in Ollama. Available: %s", model, available_models)
    except requests.RequestException as e:
        log.error("Cannot reach Ollama at %s: %s", ollama_url, e)
        raise RuntimeError(f"Cannot reach Ollama at {ollama_url}: {e}") from e

    write_mode = "a" if (cached_hashes or start_chunk > 0) else "w"
    total_reqs = 0
    total_failures = 0
    total_skipped = 0
    pipeline_start = time.time()

    with (
        open(raw_path, write_mode, encoding="utf-8") as raw_f,
        open(reqs_path, write_mode, encoding="utf-8") as reqs_f,
        open(fail_path, write_mode, encoding="utf-8") as fail_f,
    ):
        for i, chunk in enumerate(chunks):
            chunk_id = chunk["chunk_id"]

            _refs = scan_source_refs(chunk["text"])
            _hints = (
                "\nCandidate source references found in this text "
                "(use these for the \"source_ref\" field where applicable): "
                + ", ".join(_refs) + "\n"
            ) if _refs else ""
            _prompt_hash = compute_prompt_hash(
                PROMPT_TEMPLATE.format(chunk_text=chunk["text"], source_ref_hints=_hints)
            )
            if _prompt_hash in cached_hashes:
                log.info("Chunk %d/%d (id=%d): skipping (cached)", i + 1, len(chunks), chunk_id)
                total_skipped += 1
                continue

            chunk_start = time.time()
            raw_record, valid_reqs, failure = process_chunk(chunk, model, ollama_url, timeout)

            append_jsonl(raw_record, raw_f)

            for j, req in enumerate(valid_reqs):
                req["requirement_id"] = f"R-{chunk_id}-{j}"
                append_jsonl(req, reqs_f)
            total_reqs += len(valid_reqs)

            if failure:
                append_jsonl(failure, fail_f)
                total_failures += 1

            elapsed = time.time() - chunk_start
            log.info(
                "Chunk %d/%d (id=%d): %d requirements extracted in %.1fs%s",
                i + 1, len(chunks), chunk_id, len(valid_reqs), elapsed,
                " [PARSE FAILED]" if failure else "",
            )

    total_elapsed = time.time() - pipeline_start
    processed = len(chunks) - total_skipped
    log.info(
        "Done: %d chunks processed, %d skipped (cached) in %.1fs — %d requirements, %d parse failures",
        processed, total_skipped, total_elapsed, total_reqs, total_failures,
    )
    log.info("Raw responses: %s", raw_path)
    log.info("Requirements:  %s", reqs_path)
    log.info("Failures:      %s", fail_path)
    return str(reqs_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract requirements from chunks using a local LLM"
    )
    parser.add_argument("chunks_jsonl", type=str, help="Path to chunks.jsonl from Step B")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: same directory as input)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3.1:8b",
        help="Ollama model name (default: llama3.1:8b)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://192.168.90.100:11434",
        help="Ollama API base URL (default: http://192.168.90.100:11434)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Per-request timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help="Process only the first N chunks (for testing)",
    )
    parser.add_argument(
        "--start-chunk",
        type=int,
        default=0,
        help="Start processing from this chunk_id (for resuming)",
    )
    args = parser.parse_args()

    chunks_path = Path(args.chunks_jsonl).resolve()
    if not chunks_path.exists():
        log.error("Input file not found: %s", chunks_path)
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve() if args.output_dir else chunks_path.parent

    try:
        run(
            str(chunks_path),
            str(out_dir),
            model=args.model,
            ollama_url=args.ollama_url,
            timeout=args.timeout,
            max_chunks=args.max_chunks,
            start_chunk=args.start_chunk,
        )
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
