"""Unit tests for the reqbot first-run setup flow (WP-25.1b: config-only).

cmd_init() only configures Qdrant/Ollama service URLs and model/synthesis
preferences — it does not install, start, or manage either service (no Docker
bootstrap, no Ollama installer, no `ollama pull`). cmd_setup() is a deprecated
alias that delegates to cmd_init().

Tests call cmd_init()/cmd_setup() directly with mocked input() and
requests.get() — no real Qdrant/Ollama/network access, no filesystem writes
outside tmp_path.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import cli.reqbot as reqbot_cli
import core.config as core_config
from cli.reqbot import cmd_init, cmd_setup


def _mock_cfg(tmp_path):
    processed_dir = tmp_path / "processed"
    return SimpleNamespace(
        ollama_url="http://existing-ollama:11434",
        qdrant_url="http://existing-qdrant:6333",
        default_model="llama3.1:8b-instruct-q4_K_M",
        extraction_model="llama3.1:8b-instruct-q4_K_M",
        enrichment_model="llama3.1:8b-instruct-q4_K_M",
        rewrite_model="llama3.1:8b-instruct-q4_K_M",
        synthesis_model="qwen2.5:14b",
        top_k=20,
        min_score=0.02,
        processed_dir=str(processed_dir),
        processed_dir_path=lambda: processed_dir,
        remote_provider="anthropic",
        remote_model="claude-sonnet-4-6",
        api_key_env="ANTHROPIC_API_KEY",
    )


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
        return _FakeResp({"models": [{"name": "nomic-embed-text"}, {"name": "llama3.1:8b-instruct-q4_K_M"}]})
    if "/collections" in url:
        return _FakeResp({"result": {"collections": []}})
    raise requests.RequestException(f"unexpected url in test: {url}")


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    monkeypatch.setattr(core_config, "CONFIG_PATH", tmp_path / "config.json")


def _run_init(tmp_path, inputs):
    mock_cfg = _mock_cfg(tmp_path)
    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("builtins.input", side_effect=inputs), \
         patch("requests.get", side_effect=_fake_get), \
         patch("services.status_service.check", return_value={
             "ollama": {"reachable": True, "models": []},
             "qdrant": {"reachable": True, "collections": []},
             "processed_documents": [],
             "configured_models": {
                 "extraction": "x", "enrichment": "x", "rewrite": "x", "synthesis": "x",
             },
         }):
        rc = cmd_init(SimpleNamespace())
    written = json.loads((tmp_path / "config.json").read_text())
    return rc, written


# ---------------------------------------------------------------------------
# Config-only: no bootstrap capability at all
# ---------------------------------------------------------------------------

def test_no_bootstrap_functions_remain():
    """The Docker/Ollama-installer bootstrap helpers were removed, not just unused."""
    assert not hasattr(reqbot_cli, "_bootstrap_qdrant_local")
    assert not hasattr(reqbot_cli, "_bootstrap_ollama_local")


def test_subprocess_not_imported():
    """cmd_init has no reason to shell out — subprocess should not be imported."""
    assert not hasattr(reqbot_cli, "subprocess")


def test_init_prompts_directly_for_urls_no_choice_menu(tmp_path):
    """Qdrant/Ollama are configured by URL only — no existing-vs-bootstrap menu."""
    inputs = [
        "http://my-qdrant:6333", "http://my-ollama:11434",
        "", "", "", "", "",  # 5 models
        "", "", "",  # top_k, min_score, processed_dir
        "3",  # synthesis = none
    ]
    rc, written = _run_init(tmp_path, inputs)
    assert rc == 0
    assert written["qdrant_url"] == "http://my-qdrant:6333"
    assert written["ollama_url"] == "http://my-ollama:11434"


def test_init_writes_rewrite_model(tmp_path):
    """rewrite_model is a real prompt + config field now (WP-25.6b), not CLI-flag-only."""
    inputs = [
        "", "",  # qdrant/ollama URLs
        "", "", "", "custom-rewrite-model", "",  # default/extraction/enrichment/rewrite/synthesis
        "", "", "",  # top_k, min_score, processed_dir
        "3",  # synthesis = none
    ]
    rc, written = _run_init(tmp_path, inputs)
    assert rc == 0
    assert written["rewrite_model"] == "custom-rewrite-model"


def test_init_retries_url_on_failed_connection(tmp_path):
    """A failed connectivity test re-prompts unless the user chooses to keep it."""
    call_count = {"n": 0}

    def _flaky_get(url, timeout=5):
        if "/collections" in url:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise requests.RequestException("connection refused")
            return _FakeResp({"result": {"collections": []}})
        return _fake_get(url, timeout)

    inputs = [
        "http://bad-qdrant:6333",  # fails
        "n",  # don't keep it
        "http://good-qdrant:6333",  # succeeds
        "",  # ollama URL default
        "", "", "", "", "",  # 5 models
        "", "", "",  # top_k, min_score, processed_dir
        "3",  # synthesis = none
    ]
    mock_cfg = _mock_cfg(tmp_path)
    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("builtins.input", side_effect=inputs), \
         patch("requests.get", side_effect=_flaky_get), \
         patch("services.status_service.check", return_value={
             "ollama": {"reachable": True, "models": []},
             "qdrant": {"reachable": True, "collections": []},
             "processed_documents": [],
             "configured_models": {
                 "extraction": "x", "enrichment": "x", "rewrite": "x", "synthesis": "x",
             },
         }):
        rc = cmd_init(SimpleNamespace())
    written = json.loads((tmp_path / "config.json").read_text())
    assert rc == 0
    assert written["qdrant_url"] == "http://good-qdrant:6333"


# ---------------------------------------------------------------------------
# Synthesis: explicit 3-way choice
# ---------------------------------------------------------------------------

def test_synthesis_none_skips_remote_prompts_and_writes_backend_none(tmp_path):
    inputs = ["", "", "", "", "", "", "", "", "", "", "3"]
    rc, written = _run_init(tmp_path, inputs)
    assert rc == 0
    assert written["synthesis_backend"] == "none"
    # No remote prompts were consumed — default provider/model/env unchanged.
    assert written["remote_provider"] == "anthropic"
    assert written["remote_model"] == "claude-sonnet-4-6"
    assert written["api_key_env"] == "ANTHROPIC_API_KEY"


def test_synthesis_remote_prompts_for_provider_model_and_api_key_env(tmp_path):
    inputs = [
        "", "", "", "", "", "", "", "", "", "", "2",
        "openai", "gpt-4o", "OPENAI_API_KEY",
    ]
    rc, written = _run_init(tmp_path, inputs)
    assert rc == 0
    assert written["synthesis_backend"] == "remote"
    assert written["remote_provider"] == "openai"
    assert written["remote_model"] == "gpt-4o"
    assert written["api_key_env"] == "OPENAI_API_KEY"


def test_synthesis_local_needs_no_extra_prompts(tmp_path):
    inputs = ["", "", "", "", "", "", "", "", "", "", "1"]
    rc, written = _run_init(tmp_path, inputs)
    assert rc == 0
    assert written["synthesis_backend"] == "local"


# ---------------------------------------------------------------------------
# 'reqbot setup' deprecated alias
# ---------------------------------------------------------------------------

def test_setup_prints_deprecation_notice_and_delegates_to_init(capsys):
    fake_args = SimpleNamespace(advanced=False)
    with patch("cli.reqbot.cmd_init", return_value=0) as mock_init:
        rc = cmd_setup(fake_args)
    assert rc == 0
    mock_init.assert_called_once_with(fake_args)
    assert "deprecated" in capsys.readouterr().out.lower()


def test_setup_advanced_flag_is_a_no_op():
    """--advanced must not change behavior now that setup == init."""
    fake_args = SimpleNamespace(advanced=True)
    with patch("cli.reqbot.cmd_init", return_value=0) as mock_init:
        cmd_setup(fake_args)
    mock_init.assert_called_once_with(fake_args)


def test_setup_prints_notice_on_every_call_not_just_first(capsys):
    """No persistent one-time-warning state — the notice prints every invocation."""
    fake_args = SimpleNamespace(advanced=False)
    with patch("cli.reqbot.cmd_init", return_value=0):
        cmd_setup(fake_args)
        cmd_setup(fake_args)
    out = capsys.readouterr().out
    assert out.lower().count("deprecated") == 2
