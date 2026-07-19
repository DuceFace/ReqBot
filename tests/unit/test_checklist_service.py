import json
from pathlib import Path

import pytest

from services.checklist_service import (
    CONFIDENCE_REVIEW_THRESHOLD,
    _checklist_item_id,
    _page_refs,
    generate,
)

# A fully-populated requirement that should produce a clean item with no review flags
COMPLETE_REQ = {
    "requirement_id": "REQ-abc123",
    "source_quote": "Systems must enforce role-based access control.",
    "source_ref": "1.1",
    "source_pdf": "test.pdf",
    "document_id": "abc123def456ab01",
    "section_title_path": ["Access Control"],
    "domain_tags": ["access-control"],
    "confidence": 0.9,
    "page_start": 3,
    "page_end": 3,
}


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _make_doc(tmp_path: Path, doc_key: str, records: list[dict]) -> Path:
    """Write a normalized JSONL for doc_key and return processed_dir."""
    run_dir = tmp_path / f"{doc_key}_20260101_120000"
    run_dir.mkdir(exist_ok=True)
    _write_jsonl(run_dir / f"{doc_key}_requirements_normalized.jsonl", records)
    return tmp_path


def _make_enriched_doc(tmp_path: Path, doc_key: str, records: list[dict]) -> Path:
    """Write an enriched JSONL for doc_key alongside a normalized stub."""
    run_dir = tmp_path / f"{doc_key}_20260101_120000"
    run_dir.mkdir(exist_ok=True)
    # Normalized file must exist (pipeline writes both); enriched is the preferred source
    _write_jsonl(run_dir / f"{doc_key}_requirements_normalized.jsonl", records)
    _write_jsonl(run_dir / f"{doc_key}_requirements_enriched.jsonl", records)
    return tmp_path


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_checklist_item_id_prefix():
    assert _checklist_item_id(["REQ-abc"]).startswith("CHK-")


def test_checklist_item_id_deterministic():
    assert _checklist_item_id(["REQ-abc"]) == _checklist_item_id(["REQ-abc"])


def test_checklist_item_id_length():
    # CHK- (4) + 16 hex chars = 20
    assert len(_checklist_item_id(["REQ-abc"])) == 20


def test_checklist_item_id_multi_req_order_independent():
    assert _checklist_item_id(["REQ-a", "REQ-b"]) == _checklist_item_id(["REQ-b", "REQ-a"])


def test_checklist_item_id_differs_by_content():
    assert _checklist_item_id(["REQ-a"]) != _checklist_item_id(["REQ-b"])


def test_page_refs_single_page():
    assert _page_refs({"page_start": 3, "page_end": 3}) == [3]


def test_page_refs_multi_page():
    assert _page_refs({"page_start": 3, "page_end": 5}) == [3, 4, 5]


def test_page_refs_end_equals_start():
    assert _page_refs({"page_start": 7, "page_end": 7}) == [7]


def test_page_refs_missing_start():
    assert _page_refs({}) == []
    assert _page_refs({"page_end": 5}) == []


def test_page_refs_no_end():
    assert _page_refs({"page_start": 4}) == [4]


# ---------------------------------------------------------------------------
# generate() — envelope structure
# ---------------------------------------------------------------------------

def test_generate_returns_envelope_keys(tmp_path):
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert result["format"] == "reqbot-checklist"
    assert result["format_version"] == "1.0"
    assert "generated_at" in result
    assert result["generator"]["tool"] == "reqbot"
    assert "testdoc" in result["generator"]["command"]
    assert result["document"]["document_id"] == COMPLETE_REQ["document_id"]
    assert result["document"]["source_pdf"] == COMPLETE_REQ["source_pdf"]
    assert result["profile"] == "cybersecurity"
    assert "summary" in result
    assert "items" in result


def test_generate_summary_counts(tmp_path):
    low_conf = {**COMPLETE_REQ, "requirement_id": "REQ-low", "confidence": 0.6}
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ, low_conf])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert result["summary"]["total_items"] == 2
    assert result["summary"]["items_requiring_review"] == 1


# ---------------------------------------------------------------------------
# generate() — item field completeness
# ---------------------------------------------------------------------------

def test_generate_item_has_all_required_fields(tmp_path):
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    required = [
        "checklist_item_id", "requirement_ids", "domain_tags", "source_ref",
        "page_refs", "section_title_path", "source_quote", "audit_question",
        "evidence_to_request", "generation_notes", "assessor_notes", "status",
        "confidence", "requires_human_review", "review_reasons",
    ]
    for field in required:
        assert field in item, f"Missing field: {field}"


def test_generate_item_requirement_ids_populated(tmp_path):
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["requirement_ids"] == [COMPLETE_REQ["requirement_id"]]


