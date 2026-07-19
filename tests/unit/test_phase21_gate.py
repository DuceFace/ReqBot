"""Phase 21 integration gate (WP-21.6).

Verifies the full Phase 21 checklist pipeline end-to-end against fixture JSONL,
with no mocking of the service or export layers. Also confirms that existing
CLI-adjacent services (docs) still function correctly.

Commands verified:
  reqbot checklist --doc SYNTHETIC_TEST_DOC --format csv
  reqbot checklist --doc SYNTHETIC_TEST_DOC --format json
  reqbot checklist --doc SYNTHETIC_TEST_DOC --format md
  reqbot docs  (via docs_service.list_docs)

Commands reqbot ask and reqbot trace require a live Qdrant instance and are
exercised by their respective unit tests (test_ask_service.py,
test_trace_service.py) which mock the Qdrant layer.
"""
import csv
import io
import json
import shutil
from pathlib import Path

import pytest

from pipeline.checklist_export import to_csv, to_json, to_markdown
from services.checklist_service import generate
from services.docs_service import list_docs

# Path to the sample fixture shipped with the test suite
_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_normalized_reqs.jsonl"

# doc_key derived from fixture source_pdf "SYNTHETIC_TEST_DOC.pdf"
DOC_KEY = "SYNTHETIC_TEST_DOC"


@pytest.fixture()
def processed_dir(tmp_path: Path) -> Path:
    """Build a minimal processed directory tree from the sample fixture.

    Structure mirrors real pipeline output:
      processed_dir/
        SYNTHETIC_TEST_DOC_20260101_000000/
          SYNTHETIC_TEST_DOC_requirements_normalized.jsonl
    """
    run_dir = tmp_path / f"{DOC_KEY}_20260101_000000"
    run_dir.mkdir()
    shutil.copy(_FIXTURE, run_dir / f"{DOC_KEY}_requirements_normalized.jsonl")
    return tmp_path


# ---------------------------------------------------------------------------
# reqbot checklist --format csv
# ---------------------------------------------------------------------------

