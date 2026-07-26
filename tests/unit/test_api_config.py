"""Unit tests for api/routes/config.py (WP-29.3).

Covers: GET /config pass-through, POST /config's loopback-only guard, the
API-editable field restriction (processed_dir/authority_registry/authority
must not be settable via this endpoint even though config_service.update_config()
itself would accept them), partial-body behavior, and explicit-null handling
(only extraction_model/enrichment_model/rewrite_model may be cleared to null;
every other field rejects an explicit null rather than writing or dropping it).
"""
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.app import app

_LOOPBACK_CLIENT = TestClient(app, client=("127.0.0.1", 12345))
_REMOTE_CLIENT = TestClient(app, client=("203.0.113.5", 12345))

_GET_CONFIG_PATH = "api.routes.config.config_service.get_config"
_UPDATE_CONFIG_PATH = "api.routes.config.config_service.update_config"

MOCK_CONFIG = {
    "config": {"ollama_url": "http://ollama:11434", "top_k": 20},
    "env_overridden": [],
}


def test_get_config_passthrough():
    with patch(_GET_CONFIG_PATH, return_value=MOCK_CONFIG):
        resp = _LOOPBACK_CLIENT.get("/api/config")
    assert resp.status_code == 200
    assert resp.json() == MOCK_CONFIG


def test_post_config_rejects_non_loopback_request():
    with patch(_UPDATE_CONFIG_PATH) as mock_update:
        resp = _REMOTE_CLIENT.post("/api/config", json={"ollama_url": "http://x:11434"})
    assert resp.status_code == 403
    mock_update.assert_not_called()


def test_post_config_allows_loopback_request():
    with patch(_UPDATE_CONFIG_PATH, return_value=MOCK_CONFIG) as mock_update:
        resp = _LOOPBACK_CLIENT.post("/api/config", json={"ollama_url": "http://x:11434"})
    assert resp.status_code == 200
    mock_update.assert_called_once_with({"ollama_url": "http://x:11434"})


def test_post_config_only_forwards_provided_fields():
    """A partial body must not forward unset fields as explicit nulls."""
    with patch(_UPDATE_CONFIG_PATH, return_value=MOCK_CONFIG) as mock_update:
        resp = _LOOPBACK_CLIENT.post("/api/config", json={"top_k": 30})
    assert resp.status_code == 200
    mock_update.assert_called_once_with({"top_k": 30})


def test_post_config_rejects_non_editable_field():
    """processed_dir isn't in the Pydantic model at all — an unknown field in
    the request body is silently ignored by FastAPI/Pydantic, not forwarded."""
    with patch(_UPDATE_CONFIG_PATH, return_value=MOCK_CONFIG) as mock_update:
        resp = _LOOPBACK_CLIENT.post(
            "/api/config", json={"top_k": 30, "processed_dir": "/etc/passwd"}
        )
    assert resp.status_code == 200
    mock_update.assert_called_once_with({"top_k": 30})


def test_post_config_rejects_out_of_range_top_k():
    with patch(_UPDATE_CONFIG_PATH) as mock_update:
        resp = _LOOPBACK_CLIENT.post("/api/config", json={"top_k": 0})
    assert resp.status_code == 422
    mock_update.assert_not_called()


def test_post_config_rejects_invalid_remote_provider():
    with patch(_UPDATE_CONFIG_PATH) as mock_update:
        resp = _LOOPBACK_CLIENT.post("/api/config", json={"remote_provider": "not-a-provider"})
    assert resp.status_code == 422
    mock_update.assert_not_called()


def test_post_config_maps_value_error_to_400():
    with patch(_UPDATE_CONFIG_PATH, side_effect=ValueError("bad field")):
        resp = _LOOPBACK_CLIENT.post("/api/config", json={"top_k": 30})
    assert resp.status_code == 400
    assert "bad field" in resp.json()["detail"]


def test_post_config_allows_clearing_nullable_role_model_field():
    """extraction_model/enrichment_model/rewrite_model are the R-2.1 fallback
    fields — None is a legitimate stored value meaning "inherit from
    default_model", so explicit null must reach update_config() as None,
    not get dropped as if the field were merely omitted (Gemini review,
    PR #132)."""
    with patch(_UPDATE_CONFIG_PATH, return_value=MOCK_CONFIG) as mock_update:
        resp = _LOOPBACK_CLIENT.post("/api/config", json={"extraction_model": None})
    assert resp.status_code == 200
    mock_update.assert_called_once_with({"extraction_model": None})


def test_post_config_rejects_null_for_non_nullable_field():
    """ollama_url has no null-safe handling in core.config.load() (it's
    indexed straight out of the parsed dict), so an explicit null must be
    rejected rather than written or silently dropped."""
    with patch(_UPDATE_CONFIG_PATH) as mock_update:
        resp = _LOOPBACK_CLIENT.post("/api/config", json={"ollama_url": None})
    assert resp.status_code == 422
    assert "ollama_url" in resp.json()["detail"]
    mock_update.assert_not_called()


def test_post_config_omitted_field_still_excluded_alongside_explicit_null():
    """A field left out of the body entirely must stay excluded even when
    another field in the same request is an explicit, allowed null."""
    with patch(_UPDATE_CONFIG_PATH, return_value=MOCK_CONFIG) as mock_update:
        resp = _LOOPBACK_CLIENT.post(
            "/api/config", json={"extraction_model": None, "top_k": 30}
        )
    assert resp.status_code == 200
    mock_update.assert_called_once_with({"extraction_model": None, "top_k": 30})
