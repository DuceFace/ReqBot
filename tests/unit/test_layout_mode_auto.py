"""Unit tests for docling-only ingestion (WP-34.1).

Legacy pymupdf/pdfplumber chunking and the "auto" fallback between backends
were removed -- docling is now the only ingestion path, and any docling
failure (missing install, per-document parse failure) is a hard error, not a
silent downgrade. See docs/PHASE34_REQUIREMENTS.md.

_docling_available() is tested directly. The run()-level tests confirm a
docling failure always raises, unconditionally (there is no more distinction
between an "explicit" docling request and a default one -- there's only one
mode now). _detect_layout_mode_from_chunks() tests stay unchanged: that
function's whole purpose is reading the real backend off of a pre-existing
chunks.jsonl that may predate this migration (a legacy pymupdf/pdfplumber
run from before WP-34.1 shipped), which is exactly the scenario this WP
does NOT retroactively fix.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import run_pipeline

# ---------------------------------------------------------------------------
# _docling_available()
# ---------------------------------------------------------------------------

def test_docling_available_true_when_importable():
    with patch("importlib.util.find_spec", return_value=object()):
        assert run_pipeline._docling_available() is True


def test_docling_available_false_when_not_importable():
    with patch("importlib.util.find_spec", return_value=None):
        assert run_pipeline._docling_available() is False


# ---------------------------------------------------------------------------
# run()-level hard-error wiring
# ---------------------------------------------------------------------------

def _run_with_mocked_steps(tmp_path, **run_kwargs):
    """Run run_pipeline.run() with C/D/D.5/E mocked to no-op, real A/B."""
    def fake_step_c(chunks_jsonl, output_dir, **kwargs):
        out = Path(output_dir) / "doc_extracted_requirements.jsonl"
        out.write_text("", encoding="utf-8")
        return str(out)

    def fake_step_d(reqs_jsonl, chunks_jsonl, pdf_path, output_dir, **kwargs):
        norm = Path(output_dir) / "doc_requirements_normalized.jsonl"
        norm.write_text("", encoding="utf-8")
        return str(norm)

    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4")

    with (
        # Force docling "available" regardless of whether it's actually installed in
        # whatever environment runs this test -- these tests are about hard-error
        # wiring, not about detection itself (covered separately above).
        patch("pipeline.run_pipeline._docling_available", return_value=True),
        patch("pipeline.section_parser.run", side_effect=RuntimeError("docling boom")) as mock_docling,
        patch("pipeline.llm_extract_requirements.run", side_effect=fake_step_c),
        patch("pipeline.parse_and_normalize.run", side_effect=fake_step_d),
        patch("pipeline.aggregate_and_export.run"),
    ):
        kwargs = dict(skip_enrichment=True)
        kwargs.update(run_kwargs)
        result = run_pipeline.run(str(fake_pdf), str(tmp_path), **kwargs)
        return result, mock_docling


def test_docling_failure_raises_hard_error(tmp_path):
    """A docling failure on this document raises, unconditionally -- there is
    no fallback left to silently downgrade to (WP-34.1)."""
    with pytest.raises(RuntimeError, match="Docling"):
        _run_with_mocked_steps(tmp_path)


def test_docling_failure_raises_hard_error_mid_resume(tmp_path):
    """Same hard-error behavior on a resume (skip_to != "A") as on a fresh run --
    there was never a meaningful distinction to preserve once fallback itself
    was removed, but this confirms skip_to doesn't accidentally change it."""
    with pytest.raises(RuntimeError, match="Docling"):
        _run_with_mocked_steps(tmp_path, skip_to="B")


def test_missing_docling_raises_before_any_step_runs(tmp_path):
    """docling not being importable at all (e.g. a broken/incomplete install)
    must produce a clear, actionable error before any pipeline step runs --
    not a raw ImportError surfacing deep inside section_parser.py."""
    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4")
    with patch("pipeline.run_pipeline._docling_available", return_value=False):
        with pytest.raises(RuntimeError, match="docling is required"):
            run_pipeline.run(str(fake_pdf), str(tmp_path), skip_enrichment=True)