def test_csv_generation_succeeds(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_csv(checklist)
    assert isinstance(result, str)
    assert len(result) > 0


def test_csv_has_correct_column_order(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_csv(checklist)
    reader = csv.reader(io.StringIO(result))
    header = next(reader)
    # locate
    assert header[0] == "source_ref"
    assert header[1] == "section_title_path"
    assert header[2] == "page_refs"
    # ask
    assert header[3] == "source_quote"
    assert header[4] == "audit_question"
    # record
    assert header[5] == "status"
    assert header[6] == "assessor_notes"


def test_csv_row_count_matches_fixture(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_csv(checklist)
    reader = csv.reader(io.StringIO(result))
    rows = list(reader)
    # header + 1 row per fixture record (5 records, all have requirement_id + source_quote)
    assert len(rows) == 6


def test_csv_source_quotes_preserved(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_csv(checklist)
    assert "role-based access control" in result
    assert "Multi-factor authentication" in result


def test_csv_requirement_ids_present(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_csv(checklist)
    assert "REQ-a1b2c3d4e5f6" in result


# ---------------------------------------------------------------------------
# reqbot checklist --format json
# ---------------------------------------------------------------------------

def test_json_generation_succeeds(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_json(checklist)
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed["format"] == "reqbot-checklist"


def test_json_envelope_fields_present(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_json(checklist)
    parsed = json.loads(result)
    assert "format_version" in parsed
    assert "generated_at" in parsed
    assert "generator" in parsed
    assert "document" in parsed
    assert "profile" in parsed
    assert "summary" in parsed
    assert "items" in parsed


def test_json_item_count_matches_fixture(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_json(checklist)
    parsed = json.loads(result)
    assert parsed["summary"]["total_items"] == 5
    assert len(parsed["items"]) == 5


def test_json_every_item_has_provenance_anchors(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_json(checklist)
    parsed = json.loads(result)
    for item in parsed["items"]:
        assert item["requirement_ids"], f"item missing requirement_ids: {item}"
        assert item["source_quote"], f"item missing source_quote: {item}"


def test_json_checklist_item_ids_are_deterministic(processed_dir):
    checklist_a = generate(processed_dir, DOC_KEY, "cybersecurity")
    checklist_b = generate(processed_dir, DOC_KEY, "cybersecurity")
    ids_a = [i["checklist_item_id"] for i in checklist_a["items"]]
    ids_b = [i["checklist_item_id"] for i in checklist_b["items"]]
    assert ids_a == ids_b


def test_json_document_fields_populated(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_json(checklist)
    parsed = json.loads(result)
    assert parsed["document"]["source_pdf"] == "SYNTHETIC_TEST_DOC.pdf"
    assert parsed["document"]["document_id"] == "abc123def456ab01"


def test_json_profile_field_set_to_cybersecurity(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_json(checklist)
    parsed = json.loads(result)
    assert parsed["profile"] == "cybersecurity"


# ---------------------------------------------------------------------------
# reqbot checklist --format md
# ---------------------------------------------------------------------------

def test_markdown_generation_succeeds(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_markdown(checklist)
    assert isinstance(result, str)
    assert len(result) > 0


def test_markdown_title_contains_source_pdf(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_markdown(checklist)
    assert "SYNTHETIC_TEST_DOC.pdf" in result


def test_markdown_source_quotes_in_blockquotes(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_markdown(checklist)
    assert "> All systems must enforce role-based access control policies." in result


def test_markdown_review_flag_shown_for_low_confidence(processed_dir):
    # Fixture records have no confidence field → 0.0 → below 0.8 threshold
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_markdown(checklist)
    assert "Requires Review" in result
    assert "low-confidence" in result


def test_markdown_audit_question_shows_not_generated(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_markdown(checklist)
    assert "*(not generated)*" in result


def test_markdown_section_headings_present(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    result = to_markdown(checklist)
    assert "Access Control" in result
    assert "Audit and Logging" in result


# ---------------------------------------------------------------------------
# reqbot checklist — service-level envelope assertions
# ---------------------------------------------------------------------------

def test_fixture_records_produce_five_items(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    assert len(checklist["items"]) == 5


def test_assessor_fields_initialized_correctly(processed_dir):
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    for item in checklist["items"]:
        assert item["status"] == "not-started"
        assert item["assessor_notes"] == ""
        assert item["audit_question"] == ""


def test_missing_page_start_flags_review(processed_dir):
    # Fixture records have no page_start → page_refs=[] → missing-page-refs
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    for item in checklist["items"]:
        assert item["requires_human_review"] is True
        assert "missing-page-refs" in item["review_reasons"]


def test_no_profile_mismatch_on_cybersecurity_profile(processed_dir):
    # Fixture records have no domain_profile → fallback "cybersecurity" → no mismatch
    checklist = generate(processed_dir, DOC_KEY, "cybersecurity")
    for item in checklist["items"]:
        assert "profile-mismatch" not in item["review_reasons"]


def test_unknown_doc_key_raises_value_error(processed_dir):
    with pytest.raises(ValueError, match="No requirements JSONL found"):
        generate(processed_dir, "nonexistent-doc", "cybersecurity")


def test_invalid_profile_raises_file_not_found_error(processed_dir):
    with pytest.raises(FileNotFoundError):
        generate(processed_dir, DOC_KEY, "not-a-real-profile")


# ---------------------------------------------------------------------------
# reqbot docs — existing command unaffected
# ---------------------------------------------------------------------------

def test_docs_service_lists_fixture_document(processed_dir):
    result = list_docs(processed_dir)
    assert result["total_docs"] == 1
    assert result["total_reqs"] == 5
    doc = result["docs"][0]
    assert doc["doc_key"] == DOC_KEY
    assert doc["count"] == 5


def test_docs_service_empty_dir_returns_zero(tmp_path):
    result = list_docs(tmp_path)
    assert result["total_docs"] == 0
    assert result["total_reqs"] == 0
    assert result["docs"] == []


def test_docs_service_not_affected_by_checklist_generation(processed_dir):
    # Running the checklist service must not alter the JSONL on disk
    before = list_docs(processed_dir)
    generate(processed_dir, DOC_KEY, "cybersecurity")
    after = list_docs(processed_dir)
    assert before["total_reqs"] == after["total_reqs"]
