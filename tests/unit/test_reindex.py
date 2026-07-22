"""Unit tests for cmd_reindex (WP-24.2 — unified requirements + context rebuild).

Mocks qdrant_client.QdrantClient (per the tests/unit/test_trace_service.py
pattern), pipeline.embed_and_index.run, and pipeline.embed_context_index.run.
Uses real tmp_path JSONL/chunk fixture files so
core.artifact_resolver.resolve_latest_requirement_files() and
cli.reqbot._read_document_id() exercise real file I/O.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import cli.reqbot as cli_reqbot
import core.config as core_config
from cli.reqbot import cmd_reindex


def _write_doc(processed_dir: Path, doc_key: str, document_id: str, with_chunks: bool = True):
    """Create a minimal run directory with a normalized requirements JSONL
    (and optionally a chunks JSONL) for doc_key."""
    run_dir = processed_dir / f"{doc_key}_20260101_000000"
    run_dir.mkdir(parents=True, exist_ok=True)
    req_path = run_dir / f"{doc_key}_requirements_normalized.jsonl"
    req_path.write_text(json.dumps({"document_id": document_id, "requirement_id": "REQ-1"}) + "\n")
    if with_chunks:
        chunks_path = run_dir / f"{doc_key}_chunks.jsonl"
        chunks_path.write_text(json.dumps({"chunk_id": "c1", "text": "hello"}) + "\n")
    return req_path


def _args(requirements_only=False):
    return SimpleNamespace(
        qdrant_url="http://qdrant:6333",
        ollama_url="http://ollama:11434",
        requirements_only=requirements_only,
    )


def _mock_qdrant():
    client = MagicMock()
    client.get_aliases.return_value = MagicMock(aliases=[])
    return client


@pytest.fixture(autouse=True)
def _isolate_cfg(tmp_path, monkeypatch):
    mock_cfg = SimpleNamespace(processed_dir_path=lambda: tmp_path)
    monkeypatch.setattr(cli_reqbot, "_cfg", mock_cfg)


def test_default_reindex_rebuilds_both_collections(tmp_path):
    _write_doc(tmp_path, "DOC-A", "hash-a")
    _write_doc(tmp_path, "DOC-B", "hash-b")
    mock_client = _mock_qdrant()

    with patch("qdrant_client.QdrantClient", return_value=mock_client), \
         patch("pipeline.embed_and_index.run") as mock_embed, \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        rc = cmd_reindex(_args())

    assert rc == 0
    assert mock_embed.call_count == 2
    assert mock_embed_ctx.call_count == 2
    # One alias swap for grc_requirements, one for grc_context.
    assert mock_client.update_collection_aliases.call_count == 2


def test_requirements_only_skips_context_entirely(tmp_path):
    _write_doc(tmp_path, "DOC-A", "hash-a")
    mock_client = _mock_qdrant()

    with patch("qdrant_client.QdrantClient", return_value=mock_client), \
         patch("pipeline.embed_and_index.run") as mock_embed, \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        rc = cmd_reindex(_args(requirements_only=True))

    assert rc == 0
    assert mock_embed.call_count == 1
    mock_embed_ctx.assert_not_called()
    assert mock_client.update_collection_aliases.call_count == 1


def test_context_temp_collection_uses_grc_context_prefix(tmp_path):
    _write_doc(tmp_path, "DOC-A", "hash-a")
    mock_client = _mock_qdrant()

    with patch("qdrant_client.QdrantClient", return_value=mock_client), \
         patch("pipeline.embed_and_index.run"), \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        cmd_reindex(_args())

    _, kwargs = mock_embed_ctx.call_args
    assert kwargs["collection_name"].startswith("grc_context_")

    # The alias-swap call for grc_context should target that same temp name.
    alias_names = set()
    for call in mock_client.update_collection_aliases.call_args_list:
        for op in call.kwargs["change_aliases_operations"]:
            if hasattr(op, "create_alias"):
                alias_names.add((op.create_alias.alias_name, op.create_alias.collection_name))
    assert ("grc_context", kwargs["collection_name"]) in alias_names


def test_document_id_read_from_requirements_file_not_filename(tmp_path):
    _write_doc(tmp_path, "DOC-A", "pdf-hash-abc123")
    mock_client = _mock_qdrant()

    with patch("qdrant_client.QdrantClient", return_value=mock_client), \
         patch("pipeline.embed_and_index.run"), \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        cmd_reindex(_args())

    _, kwargs = mock_embed_ctx.call_args
    assert kwargs["document_id"] == "pdf-hash-abc123"


def test_two_documents_sharing_a_run_directory_get_matching_chunks(tmp_path):
    """A run directory holding artifacts for more than one document must not
    pair one document's chunks with another's document_id — chunk_files[0]
    from an unfiltered glob would do exactly that."""
    run_dir = tmp_path / "shared_run"
    run_dir.mkdir()

    req_a = run_dir / "DOC-A_requirements_normalized.jsonl"
    req_a.write_text(json.dumps({"document_id": "hash-a", "requirement_id": "REQ-1"}) + "\n")
    chunks_a = run_dir / "DOC-A_chunks.jsonl"
    chunks_a.write_text(json.dumps({"chunk_id": "a1", "text": "doc a text"}) + "\n")

    req_b = run_dir / "DOC-B_requirements_normalized.jsonl"
    req_b.write_text(json.dumps({"document_id": "hash-b", "requirement_id": "REQ-2"}) + "\n")
    chunks_b = run_dir / "DOC-B_chunks.jsonl"
    chunks_b.write_text(json.dumps({"chunk_id": "b1", "text": "doc b text"}) + "\n")

    mock_client = _mock_qdrant()

    with patch("qdrant_client.QdrantClient", return_value=mock_client), \
         patch("pipeline.embed_and_index.run"), \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        rc = cmd_reindex(_args())

    assert rc == 0
    assert mock_embed_ctx.call_count == 2
    calls_by_document_id = {c.kwargs["document_id"]: c.args[0] for c in mock_embed_ctx.call_args_list}
    assert calls_by_document_id["hash-a"] == str(chunks_a)
    assert calls_by_document_id["hash-b"] == str(chunks_b)


def test_missing_chunks_file_does_not_prevent_requirements_indexing(tmp_path):
    _write_doc(tmp_path, "DOC-A", "hash-a", with_chunks=True)
    _write_doc(tmp_path, "DOC-B", "hash-b", with_chunks=False)
    mock_client = _mock_qdrant()

    with patch("qdrant_client.QdrantClient", return_value=mock_client), \
         patch("pipeline.embed_and_index.run") as mock_embed, \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        rc = cmd_reindex(_args())

    assert rc == 0
    assert mock_embed.call_count == 2  # both requirements files indexed
    assert mock_embed_ctx.call_count == 1  # only DOC-A has chunks


def test_context_failure_for_one_doc_does_not_swap_and_deletes_temp(tmp_path, caplog):
    """embed_context_index.run() upserts in batches, so a failed document may
    have already written partial chunks into the temp collection before
    raising. The temp collection must be discarded, not swapped live, even
    though another document succeeded — otherwise grc_context would end up
    with a partial/incomplete version of the failed document."""
    _write_doc(tmp_path, "DOC-A", "hash-a")
    _write_doc(tmp_path, "DOC-B", "hash-b")
    mock_client = _mock_qdrant()

    def _ctx_side_effect(chunks_jsonl, **kwargs):
        if "DOC-B" in chunks_jsonl:
            raise RuntimeError("embedding failed")

    with patch("qdrant_client.QdrantClient", return_value=mock_client), \
         patch("pipeline.embed_and_index.run"), \
         patch("pipeline.embed_context_index.run", side_effect=_ctx_side_effect):
        rc = cmd_reindex(_args())

    assert rc == 1  # partial context failure must not report overall success
    # Only the requirements alias swap happened — context was never swapped,
    # and the temp context collection was deleted instead.
    assert mock_client.update_collection_aliases.call_count == 1
    context_temp_names = {
        call.args[0] for call in mock_client.delete_collection.call_args_list
        if call.args[0].startswith("grc_context_")
    }
    assert len(context_temp_names) == 1
    assert "REINDEX PARTIAL" in caplog.text
    assert "untouched" in caplog.text.lower()


def test_all_context_docs_fail_no_swap_and_nonzero(tmp_path):
    _write_doc(tmp_path, "DOC-A", "hash-a")
    mock_client = _mock_qdrant()

    with patch("qdrant_client.QdrantClient", return_value=mock_client), \
         patch("pipeline.embed_and_index.run"), \
         patch("pipeline.embed_context_index.run", side_effect=RuntimeError("boom")):
        rc = cmd_reindex(_args())

    assert rc == 1
    # Only the requirements alias swap happened — context never swapped.
    assert mock_client.update_collection_aliases.call_count == 1


def test_requirements_failure_aborts_before_context(tmp_path):
    _write_doc(tmp_path, "DOC-A", "hash-a")
    mock_client = _mock_qdrant()

    with patch("qdrant_client.QdrantClient", return_value=mock_client), \
         patch("pipeline.embed_and_index.run", side_effect=RuntimeError("boom")), \
         patch("pipeline.embed_context_index.run") as mock_embed_ctx:
        rc = cmd_reindex(_args())

    assert rc == 1
    mock_embed_ctx.assert_not_called()
    mock_client.update_collection_aliases.assert_not_called()


def test_no_requirements_jsonl_found_returns_1(tmp_path):
    rc = cmd_reindex(_args())
    assert rc == 1


def test_reindex_help_shows_requirements_only_flag(capsys, monkeypatch):
    # main() builds argparse defaults from every subcommand's config fields,
    # not just processed_dir_path — restore the real config for this test
    # rather than the file's simplified autouse mock.
    monkeypatch.setattr(cli_reqbot, "_cfg", core_config.load())
    monkeypatch.setattr(sys, "argv", ["reqbot", "reindex", "--help"])
    with pytest.raises(SystemExit):
        cli_reqbot.main()
    assert "--requirements-only" in capsys.readouterr().out
