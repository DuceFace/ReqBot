"""Unit tests for services/evidence_service.py's synthesis model selection
(Phase 27, WP-27.2) and document_ids filter (Phase 27, WP-27.3).

build() must select cfg.remote_model when synthesis_backend == "remote" and
cfg.synthesis_model when "local" -- previously it always used synthesis_model
even for the remote backend, silently sending a local Ollama model name to
Anthropic/OpenAI and swallowing the resulting failure into an empty
synthesis_text.

build()'s document_ids filter must resolve caller-facing doc_key/source_pdf
values against the indexed corpus and filter on the source_pdf field --
previously it filtered on the internal document_id hash, which no normal
caller can know.

All external dependencies (Qdrant, Ollama, fastembed) are mocked at their
import boundary since evidence_service.build() imports them locally.
"""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


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


def _run_build(document_id_counts: dict[str, int] | None = None, **overrides):
    from services import evidence_service

    fake_qdrant_client = MagicMock()
    fake_qdrant_client.query_points.return_value.points = [_fake_hit()]

    counts = document_id_counts or {}

    def _count(collection_name, count_filter, exact):
        match_value = count_filter.must[0].match.value
        result = MagicMock()
        result.count = counts.get(match_value, 0)
        return result

    fake_qdrant_client.count.side_effect = _count

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

    return result, mock_synthesize, fake_qdrant_client


def test_remote_backend_uses_remote_model():
    _, mock_synthesize, _ = _run_build(synthesis_backend="remote", api_key="sk-fake")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "remote-model"


def test_local_backend_uses_synthesis_model():
    _, mock_synthesize, _ = _run_build(synthesis_backend="local")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "local-model"


def test_synthesize_false_never_calls_synthesize():
    _, mock_synthesize, _ = _run_build(synthesize=False)
    mock_synthesize.assert_not_called()


def test_remote_backend_with_empty_remote_model_falls_back_to_synthesis_model():
    """Gemini review, PR #120: remote_model="" (or omitted) must not reach
    synthesize() as an empty model string -- fall back to synthesis_model
    rather than sending a doomed empty request."""
    _, mock_synthesize, _ = _run_build(synthesis_backend="remote", remote_model="")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "local-model"


# ---------------------------------------------------------------------------
# document_ids filter (Phase 27, WP-27.3)
#
# resolve_document_ids() itself (candidate resolution, .pdf-suffix handling)
# is exhaustively covered in tests/unit/test_ask_document_ids_validation.py --
# these tests only confirm build() wires document_ids through that same
# resolver and filters on the caller-facing source_pdf field, not the
# internal document_id hash.
# ---------------------------------------------------------------------------

def test_document_ids_resolved_and_filtered_on_source_pdf_not_hash():
    """A bare doc_key resolves to its real source_pdf form and the Qdrant
    filter is built on the source_pdf field -- not the internal document_id
    hash the pre-WP-27.3 filter used."""
    _, _, fake_client = _run_build(
        document_id_counts={"afi17-101.pdf": 3}, document_ids=["afi17-101"]
    )
    _, kwargs = fake_client.query_points.call_args
    filter_obj = kwargs["prefetch"][0].filter
    condition = filter_obj.must[0]
    assert condition.key == "source_pdf"
    assert condition.match.any == ["afi17-101.pdf"]


def test_document_ids_accepts_full_source_pdf_form():
    _, _, fake_client = _run_build(
        document_id_counts={"afi17-101.pdf": 3}, document_ids=["afi17-101.pdf"]
    )
    _, kwargs = fake_client.query_points.call_args
    condition = kwargs["prefetch"][0].filter.must[0]
    assert condition.match.any == ["afi17-101.pdf"]


def test_unknown_document_ids_raises_value_error_not_empty_result():
    """A stale/typo'd document_ids value must error, not silently produce an
    empty/reduced evidence pack (same hard-error rule as WP-27.1)."""
    with pytest.raises(ValueError, match="nonexistent-doc"):
        _run_build(document_id_counts={}, document_ids=["nonexistent-doc"])


def test_no_document_ids_applies_no_filter():
    _, _, fake_client = _run_build(document_ids=None)
    _, kwargs = fake_client.query_points.call_args
    assert kwargs["prefetch"][0].filter is None
