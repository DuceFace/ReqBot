"""Trace service — looks up a requirement by ID and returns provenance data.

Returns structured data; all display logic stays in cli/reqbot.py.
"""
import logging
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)

from core import constants as _const


def trace(req_id: str, qdrant_url: str, show_context: bool = False) -> dict:
    """Look up a requirement by ID and return its full provenance.

    Returns a dict with keys:
      requirement: dict (full Qdrant payload)
      cross_matches: list[dict] (same source_ref, one representative per other document)
      context_text: str | None (surrounding chunk text; None if show_context=False or unavailable)

    Raises:
      ValueError  — requirement not found
      RuntimeError — Qdrant connection or query failure
    """
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue
    except ImportError as e:
        raise RuntimeError(
            "qdrant-client is not installed — run: "
            "pip3 install --break-system-packages qdrant-client"
        ) from e

    try:
        client = QdrantClient(url=qdrant_url, timeout=10)
    except Exception as e:
        raise RuntimeError(f"Could not connect to Qdrant: {e}") from e

    # Step 1: Look up requirement by ID — scroll with filter, no vector search
    try:
        results, _ = client.scroll(
            collection_name="grc_requirements",
            scroll_filter=Filter(
                must=[FieldCondition(key="requirement_id", match=MatchValue(value=req_id))]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        raise RuntimeError(f"Qdrant query failed: {e}") from e

    if not results:
        raise ValueError(f"Requirement not found: {req_id}")

    payload = results[0].payload or {}
    source_ref = payload.get("source_ref", "")

    # Step 2: Cross-framework matches — same source_ref, one representative per other document
    cross_matches: list[dict] = []
    if source_ref:
        try:
            all_matches, _ = client.scroll(
                collection_name="grc_requirements",
                scroll_filter=Filter(
                    must=[FieldCondition(key="source_ref", match=MatchValue(value=source_ref))]
                ),
                limit=200,
                with_payload=True,
                with_vectors=False,
            )
            target_doc_id = payload.get("document_id")
            seen_docs: set = set()
            if target_doc_id:
                seen_docs.add(target_doc_id)
            for r in all_matches:
                p = r.payload or {}
                if p.get("requirement_id") == req_id:
                    continue
                doc_id = p.get("document_id")
                if doc_id:
                    if doc_id not in seen_docs:
                        seen_docs.add(doc_id)
                        cross_matches.append(p)
                else:
                    cross_matches.append(p)
        except Exception as e:
            log.warning("Cross-framework query failed: %s", e)

    # Step 3: Retrieve context chunk from grc_context (optional)
    context_text: str | None = None
    if show_context:
        doc_id = payload.get("document_id", "")
        chunk_id = payload.get("chunk_id")
        if doc_id and chunk_id is not None:
            pid = str(uuid.uuid5(_const.CONTEXT_UUID_NS, f"{doc_id}:{chunk_id}"))
            try:
                ctx_hits = client.retrieve(
                    collection_name="grc_context",
                    ids=[pid],
                    with_payload=True,
                )
                if ctx_hits:
                    ctx = ctx_hits[0].payload.get("text", "") if ctx_hits[0].payload else ""
                    if ctx:
                        quote = payload.get("source_quote", "")
                        window = 300
                        if quote and quote in ctx:
                            idx = ctx.find(quote)
                            start = max(0, idx - window)
                            end = min(len(ctx), idx + len(quote) + window)
                            prefix = "..." if start > 0 else ""
                            suffix = "..." if end < len(ctx) else ""
                            context_text = prefix + ctx[start:end] + suffix
                        else:
                            context_text = ctx[:window * 2] + ("..." if len(ctx) > window * 2 else "")
            except Exception as e:
                log.warning("Context retrieval failed: %s", e)
        else:
            log.warning("No chunk_id or document_id — cannot retrieve context chunk")

    return {
        "requirement": {**payload, "domain_profile": payload.get("domain_profile") or "cybersecurity"},
        "cross_matches": cross_matches,
        "context_text": context_text,
    }
