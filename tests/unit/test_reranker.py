"""Unit tests for WP-43's core/reranker.py.

FlashRank is always faked via a fake `flashrank` module injected into
sys.modules -- these tests must not require the optional 'rerank' extra to
be installed to run, matching this codebase's existing convention for other
optional-dependency scorers (see tests/unit/test_entailment_gate.py's
_FakeScorer for MiniCheck, the other extra-gated scorer in this codebase).
Faking the whole module (not just core.reranker._get_ranker) also exercises
rerank()'s own `from flashrank import RerankRequest` import, not just the
Ranker construction seam.
"""
import sys
import types

import pytest

from core import reranker


class _FakeRanker:
    """Stand-in for flashrank.Ranker. Scores each passage via a caller-
    supplied function of its text."""

    def __init__(self, score_fn, *_args, **_kwargs):
        self._score_fn = score_fn

    def rerank(self, request):
        for p in request.passages:
            p["score"] = self._score_fn(p["text"])
        return sorted(request.passages, key=lambda p: p["score"], reverse=True)


class _FakeRerankRequest:
    def __init__(self, query=None, passages=None):
        self.query = query
        self.passages = passages if passages is not None else []


def _install_fake_flashrank(monkeypatch, score_fn):
    fake_module = types.ModuleType("flashrank")
    fake_module.Ranker = lambda *a, **kw: _FakeRanker(score_fn)
    fake_module.RerankRequest = _FakeRerankRequest
    monkeypatch.setitem(sys.modules, "flashrank", fake_module)
    monkeypatch.setattr(reranker, "_rankers", {})


def _by_length(text: str) -> float:
    """Deterministic fake score: longer scoring text wins."""
    return float(len(text))


def _contains_restrain(text: str) -> float:
    return 1.0 if "restrain" in text.lower() else 0.0


def test_rerank_reorders_by_score(monkeypatch):
    _install_fake_flashrank(monkeypatch, _by_length)
    candidates = [
        {"requirement_id": "REQ-short", "description": "", "source_quote": "Short."},
        {"requirement_id": "REQ-long", "description": "", "source_quote": "A much longer piece of source quote text."},
    ]
    result = reranker.rerank("query", candidates, top_k=5)
    assert [r["requirement_id"] for r in result] == ["REQ-long", "REQ-short"]


def test_rerank_attaches_rerank_score(monkeypatch):
    _install_fake_flashrank(monkeypatch, _by_length)
    candidates = [{"requirement_id": "REQ-1", "description": "", "source_quote": "abc"}]
    result = reranker.rerank("query", candidates, top_k=5)
    assert result[0]["rerank_score"] == pytest.approx(3.0)
    assert isinstance(result[0]["rerank_score"], float)


def test_rerank_respects_top_k(monkeypatch):
    _install_fake_flashrank(monkeypatch, _by_length)
    candidates = [
        {"requirement_id": f"REQ-{i}", "description": "", "source_quote": "x" * i}
        for i in range(1, 6)
    ]
    result = reranker.rerank("query", candidates, top_k=2)
    assert len(result) == 2
    assert [r["requirement_id"] for r in result] == ["REQ-5", "REQ-4"]


def test_rerank_empty_candidates_returns_empty(monkeypatch):
    _install_fake_flashrank(monkeypatch, _by_length)
    assert reranker.rerank("query", [], top_k=5) == []


def test_rerank_raises_clear_error_when_flashrank_not_installed(monkeypatch):
    # The standard technique for forcing `import X` to fail without actually
    # uninstalling X: a None entry in sys.modules.
    monkeypatch.setitem(sys.modules, "flashrank", None)
    monkeypatch.setattr(reranker, "_rankers", {})
    candidates = [{"requirement_id": "REQ-1", "description": "", "source_quote": "abc"}]
    with pytest.raises(ImportError, match="rerank"):
        reranker.rerank("query", candidates, top_k=5)


def test_get_ranker_constructs_once(monkeypatch):
    calls = []
    fake_module = types.ModuleType("flashrank")
    fake_module.Ranker = lambda *a, **kw: calls.append(1) or _FakeRanker(_by_length)
    fake_module.RerankRequest = _FakeRerankRequest
    monkeypatch.setitem(sys.modules, "flashrank", fake_module)
    monkeypatch.setattr(reranker, "_rankers", {})

    reranker._get_ranker()
    reranker._get_ranker()
    assert len(calls) == 1


