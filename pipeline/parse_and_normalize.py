#!/usr/bin/env python3
"""Step D: Normalize and deduplicate extracted requirements.

Input:  extracted_requirements.jsonl (from Step C)
        chunks.jsonl (from Step B, for page reference lookup)
Output:
  - requirements_normalized.jsonl — final schema per requirement
  - normalization_failures.jsonl — requirements that failed normalization

This step is deterministic. It validates domain tags, adds page references
from chunk metadata, and deduplicates requirements by description similarity.
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

from rapidfuzz import fuzz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SCHEMA_VERSION = "2.0"
PIPELINE_VERSION = "1.0"

# WP-32.1: minimum fuzz.partial_ratio (0-100) between a requirement's source_quote
# and its own chunk's text before it's trusted as actually grounded in the source
# document, rather than fabricated by Step C. partial_ratio (not token_sort_ratio,
# which eval/eval_harness.py uses for a different comparison -- two same-length
# quotes) is the right tool here: it scores how well a short string matches the
# best-aligned substring of a long one, which is exactly "is this quote actually
# in this chunk." Exact substring matching was tried first and rejected -- it
# would have flagged ~16/30 real quotes reformatted from tabular source text
# (e.g. NIST.SP.800-53Ar5's assessment procedures) as fabricated.
#
# 60 was chosen by sweeping thresholds against eval/gold_eval_chunks_curated.jsonl's
# 2,452 hand-verified real quotes (the false-positive side) and the full local
# corpus's 33,462 requirements (the catch-rate side):
#   threshold  gold false-positive rate   corpus flagged rate
#       50            0.86%                     3.51%
#       60            1.75%                     4.42%
#       80            4.61%                     5.64%
# Diminishing returns above ~60: pushing to 80 nearly triples the gold
# false-positive rate for comparatively little extra corpus coverage -- most
# genuine fabrications score far below 60 anyway (the confirmed hallucination
# that motivated this WP scored 44). See docs/PHASE32_REQUIREMENTS.md for the
# full investigation.
QUOTE_GROUNDING_THRESHOLD = 60

VALID_DOMAIN_TAGS = {
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
}

VALID_REQUIREMENT_TYPES = {
    "policy",
    "technical-control",
    "procedural-control",
    "assessment",
    "guidance",
}


def compute_document_identity(pdf_path: Path) -> dict:
    """Compute document identity from PDF file bytes.

    Returns dict with document_id (short), document_hash_full, source_pdf.
    Hashes in 64 KB chunks to avoid loading large PDFs fully into memory.
    """
    hasher = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            hasher.update(block)
    full_hash = hasher.hexdigest()
    return {
        "document_id": full_hash[:16],
        "document_hash_full": full_hash,
        "source_pdf": pdf_path.name,
    }


def normalize_for_hash(text: str) -> str:
    """Normalize text deterministically for stable ID hashing.

    Lowercase, collapse whitespace, strip leading/trailing whitespace.
    """
    return re.sub(r"\s+", " ", text.strip().lower())


def compute_stable_id(
    document_id: str,
    source_ref: str,
    source_quote: str,
    chunk_id: int | None,
    requirement_type: str,
    description: str,
) -> str:
    """Compute a stable requirement ID based on document content.

    Uses a cascade of hash inputs ordered by stability:
    1. document_id + source_ref + normalized_source_quote (most stable)
    2. document_id + normalized_source_quote (if no source_ref)
    3. document_id + chunk_id + requirement_type + normalized_description (last resort)
    """
    norm_quote = normalize_for_hash(source_quote)
    norm_desc = normalize_for_hash(description)

    if norm_quote and source_ref:
        basis = f"{document_id}:{source_ref}:{norm_quote}"
    elif norm_quote:
        basis = f"{document_id}:{norm_quote}"
    else:
        basis = f"{document_id}:{chunk_id}:{requirement_type}:{norm_desc}"

    short_hash = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    return f"REQ-{short_hash}"


def load_jsonl(path: Path) -> list[dict]:
    """Load records from a JSONL file."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_chunk_page_map(chunks: list[dict]) -> dict[int, tuple[int, int]]:
    """Build a mapping from chunk_id to (page_start, page_end)."""
    return {
        c["chunk_id"]: (c["page_start"], c["page_end"])
        for c in chunks
    }


