"""Unit tests for WP-43's retrieve(rerank=True) wiring in core/ask.py.

core.reranker.rerank() itself is always mocked (patched as core.ask.rerank_
candidates, the name it's imported under) -- these tests must not require
the optional 'rerank' extra installed to run, same discipline as
tests/unit/test_reranker.py. All other external dependencies (Qdrant,
Ollama, fastembed) are mocked at their module-level import boundary in
core/ask.py, following tests/unit/test_ask_synthesis_model_selection.py's
established pattern.
"""
from unittest.mock import MagicMock, patch

import numpy as np

from core import ask as core_ask


def _fake_hit(requirement_id: str, score: float, **extra_payload):
    hit = MagicMock()
    hit.score = score
    hit.payload = {
        "requirement_id": requirement_id,
        "source_quote": f"Source quote for {requirement_id}.",
        "description": "",
        "embedding_text": "",
        **extra_payload,
    }
    return hit


def _run_retrieve(hits, **overrides):
    fake_qdrant_client = MagicMock()
    fake_qdrant_client.query_points.return_value.points = hits

    fake_ollama_client = MagicMock()
    fake_ollama_client.embed.return_value.embeddings = [[0.1, 0.2, 0.3]]

    fake_sparse_emb = MagicMock()
    fake_sparse_emb.indices = np.array([0, 1])
    fake_sparse_emb.values = np.array([0.5, 0.5])
    fake_sparse_model = MagicMock()
    fake_sparse_model.embed.return_value = iter([fake_sparse_emb])

    kwargs = dict(top_k=5, no_rewrite=True, hyde=False)
    kwargs.update(overrides)

    with (
        patch("core.ask.QdrantClient", return_value=fake_qdrant_client),
        patch("core.ask.ollama.Client", return_value=fake_ollama_client),
        patch("core.ask.SparseTextEmbedding", return_value=fake_sparse_model),
    ):
        result = core_ask.retrieve("access control", **kwargs)

    return result, fake_qdrant_client


def test_rerank_false_default_never_calls_reranker():
    hits = [_fake_hit("REQ-1", score=0.5)]
    with patch("core.ask.rerank_candidates") as mock_rerank:
        result, _ = _run_retrieve(hits)
    mock_rerank.assert_not_called()
    assert result["results"][0]["requirement_id"] == "REQ-1"
    assert "rerank_score" not in result["results"][0]


def test_rerank_true_widens_fusion_limit_regardless_of_min_score():
    # min_score=0 would give fusion_limit=top_k (5) under the non-rerank
    # branch -- rerank=True must widen it to rerank_pool_size regardless.
    hits = [_fake_hit("REQ-1", score=0.5)]
    with patch("core.ask.rerank_candidates", return_value=[
        {"requirement_id": "REQ-1", "rerank_score": 0.9},
    ]):
        _, fake_client = _run_retrieve(
            hits, top_k=5, min_score=0.0, rerank=True, rerank_pool_size=50,
        )
    assert fake_client.query_points.call_args.kwargs["limit"] == 50
    prefetch_legs = fake_client.query_points.call_args.kwargs["prefetch"]
    assert all(leg.limit >= 50 for leg in prefetch_legs)


def test_rerank_true_skips_min_score_filter():
    # A high min_score that would normally filter out every low-scoring hit
    # must not apply when rerank=True -- the reranker's own ordering decides.
    hits = [_fake_hit("REQ-low", score=0.01)]
    with patch("core.ask.rerank_candidates", return_value=[
        {"requirement_id": "REQ-low", "rerank_score": 0.9},
    ]):
        result, _ = _run_retrieve(hits, min_score=0.99, rerank=True)
    assert len(result["results"]) == 1
    assert result["results"][0]["requirement_id"] == "REQ-low"


def test_rerank_true_calls_reranker_with_fused_candidates():
    hits = [_fake_hit("REQ-1", score=0.5), _fake_hit("REQ-2", score=0.4)]
    with patch("core.ask.rerank_candidates", return_value=[
        {"requirement_id": "REQ-1", "rerank_score": 0.9},
        {"requirement_id": "REQ-2", "rerank_score": 0.1},
    ]) as mock_rerank:
        _run_retrieve(hits, top_k=5, rerank=True)

    call_args = mock_rerank.call_args
    query, candidates, top_k = call_args[0]
    assert isinstance(query, str)
    assert {c["requirement_id"] for c in candidates} == {"REQ-1", "REQ-2"}
    assert top_k == 5
    assert call_args.kwargs["model_name"] == core_ask.DEFAULT_RERANK_MODEL


def test_rerank_model_override_passed_through():
    hits = [_fake_hit("REQ-1", score=0.5)]
    with patch("core.ask.rerank_candidates", return_value=[
        {"requirement_id": "REQ-1", "rerank_score": 0.9},
    ]) as mock_rerank:
        _run_retrieve(hits, rerank=True, rerank_model="ms-marco-MiniLM-L-12-v2")
    assert mock_rerank.call_args.kwargs["model_name"] == "ms-marco-MiniLM-L-12-v2"


def test_rerank_score_flows_through_to_result_dict():
    hits = [_fake_hit("REQ-1", score=0.5), _fake_hit("REQ-2", score=0.9)]
    with patch("core.ask.rerank_candidates", return_value=[
        # Reranker deliberately inverts the original RRF order.
        {"requirement_id": "REQ-1", "rerank_score": 0.99},
        {"requirement_id": "REQ-2", "rerank_score": 0.01},
    ]):
        result, _ = _run_retrieve(hits, rerank=True)

    results_by_id = {r["requirement_id"]: r for r in result["results"]}
    assert results_by_id["REQ-1"]["rerank_score"] == 0.99
    assert results_by_id["REQ-1"]["score"] == 0.5  # original RRF score preserved
    assert results_by_id["REQ-2"]["rerank_score"] == 0.01
    # Final order follows the reranker's order, not the original RRF order.
    assert [r["requirement_id"] for r in result["results"]] == ["REQ-1", "REQ-2"]


def test_rerank_true_result_order_and_trim_follows_reranker():
    hits = [_fake_hit(f"REQ-{i}", score=1.0 - i * 0.1) for i in range(4)]
    # Reranker returns only 2 of the 4 candidates (top_k trim already applied
    # inside the real rerank(), simulated here), in a specific order.
    with patch("core.ask.rerank_candidates", return_value=[
        {"requirement_id": "REQ-3", "rerank_score": 0.9},
        {"requirement_id": "REQ-0", "rerank_score": 0.8},
    ]):
        result, _ = _run_retrieve(hits, top_k=2, rerank=True)

    assert [r["requirement_id"] for r in result["results"]] == ["REQ-3", "REQ-0"]
    assert result["total"] == 2
