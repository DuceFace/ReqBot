"""Docs service — lists indexed documents from the processed JSONL directory.

Returns structured data; all display logic stays in cli/reqbot.py.
"""
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
        try:
            count = sum(1 for line in open(path, encoding="utf-8") if line.strip())
        except IOError as e:
            log.warning("Could not read %s: %s", path, e)
            count = 0
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