def build_chunk_text_map(chunks: list[dict]) -> dict[int, str]:
    """Build a mapping from chunk_id to its chunk text.

    Uses the "text" field specifically -- the same field
    pipeline/llm_extract_requirements.py substitutes into Step C's prompt via
    {chunk_text}, not "raw_text" (a different, pre-cleaning field). Grounding a
    requirement's source_quote against anything other than what the LLM actually
    saw would be checking against the wrong text (WP-32.1).
    """
    return {c["chunk_id"]: c.get("text") or "" for c in chunks}


def build_chunk_hierarchy_map(chunks: list[dict]) -> dict[int, dict]:
    """Build a mapping from chunk_id to its hierarchy metadata fields.

    Returns empty-field dicts for chunks without WP-14.2 hierarchy output
    (legacy pymupdf/pdfplumber chunks) so callers get safe defaults.
    """
    result: dict[int, dict] = {}
    for c in chunks:
        result[c["chunk_id"]] = {
            "section_ref_path": c.get("section_ref_path") or [],
            "section_title_path": c.get("section_title_path") or [],
            "parent_header_text": c.get("parent_header_text"),
            "parent_context": c.get("parent_context"),
        }
    return result


def build_section_children_map(chunks: list[dict]) -> dict[str, list[str]]:
    """Build a mapping from each section ref to its direct child section refs.

    Walks every consecutive pair in each chunk's section_ref_path so that
    intermediate sections with no body chunk (heading-only, dropped by WP-14.2
    HybridChunker) are still represented.  For example, a chunk with path
    ["1", "1.1", "1.1.1"] contributes both "1" → "1.1" and "1.1" → "1.1.1",
    even if no chunk carries path ["1", "1.1"] directly.

    Only chunks with WP-14.2 numbered section_ref_path contribute; legacy
    chunks with empty paths are silently skipped.
    """
    parent_to_children: dict[str, set[str]] = {}
    for chunk in chunks:
        path = chunk.get("section_ref_path") or []
        for i in range(1, len(path)):
            parent_ref = path[i - 1]
            child_ref = path[i]
            parent_to_children.setdefault(parent_ref, set()).add(child_ref)
    return {k: sorted(v) for k, v in parent_to_children.items()}