def test_get_ranker_uses_default_model_name(monkeypatch):
    calls = []
    fake_module = types.ModuleType("flashrank")
    fake_module.Ranker = lambda *a, **kw: calls.append(kw.get("model_name")) or _FakeRanker(_by_length)
    fake_module.RerankRequest = _FakeRerankRequest
    monkeypatch.setitem(sys.modules, "flashrank", fake_module)
    monkeypatch.setattr(reranker, "_rankers", {})

    reranker._get_ranker()
    assert calls == [reranker.DEFAULT_RERANK_MODEL]


def test_get_ranker_caches_separately_per_model(monkeypatch):
    calls = []
    fake_module = types.ModuleType("flashrank")
    fake_module.Ranker = lambda *a, **kw: calls.append(kw.get("model_name")) or _FakeRanker(_by_length)
    fake_module.RerankRequest = _FakeRerankRequest
    monkeypatch.setitem(sys.modules, "flashrank", fake_module)
    monkeypatch.setattr(reranker, "_rankers", {})

    reranker._get_ranker("model-a")
    reranker._get_ranker("model-b")
    reranker._get_ranker("model-a")  # already cached -- must not construct again
    assert calls == ["model-a", "model-b"]


def test_rerank_passes_model_name_through(monkeypatch):
    fake_module = types.ModuleType("flashrank")
    captured = {}

    def _fake_ranker_ctor(*a, **kw):
        captured["model_name"] = kw.get("model_name")
        return _FakeRanker(_by_length)

    fake_module.Ranker = _fake_ranker_ctor
    fake_module.RerankRequest = _FakeRerankRequest
    monkeypatch.setitem(sys.modules, "flashrank", fake_module)
    monkeypatch.setattr(reranker, "_rankers", {})

    candidates = [{"requirement_id": "REQ-1", "description": "", "source_quote": "abc"}]
    reranker.rerank("query", candidates, top_k=5, model_name="ms-marco-MiniLM-L-12-v2")
    assert captured["model_name"] == "ms-marco-MiniLM-L-12-v2"


def test_scoring_text_prefers_embedding_text_over_source_quote():
    candidate = {
        "description": "",
        "source_quote": "(3) Restrain competition.",
        "embedding_text": "Units will actively work to prevent anti-competitive practices, "
                           "including: (3) Restrain competition.",
    }
    text = reranker._scoring_text(candidate)
    assert text == candidate["embedding_text"]


def test_scoring_text_falls_back_to_source_quote_when_no_embedding_text():
    candidate = {"description": "", "source_quote": "Passwords must be 15 characters.", "embedding_text": ""}
    text = reranker._scoring_text(candidate)
    assert text == "Passwords must be 15 characters."


def test_scoring_text_includes_description():
    candidate = {"description": "Password length", "source_quote": "Must be 15 characters.", "embedding_text": ""}
    text = reranker._scoring_text(candidate)
    assert "Password length" in text
    assert "Must be 15 characters." in text


def test_parent_child_context_fragment_scores_using_governing_clause(monkeypatch):
    """Codex review (PR #190): a fragment-shaped quote with no visible
    antecedent must be scored using its parent-stem-reconstructed
    embedding_text, not the bare fragment -- otherwise a reranker that
    scores on lexical/semantic content would never see the term that makes
    it relevant. Same underlying requirement (identical source_quote),
    varying only whether embedding_text is present, isolates the variable:
    without it, the dangling fragment alone doesn't mention "restrain" and
    scores 0; with it, the reconstructed governing clause does and scores 1."""
    _install_fake_flashrank(monkeypatch, _contains_restrain)
    dangling_fragment = "(3) Prevent monopolistic behavior."

    fragment_only = [{
        "requirement_id": "REQ-fragment",
        "description": "",
        "source_quote": dangling_fragment,
        "embedding_text": "",
    }]
    reconstructed = [{
        "requirement_id": "REQ-reconstructed",
        "description": "",
        "source_quote": dangling_fragment,
        "embedding_text": "Units will actively work to restrain anti-competitive practices, "
                           f"including: {dangling_fragment}",
    }]

    fragment_result = reranker.rerank("competition restraint rules", fragment_only, top_k=1)
    reconstructed_result = reranker.rerank("competition restraint rules", reconstructed, top_k=1)

    assert fragment_result[0]["rerank_score"] == pytest.approx(0.0)
    assert reconstructed_result[0]["rerank_score"] == pytest.approx(1.0)
