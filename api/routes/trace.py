"""GET /trace/{req_id} — full requirement provenance by ID."""
from fastapi import APIRouter, HTTPException

from core import config as _config
from services import trace_service

router = APIRouter()


@router.get("/trace/{req_id}")
def get_trace(req_id: str, context: bool = False) -> dict:
    """Return full provenance for a requirement: payload, cross-framework matches, context.

    Query params:
      context (bool, default false) — include surrounding raw chunk text from grc_context

    Returns:
      requirement:   full Qdrant payload dict
      cross_matches: list of payloads with the same source_ref from other documents
      context_text:  surrounding chunk text, or null if context=false or unavailable

    Raises 404 when the requirement ID is not found.
    Raises 503 on Qdrant connection failure.
    """
    cfg = _config.load()
    try:
        return trace_service.trace(req_id, cfg.qdrant_url, show_context=context)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
