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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
PIPELINE_VERSION = "1.0"

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


def normalize_text(text: str) -> str:
    """Normalize whitespace and casing for comparison."""
    return re.sub(r"\s+", " ", text.strip().lower())


def deduplicate_requirements(requirements: list[dict]) -> list[dict]:
    """Remove duplicate requirements based on two keys:
    1. source_ref + normalized description (original)
    2. source_ref + normalized source_quote (catches near-identical quotes)

    When duplicates exist, keep the one with more domain tags and longer source_quote.
    """
    seen: dict[str, dict] = {}
    for req in requirements:
        # Two dedupe keys: description-based and quote-based
        desc_key = f"{req.get('source_ref', '')}::desc::{normalize_text(req['description'])}"
        quote = normalize_text(req.get("source_quote", ""))
        quote_key = f"{req.get('source_ref', '')}::quote::{quote}" if quote else None

        # Check if either key was seen
        existing_key = None
        if desc_key in seen:
            existing_key = desc_key
        elif quote_key and quote_key in seen:
            existing_key = quote_key

        if existing_key:
            existing = seen[existing_key]
            new_score = len(req.get("domain_tags", [])) * 10 + len(req.get("source_quote", ""))
            old_score = len(existing.get("domain_tags", [])) * 10 + len(existing.get("source_quote", ""))
            if new_score > old_score:
                seen[existing_key] = req
        else:
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

    Returns:
        Path to the requirements_normalized.jsonl file that was written (str).
    """
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
    stem = reqs_path.stem.replace("_extracted_requirements", "")
    norm_path = out_dir / f"{stem}_requirements_normalized.jsonl"
    fail_path = out_dir / f"{stem}_normalization_failures.jsonl"

    log.info("Loading requirements from: %s", reqs_path)
    raw_reqs = load_jsonl(reqs_path)
    log.info("Loaded %d raw requirements", len(raw_reqs))

    chunk_page_map = {}
    if chunks_path.exists():
        log.info("Loading chunk metadata from: %s", chunks_path)
        chunks = load_jsonl(chunks_path)
        chunk_page_map = build_chunk_page_map(chunks)
        log.info("Loaded page references for %d chunks", len(chunk_page_map))
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
        domain_tags = [t for t in domain_tags if t in VALID_DOMAIN_TAGS]

        if req_type not in VALID_REQUIREMENT_TYPES:
            req_type = ""

        page_start = None
        page_end = None
        if chunk_id is not None and chunk_id in chunk_page_map:
            page_start, page_end = chunk_page_map[chunk_id]

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
        stem = reqs_path.stem.replace("_extracted_requirements", "")
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
