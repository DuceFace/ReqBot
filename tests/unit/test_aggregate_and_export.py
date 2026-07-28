"""Unit tests for pipeline/aggregate_and_export.py's skip_sections_applied
computation (WP-33.2).

skip_sections_applied answers "did the profile's skip_sections field actually
take effect for this ingest" -- None when nothing was configured to apply in
the first place, True/False when something was configured and either did or
didn't apply depending on which layout mode actually ran.
"""
import json

from pipeline.aggregate_and_export import run


def _write_jsonl(path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _run(tmp_path, **overrides):
    reqs_path = tmp_path / "doc_requirements_normalized.jsonl"
    _write_jsonl(reqs_path, [{"requirement_id": "REQ-a", "confidence": 0.9}])
    kwargs = dict(
        requirements_jsonl=str(reqs_path),
        output_dir=str(tmp_path),
        source_pdf="doc.pdf",
    )
    kwargs.update(overrides)
    return run(**kwargs)


def test_skip_sections_applied_none_when_nothing_configured(tmp_path):
    stats = _run(tmp_path, layout_mode_used="pymupdf", skip_sections_configured=[])
    assert stats["pipeline"]["skip_sections_applied"] is None


def test_skip_sections_applied_none_when_not_passed_at_all(tmp_path):
    """Standalone CLI usage with no caller context -- default params."""
    stats = _run(tmp_path)
    assert stats["pipeline"]["skip_sections_applied"] is None
    assert stats["pipeline"]["layout_mode_used"] == ""


def test_skip_sections_applied_true_when_configured_and_docling_used(tmp_path):
    stats = _run(
        tmp_path, layout_mode_used="docling", skip_sections_configured=["GLOSSARY"]
    )
    assert stats["pipeline"]["skip_sections_applied"] is True
    assert stats["pipeline"]["layout_mode_used"] == "docling"


def test_skip_sections_applied_false_when_configured_but_legacy_used(tmp_path):
    """The exact gap this WP surfaces: skip_sections was configured, but the
    ingest actually ran under a layout mode that can't apply it."""
    stats = _run(
        tmp_path, layout_mode_used="pymupdf", skip_sections_configured=["GLOSSARY"]
    )
    assert stats["pipeline"]["skip_sections_applied"] is False


def test_skip_sections_applied_false_when_configured_and_pdfplumber_used(tmp_path):
    stats = _run(
        tmp_path, layout_mode_used="pdfplumber", skip_sections_configured=["REFERENCES"]
    )
    assert stats["pipeline"]["skip_sections_applied"] is False


def test_stats_json_file_contains_the_same_values(tmp_path):
    _run(tmp_path, layout_mode_used="docling", skip_sections_configured=["GLOSSARY"])
    stats_path = tmp_path / "doc_stats.json"
    assert stats_path.exists()
    written = json.loads(stats_path.read_text(encoding="utf-8"))
    assert written["pipeline"]["layout_mode_used"] == "docling"
    assert written["pipeline"]["skip_sections_applied"] is True
