"""Unit tests for services/evidence_service.py's synthesis model selection
(Phase 27, WP-27.2).

build() must select cfg.remote_model when synthesis_backend == "remote" and
cfg.synthesis_model when "local" -- previously it always used synthesis_model
even for the remote backend, silently sending a local Ollama model name to
Anthropic/OpenAI and swallowing the resulting failure into an empty
synthesis_text.

All external dependencies (Qdrant, Ollama, fastembed) are mocked at their
import boundary since evidence_service.build() imports them locally.
"""
from unittest.mock import MagicMock, patch

import numpy as np


def _fake_hit(source_ref="AC-2", score=0.9):
    hit = MagicMock()
    hit.payload = {
        "source_ref": source_ref,
        "source_quote": "The organization shall enforce access control.",
        "description": "Access control requirement.",
        "confidence": 0.9,
    }
    hit.score = score
    return hit


def _run_build(**overrides):
    from services import evidence_service

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
        query="access control",
        qdrant_url="http://qdrant:6333",
        ollama_url="http://ollama:11434",
        synthesize=True,
        synthesis_backend="local",
        synthesis_model="local-model",
        remote_model="remote-model",
        provider="anthropic",
        api_key="",
    )
    kwargs.update(overrides)

    with (
        patch("qdrant_client.QdrantClient", return_value=fake_qdrant_client),
        patch("ollama.Client", return_value=fake_ollama_client),
        patch("fastembed.SparseTextEmbedding", return_value=fake_sparse_model),
        patch("core.synthesis.synthesize", return_value="synthesized summary") as mock_synthesize,
    ):
        result = evidence_service.build(**kwargs)

    return result, mock_synthesize


def test_remote_backend_uses_remote_model():
    _, mock_synthesize = _run_build(synthesis_backend="remote", api_key="sk-fake")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "remote-model"


def test_local_backend_uses_synthesis_model():
    _, mock_synthesize = _run_build(synthesis_backend="local")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "local-model"


def test_synthesize_false_never_calls_synthesize():
    _, mock_synthesize = _run_build(synthesize=False)
    mock_synthesize.assert_not_called()
