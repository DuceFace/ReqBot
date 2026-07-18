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
        doc_key = p.stem.replace("_requirements_normalized", "")
        if doc_key not in latest or p.stat().st_mtime > latest[doc_key].stat().st_mtime:
            latest[doc_key] = p

    docs = []
    total_reqs = 0

    for doc_key, path in sorted(latest.items()):
        source_pdf = ""
        count = 0
        first_record = True
        try:
            with open(path, encoding="utf-8") as _f:
                for _line in _f:
                    if _line.strip():
                        if first_record:
                            try:
                                source_pdf = json.loads(_line).get("source_pdf", "")
                            except Exception:
                                pass
                            first_record = False
                        count += 1
        except IOError as e:
            log.warning("Could not read %s: %s", path, e)
        total_reqs += count

        # Detect pdfplumber by scanning chunks for TABLE_START sentinels
        chunks = list(path.parent.glob("*_chunks.jsonl"))
        mode = "pymupdf"
        if chunks:
            with open(chunks[0], encoding="utf-8") as f:
                for line in f:
                    if "<<<TABLE_START>>>" in line:
                        mode = "pdfplumber"
                        break

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
        key = p.stem.replace("_requirements_normalized", "")
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
