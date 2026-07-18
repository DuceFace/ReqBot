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
