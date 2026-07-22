"""Tests for HyDE default-on promotion (WP-24.5).

Covers generate_hyde_hypothesis()'s debug-log gating directly, and retrieve()'s
3-leg vs 2-leg RRF fusion behavior via mocked ollama.Client / SparseTextEmbedding
/ QdrantClient — no real Ollama/Qdrant/sparse-model calls are made.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.ask import generate_hyde_hypothesis, retrieve


class _FakeSparseEmb:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return self._values


def _fake_sparse_embedding():
    return SimpleNamespace(
        indices=_FakeSparseEmb([1, 2]),
        values=_FakeSparseEmb([0.5, 0.4]),
    )


def _patched_ask_deps():
    """Patch ollama.Client, SparseTextEmbedding, and QdrantClient as used by
    core/ask.py's retrieve(), returning the three mock instances for assertions."""
    mock_ollama_client = MagicMock()
    mock_ollama_client.embed.return_value = SimpleNamespace(embeddings=[[0.1, 0.2]])

    mock_sparse_model = MagicMock()
    mock_sparse_model.embed.return_value = iter([_fake_sparse_embedding()])

    mock_qdrant_client = MagicMock()
    mock_qdrant_client.query_points.return_value = SimpleNamespace(points=[])

    return mock_ollama_client, mock_sparse_model, mock_qdrant_client


# ---------------------------------------------------------------------------
# generate_hyde_hypothesis() — debug-log gating
# ---------------------------------------------------------------------------

def test_hypothesis_logging_skipped_by_default(tmp_path):
    log_file = tmp_path / "hyde_hypotheses.jsonl"
    mock_client = MagicMock()
    mock_client.generate.return_value = SimpleNamespace(response="A system shall encrypt data at rest.")

    result = generate_hyde_hypothesis("encryption at rest", "some-model", mock_client, log_file=str(log_file))

    assert result == "A system shall encrypt data at rest."
    assert not log_file.exists()


def test_hypothesis_logging_written_when_enabled(tmp_path):
    log_file = tmp_path / "hyde_hypotheses.jsonl"
    mock_client = MagicMock()
    mock_client.generate.return_value = SimpleNamespace(response="A system shall encrypt data at rest.")

    result = generate_hyde_hypothesis(
        "encryption at rest", "some-model", mock_client, log_file=str(log_file), enabled=True,
    )

    assert result == "A system shall encrypt data at rest."
    assert log_file.exists()
    line = json.loads(log_file.read_text().strip())
    assert line["query"] == "encryption at rest"
    assert line["hypothesis"] == "A system shall encrypt data at rest."
    assert line["model"] == "some-model"


def test_empty_hypothesis_never_logs_even_when_enabled(tmp_path):
    log_file = tmp_path / "hyde_hypotheses.jsonl"
    mock_client = MagicMock()
    mock_client.generate.return_value = SimpleNamespace(response="   ")

    result = generate_hyde_hypothesis(
        "vague question", "some-model", mock_client, log_file=str(log_file), enabled=True,
    )

    assert result is None
    assert not log_file.exists()


def test_generation_failure_returns_none_and_never_logs(tmp_path):
    log_file = tmp_path / "hyde_hypotheses.jsonl"
    mock_client = MagicMock()
    mock_client.generate.side_effect = RuntimeError("ollama unreachable")

    result = generate_hyde_hypothesis(
        "encryption at rest", "some-model", mock_client, log_file=str(log_file), enabled=True,
    )

    assert result is None
    assert not log_file.exists()


# ---------------------------------------------------------------------------
# retrieve() — default-on 3-leg RRF, --no-hyde 2-leg, fail-open behavior
# ---------------------------------------------------------------------------

def test_hyde_default_on_uses_3_leg_rrf():
    mock_ollama, mock_sparse, mock_qdrant = _patched_ask_deps()
    with patch("core.ask.ollama.Client", return_value=mock_ollama), \
         patch("core.ask.SparseTextEmbedding", return_value=mock_sparse), \
         patch("core.ask.QdrantClient", return_value=mock_qdrant), \
         patch("core.ask.generate_hyde_hypothesis", return_value="A hypothetical requirement.") as mock_gen:
        retrieve("encryption at rest", no_rewrite=True)

    mock_gen.assert_called_once()
    _, kwargs = mock_qdrant.query_points.call_args
    assert len(kwargs["prefetch"]) == 3


