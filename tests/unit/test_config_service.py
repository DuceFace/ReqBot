"""Unit tests for services/config_service.py (WP-29.3).

Covers: env-override detection in get_config(), and update_config()'s
partial-merge semantics, unknown-field rejection, and restrictive
permissions on write.
"""
import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core import config as _config
from services import config_service


@pytest.fixture(autouse=True)
def _isolated_config_path(tmp_path, monkeypatch):
    """Point core.config.CONFIG_PATH at a scratch file for every test here."""
    monkeypatch.setattr(_config, "CONFIG_PATH", tmp_path / "config.json")
    return tmp_path


def test_get_config_reports_no_overrides_by_default():
    result = config_service.get_config()
    assert result["env_overridden"] == []
    assert result["config"]["ollama_url"] == _config._DEFAULTS["ollama_url"]


def test_get_config_flags_env_overridden_field(monkeypatch):
    monkeypatch.setenv("REQBOT_TOP_K", "42")
    result = config_service.get_config()
    assert "top_k" in result["env_overridden"]
    assert result["config"]["top_k"] == 42


def test_update_config_writes_new_file_from_defaults():
    result = config_service.update_config({"ollama_url": "http://example:11434"})
    assert result["config"]["ollama_url"] == "http://example:11434"
    # Untouched field still carries its default.
    assert result["config"]["qdrant_url"] == _config._DEFAULTS["qdrant_url"]


def test_update_config_only_changes_provided_keys():
    config_service.update_config({
        "ollama_url": "http://first:11434",
        "processed_dir": "/tmp/first",
        "authority_registry": "/tmp/authority.json",
    })
    config_service.update_config({"ollama_url": "http://second:11434"})

    result = config_service.get_config()
    assert result["config"]["ollama_url"] == "http://second:11434"
    # Fields outside the API-editable set (enforced by the route, not this
    # service) survive an unrelated partial update untouched.
    assert result["config"]["processed_dir"] == "/tmp/first"
    assert result["config"]["authority_registry"] == "/tmp/authority.json"


def test_update_config_rejects_unknown_field():
    with pytest.raises(ValueError, match="not_a_real_field"):
        config_service.update_config({"not_a_real_field": "x"})


def test_update_config_sets_restrictive_permissions():
    config_service.update_config({"ollama_url": "http://example:11434"})
    mode = stat.S_IMODE(_config.CONFIG_PATH.stat().st_mode)
    assert mode == 0o600


def test_update_config_persists_across_calls_on_disk():
    config_service.update_config({"top_k": 5})
    on_disk = json.loads(_config.CONFIG_PATH.read_text(encoding="utf-8"))
    assert on_disk["top_k"] == 5
