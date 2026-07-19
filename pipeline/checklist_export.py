"""Checklist export — serialize a checklist envelope dict to CSV, JSON, or Markdown.

Input:  the dict returned by services/checklist_service.py::generate()
Output: a string in the requested format; caller writes to file or stdout.

All display and export logic lives here and in cli/reqbot.py (WP-21.5).
"""
import csv
import io
import json

# CSV column order: locate → ask → record → verify → trace
_CSV_COLUMNS = [
    "source_ref",
    "section_title_path",
    "page_refs",
    "source_quote",
    "audit_question",
    "status",
    "assessor_notes",
    "requires_human_review",
    "review_reasons",
    "confidence",
    "checklist_item_id",
    "requirement_ids",
    "domain_tags",
]


def _join(values: list, sep: str) -> str:
    return sep.join(str(v) for v in values)


def _csv_row(item: dict) -> dict:
    return {
        "source_ref": item.get("source_ref", ""),
        "section_title_path": _join(item.get("section_title_path") or [], " > "),
        "page_refs": _join(item.get("page_refs") or [], ", "),
        "source_quote": item.get("source_quote", ""),
        "audit_question": item.get("audit_question", ""),
        "status": item.get("status", ""),
        "assessor_notes": item.get("assessor_notes", ""),
        "requires_human_review": item.get("requires_human_review", False),
        "review_reasons": _join(item.get("review_reasons") or [], "; "),
        "confidence": item.get("confidence", 0.0),
        "checklist_item_id": item.get("checklist_item_id", ""),
        "requirement_ids": _join(item.get("requirement_ids") or [], ", "),
        "domain_tags": _join(item.get("domain_tags") or [], ", "),
    }


def to_csv(checklist: dict) -> str:
    """Return the checklist items as a CSV string (UTF-8, Excel-friendly)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for item in checklist.get("items", []):
        writer.writerow(_csv_row(item))
    return buf.getvalue()


def to_json(checklist: dict) -> str:
    """Return the full checklist envelope as a pretty-printed JSON string."""
    return json.dumps(checklist, indent=2, default=str)


def _md_item(item: dict, index: int) -> str:
    section = _join(item.get("section_title_path") or [], " > ")
    pages = _join(item.get("page_refs") or [], ", ")
    header_parts = []
    if section:
        header_parts.append(section)
    if pages:
        header_parts.append(f"p. {pages}")
    heading = " — ".join(header_parts) if header_parts else f"Item {index}"

    lines = [f"## {heading}", ""]

    source_ref = item.get("source_ref", "")
    if source_ref:
        lines.append(f"**Source Ref:** {source_ref}  ")
    tags = _join(item.get("domain_tags") or [], ", ")
    if tags:
        lines.append(f"**Domain Tags:** {tags}  ")
    conf = item.get("confidence")
    if conf is None:
        conf = 0.0
    lines.append(f"**Confidence:** {conf:.2f}  ")
    lines.append("")

    quote = item.get("source_quote", "")
    lines.append(f"> {quote}")
    lines.append("")

    audit_q = item.get("audit_question", "")
    lines.append(f"**Audit Question:** {audit_q if audit_q else '*(not generated)*'}  ")

    status = item.get("status", "not-started")
    assessor = item.get("assessor_notes", "")
    lines.append(f"**Status:** {status}  ")
    lines.append(f"**Assessor Notes:** {assessor if assessor else '*(none)*'}  ")
    lines.append("")

    if item.get("requires_human_review"):
        reasons = _join(item.get("review_reasons") or [], "; ")
        lines.append(f"> ⚠ **Requires Review:** {reasons}  ")
        lines.append("")

    req_ids = _join(item.get("requirement_ids") or [], ", ")
    lines.append(f"*ID: {item.get('checklist_item_id', '')} | Req: {req_ids}*")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def to_markdown(checklist: dict) -> str:
    """Return the checklist as a Markdown string."""
    doc = checklist.get("document", {})
    source_pdf = doc.get("source_pdf", "")
    title = source_pdf if source_pdf else doc.get("document_id", "Unknown Document")

    summary = checklist.get("summary", {})
    total = summary.get("total_items", 0)
    review_count = summary.get("items_requiring_review", 0)

    lines = [
        f"# Checklist: {title}",
        "",
        f"**Profile:** {checklist.get('profile', '')}  ",
        f"**Generated:** {checklist.get('generated_at', '')}  ",
        f"**Items:** {total} total, {review_count} requiring review  ",
        "",
        "---",
        "",
    ]

    for i, item in enumerate(checklist.get("items", []), start=1):
        lines.append(_md_item(item, i))

    return "\n".join(lines)
