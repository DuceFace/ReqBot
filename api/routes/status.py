"""GET /status — Ollama + Qdrant health checks and processed document listing."""
from fastapi import APIRouter, HTTPException

from core import config as _config
from services import status_service

router = APIRouter()


@router.get("/status")
def get_status() -> dict:
    """Return Ollama reachability, Qdrant reachability, and processed document count."""
    cfg = _config.load()
    try:
        return status_service.check(
            cfg.ollama_url,
            cfg.qdrant_url,
            cfg.processed_dir_path(),
            {
                "embedding": cfg.embedding_model,
                "extraction": cfg.extraction_model,
                "enrichment": cfg.enrichment_model,
                "rewrite": cfg.rewrite_model,
                "synthesis": cfg.synthesis_model,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
