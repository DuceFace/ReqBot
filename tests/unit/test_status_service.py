"""Unit tests for services/status_service.py's configured_models field (WP-25.6b).

configured_models reports which model ReqBot is actually configured to use per
role, distinct from ollama.models (what's merely installed on the server).
"""
import sys
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services import status_service


class _FakeResp:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._json


def _fake_get(url, timeout=5):
    if "/api/tags" in url:
        return _FakeResp({"models": []})
    if "/collections" in url:
        return _FakeResp({"result": {"collections": []}})
    raise requests.RequestException(f"unexpected url in test: {url}")


def test_configured_models_passthrough(tmp_path):
    configured = {
        "extraction": "extract-model",
        "enrichment": "enrich-model",
        "rewrite": "rewrite-model",
        "synthesis": "synth-model",
    }
    with patch("requests.get", side_effect=_fake_get):
        result = status_service.check(
            "http://ollama:11434", "http://qdrant:6333", tmp_path, configured
        )
    assert result["configured_models"] == configured


def test_configured_models_defaults_to_empty_dict_when_omitted(tmp_path):
    with patch("requests.get", side_effect=_fake_get):
        result = status_service.check("http://ollama:11434", "http://qdrant:6333", tmp_path)
    assert result["configured_models"] == {}
