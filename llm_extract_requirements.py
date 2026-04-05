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

PASS1_PROMPT_TEMPLATE = """You are a requirements extraction system for cybersecurity compliance documents.

Your ONLY task: identify and extract ACTIONABLE REQUIREMENTS from the text below.
A requirement is something an organization MUST DO — it expresses obligation, mandate, or necessity.

Extract statements containing: shall, must, required to, ensure, implement, establish, maintain, enforce,
or equivalent mandatory language (e.g., "is responsible for", "will", "are to") when used as a mandate.

DO NOT extract:
- Definitions or glossary entries
- Document change logs or errata (e.g., "Change X to Y")
- Tables of contents or section headings
- Cross-references to other controls (e.g., "Related controls: AC-2, IA-1")
- General background, context, or informational text

Return a JSON object with a single "requirements" key whose value is an array.
No markdown code fences. No text before or after the JSON object.
If there are no actionable requirements, return: {"requirements": []}

Each element in the "requirements" array must be a JSON object with exactly these keys:
- "source_quote": (REQUIRED) The exact verbatim quote from the text establishing this requirement
  (under 500 characters). Copy word-for-word — do NOT paraphrase or summarize. If you cannot find
  an exact verbatim quote for a requirement, do NOT include that requirement.
- "source_ref": The document-specific locator for this requirement (e.g., "AC-4", "Section 5.2.1",
  "Para 3.4.1") or "" if none is visible in the text. Copy it exactly as written — do not infer or construct.

--- EXAMPLES ---

Example 1 — NIST prose (requirements present):
Text: "AC-3 ACCESS ENFORCEMENT\nControl: The information system enforces approved authorizations for logical access to information and system resources in accordance with applicable access control policies.\nSupplemental Guidance: Access control policies (e.g., identity-based policies, role-based policies, attribute-based policies) and access enforcement mechanisms are employed by organizations to control access between active entities or subjects and passive entities or objects in information systems."
Output: {"requirements": [{"source_quote": "The information system enforces approved authorizations for logical access to information and system resources in accordance with applicable access control policies.", "source_ref": "AC-3"}]}

Example 2 — DoD policy table (multiple requirements):
Text: "3.2 POLICY\n3.2.1 All DoD information systems shall implement multi-factor authentication for all privileged user accounts.\n3.2.2 Password complexity requirements shall conform to NIST SP 800-63B guidelines. Minimum password length is 12 characters.\n3.2.3 See Table 3.2-1 for password requirements by account type (informational)."
Output: {"requirements": [{"source_quote": "All DoD information systems shall implement multi-factor authentication for all privileged user accounts.", "source_ref": "3.2.1"}, {"source_quote": "Password complexity requirements shall conform to NIST SP 800-63B guidelines. Minimum password length is 12 characters.", "source_ref": "3.2.2"}]}

Example 3 — References section (no requirements):
Text: "1. REFERENCES\na. DoD Instruction 8500.01, Cybersecurity, March 14, 2014, as amended.\nb. NIST Special Publication 800-53, Security and Privacy Controls for Federal Information Systems and Organizations, Revision 5, September 2020.\nc. Committee on National Security Systems Instruction No. 1253."
Output: {"requirements": []}

--- END EXAMPLES ---
{source_ref_hints}
Text:
{chunk_text}"""


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

# Ollama object-wrapped JSON Schema for Pass 1 structured output.
# Constrains the model at the tokenizer level — eliminates parse failures
# caused by preamble text, markdown fences, or malformed bare arrays.
# The response will always be {"requirements": [...]}, which extract_json_array()
# unwraps before the existing fallback strategies.
# NOTE: this constant is not used by the legacy PROMPT_TEMPLATE path (--full-extraction).
_PASS1_FORMAT_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_quote": {"type": "string"},
                    "source_ref": {"type": "string"},
                },
                "required": ["source_quote", "source_ref"],
            },
        }
    },
    "required": ["requirements"],
}


