import json
import os
from pathlib import Path

import pytest

from services.docs_service import list_docs

SAMPLE_REQ = {
    "requirement_id": "REQ-abc123def456",
    "source_quote": "Systems must enforce access control.",
    "source_pdf": "TEST_DOC.pdf",
}


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_empty_directory_returns_empty(tmp_path):
    result = list_docs(tmp_path)
    assert result["docs"] == []
    assert result["total_reqs"] == 0
    assert result["total_docs"] == 0


def test_single_valid_jsonl(tmp_path):
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    _write_jsonl(run_dir / "doc_requirements_normalized.jsonl", [SAMPLE_REQ] * 3)
    result = list_docs(tmp_path)
    assert result["total_docs"] == 1
    assert result["total_reqs"] == 3
    assert result["docs"][0]["count"] == 3
    assert result["docs"][0]["source_pdf"] == "TEST_DOC.pdf"
    assert result["docs"][0]["run_date"] == "2026-01-01"


def test_multiple_docs_counted_separately(tmp_path):
    for name in ("alpha", "beta"):
        d = tmp_path / f"{name}_20260101_120000"
        d.mkdir()
        _write_jsonl(d / f"{name}_requirements_normalized.jsonl", [SAMPLE_REQ, SAMPLE_REQ])
    result = list_docs(tmp_path)
    assert result["total_docs"] == 2
    assert result["total_reqs"] == 4


def test_mtime_dedup_keeps_most_recent(tmp_path):
    """Two runs of the same document stem — only the higher-mtime file is kept."""
    old_dir = tmp_path / "run_old"
    new_dir = tmp_path / "run_new"
    old_dir.mkdir()
    new_dir.mkdir()
    old_file = old_dir / "doc_requirements_normalized.jsonl"
    new_file = new_dir / "doc_requirements_normalized.jsonl"
    _write_jsonl(old_file, [SAMPLE_REQ])        # 1 record
    _write_jsonl(new_file, [SAMPLE_REQ] * 5)    # 5 records
    os.utime(old_file, (1000.0, 1000.0))
    os.utime(new_file, (2000.0, 2000.0))
    result = list_docs(tmp_path)
    assert result["total_docs"] == 1
    assert result["docs"][0]["count"] == 5


def test_missing_processed_dir_raises(tmp_path):
    with pytest.raises(OSError):
        list_docs(tmp_path / "does_not_exist")


def test_empty_file_no_crash(tmp_path):
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    (run_dir / "doc_requirements_normalized.jsonl").write_text("")
    result = list_docs(tmp_path)
    assert result["docs"][0]["count"] == 0
    assert result["total_reqs"] == 0


def test_blank_lines_skipped(tmp_path):
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    content = json.dumps(SAMPLE_REQ) + "\n\n   \n" + json.dumps(SAMPLE_REQ) + "\n"
    (run_dir / "doc_requirements_normalized.jsonl").write_text(content)
    result = list_docs(tmp_path)
    assert result["docs"][0]["count"] == 2


def test_malformed_json_no_crash(tmp_path):
    """Malformed lines do not crash list_docs.
    Current behavior: non-empty lines are counted regardless of JSON validity
    (observable corruption contract is not enforced — known gap)."""
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    content = (
        json.dumps(SAMPLE_REQ) + "\n"
        "NOT VALID JSON\n"
        + json.dumps(SAMPLE_REQ) + "\n"
    )
    (run_dir / "doc_requirements_normalized.jsonl").write_text(content)
    result = list_docs(tmp_path)
    assert result["docs"][0]["count"] == 3


def test_missing_source_pdf_field_no_crash(tmp_path):
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    rec = {"requirement_id": "REQ-abc", "source_quote": "Some requirement text."}
    _write_jsonl(run_dir / "doc_requirements_normalized.jsonl", [rec])
    result = list_docs(tmp_path)
    assert result["docs"][0]["source_pdf"] == ""
    assert result["docs"][0]["count"] == 1


# ---------------------------------------------------------------------------
# WP-33.2: layout mode detection + skip_sections visibility
# ---------------------------------------------------------------------------

def _write_stats(run_dir: Path, pipeline_stats: dict) -> None:
    (run_dir / "doc_stats.json").write_text(
        json.dumps({"pipeline": pipeline_stats}), encoding="utf-8"
    )


