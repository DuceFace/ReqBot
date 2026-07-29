"""Unit tests for cmd_ingest (WP-24.3 — index-by-default + --no-index).

Mocks pipeline.run_pipeline.run, pipeline.embed_and_index.run, and
pipeline.embed_context_index.run. Uses real tmp_path files so the exact
doc_key-based chunk-file matching (core.artifact_resolver, also fixed in this
WP) exercises real file I/O.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cli.reqbot import cmd_ingest


def _args(pdf_path, output_dir, no_index=False):
    return SimpleNamespace(
        pdf=str(pdf_path),
        output_dir=str(output_dir),
        model="test-model",
        extraction_model=None,
        enrichment_model=None,
        max_chunks=None,
        no_index=no_index,
        skip_enrichment=False,
        profile="cybersecurity",
        ollama_url="http://ollama:11434",
        qdrant_url="http://qdrant:6333",
    )


def _make_fake_index_path(out_dir: Path, document_id="hash-a"):
    """Simulate run_pipeline.run()'s output: a normalized JSONL + matching chunks file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "DOC-A_requirements_normalized.jsonl"
    index_path.write_text(json.dumps({"document_id": document_id, "requirement_id": "REQ-1"}) + "\n")
    chunks_path = out_dir / "DOC-A_chunks.jsonl"
    chunks_path.write_text(json.dumps({"chunk_id": "c1", "text": "hello"}) + "\n")
    return str(index_path)


def test_default_indexes_both_requirements_and_context(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out_dir = tmp_path / "out"

    with patch("pipeline.run_pipeline.run", return_value=_make_fake_index_path(out_dir)) as mock_run, \
         patch("pipeline.embed_and_index.run") as mock_embed, \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        rc = cmd_ingest(_args(pdf, out_dir))

    assert rc == 0
    mock_run.assert_called_once()
    mock_embed.assert_called_once()
    mock_embed_ctx.assert_called_once()
    _, kwargs = mock_embed_ctx.call_args
    assert kwargs["document_id"] == "hash-a"


def test_no_index_writes_artifacts_but_skips_both_indexing_calls(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out_dir = tmp_path / "out"

    with patch("pipeline.run_pipeline.run", return_value=_make_fake_index_path(out_dir)) as mock_run, \
         patch("pipeline.embed_and_index.run") as mock_embed, \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        rc = cmd_ingest(_args(pdf, out_dir, no_index=True))

    assert rc == 0
    mock_run.assert_called_once()  # pipeline still runs — artifacts still written
    mock_embed.assert_not_called()
    mock_embed_ctx.assert_not_called()


def test_old_index_flag_still_accepted_and_behaves_like_default(tmp_path):
    """Hidden --index compat flag: cmd_ingest never reads args.index at all, only
    args.no_index — so a Namespace with a stray index=True attribute (as the
    hidden argparse flag would produce) still indexes by default."""
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out_dir = tmp_path / "out"

    args = _args(pdf, out_dir)
    args.index = True  # simulates the hidden compat flag being parsed
    with patch("pipeline.run_pipeline.run", return_value=_make_fake_index_path(out_dir)), \
         patch("pipeline.embed_and_index.run") as mock_embed, \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        rc = cmd_ingest(args)

    assert rc == 0
    mock_embed.assert_called_once()
    mock_embed_ctx.assert_called_once()


def test_missing_no_index_attribute_defaults_to_indexing(tmp_path):
    """cmd_ingest uses getattr(args, "no_index", False) — a Namespace built before
    this WP (no no_index attribute at all) must still index by default, not crash."""
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out_dir = tmp_path / "out"

    args = _args(pdf, out_dir)
    del args.no_index
    with patch("pipeline.run_pipeline.run", return_value=_make_fake_index_path(out_dir)), \
         patch("pipeline.embed_and_index.run") as mock_embed, \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        rc = cmd_ingest(args)

    assert rc == 0
    mock_embed.assert_called_once()
    mock_embed_ctx.assert_called_once()


def test_ingest_help_shows_no_index_not_index(capsys, monkeypatch):
    import cli.reqbot as cli_reqbot

    monkeypatch.setattr(sys, "argv", ["reqbot", "ingest", "--help"])
    with pytest.raises(SystemExit):
        cli_reqbot.main()
    out = capsys.readouterr().out
    assert "--no-index" in out
    assert "--index" not in out