def _is_ip_address(candidate: str) -> bool:
    """Return True if candidate looks like an IPv4 address.

    Filters out IP addresses that the dragnet numeric pattern captures but
    that are useless as source_ref hints (e.g. 192.168.1.1 in network docs).
    Checks for exactly 4 dot-separated segments each in [0, 255].
    """
    parts = candidate.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def scan_source_refs(text: str) -> list[str]:
    """Regex-scan chunk text for candidate source references.

    Returns a deduplicated, sorted list of up to _MAX_HINT_REFS candidate
    ref strings found in the text. These are injected into the LLM prompt
    as hints to improve source_ref accuracy on the extracted requirements.

    IPv4 addresses that match the dragnet numeric pattern are filtered out
    to avoid wasting hint slots on noise in network-heavy documents.
    """
    candidates: set[str] = set()
    for pattern in _SOURCE_REF_PATTERNS:
        for match in pattern.finditer(text):
            candidate = match.group().strip()
            if _is_ip_address(candidate):
                continue
            candidates.add(candidate)
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
    json_schema: dict | None = None,
) -> str:
    """Call the Ollama generate API with exponential backoff for transient errors.

    Args:
        prompt: The full prompt string.
        model: Ollama model name (e.g., "llama3.1:8b").
        base_url: Ollama API base URL.
        timeout: Request timeout in seconds.
        max_retries: Number of retries before giving up (default: 3).
        json_schema: Optional Ollama object-wrapped JSON Schema for constrained
            generation (passed as the "format" field). When provided, the model
            output is guaranteed to match the schema — eliminates parse failures
            from preamble text and malformed JSON. Pass None for unconstrained
            generation (legacy PROMPT_TEMPLATE / --full-extraction path).

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
    if json_schema is not None:
        payload["format"] = json_schema

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
        # Unwrap Ollama structured-output response: {"requirements": [...]}
        if isinstance(result, dict) and isinstance(result.get("requirements"), list):
            return result["requirements"]
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
                    log.warning(
                        "JSON parse fallback (Strategy 2): extracted array from "
                        "non-bare response (%d chars prefix before '[')",
                        start_idx,
                    )
                    return result
            except json.JSONDecodeError:
                pass

    # Strategy 3: Handle truncated JSON arrays (LLM hit token limit).
    # Walk forward from the opening '[' with full string-literal awareness to find
    # the last complete top-level object boundary. This avoids the rfind("}") approach
    # which has no awareness of '}' characters inside quoted string values.
    if start_idx != -1:
        s3_depth = 0
        s3_in_string = False
        s3_escape_next = False
        last_obj_end = None  # index in `text` of last '}' that returned depth to 1

        for i in range(start_idx, len(text)):
            ch = text[i]
            if s3_escape_next:
                s3_escape_next = False
                continue
            if ch == "\\":
                s3_escape_next = True
                continue
            if ch == '"':
                s3_in_string = not s3_in_string
                continue
            if s3_in_string:
                continue
            if ch in ("[", "{"):
                s3_depth += 1
            elif ch in ("]", "}"):
                s3_depth -= 1
                if ch == "}" and s3_depth == 1:
                    # Just closed a top-level object within the array
                    last_obj_end = i

        if last_obj_end is not None:
            truncated = text[start_idx:last_obj_end + 1] + "]"
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
    prompt_template: str = PROMPT_TEMPLATE,
    json_schema: dict | None = None,
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

    prompt = (
        prompt_template
        .replace("{source_ref_hints}", source_ref_hints)
        .replace("{chunk_text}", chunk_text)
    )
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
        raw_response = call_ollama(prompt, model, base_url, timeout, json_schema=json_schema)
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
    pass1_only: bool = False,
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
        pass1_only:   Use PASS1_PROMPT_TEMPLATE (source_quote + source_ref only).
                      Faster and higher-recall; description/tags/type left to Pass 2
                      enrichment. Default False (full single-pass extraction).

    Returns:
        Path to the extracted_requirements.jsonl file that was written (str).
    """
    template = PASS1_PROMPT_TEMPLATE if pass1_only else PROMPT_TEMPLATE
    # Pass 1 uses Ollama constrained generation — eliminates parse failures
    # from preamble text and malformed bare arrays (Codex P1 fix).
    # Legacy full-extraction path (PROMPT_TEMPLATE) uses unconstrained generation.
    schema = _PASS1_FORMAT_SCHEMA if pass1_only else None
    if pass1_only:
        log.info("Using Pass 1 prompt (source_quote + source_ref only) with structured output")

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

    # Keep the full list for stale-cache detection (below). Filtering by
    # max_chunks or start_chunk would cause the scan to miss valid cache
    # entries outside the current subset and falsely discard the cache.
    all_chunks = chunks

    if start_chunk > 0:
        chunks = [c for c in chunks if c["chunk_id"] >= start_chunk]

    if max_chunks is not None:
        chunks = chunks[:max_chunks]

    cached_hashes: set[str] = set()
    if raw_path.exists():
        skipped_model_mismatch = 0
        with open(raw_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        # Only accept cache entries produced by the same model (R-2.2 fix).
                        # Switching --extraction-model must not reuse prior model's output.
                        if rec.get("model") != model:
                            skipped_model_mismatch += 1
                            continue
                        if ph := rec.get("prompt_hash"):
                            cached_hashes.add(ph)
                    except json.JSONDecodeError:
                        pass
        if skipped_model_mismatch:
            log.info(
                "Skipped %d cached entries from a different model — will re-process with %s",
                skipped_model_mismatch, model,
            )
        if cached_hashes:
            log.info(
                "Loaded %d cached prompt hashes (model=%s) — matching chunks will be skipped",
                len(cached_hashes), model,
            )
            # Guard against stale cache after a prompt template change (e.g. structured
            # output upgrade). If cached_hashes is non-empty but NO chunk's current
            # prompt hash matches, opening files in append mode would duplicate every row.
            # Scan chunks with early exit: if at least one hit exists the cache is valid;
            # if none match, discard it so write_mode falls through to "w".
            any_cache_hit = False
            for _c in all_chunks:
                _refs = scan_source_refs(_c["text"])
                _hints = (
                    "\nCandidate source references found in this text "
                    "(use these for the \"source_ref\" field where applicable): "
                    + ", ".join(_refs) + "\n"
                ) if _refs else ""
                _ph = compute_prompt_hash(
                    template
                    .replace("{source_ref_hints}", _hints)
                    .replace("{chunk_text}", _c["text"])
                )
                if _ph in cached_hashes:
                    any_cache_hit = True
                    break
            if not any_cache_hit:
                log.warning(
                    "Cached prompt hashes exist but none match the current template — "
                    "prompt may have changed. Discarding stale cache and starting fresh write."
                )
                cached_hashes = set()

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
                template
                .replace("{source_ref_hints}", _hints)
                .replace("{chunk_text}", chunk["text"])
            )
            if _prompt_hash in cached_hashes:
                log.info("Chunk %d/%d (id=%d): skipping (cached)", i + 1, len(chunks), chunk_id)
                total_skipped += 1
                continue

            chunk_start = time.time()
            raw_record, valid_reqs, failure = process_chunk(chunk, model, ollama_url, timeout, template, json_schema=schema)

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
