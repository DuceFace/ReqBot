import csv
import io
import json

from pipeline.checklist_export import (
    _CSV_COLUMNS,
    _csv_row,
    _csv_safe,
    to_csv,
    to_json,
    to_markdown,
)

# Minimal fully-populated checklist item for fixture use
COMPLETE_ITEM = {
    "checklist_item_id": "CHK-abcdef1234567890",
    "requirement_ids": ["REQ-abc123"],
    "domain_tags": ["access-control", "authentication"],
    "source_ref": "4.2.1",
    "page_refs": [12, 13],
    "section_title_path": ["Access Control", "MFA Policy"],
    "source_quote": "The system shall enforce MFA for all privileged accounts.",
    "audit_question": "",
    "evidence_to_request": [],
    "generation_notes": "",
    "assessor_notes": "",
    "status": "not-started",
    "confidence": 0.9,
    "requires_human_review": False,
    "review_reasons": [],
}

REVIEW_ITEM = {
    **COMPLETE_ITEM,
    "checklist_item_id": "CHK-bbbbbbbbbbbbbbbb",
    "requirement_ids": ["REQ-def456"],
    "source_ref": "",
    "section_title_path": [],
    "page_refs": [],
    "domain_tags": [],
    "confidence": 0.6,
    "requires_human_review": True,
    "review_reasons": ["missing-source-ref", "low-confidence", "missing-page-refs", "missing-section-title-path", "missing-domain-tags"],
}

ENVELOPE = {
    "format": "reqbot-checklist",
    "format_version": "1.0",
    "generated_at": "2026-07-19T12:00:00+00:00",
    "generator": {"tool": "reqbot", "command": "reqbot checklist --doc test-doc --profile cybersecurity"},
    "document": {"document_id": "abc123", "source_pdf": "test-doc.pdf"},
    "profile": "cybersecurity",
    "summary": {"total_items": 2, "items_requiring_review": 1},
    "items": [COMPLETE_ITEM, REVIEW_ITEM],
}

EMPTY_ENVELOPE = {**ENVELOPE, "summary": {"total_items": 0, "items_requiring_review": 0}, "items": []}


# --- _csv_row ---

def test_csv_row_array_joins():
    row = _csv_row(COMPLETE_ITEM)
    assert row["section_title_path"] == "Access Control > MFA Policy"
    assert row["page_refs"] == "12, 13"
    assert row["requirement_ids"] == "REQ-abc123"
    assert row["domain_tags"] == "access-control, authentication"


def test_csv_row_review_reasons_semicolon_join():
    row = _csv_row(REVIEW_ITEM)
    assert "missing-source-ref" in row["review_reasons"]
    assert ";" in row["review_reasons"]


def test_csv_row_empty_arrays_produce_empty_strings():
    row = _csv_row(REVIEW_ITEM)
    assert row["section_title_path"] == ""
    assert row["page_refs"] == ""
    assert row["domain_tags"] == ""
    assert row["review_reasons"].count(";") >= 1  # multiple reasons joined


def test_csv_row_none_arrays_produce_empty_strings():
    item = {**COMPLETE_ITEM, "section_title_path": None, "page_refs": None, "domain_tags": None, "review_reasons": None}
    row = _csv_row(item)
    assert row["section_title_path"] == ""
    assert row["page_refs"] == ""
    assert row["domain_tags"] == ""
    assert row["review_reasons"] == ""


# --- to_csv ---

def test_to_csv_returns_string():
    result = to_csv(ENVELOPE)
    assert isinstance(result, str)


def test_to_csv_column_order():
    result = to_csv(ENVELOPE)
    reader = csv.reader(io.StringIO(result))
    header = next(reader)
    assert header == _CSV_COLUMNS


def test_to_csv_row_count():
    result = to_csv(ENVELOPE)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 3  # header + 2 items


def test_to_csv_empty_items():
    result = to_csv(EMPTY_ENVELOPE)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 1  # header only


def test_to_csv_source_quote_present():
    result = to_csv(ENVELOPE)
    assert "The system shall enforce MFA" in result


def test_to_csv_requires_human_review_serialized():
    result = to_csv(ENVELOPE)
    assert "False" in result
    assert "True" in result


def test_to_csv_confidence_in_output():
    result = to_csv(ENVELOPE)
    assert "0.9" in result


def test_to_csv_no_crash_on_missing_item_fields():
    sparse_item = {"requirement_ids": ["REQ-001"], "source_quote": "Minimal."}
    checklist = {**EMPTY_ENVELOPE, "items": [sparse_item]}
    result = to_csv(checklist)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 2


# --- to_json ---

def test_to_json_returns_valid_json():
    result = to_json(ENVELOPE)
    parsed = json.loads(result)
    assert parsed["format"] == "reqbot-checklist"


def test_to_json_roundtrip_preserves_items():
    result = to_json(ENVELOPE)
    parsed = json.loads(result)
    assert len(parsed["items"]) == 2


def test_to_json_is_pretty_printed():
    result = to_json(ENVELOPE)
    assert "\n" in result


def test_to_json_empty_items():
    result = to_json(EMPTY_ENVELOPE)
    parsed = json.loads(result)
    assert parsed["items"] == []


def test_to_json_preserves_envelope_fields():
    result = to_json(ENVELOPE)
    parsed = json.loads(result)
    assert parsed["profile"] == "cybersecurity"
    assert parsed["document"]["source_pdf"] == "test-doc.pdf"


