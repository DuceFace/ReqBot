"""Shared requirements-JSONL artifact resolution.

For a given document, prefers *_requirements_enriched.jsonl (Step D.5) over
*_requirements_normalized.jsonl (Step D) when both exist for the same run,
and prefers the most recently modified run when multiple runs exist for the
same document ("latest run wins").

Reused by services/checklist_service.py (single doc_key lookup) and
cli/reqbot.py's cmd_reindex (bulk enumeration across all documents) so the
enriched-preference/latest-run-wins rule is defined in exactly one place.
"""
from pathlib import Path

_ENRICHED_SUFFIX = "_requirements_enriched"
_NORMALIZED_SUFFIX = "_requirements_normalized"


def resolve_latest_requirement_files(processed_dir: Path) -> dict[str, Path]:
    """Return the best requirements JSONL path for every document under processed_dir.

    Groups candidate files by (doc_key, run directory). For each doc_key, picks
    the run directory with the most recently modified candidate file within it
    ("latest run wins" — an older enriched file from a previous run never beats
    a newer normalized file from a later run), then prefers the enriched file
    over the normalized file within that winning run.
    """
    # {doc_key: {run_dir: {"enriched"|"normalized": Path}}}
    by_doc: dict[str, dict[Path, dict[str, Path]]] = {}

    for suffix, key in ((_ENRICHED_SUFFIX, "enriched"), (_NORMALIZED_SUFFIX, "normalized")):
        for p in processed_dir.rglob(f"*{suffix}.jsonl"):
            stem = p.stem
            if not stem.endswith(suffix):
                continue
            doc_key = stem[: -len(suffix)]
            by_doc.setdefault(doc_key, {}).setdefault(p.parent, {})[key] = p

    result: dict[str, Path] = {}
    for doc_key, runs in by_doc.items():
        latest_run = max(runs, key=lambda d: max(p.stat().st_mtime for p in runs[d].values()))
        candidates = runs[latest_run]
        result[doc_key] = candidates.get("enriched") or candidates["normalized"]
    return result


def resolve_requirement_file(processed_dir: Path, doc_key: str) -> Path:
    """Return the best requirements JSONL path for a single doc_key.

    Raises ValueError if doc_key is not found in processed_dir.
    """
    files = resolve_latest_requirement_files(processed_dir)
    if doc_key not in files:
        raise ValueError(f"No requirements JSONL found for doc_key '{doc_key}' in {processed_dir}")
    return files[doc_key]