def test_no_hyde_uses_2_leg_rrf_and_skips_hypothesis_generation():
    mock_ollama, mock_sparse, mock_qdrant = _patched_ask_deps()
    with patch("core.ask.ollama.Client", return_value=mock_ollama), \
         patch("core.ask.SparseTextEmbedding", return_value=mock_sparse), \
         patch("core.ask.QdrantClient", return_value=mock_qdrant), \
         patch("core.ask.generate_hyde_hypothesis") as mock_gen:
        retrieve("encryption at rest", no_rewrite=True, hyde=False)

    mock_gen.assert_not_called()
    _, kwargs = mock_qdrant.query_points.call_args
    assert len(kwargs["prefetch"]) == 2


def test_no_hypothesis_falls_back_to_2_leg_rrf():
    """generate_hyde_hypothesis() returning None (empty/failed generation) must
    not add a HyDE leg — this is the fail-open path for generation failures."""
    mock_ollama, mock_sparse, mock_qdrant = _patched_ask_deps()
    with patch("core.ask.ollama.Client", return_value=mock_ollama), \
         patch("core.ask.SparseTextEmbedding", return_value=mock_sparse), \
         patch("core.ask.QdrantClient", return_value=mock_qdrant), \
         patch("core.ask.generate_hyde_hypothesis", return_value=None):
        retrieve("encryption at rest", no_rewrite=True)

    _, kwargs = mock_qdrant.query_points.call_args
    assert len(kwargs["prefetch"]) == 2
    # Only the baseline dense embed should have happened — no hypothesis embed attempt.
    assert mock_ollama.embed.call_count == 1


def test_hypothesis_embedding_failure_falls_back_to_2_leg_rrf():
    """A hypothesis is generated successfully, but embedding it fails — must
    still fall back to baseline 2-leg RRF rather than erroring."""
    mock_ollama, mock_sparse, mock_qdrant = _patched_ask_deps()
    mock_ollama.embed.side_effect = [
        SimpleNamespace(embeddings=[[0.1, 0.2]]),  # baseline dense embed succeeds
        RuntimeError("embedding backend unavailable"),  # hypothesis embed fails
    ]
    with patch("core.ask.ollama.Client", return_value=mock_ollama), \
         patch("core.ask.SparseTextEmbedding", return_value=mock_sparse), \
         patch("core.ask.QdrantClient", return_value=mock_qdrant), \
         patch("core.ask.generate_hyde_hypothesis", return_value="A hypothetical requirement."):
        result = retrieve("encryption at rest", no_rewrite=True)

    assert result["results"] == []
    _, kwargs = mock_qdrant.query_points.call_args
    assert len(kwargs["prefetch"]) == 2


def test_hyde_debug_log_disabled_by_default():
    mock_ollama, mock_sparse, mock_qdrant = _patched_ask_deps()
    with patch("core.ask.ollama.Client", return_value=mock_ollama), \
         patch("core.ask.SparseTextEmbedding", return_value=mock_sparse), \
         patch("core.ask.QdrantClient", return_value=mock_qdrant), \
         patch("core.ask.generate_hyde_hypothesis", return_value="hyp") as mock_gen:
        retrieve("encryption at rest", no_rewrite=True)

    _, kwargs = mock_gen.call_args
    assert kwargs["enabled"] is False


def test_hyde_debug_log_true_is_plumbed_through():
    mock_ollama, mock_sparse, mock_qdrant = _patched_ask_deps()
    with patch("core.ask.ollama.Client", return_value=mock_ollama), \
         patch("core.ask.SparseTextEmbedding", return_value=mock_sparse), \
         patch("core.ask.QdrantClient", return_value=mock_qdrant), \
         patch("core.ask.generate_hyde_hypothesis", return_value="hyp") as mock_gen:
        retrieve("encryption at rest", no_rewrite=True, hyde_debug_log=True)

    _, kwargs = mock_gen.call_args
    assert kwargs["enabled"] is True