def test_stats_json_resolved_by_doc_key_not_first_glob_match(tmp_path):
    """Regression test (Codex review, PR #155): an explicitly shared --output-dir
    holding artifacts for more than one PDF stem must not let one document's
    stats.json leak into another's row via glob()[0] picking whichever file the
    filesystem happens to return first."""
    run_dir = tmp_path / "shared_run"
    run_dir.mkdir()
    _write_jsonl(run_dir / "alpha_requirements_normalized.jsonl", [SAMPLE_REQ])
    _write_jsonl(run_dir / "beta_requirements_normalized.jsonl", [SAMPLE_REQ])
    (run_dir / "alpha_stats.json").write_text(
        json.dumps({"pipeline": {"layout_mode_used": "docling", "skip_sections_applied": True}}),
        encoding="utf-8",
    )
    (run_dir / "beta_stats.json").write_text(
        json.dumps({"pipeline": {"layout_mode_used": "pymupdf", "skip_sections_applied": False}}),
        encoding="utf-8",
    )
    result = list_docs(tmp_path)
    by_key = {d["doc_key"]: d for d in result["docs"]}
    assert by_key["alpha"]["mode"] == "docling"
    assert by_key["alpha"]["skip_sections_applied"] is True
    assert by_key["beta"]["mode"] == "pymupdf"
    assert by_key["beta"]["skip_sections_applied"] is False


def test_stats_json_layout_mode_and_skip_sections_used_when_present(tmp_path):
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    _write_jsonl(run_dir / "doc_requirements_normalized.jsonl", [SAMPLE_REQ])
    _write_stats(run_dir, {"layout_mode_used": "docling", "skip_sections_applied": True})
    result = list_docs(tmp_path)
    assert result["docs"][0]["mode"] == "docling"
    assert result["docs"][0]["skip_sections_applied"] is True


def test_stats_json_skip_sections_applied_false_configured_but_not_applied(tmp_path):
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    _write_jsonl(run_dir / "doc_requirements_normalized.jsonl", [SAMPLE_REQ])
    _write_stats(run_dir, {"layout_mode_used": "pymupdf", "skip_sections_applied": False})
    result = list_docs(tmp_path)
    assert result["docs"][0]["mode"] == "pymupdf"
    assert result["docs"][0]["skip_sections_applied"] is False


def test_no_stats_json_skip_sections_applied_defaults_none(tmp_path):
    """Documents ingested before WP-33.2 have no stats.json skip_sections_applied
    key at all -- must not be misreported as False (which would mean "configured
    but didn't apply"), since nothing is actually known either way."""
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    _write_jsonl(run_dir / "doc_requirements_normalized.jsonl", [SAMPLE_REQ])
    result = list_docs(tmp_path)
    assert result["docs"][0]["skip_sections_applied"] is None


def test_mode_falls_back_to_docling_signature_when_stats_json_missing(tmp_path):
    """Regression test for a real pre-existing bug: the old mode-detection
    heuristic only ever checked for a pdfplumber TABLE_START sentinel, so it
    silently mislabeled every already-ingested docling document as "pymupdf".
    section_ref_path key presence on a chunk record is docling's own signature
    (legacy chunking never writes that key at all -- confirmed during Phase 32)."""
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    _write_jsonl(run_dir / "doc_requirements_normalized.jsonl", [SAMPLE_REQ])
    _write_jsonl(run_dir / "doc_chunks.jsonl", [{"chunk_id": 0, "text": "x", "section_ref_path": []}])
    result = list_docs(tmp_path)
    assert result["docs"][0]["mode"] == "docling"


def test_mode_falls_back_to_pdfplumber_sentinel_when_stats_json_missing(tmp_path):
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    _write_jsonl(run_dir / "doc_requirements_normalized.jsonl", [SAMPLE_REQ])
    (run_dir / "doc_chunks.jsonl").write_text(
        json.dumps({"chunk_id": 0, "text": "<<<TABLE_START>>>a|b<<<TABLE_END>>>"}) + "\n"
    )
    result = list_docs(tmp_path)
    assert result["docs"][0]["mode"] == "pdfplumber"


def test_mode_defaults_pymupdf_when_neither_signature_present(tmp_path):
    run_dir = tmp_path / "doc_20260101_120000"
    run_dir.mkdir()
    _write_jsonl(run_dir / "doc_requirements_normalized.jsonl", [SAMPLE_REQ])
    _write_jsonl(run_dir / "doc_chunks.jsonl", [{"chunk_id": 0, "text": "plain text"}])
    result = list_docs(tmp_path)
    assert result["docs"][0]["mode"] == "pymupdf"


def test_doc_key_preserves_pdf_stem_containing_normalized_substring(tmp_path):
    """Codex PR #92 review: a PDF literally named
    "policy_requirements_normalized_v1.pdf" must not have its doc_key mangled
    by a broad substring replace — doc_key_from_requirements_path() strips
    only the trailing suffix."""
    stem = "policy_requirements_normalized_v1"
    run_dir = tmp_path / f"{stem}_20260101_120000"
    run_dir.mkdir()
    _write_jsonl(run_dir / f"{stem}_requirements_normalized.jsonl", [SAMPLE_REQ])
    result = list_docs(tmp_path)
    assert result["docs"][0]["doc_key"] == stem
