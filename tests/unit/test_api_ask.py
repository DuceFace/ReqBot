"""Unit tests for api/routes/ask.py's model/rewrite_model resolution (WP-25.6b).

Confirms the API route resolves an omitted model/rewrite_model from config rather
than passing an empty string straight through to ask_service.ask() (which used to
fall back to a hardcoded literal, ignoring whatever the user actually configured).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.app import app

client = TestClient(app)

_ASK_PATH = "api.routes.ask.ask_service.ask"

MOCK_RESULT = {
    "query": "access control",
    "filters": {"document_id": None, "domain_tag": None, "requirement_type": None},
    "results": [],
    "metadata": {"top_k": 20, "result_count": 0, "retrieval_ms": 1.0, "synthesis": None},
}


def _mock_cfg(**overrides):
    cfg = MagicMock()
    cfg.qdrant_url = "http://qdrant:6333"
    cfg.ollama_url = "http://ollama:11434"
    cfg.synthesis_backend = "local"
    cfg.remote_provider = "anthropic"
    cfg.api_key_env = "ANTHROPIC_API_KEY"
    cfg.synthesis_model = "configured-synth-model"
    cfg.rewrite_model = "configured-rewrite-model"
    cfg.processed_dir_path.return_value = "/fake/processed"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_omitted_model_and_rewrite_model_fall_back_to_config():
    with patch("api.routes.ask._config.load", return_value=_mock_cfg()), \
         patch(_ASK_PATH, return_value=MOCK_RESULT) as mock_ask:
        resp = client.post("/api/ask", json={"question": "access control"})
    assert resp.status_code == 200
    _, kwargs = mock_ask.call_args
    assert kwargs["model"] == "configured-synth-model"
    assert kwargs["rewrite_model"] == "configured-rewrite-model"


def test_explicit_model_and_rewrite_model_override_config():
    with patch("api.routes.ask._config.load", return_value=_mock_cfg()), \
         patch(_ASK_PATH, return_value=MOCK_RESULT) as mock_ask:
        resp = client.post(
            "/api/ask",
            json={
                "question": "access control",
                "model": "explicit-model",
                "rewrite_model": "explicit-rewrite-model",
            },
        )
    assert resp.status_code == 200
    _, kwargs = mock_ask.call_args
    assert kwargs["model"] == "explicit-model"
    assert kwargs["rewrite_model"] == "explicit-rewrite-model"


def test_processed_dir_passed_to_ask_service():
    with patch("api.routes.ask._config.load", return_value=_mock_cfg()), \
         patch(_ASK_PATH, return_value=MOCK_RESULT) as mock_ask:
        client.post("/api/ask", json={"question": "access control"})
    _, kwargs = mock_ask.call_args
    assert kwargs["processed_dir"] == "/fake/processed"


def test_unknown_document_ids_returns_404():
    """Phase 27, WP-27.1: an unknown document_ids value is a 4xx client error,
    not a 503 backend failure -- distinguish it from RuntimeError's 503 mapping."""
    with patch("api.routes.ask._config.load", return_value=_mock_cfg()), \
         patch(_ASK_PATH, side_effect=ValueError("Unknown document_ids: bad-doc")):
        resp = client.post(
            "/api/ask", json={"question": "access control", "document_ids": ["bad-doc"]},
        )
    assert resp.status_code == 404
    assert "bad-doc" in resp.json()["detail"]
