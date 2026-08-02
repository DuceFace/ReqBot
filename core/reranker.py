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

# FlashRank's own default. Named explicitly here (not left implicit in a bare
# Ranker() call) because WP-43's spike measured this exact model and found it
# doesn't clear the Precision@5 gate -- see docs/PHASE43_REQUIREMENTS.md §11.
# model_name is a parameter specifically so a stronger bundled FlashRank model
# (e.g. "ms-marco-MiniLM-L-12-v2") can be swapped in and measured without
# touching this module's shape -- see §11.5's Backlog.
DEFAULT_RERANK_MODEL = "ms-marco-TinyBERT-L-2-v2"

_rankers: dict = {}


def _get_ranker(model_name: str = DEFAULT_RERANK_MODEL):
    """Lazily construct and cache one FlashRank Ranker per model_name for the
    process lifetime -- loading the ONNX model/tokenizer on every call would
    dominate latency and contaminate any latency measurement."""
    if model_name not in _rankers:
        try:
            from flashrank import Ranker
        except ImportError as exc:
            raise ImportError(
                "Reranking requires the 'rerank' extra: pip install '.[rerank]' "
                "(or `pip install flashrank`)."
            ) from exc
        _rankers[model_name] = Ranker(model_name=model_name)
    return _rankers[model_name]


def _scoring_text(candidate: dict) -> str:
    """Text FlashRank scores against the query for one candidate.

    Prefers embedding_text (WP-39.2's parent-stem-prefixed reconstruction)
    over bare source_quote, mirroring pipeline/embed_and_index.py's
    build_embedding_text() precedence at index time -- without it, a
    fragment-shaped quote (e.g. "(3) Restrain competition." with no visible
    list-introducing clause) reaches the reranker with no governing context
    and can be wrongly demoted.

    Also includes source_ref when present (Codex review, PR #191), for the
    same reason build_embedding_text() appends it at index time: for a
    control-catalog-style corpus (e.g. NIST 800-53), source_ref can itself be
    the control ID (e.g. "AC-3") -- an exact-match signal on the candidate
    side that would otherwise only exist in the query (dense_query/
    expanded_query already retains control ID text as verified live against
    the rewrite model; sparse/BM25 already gets it explicitly). No document
    currently indexed has a control-ID-shaped source_ref (verified live
    against the corpus), but source_ref itself (section/paragraph numbers
    for this corpus's actual documents) is present on virtually every
    record, so this changes the scoring text for every candidate today, not
    just a hypothetical future one -- §11's committed artifacts were
    regenerated after this change for that reason.
    """
    description = (candidate.get("description") or "").strip()
    body = (candidate.get("embedding_text") or "").strip() or (candidate.get("source_quote") or "").strip()
    source_ref = (candidate.get("source_ref") or "").strip()
    parts = [p for p in (description, body) if p]
    text = "\n".join(parts)
    if source_ref:
        text += f"\nRef: {source_ref}"
    return text


def rerank(
    query: str, candidates: list[dict], top_k: int, model_name: str = DEFAULT_RERANK_MODEL,
) -> list[dict]:
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
    ranker = _get_ranker(model_name)
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
