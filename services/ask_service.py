"""Ask service — thin orchestration wrapper over core/ask.retrieve().

Calls retrieve() and returns the canonical API response shape. No retrieval
logic lives here; all search/embedding/synthesis logic stays in core/ask.py.

Returns structured data; all display/rendering stays in cli/reqbot.py.
"""
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)


def ask(
    question: str,
    qdrant_url: str,
    ollama_url: str,
    *,
    top_k: int = 20,
    min_score: float = 0.02,
    synthesize: bool = False,
    model: str = "",
    rewrite_model: str = "",
    domain_tags: list | None = None,
    requirement_types: list | None = None,
    document_ids: list | None = None,
    no_rewrite: bool = False,
    context: bool = False,
    context_collection: str = "grc_context",
    hyde: bool = False,
    synthesis_backend: str = "local",
    synthesis_provider: str = "anthropic",
    synthesis_api_key: str = "",
) -> dict:
    """Search requirements and return the canonical API response shape.

    Returns a dict with keys:
      query:    str    — original question
      filters:  dict   — active filters (None when not applied)
      results:  list   — score + payload fields per result; context_text included when context=True
      metadata: dict   — top_k, result_count, retrieval_ms, synthesis (str | None)
                         retrieval_ms is the pure retrieval wall-time (ms) from entry to just
                         before synthesis; synthesis latency is excluded even when synthesize=True.

    Does not raise ValueError for empty results — returns result_count=0 instead.
    Raises RuntimeError on connection or embedding failure (propagated from retrieve()).
    """
    from core import ask as _ask

    data = _ask.retrieve(
        question,
        top_k=top_k,
        min_score=min_score,
        synthesize=synthesize,
        model=model or _ask.DEFAULT_SYNTHESIS_MODEL,
        domain_tags=domain_tags,
        requirement_types=requirement_types,
        document_ids=document_ids,
        no_rewrite=no_rewrite,
        rewrite_model=rewrite_model or _ask.DEFAULT_REWRITE_MODEL,
        qdrant_url=qdrant_url,
        ollama_url=ollama_url,
        context=context,
        context_collection=context_collection,
        hyde=hyde,
        synthesis_backend=synthesis_backend,
        synthesis_provider=synthesis_provider,
        synthesis_api_key=synthesis_api_key,
    )
    return {
        "query": question,
        "filters": {
            "document_id": document_ids or None,
            "domain_tag": domain_tags or None,
            "requirement_type": requirement_types or None,
        },
        "results": data["results"],
        "metadata": {
            "top_k": top_k,
            "result_count": data["total"],
            "retrieval_ms": data["retrieval_ms"],
            "synthesis": data["synthesis_text"] or None,
        },
    }