def test_generate_item_provenance_copied(tmp_path):
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["source_quote"] == COMPLETE_REQ["source_quote"]
    assert item["source_ref"] == COMPLETE_REQ["source_ref"]
    assert item["section_title_path"] == COMPLETE_REQ["section_title_path"]
    assert item["domain_tags"] == COMPLETE_REQ["domain_tags"]
    assert item["page_refs"] == [3]
    assert item["confidence"] == COMPLETE_REQ["confidence"]


# ---------------------------------------------------------------------------
# generate() — assessor-owned fields
# ---------------------------------------------------------------------------

def test_generate_status_initialized_to_not_started(tmp_path):
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["status"] == "not-started"


def test_generate_assessor_notes_blank_at_generation(tmp_path):
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["assessor_notes"] == ""


def test_generate_audit_question_blank_at_generation(tmp_path):
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["audit_question"] == ""


# ---------------------------------------------------------------------------
# generate() — hard provenance skip rules
# ---------------------------------------------------------------------------

def test_generate_skips_record_missing_requirement_id(tmp_path):
    rec = {k: v for k, v in COMPLETE_REQ.items() if k != "requirement_id"}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert result["items"] == []
    assert result["summary"]["total_items"] == 0


def test_generate_skips_record_empty_requirement_id(tmp_path):
    rec = {**COMPLETE_REQ, "requirement_id": ""}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert result["items"] == []


def test_generate_skips_record_missing_source_quote(tmp_path):
    rec = {k: v for k, v in COMPLETE_REQ.items() if k != "source_quote"}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert result["items"] == []


def test_generate_skips_record_empty_source_quote(tmp_path):
    rec = {**COMPLETE_REQ, "source_quote": ""}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert result["items"] == []


def test_generate_skip_does_not_flag_item(tmp_path):
    """Skipped records must produce zero items — not a flagged item."""
    rec = {**COMPLETE_REQ, "requirement_id": ""}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert len(result["items"]) == 0


# ---------------------------------------------------------------------------
# generate() — weak provenance flag rules
# ---------------------------------------------------------------------------

def test_generate_flags_missing_source_ref(tmp_path):
    rec = {**COMPLETE_REQ, "source_ref": ""}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["requires_human_review"] is True
    assert "missing-source-ref" in item["review_reasons"]


def test_generate_flags_missing_domain_tags(tmp_path):
    rec = {**COMPLETE_REQ, "domain_tags": []}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["requires_human_review"] is True
    assert "missing-domain-tags" in item["review_reasons"]


def test_generate_flags_missing_section_title_path(tmp_path):
    rec = {**COMPLETE_REQ, "section_title_path": []}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["requires_human_review"] is True
    assert "missing-section-title-path" in item["review_reasons"]


def test_generate_flags_missing_page_refs(tmp_path):
    rec = {k: v for k, v in COMPLETE_REQ.items() if k not in ("page_start", "page_end")}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["requires_human_review"] is True
    assert "missing-page-refs" in item["review_reasons"]


def test_generate_weak_provenance_creates_item_not_skips(tmp_path):
    """A record missing only weak provenance must produce an item, not be skipped."""
    rec = {**COMPLETE_REQ, "source_ref": "", "domain_tags": []}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert len(result["items"]) == 1


# ---------------------------------------------------------------------------
# generate() — confidence threshold
# ---------------------------------------------------------------------------

def test_generate_low_confidence_flags_review(tmp_path):
    rec = {**COMPLETE_REQ, "confidence": CONFIDENCE_REVIEW_THRESHOLD - 0.01}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["requires_human_review"] is True
    assert "low-confidence" in item["review_reasons"]


def test_generate_at_threshold_does_not_flag(tmp_path):
    rec = {**COMPLETE_REQ, "confidence": CONFIDENCE_REVIEW_THRESHOLD}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert "low-confidence" not in item["review_reasons"]


def test_generate_high_confidence_complete_record_no_review_flag(tmp_path):
    rec = {**COMPLETE_REQ, "confidence": 1.0}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["requires_human_review"] is False
    assert item["review_reasons"] == []


def test_generate_missing_confidence_treated_as_zero(tmp_path):
    rec = {k: v for k, v in COMPLETE_REQ.items() if k != "confidence"}
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert item["confidence"] == 0.0
    assert "low-confidence" in item["review_reasons"]


# ---------------------------------------------------------------------------
# generate() — domain_profile fallback (pre-Phase-20 records)
# ---------------------------------------------------------------------------

def test_generate_does_not_crash_on_missing_domain_profile(tmp_path):
    """Pre-Phase-20 records have no domain_profile field — must not crash."""
    rec = {k: v for k, v in COMPLETE_REQ.items() if k != "domain_profile"}
    assert "domain_profile" not in rec
    processed_dir = _make_doc(tmp_path, "testdoc", [rec])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert len(result["items"]) == 1


