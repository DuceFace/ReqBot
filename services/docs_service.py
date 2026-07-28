"""Docs service — lists indexed documents from the processed JSONL directory.

Returns structured data; all display logic stays in cli/reqbot.py.
"""
import json
import logging
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.artifact_resolver import doc_key_from_requirements_path

log = logging.getLogger(__name__)


def list_docs(processed_dir: Path) -> dict:
    """Scan the processed directory and return document listing.

    Returns a dict with keys:
      docs: list of {doc_key, path, count, mode, run_date}
      total_reqs: int
      total_docs: int
    """
    if not processed_dir.exists():
        raise FileNotFoundError(f"processed_dir not found: {processed_dir}")
    all_files = sorted(processed_dir.rglob("*_requirements_normalized.jsonl"))

    # Deduplicate by doc stem — keep the most recently modified file per document
    latest: dict[str, Path] = {}
    for p in all_files:
        doc_key = doc_key_from_requirements_path(p)
        if doc_key not in latest or p.stat().st_mtime > latest[doc_key].stat().st_mtime:
            latest[doc_key] = p

    docs = []
    total_reqs = 0

    for doc_key, path in sorted(latest.items()):
        source_pdf = ""
        domain_profile = "cybersecurity"
        count = 0
        first_record = True
        try:
            with open(path, encoding="utf-8") as _f:
                for _line in _f:
                    if _line.strip():
                        if first_record:
                            try:
                                rec = json.loads(_line)
                                source_pdf = rec.get("source_pdf", "")
                                domain_profile = rec.get("domain_profile") or "cybersecurity"
                            except Exception:
                                pass
                            first_record = False
                        count += 1
        except IOError as e:
            log.warning("Could not read %s: %s", path, e)
        total_reqs += count

        # WP-33.2: prefer stats.json's authoritative layout_mode_used (written by
        # run_pipeline.py since this WP) over guessing. Falls back to inspecting
        # chunks.jsonl for documents ingested before this field existed --
        # section_ref_path key presence on any chunk is docling's own signature
        # (legacy chunking never writes that key at all, confirmed during Phase 32's
        # investigation); a TABLE_START sentinel is pdfplumber's. This fallback also
        # fixes a real pre-existing bug: the old logic only ever checked for the
        # pdfplumber sentinel, so it silently mislabeled every already-ingested
        # docling document as "pymupdf".
        # Resolve this document's own stats/chunks files by deterministic name
        # (doc_key-prefixed), not a directory-wide glob()[0] -- an explicitly
        # shared --output-dir holding artifacts for more than one PDF stem would
        # otherwise let one document's stats/chunks leak into another's row
        # (Codex review, PR #155).
        mode = "pymupdf"
        skip_sections_applied = None
        stats_path = path.parent / f"{doc_key}_stats.json"
        stats_layout_mode = ""
        if stats_path.exists():
            try:
                with open(stats_path, encoding="utf-8") as f:
                    stats = json.load(f)
                pipeline_stats = stats.get("pipeline", {})
                stats_layout_mode = pipeline_stats.get("layout_mode_used", "")
                if "skip_sections_applied" in pipeline_stats:
                    skip_sections_applied = pipeline_stats["skip_sections_applied"]
            except Exception as e:
                log.warning("Could not read %s: %s", stats_path, e)

        if stats_layout_mode:
            mode = stats_layout_mode
        else:
            chunks_path = path.parent / f"{doc_key}_chunks.jsonl"
            if chunks_path.exists():
                with open(chunks_path, encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        if "<<<TABLE_START>>>" in line:
                            mode = "pdfplumber"
                            break
                        try:
                            if "section_ref_path" in json.loads(line):
                                mode = "docling"
                                break
                        except json.JSONDecodeError:
                            pass

        # Run date from directory timestamp suffix
        dir_name = path.parent.name
        ts_match = re.search(r"_(\d{4})(\d{2})(\d{2})_\d{6}$", dir_name)
        run_date = (
            f"{ts_match.group(1)}-{ts_match.group(2)}-{ts_match.group(3)}"
            if ts_match else "unknown"
        )

        docs.append({
            "doc_key": doc_key,
            "source_pdf": source_pdf,
            "path": str(path),
            "count": count,
            "mode": mode,
            "run_date": run_date,
            "profile": domain_profile,
            # WP-33.2: True/False if the profile's skip_sections was configured for
            # this ingest, None if nothing was configured to apply in the first
            # place. Only known for documents ingested since this WP (stats.json
            # written before it has no skip_sections_applied key at all).
            "skip_sections_applied": skip_sections_applied,
        })

    return {
        "docs": docs,
        "total_reqs": total_reqs,
        "total_docs": len(latest),
    }


def resolve_source_pdfs(processed_dir: Path, doc_keys: list[str]) -> dict[str, str]:
    """Resolve a list of doc_keys to their canonical source_pdf values.

    Reads only the first record of each matching JSONL — much cheaper than
    list_docs() when the caller only needs source_pdf for a small set of keys.

    Returns a dict mapping each requested doc_key to its source_pdf (empty
    string if not found).
    """
    all_files = sorted(processed_dir.rglob("*_requirements_normalized.jsonl"))
    latest: dict[str, Path] = {}
    for p in all_files:
        key = doc_key_from_requirements_path(p)
        if key not in latest or p.stat().st_mtime > latest[key].stat().st_mtime:
            latest[key] = p

    result: dict[str, str] = {k: "" for k in doc_keys}
    for key in doc_keys:
        path = latest.get(key)
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        result[key] = json.loads(line).get("source_pdf", "")
                        break
        except Exception as e:
            log.warning("Could not resolve source_pdf for %s: %s", key, e)
    return result
