"""GET/POST /config — settings screen config service (WP-29.3)."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services import config_service

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    """API-editable config fields only.

    `processed_dir`, `authority_registry`, and `authority` are deliberately
    absent — the settings screen can't set them even though
    config_service.update_config() (the same write path cmd_init() uses)
    would accept them if called directly. Only fields set here (non-None)
    are written; everything else is left untouched (WP-29.3).
    """
    ollama_url: Optional[str] = None
    qdrant_url: Optional[str] = None
    default_model: Optional[str] = None
    extraction_model: Optional[str] = None
    enrichment_model: Optional[str] = None
    rewrite_model: Optional[str] = None
    synthesis_model: Optional[str] = None
    embedding_model: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=100)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    synthesis_backend: Optional[Literal["local", "remote", "none"]] = None
    remote_provider: Optional[Literal["anthropic", "openai"]] = None
    remote_model: Optional[str] = None
    api_key_env: Optional[str] = None


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else None
    return host in ("127.0.0.1", "::1")


@router.get("/config")
def get_config() -> dict:
    """Return effective config values plus which fields are env-overridden."""
    return config_service.get_config()


@router.post("/config")
def post_config(req: ConfigUpdateRequest, request: Request) -> dict:
    """Partial-merge the provided fields into config.json.

    Loopback-only: `reqbot serve` may be bound to a non-loopback interface
    for GUI access from other machines, but this mutating endpoint only
    accepts requests whose direct client address is localhost (see Guardrail
    #7 — this is a stopgap against LAN-visible config writes, not a
    substitute for real authentication).
    """
    if not _is_loopback(request):
        raise HTTPException(
            status_code=403, detail="POST /config is restricted to localhost"
        )
    partial = req.model_dump(exclude_none=True)
    try:
        return config_service.update_config(partial)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
