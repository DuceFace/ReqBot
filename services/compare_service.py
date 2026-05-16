"""Compare service — cross-framework comparison by control ID or free-text query.

Returns structured data; all display and formatting logic stays in cli/reqbot.py.
"""
import logging
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)

# Control ID detection: AC-2, IA-5(1), AU-9, AC-2(j), IA-5(1)(a), SA-4(10)
CONTROL_ID_RE = re.compile(r"^[A-Z]{1,4}-\d+(\([0-9a-z]+\))*$", re.IGNORECASE)


def compare(
    query: str,
    qdrant_url: str,
    ollama_url: str,
    top_k: int = 10,
    document_ids: list | None = None,
) -> dict:
    """Compare a control ID or free-text query across all indexed documents.

    Returns a dict with keys:
      query: str
      mode: "exact" | "semantic"

      For exact mode:
        source_ref: str
        groups: dict[doc_key, payload]

      For semantic mode:
        ref_order: list[str]
        ref_groups: dict[ref, dict[doc_key, payload]]

    Raises:
      ValueError  — no results found
      RuntimeError — connection or embedding failure
    """
    try:
        from qdrant_client import QdrantClient
        from qdrant_client import models as _qm
    except ImportError as e:
        raise RuntimeError(
            "qdrant-client is not installed — run: "
            "pip3 install --break-system-packages qdrant-client"
        ) from e

    document_ids = document_ids or []
    is_control_id = bool(CONTROL_ID_RE.match(query.strip()))

    try:
        client = QdrantClient(url=qdrant_url, timeout=10)
    except Exception as e:
        raise RuntimeError(f"Could not connect to Qdrant: {e}") from e

    # -------------------------------------------------------------------
    # Exact match — control ID detected; scroll with source_ref filter
    # -------------------------------------------------------------------
    if is_control_id:
        query = query.strip().upper()  # Federal control IDs are always uppercase
        log.info("Control ID detected — using exact source_ref match for: %s", query)

        conditions: list = [
            _qm.FieldCondition(key="source_ref", match=_qm.MatchValue(value=query))
        ]
        if document_ids:
            conditions.append(
                _qm.FieldCondition(key="document_id", match=_qm.MatchAny(any=document_ids))
            )

        try:
            scroll_results, _ = client.scroll(
                collection_name="grc_requirements",
                scroll_filter=_qm.Filter(must=conditions),
                limit=200,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as e:
            raise RuntimeError(f"Qdrant query failed: {e}") from e

        if not scroll_results:
            raise ValueError(f"No requirements found with source_ref: {query}")

        # One representative per document — highest confidence wins ties
        doc_groups: dict[str, dict] = {}
        for r in scroll_results:
            p = r.payload or {}
            doc_key = p.get("source_pdf") or p.get("document_id") or "unknown"
            existing = doc_groups.get(doc_key)
            if existing is None or (p.get("confidence") or 0) > (existing.get("confidence") or 0):
                doc_groups[doc_key] = p

        return {
            "query": query,
            "mode": "exact",
            "source_ref": query,
            "groups": doc_groups,
        }

    # -------------------------------------------------------------------
    # Semantic path — free text; hybrid search, group by source_ref
    # -------------------------------------------------------------------
    log.info("Free-text query — using hybrid semantic search for: %s", query)

    try:
        import ollama as _ollama
        dense_vector = _ollama.Client(host=ollama_url).embed(
            model="nomic-embed-text", input=query
        ).embeddings[0]
    except Exception as e:
        raise RuntimeError(f"Dense embedding failed: {e}") from e

    try:
        from fastembed import SparseTextEmbedding as _STE
        sparse_emb = next(iter(_STE(model_name="Qdrant/bm25").embed([query])))
        sparse_vector = _qm.SparseVector(
            indices=sparse_emb.indices.tolist(),
            values=sparse_emb.values.tolist(),
        )
    except Exception as e:
        raise RuntimeError(f"Sparse embedding failed: {e}") from e

    prefetch_limit = max(100, top_k * 5)
    filter_obj = (
        _qm.Filter(must=[
            _qm.FieldCondition(key="document_id", match=_qm.MatchAny(any=document_ids))
        ])
        if document_ids else None
    )

    try:
        hits = client.query_points(
            collection_name="grc_requirements",
            prefetch=[
                _qm.Prefetch(
                    query=dense_vector, using="dense",
                    filter=filter_obj, limit=prefetch_limit,
                ),
                _qm.Prefetch(
                    query=sparse_vector, using="sparse",
                    filter=filter_obj, limit=prefetch_limit,
                ),
            ],
            query=_qm.FusionQuery(fusion=_qm.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        ).points
    except Exception as e:
        raise RuntimeError(f"Hybrid search failed: {e}") from e

    if not hits:
        raise ValueError(f"No results found for: {query}")

    # Group by source_ref, one representative per (source_ref, document) pair.
    # Preserve rank order — first occurrence of each source_ref wins ordering.
    ref_groups: dict[str, dict[str, dict]] = {}
    ref_order: list[str] = []
    for hit in hits:
        p = hit.payload or {}
        ref = p.get("source_ref") or "(no ref)"
        doc_key = p.get("source_pdf") or p.get("document_id") or "unknown"
        if ref not in ref_groups:
            ref_groups[ref] = {}
            ref_order.append(ref)
        if doc_key not in ref_groups[ref]:
            ref_groups[ref][doc_key] = p

    return {
        "query": query,
        "mode": "semantic",
        "ref_order": ref_order,
        "ref_groups": ref_groups,
    }
