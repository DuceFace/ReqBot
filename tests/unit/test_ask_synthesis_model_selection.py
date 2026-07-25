"""Unit tests for core/ask.py's retrieve() synthesis model selection
(Phase 27, WP-27.4).

retrieve() must select remote_model when synthesis_backend == "remote" (and
remote_model is non-empty) and synthesis_model when "local" -- previously
run() (CLI) and ask_service.ask() (API) each pre-resolved a single "model"
string using only synthesis_model, so a remote-configured backend silently
sent the local Ollama model name to the remote provider. An explicit `model`
override always wins regardless of backend.

All external dependencies (Qdrant, Ollama, fastembed) are mocked at their
module-level import boundary in core/ask.py -- hyde=False and no_rewrite=True
keep the mock surface small by skipping the query-rewrite and HyDE-hypothesis
Ollama calls, which aren't relevant to model selection.
"""
from unittest.mock import MagicMock, patch

import numpy as np

from core import ask as core_ask


def _fake_hit(score=0.9):
    hit = MagicMock()
    hit.score = score
    hit.payload = {
        "requirement_id": "REQ-abc123",
        "source_quote": "Systems must enforce access control.",
        "source_ref": "1.1",
    }
    return hit


def _run_retrieve(**overrides):
    fake_qdrant_client = MagicMock()
    fake_qdrant_client.query_points.return_value.points = [_fake_hit()]

    fake_ollama_client = MagicMock()
    fake_ollama_client.embed.return_value.embeddings = [[0.1, 0.2, 0.3]]

    fake_sparse_emb = MagicMock()
    fake_sparse_emb.indices = np.array([0, 1])
    fake_sparse_emb.values = np.array([0.5, 0.5])
    fake_sparse_model = MagicMock()
    fake_sparse_model.embed.return_value = iter([fake_sparse_emb])

    kwargs = dict(
        top_k=5,
        synthesize=True,
        synthesis_backend="local",
        synthesis_model="local-model",
        remote_model="remote-model",
        no_rewrite=True,
        hyde=False,
    )
    kwargs.update(overrides)

    with (
        patch("core.ask.QdrantClient", return_value=fake_qdrant_client),
        patch("core.ask.ollama.Client", return_value=fake_ollama_client),
        patch("core.ask.SparseTextEmbedding", return_value=fake_sparse_model),
        patch("core.synthesis.synthesize", return_value="synthesized answer") as mock_synthesize,
    ):
        result = core_ask.retrieve("access control", **kwargs)

    return result, mock_synthesize


def test_remote_backend_uses_remote_model():
    _, mock_synthesize = _run_retrieve(synthesis_backend="remote")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "remote-model"


def test_local_backend_uses_synthesis_model():
    _, mock_synthesize = _run_retrieve(synthesis_backend="local")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "local-model"


def test_remote_backend_with_empty_remote_model_falls_back_to_synthesis_model():
    """Same fallback WP-27.2 added for evidence: an empty remote_model must
    not reach synthesize() as an empty model string."""
    _, mock_synthesize = _run_retrieve(synthesis_backend="remote", remote_model="")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "local-model"


def test_explicit_model_override_wins_over_local_backend():
    _, mock_synthesize = _run_retrieve(synthesis_backend="local", model="explicit-model")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "explicit-model"


def test_explicit_model_override_wins_over_remote_backend():
    """The explicit caller override (--model / AskRequest.model) must win
    regardless of synthesis_backend -- unlike evidence, ask/search_requirements
    expose a per-call override that predates and takes priority over the
    backend-based selection this WP added."""
    _, mock_synthesize = _run_retrieve(synthesis_backend="remote", model="explicit-model")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "explicit-model"


def test_synthesize_false_never_calls_synthesize():
    _, mock_synthesize = _run_retrieve(synthesize=False)
    mock_synthesize.assert_not_called()
