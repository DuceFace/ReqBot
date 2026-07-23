"""Unit tests for WP-25.6c — embedding model configurability + index provenance.

Covers the pure/local logic that's testable without a real Ollama/Qdrant:
  - embed_and_index.build_payload()/embed_batch() thread embedding_model through
  - embed_context_index.embed_batch() threads embedding_model through
  - core.ask._embedding_mismatch_warnings() / compare_service._embedding_warnings() /
    evidence_service._embedding_warnings() detect mismatches correctly and never
    block (empty list = no warning, not an error)
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.ask import _embedding_mismatch_warnings
from pipeline.embed_and_index import build_payload
from pipeline.embed_and_index import embed_batch as embed_and_index_batch
from pipeline.embed_context_index import embed_batch as embed_context_batch
from services.compare_service import _embedding_warnings as compare_warnings
from services.evidence_service import _embedding_warnings as evidence_warnings

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
