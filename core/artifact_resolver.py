"""Shared requirements-JSONL artifact resolution.

For a given document, prefers *_requirements_gated.jsonl (Step D.6, WP-35.4)
over *_requirements_enriched.jsonl (Step D.5) over *_requirements_normalized.jsonl
(Step D) when multiple exist for the same run, and prefers the most recently
modified run when multiple runs exist for the same document ("latest run wins").

Reused by services/checklist_service.py (single doc_key lookup) and
cli/reqbot.py's cmd_reindex (bulk enumeration across all documents) so the
preference/latest-run-wins rule is defined in exactly one place. This is the
reason the gated file (WP-35.4's description-grounding gate) has to be added
here and not just wired into pipeline/run_pipeline.py's own index_path
variable — every consumer that reads a document's requirements outside a
fresh pipeline run goes through this resolver, and would otherwise keep
reading the ungated (pre-check) file forever, silently bypassing the gate.

Also home to doc_key_from_extracted_path(), used by parse_and_normalize.py.
Every stem-stripping helper here is anchored (str.endswith + slice), never a
broad str.replace() — a PDF whose own stem happens to contain one of these
suffixes as a substring (e.g. "policy_requirements_normalized_v1.pdf") would
otherwise have that substring collapsed everywhere it appears, producing a
mangled doc_key that no longer matches the real *_chunks.jsonl file and
silently breaking context indexing downstream (Codex PR #92 review).
"""
from pathlib import Path

_GATED_SUFFIX = "_requirements_gated"
_ENRICHED_SUFFIX = "_requirements_enriched"
_NORMALIZED_SUFFIX = "_requirements_normalized"
_EXTRACTED_SUFFIX = "_extracted_requirements"


def _strip_suffix(stem: str, *suffixes: str) -> str:
    """Strip the first matching suffix from stem (anchored — not a substring
    replace). Returns stem unchanged if none match."""
    for suffix in suffixes:
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def doc_key_from_requirements_path(path: Path) -> str:
    """Strip the _requirements_gated/_requirements_enriched/_requirements_normalized
    suffix from a requirements JSONL path's stem to get the canonical doc_key.

    Falls back to the bare stem if none match (defensive — every requirements
    JSONL the pipeline produces has one of these three suffixes).
    """
    return _strip_suffix(path.stem, _GATED_SUFFIX, _ENRICHED_SUFFIX, _NORMALIZED_SUFFIX)


def doc_key_from_extracted_path(path: Path) -> str:
    """Strip the _extracted_requirements suffix from a Step C output path's
    stem (extracted_requirements.jsonl) to get the canonical doc_key.

    Falls back to the bare stem if the suffix doesn't match.
    """
    return _strip_suffix(path.stem, _EXTRACTED_SUFFIX)


_TIER_ORDER = ("gated", "enriched", "normalized")


def _freshest_acceptable_tier(candidates: dict[str, Path]) -> Path:
    """Pick the best file among the gated/enriched/normalized candidates in
    one run directory.

    Prefers a higher tier only when it is not older than every lower tier
    present. A run directory can be reused across multiple invocations
    (e.g. `--skip-to D`, or `--skip-to D --skip-description-gate` /
    a failed Step D.6, WP-35.4) — Step D.5/D.6 are independently skippable,
    so a later, partial rerun can regenerate a lower tier (enriched or
    normalized) without regenerating a higher one, leaving that higher tier
    describing an older, now-inconsistent version of the data. An older
    "better" file is not actually better (Codex review, PR #169 — found via
    the exact `--skip-to D --skip-description-gate` scenario: a stale gated
    file surviving a rerun that only regenerated normalized/enriched). Falls
    through to the next tier down when that happens.
    """
    present = [t for t in _TIER_ORDER if t in candidates]
    for i, tier in enumerate(present):
        lower = present[i + 1:]
        if not lower or all(
            candidates[tier].stat().st_mtime >= candidates[t].stat().st_mtime for t in lower
        ):
            return candidates[tier]
    return candidates[present[-1]]


def resolve_latest_requirement_files(processed_dir: Path) -> dict[str, Path]:
    """Return the best requirements JSONL path for every document under processed_dir.

    Groups candidate files by (doc_key, run directory). For each doc_key, picks
    the run directory with the most recently modified candidate file within it
    ("latest run wins" — an older gated file from a previous run never beats a
    newer normalized file from a later run), then within that winning run picks
    the freshest acceptable tier (gated > enriched > normalized, but never a
    tier older than one beneath it — see _freshest_acceptable_tier).
    """
    # {doc_key: {run_dir: {"gated"|"enriched"|"normalized": Path}}}
    by_doc: dict[str, dict[Path, dict[str, Path]]] = {}

    for suffix, key in (
        (_GATED_SUFFIX, "gated"), (_ENRICHED_SUFFIX, "enriched"), (_NORMALIZED_SUFFIX, "normalized"),
    ):
        for p in processed_dir.rglob(f"*{suffix}.jsonl"):
            doc_key = doc_key_from_requirements_path(p)
            by_doc.setdefault(doc_key, {}).setdefault(p.parent, {})[key] = p

    result: dict[str, Path] = {}
    for doc_key, runs in by_doc.items():
        latest_run = max(runs, key=lambda d: max(p.stat().st_mtime for p in runs[d].values()))
        result[doc_key] = _freshest_acceptable_tier(runs[latest_run])
    return result


def resolve_requirement_file(processed_dir: Path, doc_key: str) -> Path:
    """Return the best requirements JSONL path for a single doc_key.

    Raises ValueError if doc_key is not found in processed_dir.
    """
    files = resolve_latest_requirement_files(processed_dir)
    if doc_key not in files:
        raise ValueError(f"No requirements JSONL found for doc_key '{doc_key}' in {processed_dir}")
    return files[doc_key]
