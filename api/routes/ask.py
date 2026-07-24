"""POST /ask — hybrid vector search with optional LLM synthesis."""
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core import config as _config
from services import ask_service

router = APIRouter()


class AskRequest(BaseModel):
    question: str
    top_k: int = Field(default=20, ge=1, le=100)
    min_score: float = Field(default=0.02, ge=0.0, le=1.0)
    synthesize: bool = False
    model: str = ""
    rewrite_model: str = ""
    domain_tags: list[str] = Field(default_factory=list)
    requirement_types: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    no_rewrite: bool = False
    context: bool = False
    hyde: bool = True


@router.post("/ask")
def post_ask(req: AskRequest) -> dict:
    """Search requirements and return ranked results with optional synthesis.

    Returns the canonical response shape:
      query:    original question
      filters:  active filters (null when not applied)
      results:  list of matching requirements (score + payload fields)
      metadata: top_k, result_count, retrieval_ms, synthesis (str | null)
      warnings: list of strings, e.g. embedding-model mismatch (WP-25.6c)
    """
    cfg = _config.load()

    # Resolve synthesis backend config
    syn_backend = cfg.synthesis_backend
    syn_provider = cfg.remote_provider
    syn_api_key = ""
    if syn_backend == "remote":
        syn_api_key = os.environ.get(cfg.api_key_env, "")
        if not syn_api_key:
            syn_backend = "local"  # fall back silently; no stdout available in API

    try:
        return ask_service.ask(
            req.question,
            cfg.qdrant_url,
            cfg.ollama_url,
            top_k=req.top_k,
            min_score=req.min_score,
            synthesize=req.synthesize,
            model=req.model or cfg.synthesis_model,
            rewrite_model=req.rewrite_model or cfg.rewrite_model,
            embedding_model=cfg.embedding_model,
            domain_tags=req.domain_tags or None,
            requirement_types=req.requirement_types or None,
            document_ids=req.document_ids or None,
            processed_dir=cfg.processed_dir_path(),
            no_rewrite=req.no_rewrite,
            context=req.context,
            hyde=req.hyde,
            synthesis_backend=syn_backend,
            synthesis_provider=syn_provider,
            synthesis_api_key=syn_api_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001 — normalise unexpected backend errors
        raise HTTPException(status_code=503, detail=f"Unexpected backend error: {e}")