# --- to_markdown ---

def test_to_markdown_returns_string():
    result = to_markdown(ENVELOPE)
    assert isinstance(result, str)


def test_to_markdown_title_includes_source_pdf():
    result = to_markdown(ENVELOPE)
    assert "test-doc.pdf" in result


def test_to_markdown_profile_present():
    result = to_markdown(ENVELOPE)
    assert "cybersecurity" in result


def test_to_markdown_source_quote_present():
    result = to_markdown(ENVELOPE)
    assert "The system shall enforce MFA" in result


def test_to_markdown_section_title_path_in_heading():
    result = to_markdown(ENVELOPE)
    assert "Access Control" in result
    assert "MFA Policy" in result


def test_to_markdown_page_refs_in_heading():
    result = to_markdown(ENVELOPE)
    assert "p. 12" in result


def test_to_markdown_review_flag_shown_for_flagged_item():
    result = to_markdown(ENVELOPE)
    assert "Requires Review" in result
    assert "low-confidence" in result


def test_to_markdown_no_review_flag_for_clean_item():
    result = to_markdown({**EMPTY_ENVELOPE, "items": [COMPLETE_ITEM]})
    # Verify the item itself rendered (not just an empty list)
    assert "The system shall enforce MFA" in result
    assert "Requires Review" not in result


def test_to_markdown_audit_question_blank_shows_not_generated():
    result = to_markdown(ENVELOPE)
    assert "*(not generated)*" in result


def test_to_markdown_audit_question_shown_when_present():
    item = {**COMPLETE_ITEM, "audit_question": "Has MFA been enforced?"}
    checklist = {**EMPTY_ENVELOPE, "items": [item]}
    result = to_markdown(checklist)
    assert "Has MFA been enforced?" in result


def test_to_markdown_empty_items_no_crash():
    result = to_markdown(EMPTY_ENVELOPE)
    assert "test-doc.pdf" in result
    assert "0 total" in result


def test_to_markdown_item_id_and_req_id_in_output():
    result = to_markdown(ENVELOPE)
    assert "CHK-abcdef1234567890" in result
    assert "REQ-abc123" in result


def test_to_markdown_no_source_pdf_falls_back_to_document_id():
    checklist = {**EMPTY_ENVELOPE, "document": {"document_id": "abc123", "source_pdf": ""}}
    result = to_markdown(checklist)
    assert "abc123" in result


def test_to_markdown_null_confidence_renders_as_zero():
    item = {**COMPLETE_ITEM, "confidence": None}
    checklist = {**EMPTY_ENVELOPE, "items": [item]}
    result = to_markdown(checklist)
    assert "0.00" in result


# --- _csv_safe (formula injection prevention) ---

def test_csv_safe_equals_prefix_escaped():
    assert _csv_safe("=SUM(A1:A10)") == "'=SUM(A1:A10)"


def test_csv_safe_plus_prefix_escaped():
    assert _csv_safe("+1234") == "'+1234"


def test_csv_safe_minus_prefix_escaped():
    assert _csv_safe("-DROP TABLE") == "'-DROP TABLE"


def test_csv_safe_at_prefix_escaped():
    assert _csv_safe("@user") == "'@user"


def test_csv_safe_whitespace_then_formula_escaped():
    assert _csv_safe("  =dangerous") == "'  =dangerous"


def test_csv_safe_tab_then_formula_escaped():
    assert _csv_safe("\t=foo") == "'\t=foo"


def test_csv_safe_normal_text_unchanged():
    assert _csv_safe("Systems must enforce MFA.") == "Systems must enforce MFA."


def test_csv_safe_empty_string_unchanged():
    assert _csv_safe("") == ""


def test_csv_safe_whitespace_only_unchanged():
    assert _csv_safe("   ") == "   "


def test_csv_safe_nonstring_bool_unchanged():
    assert _csv_safe(True) is True


def test_csv_safe_nonstring_float_unchanged():
    assert _csv_safe(0.9) == 0.9


# --- CSV formula injection integration ---

def test_to_csv_formula_source_quote_escaped():
    item = {**COMPLETE_ITEM, "source_quote": "=HYPERLINK(\"http://evil.example\",\"click\")"}
    checklist = {**EMPTY_ENVELOPE, "items": [item]}
    result = to_csv(checklist)
    assert "'=HYPERLINK" in result


def test_to_csv_formula_source_ref_escaped():
    item = {**COMPLETE_ITEM, "source_ref": "+1.2.3"}
    checklist = {**EMPTY_ENVELOPE, "items": [item]}
    result = to_csv(checklist)
    assert "'+1.2.3" in result


def test_to_json_formula_value_not_escaped():
    """JSON export must not mutate the checklist envelope."""
    item = {**COMPLETE_ITEM, "source_quote": "=dangerous"}
    checklist = {**EMPTY_ENVELOPE, "items": [item]}
    result = to_json(checklist)
    parsed = json.loads(result)
    assert parsed["items"][0]["source_quote"] == "=dangerous"


def test_to_markdown_formula_value_not_escaped():
    """Markdown export must not apply CSV escaping."""
    item = {**COMPLETE_ITEM, "source_quote": "=Systems shall enforce MFA."}
    checklist = {**EMPTY_ENVELOPE, "items": [item]}
    result = to_markdown(checklist)
    assert "=Systems shall enforce MFA." in result
    assert "'=Systems" not in result
