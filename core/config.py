#!/usr/bin/env python3
"""ReqBot configuration loader.

Load order (later layers override earlier ones):
  1. Hardcoded fallbacks
  2. ~/.config/reqbot/config.json
  3. Environment variables (REQBOT_*)

No external dependencies — stdlib only.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path.home() / ".config" / "reqbot" / "config.json"
AUTHORITY_REGISTRY_PATH = Path.home() / ".config" / "reqbot" / "authority.json"

_DEFAULTS: dict = {
    "ollama_url": "http://localhost:11434",
    "qdrant_url": "http://localhost:6333",
    "default_model": "llama3.1:8b-instruct-q4_K_M",
    "extraction_model": None,   # None → falls back to default_model at load time (R-2.1)
    "enrichment_model": None,   # None → falls back to default_model at load time (R-2.1)
    "rewrite_model": None,      # None → falls back to default_model at load time (R-2.1)
    "synthesis_model": "qwen2.5:14b",
    # embedding_model is independent of default_model — it defines the vector shape
    # already stored in Qdrant, so it never silently inherits a default_model change
    # the way extraction/enrichment/rewrite do (WP-25.6c).
    "embedding_model": "nomic-embed-text",
    "top_k": 20,
    "min_score": 0.02,
    "processed_dir": "~/documents/processed",
    "authority_registry": None,
    "synthesis_backend": "local",
    "remote_provider": "anthropic",
    "remote_model": "claude-sonnet-4-6",
    "api_key_env": "ANTHROPIC_API_KEY",
}

_ENV_MAP: dict[str, str] = {
    "ollama_url": "REQBOT_OLLAMA_URL",
    "qdrant_url": "REQBOT_QDRANT_URL",
    "default_model": "REQBOT_DEFAULT_MODEL",
    "extraction_model": "REQBOT_EXTRACTION_MODEL",
    "enrichment_model": "REQBOT_ENRICHMENT_MODEL",
    "rewrite_model": "REQBOT_REWRITE_MODEL",
    "synthesis_model": "REQBOT_SYNTHESIS_MODEL",
    "embedding_model": "REQBOT_EMBEDDING_MODEL",
    "top_k": "REQBOT_TOP_K",
    "min_score": "REQBOT_MIN_SCORE",
    "processed_dir": "REQBOT_PROCESSED_DIR",
    "synthesis_backend": "REQBOT_SYNTHESIS_BACKEND",
}


@dataclass
class AuthorityEntry:
    source_pdf: str
    authority_weight: int
    document_type: str = ""
    framework: str = ""
    revision: str = ""
    publication_date: str = ""


@dataclass
class ReqBotConfig:
    ollama_url: str
    qdrant_url: str
    default_model: str
    extraction_model: str   # Step C; falls back to default_model when not set in config
    enrichment_model: str   # Step D.5; falls back to default_model when not set in config
    rewrite_model: str      # query rewrite + HyDE; falls back to default_model when not set
    synthesis_model: str
    embedding_model: str    # defines the vector shape stored in Qdrant; independent of default_model
    top_k: int
    min_score: float
    processed_dir: str
    authority_registry: Optional[str] = None
    synthesis_backend: str = "local"
    remote_provider: str = "anthropic"
    remote_model: str = "claude-sonnet-4-6"
    api_key_env: str = "ANTHROPIC_API_KEY"
    authority: dict = field(default_factory=dict)  # source_pdf -> AuthorityEntry

    def processed_dir_path(self) -> Path:
        """Return processed_dir as an expanded, absolute Path."""
        return Path(self.processed_dir).expanduser().resolve()

    def authority_weight(self, source_pdf: str) -> Optional[int]:
        """Return authority weight for a document, or None if not registered."""
        entry = self.authority.get(source_pdf)
        return entry.authority_weight if entry else None

    def authority_framework(self, source_pdf: str) -> str:
        """Return framework name for a document, or empty string if not registered."""
        entry = self.authority.get(source_pdf)
        return entry.framework if entry else ""


def _load_authority_registry(registry_path: str) -> dict:
    """Load authority.json and return {source_pdf: AuthorityEntry} map."""
    try:
        path = Path(registry_path).expanduser()
        if not path.exists():
            # Also try the default location
            path = AUTHORITY_REGISTRY_PATH
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        result = {}
        for doc in data.get("documents", []):
            src = doc.get("source_pdf", "")
            if src:
                result[src] = AuthorityEntry(
                    source_pdf=src,
                    authority_weight=int(doc.get("authority_weight", 1)),
                    document_type=doc.get("document_type", ""),
                    framework=doc.get("framework", ""),
                    revision=doc.get("revision", ""),
                    publication_date=doc.get("publication_date", ""),
                )
        return result
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def load() -> ReqBotConfig:
    """Load config with three-layer fallback: defaults → file → env vars."""
    values: dict = dict(_DEFAULTS)

    # Layer 1: config file
    if CONFIG_PATH.exists():
        try:
            file_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for key in _DEFAULTS:
                if key in file_cfg:
                    values[key] = file_cfg[key]
        except (json.JSONDecodeError, OSError):
            pass  # corrupted or unreadable — fall through to env/defaults

    # Layer 2: environment variables (override file)
    for key, env_var in _ENV_MAP.items():
        val = os.environ.get(env_var)
        if val is not None:
            if key == "top_k":
                try:
                    values[key] = int(val)
                except ValueError:
                    pass  # ignore malformed int, keep file/default value
            elif key == "min_score":
                try:
                    values[key] = float(val)
                except ValueError:
                    pass  # ignore malformed float, keep file/default value
            else:
                values[key] = val

    # R-2.1: extraction_model / enrichment_model / rewrite_model fall back to default_model
    # when absent. Existing configs that predate WP-2 (or WP-25.6b for rewrite_model) will
    # have None here — resolve silently.
    default_model = values["default_model"]
    extraction_model = values.get("extraction_model") or default_model
    enrichment_model = values.get("enrichment_model") or default_model
    rewrite_model = values.get("rewrite_model") or default_model

    cfg = ReqBotConfig(
        ollama_url=values["ollama_url"],
        qdrant_url=values["qdrant_url"],
        default_model=default_model,
        extraction_model=extraction_model,
        enrichment_model=enrichment_model,
        rewrite_model=rewrite_model,
        synthesis_model=values["synthesis_model"],
        embedding_model=values["embedding_model"],
        top_k=values["top_k"],
        min_score=values["min_score"],
        processed_dir=values["processed_dir"],
        authority_registry=values.get("authority_registry"),
        synthesis_backend=values.get("synthesis_backend", "local"),
        remote_provider=values.get("remote_provider", "anthropic"),
        # `or` (not .get(key, default)) on remote_model/api_key_env -- an explicit
        # `null` in config.json must not survive as None/empty. Neither key has a
        # REQBOT_* env mapping, so a hand-edited config file is the only way either
        # gets set; a None/empty remote_model reaching evidence_service.build() or
        # a None api_key_env reaching os.environ.get() in api/routes/evidence.py,
        # mcp_server/server.py, or cli/reqbot.py would misbehave otherwise
        # (Phase 27, WP-27.2; remote_model consistency fix per Gemini review, PR #120).
        remote_model=values.get("remote_model") or "claude-sonnet-4-6",
        api_key_env=values.get("api_key_env") or "ANTHROPIC_API_KEY",
    )

    # Load authority registry (optional — graceful if missing)
    registry_path = cfg.authority_registry or str(AUTHORITY_REGISTRY_PATH)
    cfg.authority = _load_authority_registry(registry_path)

    return cfg
