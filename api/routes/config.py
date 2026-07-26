"""GET/POST /config — settings screen config service (WP-29.3)."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services import config_service

router = APIRouter()

# Fields where `null` is itself a legitimate stored value, not just "omitted
# from this request" — these three fall back to default_model at load time
# (R-2.1) when None, so the settings screen needs a way to explicitly clear
# a role-model override back to "inherit." Every other field has no such
# null-safe handling in core.config.load() (e.g. ollama_url is indexed
# straight out of the parsed dict with no `or`/default fallback), so an
# explicit null there would write a broken value into config.json.
_NULLABLE_FIELDS = frozenset({"extraction_model", "enrichment_model", "rewrite_model"})


class ConfigUpdateRequest(BaseModel):
    """API-editable config fields only.

    `processed_dir`, `authority_registry`, and `authority` are deliberately
    absent — the settings screen can't set them even though
    config_service.update_config() (the same write path cmd_init() uses)
    would accept them if called directly. Only fields actually present in
    the request body are written; everything else is left untouched
    (WP-29.3). A field sent as explicit `null` is only honored for
    `_NULLABLE_FIELDS` (see below) — for every other field, `null` is
    rejected rather than silently written or silently dropped.
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
    # exclude_unset (not exclude_none) so an explicit `null` for a
    # _NULLABLE_FIELDS entry is distinguishable from that field being
    # omitted entirely — omitted must leave the stored value untouched,
    # explicit null must clear it (Gemini review, PR #132).
    partial = req.model_dump(exclude_unset=True)
    invalid_nulls = sorted(
        key for key, value in partial.items()
        if value is None and key not in _NULLABLE_FIELDS
    )
    if invalid_nulls:
        raise HTTPException(
            status_code=422,
            detail=f"Field(s) cannot be cleared to null: {', '.join(invalid_nulls)}",
        )
    try:
        return config_service.update_config(partial)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
