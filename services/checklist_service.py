"""Checklist service — generates audit checklist items from validated requirement records.

Prefers enriched requirement output (*_requirements_enriched.jsonl, Step D.5) when
available for a document, so checklist items reflect final domain_tags, description,
and requirement_type. Falls back to normalized output (*_requirements_normalized.jsonl,
Step D) when enriched output does not yet exist.

Returns structured data; all display and export logic stays in cli/reqbot.py and
pipeline/checklist_export.py (WP-21.4).
"""
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.profiles import load_profile

log = logging.getLogger(__name__)

CONFIDENCE_REVIEW_THRESHOLD = 0.8


def _resolve_doc_path(processed_dir: Path, doc_key: str) -> Path:
    """Return the best requirements JSONL path for doc_key.

    Groups candidates by run directory (parent dir). Picks the most recent run
    using the latest file mtime within each run, then prefers enriched over
    normalized within that run. This prevents an older enriched file from a
    previous run from beating a newer normalized file from a later run.

    Raises ValueError if no matching file is found.
    """
    runs: dict[Path, dict[str, Path]] = {}
    for suffix in ("enriched", "normalized"):
        suffix_str = f"_requirements_{suffix}"
        for p in processed_dir.rglob(f"*{suffix_str}.jsonl"):
            stem = p.stem
            if stem.endswith(suffix_str) and stem[: -len(suffix_str)] == doc_key:
                runs.setdefault(p.parent, {})[suffix] = p

    if not runs:
        raise ValueError(
            f"No requirements JSONL found for doc_key '{doc_key}' in {processed_dir}"
        )

    latest_run = max(
        runs,
        key=lambda d: max(p.stat().st_mtime for p in runs[d].values()),
    )
    candidates = runs[latest_run]
    return candidates.get("enriched") or candidates["normalized"]


def _checklist_item_id(requirement_ids: list[str]) -> str:
    """Derive a stable deterministic CHK- ID from one or more requirement IDs."""
    key = "|".join(sorted(requirement_ids))
    return "CHK-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _page_refs(req: dict) -> list[int]:
    """Derive page reference list from page_start / page_end fields."""
    try:
        start = req.get("page_start")
        if start is None:
            return []
        start = int(start)
        end = req.get("page_end")
        if end is not None:
            end = int(end)
            if end > start:
                return list(range(start, end + 1))
        return [start]
    except (ValueError, TypeError):
        return []


def generate(processed_dir: Path, doc_key: str, profile_name: str) -> dict:
    """Generate a checklist envelope dict from normalized requirements for doc_key.

    Raises FileNotFoundError if processed_dir does not exist.
    Raises ValueError if doc_key is not found in processed_dir.
    Raises ValueError if profile_name is not a valid profile.
    """
    if not processed_dir.exists():
        raise FileNotFoundError(f"processed_dir not found: {processed_dir}")

    load_profile(profile_name)  # validate profile exists and is well-formed; reserved for WP-21.3 content
    jsonl_path = _resolve_doc_path(processed_dir, doc_key)

    items = []
    document_id = ""
    source_pdf = ""
    skipped = 0

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                log.warning("Skipping malformed JSON line in %s", jsonl_path)
                continue

            if not document_id:
                document_id = req.get("document_id", "")
                source_pdf = req.get("source_pdf", "")

            req_id = req.get("requirement_id", "")
            source_quote = req.get("source_quote", "")

            # Hard provenance anchors — missing either means no checklist item
            if not req_id or not source_quote:
                skipped += 1
                log.debug("Skipping record — missing requirement_id or source_quote")
                continue

            page_refs = _page_refs(req)
            source_ref = req.get("source_ref") or ""
            section_title_path = req.get("section_title_path") or []
            domain_tags = req.get("domain_tags") or []
            confidence = req.get("confidence")
            if confidence is None:
                confidence = 0.0

            source_profile = req.get("domain_profile") or "cybersecurity"

            review_reasons: list[str] = []
            if not source_ref:
                review_reasons.append("missing-source-ref")
            if not section_title_path:
                review_reasons.append("missing-section-title-path")
            if not page_refs:
                review_reasons.append("missing-page-refs")
            if not domain_tags:
                review_reasons.append("missing-domain-tags")
            if confidence < CONFIDENCE_REVIEW_THRESHOLD:
                review_reasons.append("low-confidence")
            if source_profile != profile_name:
                review_reasons.append("profile-mismatch")

            items.append({
                "checklist_item_id": _checklist_item_id([req_id]),
                "requirement_ids": [req_id],
                "domain_tags": domain_tags,
                "source_ref": source_ref,
                "page_refs": page_refs,
                "section_title_path": section_title_path,
                "source_quote": source_quote,
                "audit_question": "",
                "evidence_to_request": [],
                "generation_notes": "",
                "assessor_notes": "",
                "status": "not-started",
                "confidence": confidence,
                "requires_human_review": bool(review_reasons),
                "review_reasons": review_reasons,
            })

    if skipped:
        log.info("Skipped %d record(s) missing requirement_id or source_quote", skipped)

    return {
        "format": "reqbot-checklist",
        "format_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": {
            "tool": "reqbot",
            "command": f"reqbot checklist --doc {doc_key} --profile {profile_name}",
        },
        "document": {
            "document_id": document_id,
            "source_pdf": source_pdf,
        },
        "profile": profile_name,
        "summary": {
            "total_items": len(items),
            "items_requiring_review": sum(1 for i in items if i["requires_human_review"]),
        },
        "items": items,
    }
