"""Unit tests for layout_mode="auto" default (docling when installed,
falling back to pymupdf otherwise or on a per-document docling failure).

_docling_available()/resolve_layout_mode() are pure-ish and tested directly.
The run()-level tests confirm the fallback is actually wired in and that an
explicit --layout-mode docling request still fails loudly instead of silently
downgrading.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import run_pipeline

# ---------------------------------------------------------------------------
# _docling_available() / resolve_layout_mode()
# ---------------------------------------------------------------------------

def test_docling_available_true_when_importable():
    with patch("importlib.util.find_spec", return_value=object()):
        assert run_pipeline._docling_available() is True


def test_docling_available_false_when_not_importable():
    with patch("importlib.util.find_spec", return_value=None):
        assert run_pipeline._docling_available() is False


def test_resolve_auto_to_docling_when_available():
    with patch("importlib.util.find_spec", return_value=object()):
        assert run_pipeline.resolve_layout_mode("auto") == "docling"


def test_resolve_auto_to_pymupdf_when_unavailable():
    with patch("importlib.util.find_spec", return_value=None):
        assert run_pipeline.resolve_layout_mode("auto") == "pymupdf"


@pytest.mark.parametrize("explicit", ["docling", "pymupdf", "pdfplumber"])
def test_resolve_explicit_choices_pass_through_unchanged(explicit):
    """An explicit choice must not be affected by whether docling is installed."""
    with patch("importlib.util.find_spec", return_value=None):
        assert run_pipeline.resolve_layout_mode(explicit) == explicit
    with patch("importlib.util.find_spec", return_value=object()):
        assert run_pipeline.resolve_layout_mode(explicit) == explicit


# ---------------------------------------------------------------------------
# run()-level fallback wiring
#
# Same mocking pattern as test_wp_20_3.py's test_run_pipeline_passes_profile_to_step_c
# -- mock every step at its import boundary, run the real orchestrator.
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
        # whatever environment runs this test (CI's base install doesn't have it) --
        # these tests are about the fallback wiring, not about detection itself
        # (that's covered separately by test_docling_available_*).
        patch("pipeline.run_pipeline._docling_available", return_value=True),
        patch("pipeline.section_parser.run", side_effect=RuntimeError("docling boom")) as mock_docling,
        patch("pipeline.extract_pdf_to_text.run") as mock_legacy,
        patch("pipeline.chunk_text.run", return_value=str(tmp_path / "doc_chunks.jsonl")),
        patch("pipeline.llm_extract_requirements.run", side_effect=fake_step_c),
        patch("pipeline.parse_and_normalize.run", side_effect=fake_step_d),
        patch("pipeline.aggregate_and_export.run"),
    ):
        kwargs = dict(skip_enrichment=True)
        kwargs.update(run_kwargs)
        result = run_pipeline.run(str(fake_pdf), str(tmp_path), **kwargs)
        return result, mock_docling, mock_legacy


def test_auto_falls_back_to_pymupdf_when_docling_fails(tmp_path):
    """The core auto-default behavior: layout_mode="auto" (default) + a docling failure
    on this specific document falls back to pymupdf instead of raising."""
    result, mock_docling, mock_legacy = _run_with_mocked_steps(tmp_path, layout_mode="auto")
    assert mock_docling.called
    assert mock_legacy.called
    assert result is not None


def test_explicit_docling_request_raises_instead_of_falling_back(tmp_path):
    """An explicit --layout-mode docling must fail loudly, not silently downgrade --
    the caller asked for docling specifically and deserves to know it didn't happen."""
    with pytest.raises(RuntimeError, match="Docling"):
        _run_with_mocked_steps(tmp_path, layout_mode="docling")


def test_auto_does_not_fall_back_mid_resume(tmp_path):
    """skip_to != "A" means this is a resume of a prior run -- a docling failure
    here must not silently rewrite the resume into a fresh legacy extraction."""
    with pytest.raises(RuntimeError, match="Docling"):
        _run_with_mocked_steps(tmp_path, layout_mode="auto", skip_to="B")


# ---------------------------------------------------------------------------
# WP-33.2 fix (Codex review, PR #155): layout_mode_used recorded for Step E
# must describe the chunks actually being aggregated, not a fresh "auto"
# resolution that can disagree with what an earlier run actually produced.
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


def test_resume_past_step_b_records_actual_chunks_mode_not_fresh_resolution(tmp_path):
    """Reproduces the exact bug Codex flagged: an earlier run fell back to
    pymupdf (chunks.jsonl has no docling signature), but docling is available
    NOW -- a --skip-to C resume must still record layout_mode_used="pymupdf",
    matching the chunks Step E is actually aggregating, not "docling" (what
    resolve_layout_mode("auto") would freshly resolve to today)."""
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
            layout_mode="auto", skip_to="C", skip_enrichment=True,
        )

    assert mock_step_e.call_args.kwargs["layout_mode_used"] == "pymupdf"
