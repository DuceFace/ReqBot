"""WP-43: standalone, retrieval-agnostic reranker.

Deliberately decoupled from core.ask.retrieve() -- takes a query and a list
of already-fetched candidate dicts, returns them reordered by a local
cross-encoder's relevance score. Any future caller (Evidence, Compare) can
reuse this once it has its own candidate-pool headroom; this module makes no
assumption about who fetched its input. See docs/PHASE43_REQUIREMENTS.md §4.

Uses FlashRank (flashrank.Ranker), imported lazily so this module can be
imported without the optional 'rerank' extra installed -- only actually
calling rerank() requires it.
"""
import logging

log = logging.getLogger(__name__)

_ranker = None


def _get_ranker():
    """Lazily construct and cache a single FlashRank Ranker for the process
    lifetime -- loading the ONNX model/tokenizer on every call would dominate
    latency and contaminate any latency measurement."""
    global _ranker
    if _ranker is None:
        try:
            from flashrank import Ranker
        except ImportError as exc:
            raise ImportError(
                "Reranking requires the 'rerank' extra: pip install '.[rerank]' "
                "(or `pip install flashrank`)."
            ) from exc
        _ranker = Ranker()
    return _ranker


def _scoring_text(candidate: dict) -> str:
    """Text FlashRank scores against the query for one candidate.

    Prefers embedding_text (WP-39.2's parent-stem-prefixed reconstruction)
    over bare source_quote, mirroring pipeline/embed_and_index.py's
    build_embedding_text() precedence at index time -- without it, a
    fragment-shaped quote (e.g. "(3) Restrain competition." with no visible
    list-introducing clause) reaches the reranker with no governing context
    and can be wrongly demoted.
    """
    description = (candidate.get("description") or "").strip()
    body = (candidate.get("embedding_text") or "").strip() or (candidate.get("source_quote") or "").strip()
    parts = [p for p in (description, body) if p]
    return "\n".join(parts)


def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Reorder candidates by relevance to query, trim to top_k.

    Each returned dict is the same object passed in, with a new
    rerank_score field attached (float, FlashRank's own confidence score --
    higher is more relevant). Order is descending by rerank_score.
    """
    if not candidates:
        return []

    # _get_ranker() first -- it's the seam that raises the clear "install the
    # 'rerank' extra" error. Importing RerankRequest before it would instead
    # surface flashrank's own bare ModuleNotFoundError when the extra isn't
    # installed.
    ranker = _get_ranker()
    from flashrank import RerankRequest

    passages = [
        {"id": i, "text": _scoring_text(c)}
        for i, c in enumerate(candidates)
    ]
    scored = ranker.rerank(RerankRequest(query=query, passages=passages))
    score_by_id = {p["id"]: p["score"] for p in scored}

    for i, c in enumerate(candidates):
        c["rerank_score"] = float(score_by_id[i])

    ordered = sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
    return ordered[:top_k]