# ---------------------------------------------------------------------------
# generate() — multiple items, ordering, ID stability
# ---------------------------------------------------------------------------

def test_generate_item_count_matches_valid_records(tmp_path):
    reqs = [
        {**COMPLETE_REQ, "requirement_id": f"REQ-{i:04d}"}
        for i in range(5)
    ]
    processed_dir = _make_doc(tmp_path, "testdoc", reqs)
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert result["summary"]["total_items"] == 5


def test_generate_ids_are_deterministic_across_runs(tmp_path):
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    id1 = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]["checklist_item_id"]
    id2 = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]["checklist_item_id"]
    assert id1 == id2


def test_generate_skipped_and_valid_mixed(tmp_path):
    no_id = {k: v for k, v in COMPLETE_REQ.items() if k != "requirement_id"}
    valid = {**COMPLETE_REQ, "requirement_id": "REQ-valid"}
    processed_dir = _make_doc(tmp_path, "testdoc", [no_id, valid, no_id])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert result["summary"]["total_items"] == 1
    assert result["items"][0]["requirement_ids"] == ["REQ-valid"]


# ---------------------------------------------------------------------------
# generate() — source file preference (enriched > normalized)
# ---------------------------------------------------------------------------

def test_generate_prefers_enriched_when_both_exist(tmp_path):
    """When enriched and normalized files both exist, enriched must be used."""
    run_dir = tmp_path / "testdoc_20260101_120000"
    run_dir.mkdir()
    # Normalized: record with no domain_tags (would trigger missing-domain-tags flag)
    normalized_rec = {**COMPLETE_REQ, "domain_tags": []}
    _write_jsonl(run_dir / "testdoc_requirements_normalized.jsonl", [normalized_rec])
    # Enriched: same record with domain_tags populated
    enriched_rec = {**COMPLETE_REQ, "domain_tags": ["access-control"]}
    _write_jsonl(run_dir / "testdoc_requirements_enriched.jsonl", [enriched_rec])
    item = generate(tmp_path, "testdoc", "cybersecurity")["items"][0]
    assert item["domain_tags"] == ["access-control"]
    assert "missing-domain-tags" not in item["review_reasons"]


def test_generate_falls_back_to_normalized_when_no_enriched(tmp_path):
    """When no enriched file exists, normalized JSONL is used without error."""
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    result = generate(processed_dir, "testdoc", "cybersecurity")
    assert result["summary"]["total_items"] == 1


def test_generate_enriched_domain_tags_suppress_review_flag(tmp_path):
    """Enriched domain_tags prevent the missing-domain-tags review flag."""
    enriched_rec = {**COMPLETE_REQ, "domain_tags": ["audit-and-logging"]}
    processed_dir = _make_enriched_doc(tmp_path, "testdoc", [enriched_rec])
    item = generate(processed_dir, "testdoc", "cybersecurity")["items"][0]
    assert "missing-domain-tags" not in item["review_reasons"]
    assert item["requires_human_review"] is False


# ---------------------------------------------------------------------------
# generate() — error cases
# ---------------------------------------------------------------------------

def test_generate_raises_on_missing_processed_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate(tmp_path / "does_not_exist", "testdoc", "cybersecurity")


def test_generate_raises_on_unknown_doc_key(tmp_path):
    _make_doc(tmp_path, "existing-doc", [COMPLETE_REQ])
    with pytest.raises(ValueError, match="no_such_doc"):
        generate(tmp_path, "no_such_doc", "cybersecurity")


def test_generate_raises_on_invalid_profile(tmp_path):
    processed_dir = _make_doc(tmp_path, "testdoc", [COMPLETE_REQ])
    with pytest.raises((ValueError, FileNotFoundError)):
        generate(processed_dir, "testdoc", "nonexistent-profile")


def test_generate_empty_jsonl_produces_no_items(tmp_path):
    run_dir = tmp_path / "testdoc_20260101_120000"
    run_dir.mkdir()
    (run_dir / "testdoc_requirements_normalized.jsonl").write_text("")
    result = generate(tmp_path, "testdoc", "cybersecurity")
    assert result["items"] == []
    assert result["summary"]["total_items"] == 0


def test_generate_blank_lines_skipped(tmp_path):
    run_dir = tmp_path / "testdoc_20260101_120000"
    run_dir.mkdir()
    content = "\n\n" + json.dumps(COMPLETE_REQ) + "\n\n"
    (run_dir / "testdoc_requirements_normalized.jsonl").write_text(content)
    result = generate(tmp_path, "testdoc", "cybersecurity")
    assert result["summary"]["total_items"] == 1
