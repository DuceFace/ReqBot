"""Unit tests for api/routes/evidence.py's remote_model pass-through (Phase 27,
WP-27.2) and document_ids pass-through (Phase 27, WP-27.3).

Confirms cfg.remote_model is threaded into evidence_service.build() alongside
synthesis_model -- previously only synthesis_model was passed, so a
remote-configured synthesis backend silently used the wrong model.

Also confirms EvidenceRequest.document_ids reaches build() (previously
hardcoded to None) and that an unresolved document_ids value surfaces as a
404, not a silent empty result.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.app import app

client = TestClient(app)

_BUILD_PATH = "api.routes.evidence.evidence_service.build"

MOCK_RESULT = {
    "query": "access control",
    "timestamp": "2026-07-25T00:00:00Z",
    "group_order": [],
    "groups": {},
    "total_sources": 0,
    "synthesis_text": "",
    "warnings": [],
}


def _mock_cfg(**overrides):
    cfg = MagicMock()
    cfg.qdrant_url = "http://qdrant:6333"
    cfg.ollama_url = "http://ollama:11434"
    cfg.synthesis_backend = "local"
    cfg.remote_provider = "anthropic"
    cfg.api_key_env = "ANTHROPIC_API_KEY"
    cfg.synthesis_model = "configured-synth-model"
    cfg.remote_model = "configured-remote-model"
    cfg.embedding_model = "configured-embedding-model"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_remote_model_passed_through():
    with patch("api.routes.evidence._config.load", return_value=_mock_cfg()), \
         patch(_BUILD_PATH, return_value=MOCK_RESULT) as mock_build:
        resp = client.post("/api/evidence", json={"topic": "access control"})
    assert resp.status_code == 200
    _, kwargs = mock_build.call_args
    assert kwargs["remote_model"] == "configured-remote-model"
    assert kwargs["synthesis_model"] == "configured-synth-model"


def test_document_ids_passed_through():
    """Phase 27, WP-27.3: EvidenceRequest.document_ids threads into build()."""
    with patch("api.routes.evidence._config.load", return_value=_mock_cfg()), \
         patch(_BUILD_PATH, return_value=MOCK_RESULT) as mock_build:
        resp = client.post(
            "/api/evidence",
            json={"topic": "access control", "document_ids": ["afi17-101"]},
        )
    assert resp.status_code == 200
    _, kwargs = mock_build.call_args
    assert kwargs["document_ids"] == ["afi17-101"]


def test_omitted_document_ids_passes_none_no_regression():
    """Omitting document_ids must behave exactly as it did before this WP."""
    with patch("api.routes.evidence._config.load", return_value=_mock_cfg()), \
         patch(_BUILD_PATH, return_value=MOCK_RESULT) as mock_build:
        resp = client.post("/api/evidence", json={"topic": "access control"})
    assert resp.status_code == 200
    _, kwargs = mock_build.call_args
    assert kwargs["document_ids"] is None


def test_unknown_document_ids_returns_404():
    """A ValueError from build() (unresolved document_ids) surfaces as 404,
    same mapping as /ask (Phase 27, WP-27.1)."""
    with patch("api.routes.evidence._config.load", return_value=_mock_cfg()), \
         patch(_BUILD_PATH, side_effect=ValueError("Unknown document_ids: bogus-doc")):
        resp = client.post(
            "/api/evidence",
            json={"topic": "access control", "document_ids": ["bogus-doc"]},
        )
    assert resp.status_code == 404
    assert "bogus-doc" in resp.json()["detail"]
