"""POST /evidence — compliance evidence mapping for a topic."""
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core import config as _config
from services import evidence_service

router = APIRouter()


class EvidenceRequest(BaseModel):
    topic: str
    # accepts bare doc_key ("afi17-101") or full source_pdf ("afi17-101.pdf") --
    # resolved against the indexed corpus by evidence_service.build() (WP-27.3)
    document_ids: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    requirement_types: list[str] = Field(default_factory=list)
    synthesize: bool = False
    top_k: int = Field(default=10, ge=1, le=100)
    show_context: bool = False


@router.post("/evidence")
def post_evidence(req: EvidenceRequest) -> dict:
    """Map evidence requirements for a topic, grouped by control ID.

    Returns the evidence_service result:
      query:          the topic string
      timestamp:      ISO 8601 UTC string
      group_order:    list of source_ref strings in rank order
      groups:         dict[source_ref, {source_ref, representative, sources, context_text}]
      total_sources:  total matched requirement count
      synthesis_text: executive summary (empty string when synthesize=false)
    """
    cfg = _config.load()

    syn_backend = cfg.synthesis_backend
    syn_provider = cfg.remote_provider
    syn_api_key = ""
    if syn_backend == "remote":
        syn_api_key = os.environ.get(cfg.api_key_env, "")
        if not syn_api_key:
            syn_backend = "local"

    try:
        return evidence_service.build(
            query=req.topic,
            qdrant_url=cfg.qdrant_url,
            ollama_url=cfg.ollama_url,
            top_k=req.top_k,
            show_context=req.show_context,
            document_ids=req.document_ids or None,
            domain_tags=req.domain_tags or None,
            requirement_types=req.requirement_types or None,
            synthesize=req.synthesize,
            synthesis_backend=syn_backend,
            synthesis_model=cfg.synthesis_model,
            remote_model=cfg.remote_model,
            provider=syn_provider,
            api_key=syn_api_key,
            embedding_model=cfg.embedding_model,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Unexpected backend error: {e}")