# ---------------------------------------------------------------------------
# WP-33.2 fix (Codex review, PR #155): layout_mode_used recorded for Step E
# must describe the chunks actually being aggregated, not an assumption about
# what produced them. Still relevant post-WP-34.1: a --skip-to C/D/E resume
# can target a chunks.jsonl from before this migration shipped.
# ---------------------------------------------------------------------------

def test_detect_layout_mode_from_chunks_docling_signature(tmp_path):
    chunks = tmp_path / "doc_chunks.jsonl"
    chunks.write_text('{"chunk_id": 0, "text": "x", "section_ref_path": []}\n')
    assert run_pipeline._detect_layout_mode_from_chunks(chunks) == "docling"


def test_detect_layout_mode_from_chunks_pdfplumber_signature(tmp_path):
    chunks = tmp_path / "doc_chunks.jsonl"
    chunks.write_text('{"chunk_id": 0, "text": "<<<TABLE_START>>>a|b<<<TABLE_END>>>"}\n')
    assert run_pipeline._detect_layout_mode_from_chunks(chunks) == "pdfplumber"


def test_detect_layout_mode_from_chunks_defaults_pymupdf(tmp_path):
    chunks = tmp_path / "doc_chunks.jsonl"
    chunks.write_text('{"chunk_id": 0, "text": "plain text"}\n')
    assert run_pipeline._detect_layout_mode_from_chunks(chunks) == "pymupdf"


@pytest.mark.parametrize("non_dict_line", ["null", "123", '"just a string"', "[1, 2, 3]"])
def test_detect_layout_mode_from_chunks_non_dict_json_line_does_not_crash(tmp_path, non_dict_line):
    """Gemini review, PR #155: a valid-JSON-but-not-a-dict line (null, a bare
    number, etc.) must not raise TypeError from `"section_ref_path" in data`
    -- only json.JSONDecodeError was being caught, not the type mismatch."""
    chunks = tmp_path / "doc_chunks.jsonl"
    chunks.write_text(non_dict_line + "\n")
    assert run_pipeline._detect_layout_mode_from_chunks(chunks) == "pymupdf"


def test_detect_layout_mode_from_chunks_missing_file_returns_empty(tmp_path):
    assert run_pipeline._detect_layout_mode_from_chunks(tmp_path / "missing.jsonl") == ""


def test_resume_past_step_b_records_actual_chunks_mode_not_fresh_assumption(tmp_path):
    """A --skip-to C resume against a pre-WP-34.1 chunks.jsonl (no docling
    signature -- produced by the now-removed legacy path) must still record
    layout_mode_used="pymupdf", matching the chunks Step E is actually
    aggregating, not "docling" (what every fresh Step A/B run produces now)."""
    chunks = tmp_path / "doc_chunks.jsonl"
    chunks.write_text('{"chunk_id": 0, "text": "plain pymupdf text"}\n')

    def fake_step_c(chunks_jsonl, output_dir, **kwargs):
        out = Path(output_dir) / "doc_extracted_requirements.jsonl"
        out.write_text("", encoding="utf-8")
        return str(out)

    def fake_step_d(reqs_jsonl, chunks_jsonl, pdf_path, output_dir, **kwargs):
        norm = Path(output_dir) / "doc_requirements_normalized.jsonl"
        norm.write_text("", encoding="utf-8")
        return str(norm)

    fake_pdf = tmp_path / "doc.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4")

    with (
        patch("pipeline.run_pipeline._docling_available", return_value=True),
        patch("pipeline.llm_extract_requirements.run", side_effect=fake_step_c),
        patch("pipeline.parse_and_normalize.run", side_effect=fake_step_d),
        patch("pipeline.aggregate_and_export.run") as mock_step_e,
    ):
        run_pipeline.run(
            str(fake_pdf), str(tmp_path),
            skip_to="C", skip_enrichment=True,
        )

    assert mock_step_e.call_args.kwargs["layout_mode_used"] == "pymupdf"
