"""Unit tests for WP-25.6c — embedding model configurability + index provenance.

Covers the pure/local logic that's testable without a real Ollama/Qdrant:
  - embed_and_index.build_payload()/embed_batch() thread embedding_model through
  - embed_context_index.embed_batch() threads embedding_model through
  - core.ask._embedding_mismatch_warnings() / compare_service._embedding_warnings() /
    evidence_service._embedding_warnings() detect mismatches correctly and never
    block (empty list = no warning, not an error)
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.ask import _embedding_mismatch_warnings
from pipeline.embed_and_index import build_payload
from pipeline.embed_and_index import embed_batch as embed_and_index_batch
from pipeline.embed_and_index import run as embed_and_index_run
from pipeline.embed_context_index import embed_batch as embed_context_batch
from pipeline.embed_context_index import run as embed_context_index_run
from services.compare_service import _embedding_warnings as compare_warnings
from services.evidence_service import _embedding_warnings as evidence_warnings


def _mock_sparse_model():
    """A fastembed.SparseTextEmbedding stand-in: .embed(texts) yields one
    fake sparse embedding object per input text."""
    mock_model = MagicMock()

    def _embed(texts):
        for _ in texts:
            emb = MagicMock()
            emb.indices.tolist.return_value = [0]
            emb.values.tolist.return_value = [1.0]
            yield emb

    mock_model.embed.side_effect = _embed
    return mock_model

# ---------------------------------------------------------------------------
# build_payload — provenance written at index time
# ---------------------------------------------------------------------------

_MIN_REQ = {"requirement_id": "REQ-1", "source_quote": "Systems must enforce MFA."}


def test_build_payload_includes_embedding_provenance():
    payload = build_payload(_MIN_REQ, "nomic-embed-text", 768)
    assert payload["embedding_model"] == "nomic-embed-text"
    assert payload["embedding_dim"] == 768


def test_build_payload_provenance_reflects_configured_model_not_hardcoded():
    payload = build_payload(_MIN_REQ, "a-different-model", 1024)
    assert payload["embedding_model"] == "a-different-model"
    assert payload["embedding_dim"] == 1024


# ---------------------------------------------------------------------------
# embed_batch — configured model actually reaches the Ollama client call
# ---------------------------------------------------------------------------

def test_embed_and_index_embed_batch_uses_configured_model():
    mock_client = MagicMock()
    mock_client.embed.return_value = MagicMock(embeddings=[[0.1, 0.2]])
    embed_and_index_batch(["some text"], mock_client, "custom-embed-model")
    mock_client.embed.assert_called_once_with(model="custom-embed-model", input=["some text"])


def test_embed_context_index_embed_batch_uses_configured_model():
    mock_client = MagicMock()
    mock_client.embed.return_value = MagicMock(embeddings=[[0.1, 0.2]])
    embed_context_batch(["some text"], mock_client, "custom-embed-model")
    mock_client.embed.assert_called_once_with(model="custom-embed-model", input=["some text"])


# ---------------------------------------------------------------------------
# Mismatch warnings — shared behavior across core/ask.py, compare_service,
# evidence_service: no mismatch → [], mismatch → one descriptive warning,
# never raises/blocks.
# ---------------------------------------------------------------------------

def test_no_warning_when_all_results_match_configured_model():
    results = [{"embedding_model": "nomic-embed-text"}] * 3
    assert _embedding_mismatch_warnings(results, "nomic-embed-text") == []
    assert compare_warnings(results, "nomic-embed-text") == []
    assert evidence_warnings(results, "nomic-embed-text") == []


def test_legacy_points_with_no_embedding_model_field_treated_as_nomic_embed_text():
    """Points indexed before WP-25.6c carry no embedding_model field at all —
    must not produce a false-positive warning when config is still the
    unchanged default."""
    results = [{"requirement_id": "REQ-1"}, {"requirement_id": "REQ-2"}]
    assert _embedding_mismatch_warnings(results, "nomic-embed-text") == []


def test_warning_when_configured_model_differs_from_indexed_model():
    results = [{"embedding_model": "nomic-embed-text"}] * 7 + [{"embedding_model": "other-model"}] * 3
    warnings = _embedding_mismatch_warnings(results, "other-model")
    assert len(warnings) == 1
    assert "7 of 10" in warnings[0]
    assert "nomic-embed-text" in warnings[0]
    assert "other-model" in warnings[0]
    assert "reindex" in warnings[0]


def test_mismatch_never_blocks_only_warns():
    """A partially reindexed corpus is a valid, common state — mismatch
    produces a warning string, never an exception, and results themselves
    are untouched by the warning computation."""
    results = [{"embedding_model": "old-model", "requirement_id": "REQ-1"}]
    warnings = _embedding_mismatch_warnings(results, "new-model")
    assert warnings  # non-empty, but no exception raised getting here
    assert results == [{"embedding_model": "old-model", "requirement_id": "REQ-1"}]


def test_compare_and_evidence_warnings_match_core_ask_behavior():
    results = [{"embedding_model": "old-model"}] * 2
    core_w = _embedding_mismatch_warnings(results, "new-model")
    compare_w = compare_warnings(results, "new-model")
    evidence_w = evidence_warnings(results, "new-model")
    assert core_w == compare_w == evidence_w


# ---------------------------------------------------------------------------
# Collection creation — dimension derived from the actual embedding, not a
# hardcoded 768 (Codex review, PR #108: a hardcoded VECTOR_DIM would make
# `reqbot reindex` fail outright for any embedding_model with a different
# output dimension, undermining the whole point of WP-25.6c).
# ---------------------------------------------------------------------------

def test_embed_and_index_create_collection_uses_actual_embedding_dimension(tmp_path):
    jsonl_path = tmp_path / "reqs.jsonl"
    jsonl_path.write_text(json.dumps(_MIN_REQ) + "\n")

    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists.return_value = False
    mock_qdrant.get_collection.return_value = MagicMock(points_count=1)

    mock_ollama_client = MagicMock()
    mock_ollama_client.embed.return_value = MagicMock(embeddings=[[0.0] * 1024])

    with patch("pipeline.embed_and_index.QdrantClient", return_value=mock_qdrant), \
         patch("pipeline.embed_and_index.ollama.Client", return_value=mock_ollama_client), \
         patch("pipeline.embed_and_index.SparseTextEmbedding", return_value=_mock_sparse_model()):
        embed_and_index_run(str(jsonl_path), embedding_model="a-1024-dim-model")

    mock_qdrant.create_collection.assert_called_once()
    _, kwargs = mock_qdrant.create_collection.call_args
    assert kwargs["vectors_config"]["dense"].size == 1024


def test_embed_context_index_create_collection_uses_actual_embedding_dimension(tmp_path):
    chunks_path = tmp_path / "doc_chunks.jsonl"
    chunks_path.write_text(json.dumps({"chunk_id": "c1", "text": "hello world"}) + "\n")

    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists.return_value = False
    mock_qdrant.get_collection.return_value = MagicMock(points_count=1)

    mock_ollama_client = MagicMock()
    mock_ollama_client.embed.return_value = MagicMock(embeddings=[[0.0] * 1024])

    with patch("pipeline.embed_context_index.QdrantClient", return_value=mock_qdrant), \
         patch("pipeline.embed_context_index.ollama.Client", return_value=mock_ollama_client), \
         patch("pipeline.embed_context_index.SparseTextEmbedding", return_value=_mock_sparse_model()):
        embed_context_index_run(str(chunks_path), embedding_model="a-1024-dim-model")

    mock_qdrant.create_collection.assert_called_once()
    _, kwargs = mock_qdrant.create_collection.call_args
    assert kwargs["vectors_config"]["dense"].size == 1024


def test_embed_and_index_skips_creation_when_collection_already_exists(tmp_path):
    """recreate=False and an existing collection must not attempt creation at
    all — upserts into whatever dimension the collection already has."""
    jsonl_path = tmp_path / "reqs.jsonl"
    jsonl_path.write_text(json.dumps(_MIN_REQ) + "\n")

    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists.return_value = True
    mock_qdrant.get_collection.return_value = MagicMock(points_count=1)

    mock_ollama_client = MagicMock()
    mock_ollama_client.embed.return_value = MagicMock(embeddings=[[0.0] * 768])

    with patch("pipeline.embed_and_index.QdrantClient", return_value=mock_qdrant), \
         patch("pipeline.embed_and_index.ollama.Client", return_value=mock_ollama_client), \
         patch("pipeline.embed_and_index.SparseTextEmbedding", return_value=_mock_sparse_model()):
        embed_and_index_run(str(jsonl_path))

    mock_qdrant.create_collection.assert_not_called()