def normalize_text(text: str) -> str:
    """Normalize whitespace and casing for comparison."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _dedup_score(req: dict) -> float:
    """Score a requirement for winner selection during deduplication.

    Higher score = preferred record. Formula:
      confidence * 1000 - len(source_quote)

    Confidence (0.0–1.0) dominates: a record with higher confidence always
    wins over one with lower confidence. For equal confidence, a shorter
    source_quote is preferred — it indicates a more precise verbatim capture
    rather than a padded or over-long quote.

    Tag count is intentionally excluded: the LLM can hallucinate tags, and
    more tags does not imply a better extraction.
    """
    confidence = req.get("confidence", 0.0)
    quote_len = len(req.get("source_quote", ""))
    return confidence * 1000 - quote_len


def deduplicate_requirements(requirements: list[dict]) -> list[dict]:
    """Remove duplicate requirements based on two keys:
    1. source_ref + normalized description (only when description is non-empty)
    2. source_ref + normalized source_quote (catches near-identical quotes)

    When duplicates exist, keep the higher-confidence record; for equal
    confidence, prefer the shorter (more precise) source_quote.

    Note: desc_key is skipped when description is empty. In Pass 1 mode all
    descriptions are empty, so using desc_key would collapse distinct requirements
    that share a source_ref into a single record, dropping valid extractions.
    """
    seen: dict[str, dict] = {}
    for req in requirements:
        source_ref = req.get("source_ref", "")
        description = normalize_text(req.get("description", ""))
        quote = normalize_text(req.get("source_quote", ""))

        # Only build desc_key when description is non-empty; an empty description
        # is not a meaningful dedupe signal and would cause false collisions in
        # Pass 1 mode where all descriptions are intentionally absent.
        desc_key = f"{source_ref}::desc::{description}" if description else None
        quote_key = f"{source_ref}::quote::{quote}" if quote else None

        # Check if either key was seen
        existing_key = None
        if desc_key and desc_key in seen:
            existing_key = desc_key
        elif quote_key and quote_key in seen:
            existing_key = quote_key

        if existing_key:
            existing = seen[existing_key]
            if _dedup_score(req) > _dedup_score(existing):
                seen[existing_key] = req
        else:
            if desc_key:
                seen[desc_key] = req
            if quote_key:
                seen[quote_key] = req
    # Deduplicate the values (a req may be stored under both keys)
    unique = {id(v): v for v in seen.values()}
    return list(unique.values())


def run(
    requirements_jsonl: str,
    chunks_jsonl: str,
    source_pdf_path: str,
    output_dir: str,
    *,
    extraction_model: str = "llama3.1:8b-instruct-q4_K_M",
    profile: dict | None = None,
) -> str:
    """Normalize and deduplicate extracted requirements and write output JSONL.

    Callable interface for in-process use by run_pipeline.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        requirements_jsonl: Path to extracted_requirements.jsonl from Step C.
        chunks_jsonl:       Path to chunks.jsonl from Step B (for page refs).
        source_pdf_path:    Path to original PDF (for document identity hash).
        output_dir:         Directory to write normalized JSONL into.
        extraction_model:   LLM name used in Step C (written to schema).
        profile:            Validated profile dict from core.profiles.load_profile().
                            When None, the cybersecurity default profile is loaded.

    Returns:
        Path to the requirements_normalized.jsonl file that was written (str).
    """
    if profile is None:
        from core.profiles import default_profile as _default_profile
        profile = _default_profile()

    _valid_domain_tags: frozenset[str] = frozenset(profile["domain_tags"])
    _valid_requirement_types: frozenset[str] = frozenset(profile["requirement_types"])

    reqs_path = Path(requirements_jsonl).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    doc_identity = {"document_id": "", "document_hash_full": "", "source_pdf": ""}
    if source_pdf_path:
        pdf_path = Path(source_pdf_path).resolve()
        if pdf_path.exists():
            doc_identity = compute_document_identity(pdf_path)
            log.info("Document identity: %s (%s)", doc_identity["document_id"], doc_identity["source_pdf"])
        else:
            log.warning("PDF file not found: %s — document_id will be empty", pdf_path)

    chunks_path = Path(chunks_jsonl).resolve()
    from core.artifact_resolver import doc_key_from_extracted_path
    stem = doc_key_from_extracted_path(reqs_path)
    norm_path = out_dir / f"{stem}_requirements_normalized.jsonl"
    fail_path = out_dir / f"{stem}_normalization_failures.jsonl"

    log.info("Loading requirements from: %s", reqs_path)
    raw_reqs = load_jsonl(reqs_path)
    log.info("Loaded %d raw requirements", len(raw_reqs))

    chunk_page_map: dict[int, tuple[int, int]] = {}
    chunk_hierarchy_map: dict[int, dict] = {}
    section_children_map: dict[str, list[str]] = {}
    chunk_text_map: dict[int, str] = {}
    if chunks_path.exists():
        log.info("Loading chunk metadata from: %s", chunks_path)
        chunks = load_jsonl(chunks_path)
        chunk_page_map = build_chunk_page_map(chunks)
        chunk_hierarchy_map = build_chunk_hierarchy_map(chunks)
        section_children_map = build_section_children_map(chunks)
        chunk_text_map = build_chunk_text_map(chunks)
        log.info("Loaded page references for %d chunks", len(chunk_page_map))
        sections_with_children = sum(1 for v in section_children_map.values() if v)
        log.info(
            "Hierarchy map: %d chunks, %d sections with children",
            len(chunk_hierarchy_map), sections_with_children,
        )
    else:
        log.warning("Chunks file not found: %s — page references will be empty", chunks_path)

    run_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    start = time.time()

    valid_reqs = []
    failures = []

    for req in raw_reqs:
        description = req.get("description", "").strip()
        source_ref = req.get("source_ref", "").strip()
        source_quote = req.get("source_quote", "").strip()
        req_type = req.get("requirement_type", "").strip().lower()
        chunk_id = req.get("chunk_id")

        if not source_quote:
            failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "empty_source_quote", "raw": req})
            continue

        # WP-32.1: reject requirements whose source_quote isn't actually grounded in
        # its own chunk's text -- Step C's extraction model was found to sometimes
        # fabricate plausible-sounding requirements (confirmed at 21.55% across the
        # existing corpus during this WP's spike) rather than only extracting what's
        # present. Skipped (not rejected) when chunk_id/chunk text isn't available to
        # verify against -- this check only fires when it can actually check, it
        # doesn't punish missing chunk metadata, a separate pre-existing condition.
        chunk_text = chunk_text_map.get(chunk_id) if chunk_id is not None else None
        if chunk_text:
            grounding_score = fuzz.partial_ratio(normalize_text(source_quote), normalize_text(chunk_text))
            if grounding_score < QUOTE_GROUNDING_THRESHOLD:
                failures.append({
                    "requirement_id": req.get("requirement_id", "UNKNOWN"),
                    "chunk_id": chunk_id,
                    "error": "quote_not_grounded_in_chunk",
                    "grounding_score": round(grounding_score, 1),
                    "raw": req,
                })
                continue

        if description:
            desc_lower = description.lower()
            if desc_lower.startswith("not explicitly stated"):
                failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "not_actionable", "raw": req})
                continue

            if desc_lower.startswith("change ") and (" to " in desc_lower or " from " in desc_lower):
                if len(description) < 100:
                    failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "errata_change_entry", "raw": req})
                    continue

        raw_tags = req.get("domain_tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        domain_tags = [t.strip().lower() for t in raw_tags if isinstance(t, str)]
        domain_tags = [t for t in domain_tags if t in _valid_domain_tags]

        if req_type not in _valid_requirement_types:
            req_type = ""

        page_start = None
        page_end = None
        if chunk_id is not None and chunk_id in chunk_page_map:
            page_start, page_end = chunk_page_map[chunk_id]

        # Hierarchy metadata — sourced from deterministic WP-14.2 parser output.
        # Falls back to empty values for legacy (pre-WP-14.2) chunks.
        hierarchy = chunk_hierarchy_map.get(chunk_id) if chunk_id is not None else None
        if hierarchy:
            section_ref_path: list[str] = hierarchy["section_ref_path"]
            section_title_path: list[str] = hierarchy["section_title_path"]
            parent_context: str | None = hierarchy["parent_context"]
            # parent_section_ref: penultimate element of the ancestry path
            parent_section_ref: str | None = (
                section_ref_path[-2] if len(section_ref_path) >= 2 else None
            )
            # child_section_refs: direct children of this section across all chunks
            current_ref = section_ref_path[-1] if section_ref_path else None
            child_section_refs: list[str] = (
                section_children_map.get(current_ref, []) if current_ref else []
            )
        else:
            section_ref_path = []
            section_title_path = []
            parent_context = None
            parent_section_ref = None
            child_section_refs = []

        confidence = 1.0
        if not domain_tags:
            confidence -= 0.2
        if not source_quote:
            confidence -= 0.2
        if len(description) < 20:
            confidence -= 0.1
        if not source_ref:
            confidence -= 0.1

        normalized = {
            "requirement_id": req.get("requirement_id", f"R-{chunk_id}-X"),
            "description": description,
            "source_ref": source_ref,
            "domain_tags": domain_tags,
            "requirement_type": req_type,
            "source_quote": source_quote,
            "chunk_id": chunk_id,
            "page_start": page_start,
            "page_end": page_end,
            "confidence": round(max(0.0, confidence), 2),
            # Hierarchy metadata (WP-14.3) — deterministic parser output from WP-14.2.
            # Empty for requirements produced by the legacy fixed-size chunker.
            "section_ref_path": section_ref_path,
            "section_title_path": section_title_path,
            "parent_section_ref": parent_section_ref,
            "parent_context": parent_context,
            "child_section_refs": child_section_refs,
            "recovered_truncated": req.get("recovered_truncated", False),
            "domain_profile": profile["name"],
            "document_id": doc_identity["document_id"],
            "document_hash_full": doc_identity["document_hash_full"],
            "source_pdf": doc_identity["source_pdf"],
            "schema_version": SCHEMA_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "extraction_model": extraction_model,
            "run_timestamp": run_timestamp,
        }
        valid_reqs.append(normalized)

    before_dedup = len(valid_reqs)
    valid_reqs = deduplicate_requirements(valid_reqs)
    dedup_removed = before_dedup - len(valid_reqs)

    for req in valid_reqs:
        req["requirement_id"] = compute_stable_id(
            document_id=req["document_id"],
            source_ref=req["source_ref"],
            source_quote=req["source_quote"],
            chunk_id=req.get("chunk_id"),
            requirement_type=req["requirement_type"],
            description=req["description"],
        )

    elapsed = time.time() - start

    tagged_count = sum(1 for r in valid_reqs if r["domain_tags"])
    typed_count = sum(1 for r in valid_reqs if r["requirement_type"])
    log.info(
        "Normalized %d requirements in %.2fs — %d failures, %d duplicates removed",
        len(valid_reqs), elapsed, len(failures), dedup_removed,
    )
    log.info(
        "Domain tags assigned: %d/%d (%.1f%%), typed: %d/%d (%.1f%%)",
        tagged_count, len(valid_reqs),
        tagged_count / len(valid_reqs) * 100 if valid_reqs else 0,
        typed_count, len(valid_reqs),
        typed_count / len(valid_reqs) * 100 if valid_reqs else 0,
    )

    with open(norm_path, "w", encoding="utf-8") as f:
        for req in valid_reqs:
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
    log.info("Wrote %s", norm_path)

    with open(fail_path, "w", encoding="utf-8") as f:
        for failure in failures:
            f.write(json.dumps(failure, ensure_ascii=False) + "\n")
    log.info("Wrote %s (%d failures)", fail_path, len(failures))

    return str(norm_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize and deduplicate extracted requirements"
    )
    parser.add_argument(
        "requirements_jsonl",
        type=str,
        help="Path to extracted_requirements.jsonl from Step C",
    )
    parser.add_argument(
        "--chunks-jsonl",
        type=str,
        default=None,
        help="Path to chunks.jsonl from Step B (for page references). "
             "Auto-detected if not provided.",
    )
    parser.add_argument(
        "--source-pdf-path",
        type=str,
        default=None,
        help="Path to original PDF file (for document identity hashing). "
             "If not provided, document_id fields will be empty.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: same directory as input)",
    )
    parser.add_argument(
        "--extraction-model",
        type=str,
        default="llama3.1:8b-instruct-q4_K_M",
        help="Name of the LLM used in Step C extraction (written to schema metadata).",
    )
    args = parser.parse_args()

    reqs_path = Path(args.requirements_jsonl).resolve()
    if not reqs_path.exists():
        log.error("Input file not found: %s", reqs_path)
        sys.exit(1)

    # Auto-detect chunks file if not provided
    if args.chunks_jsonl:
        chunks_path = str(Path(args.chunks_jsonl).resolve())
    else:
        from core.artifact_resolver import doc_key_from_extracted_path
        stem = doc_key_from_extracted_path(reqs_path)
        chunks_path = str(reqs_path.parent / f"{stem}_chunks.jsonl")

    out_dir = Path(args.output_dir).resolve() if args.output_dir else reqs_path.parent

    run(
        str(reqs_path),
        chunks_path,
        args.source_pdf_path or "",
        str(out_dir),
        extraction_model=args.extraction_model,
    )


if __name__ == "__main__":
    main()
