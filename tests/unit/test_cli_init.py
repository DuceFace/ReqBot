"""Unit tests for the merged reqbot first-run setup flow (WP-24.1).

cmd_init() is the single guided flow (Qdrant existing-vs-bootstrap, Ollama
existing-vs-bootstrap, then models/top_k/min_score/processed_dir/synthesis).
cmd_setup() is a deprecated alias that delegates to cmd_init().

Tests call cmd_init()/cmd_setup() directly with mocked input(), requests.get(),
and subprocess.run() — no real Docker/Ollama/network access, no filesystem
writes outside tmp_path.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_subprocess_run(cmd, **kwargs):
    if cmd[:2] == ["docker", "info"]:
        return _FakeCompleted(0)
    if cmd[:2] == ["docker", "--version"]:
        return _FakeCompleted(0, stdout="Docker version 24.0.0")
    if cmd[:3] == ["docker", "ps", "--filter"]:
        return _FakeCompleted(0, stdout="")  # not currently running
    if cmd[:3] == ["docker", "ps", "-a"]:
        return _FakeCompleted(0, stdout="")  # container doesn't exist yet
    if cmd[:2] == ["docker", "run"]:
        return _FakeCompleted(0)
    if cmd == ["ollama", "--version"]:
        return _FakeCompleted(0, stdout="ollama version 0.1.0")
    if cmd == ["ollama", "list"]:
        return _FakeCompleted(0, stdout="nomic-embed-text\nllama3.1:8b-instruct-q4_K_M\n")
    if cmd[:2] == ["ollama", "pull"]:
        return _FakeCompleted(0)
    raise AssertionError(f"unexpected subprocess call in test: {cmd}")


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    monkeypatch.setattr(core_config, "CONFIG_PATH", tmp_path / "config.json")


def _run_init(tmp_path, inputs):
    mock_cfg = _mock_cfg(tmp_path)
    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("builtins.input", side_effect=inputs), \
         patch("requests.get", side_effect=_fake_get), \
         patch("subprocess.run", side_effect=_fake_subprocess_run), \
         patch("services.status_service.check", return_value={
             "ollama": {"reachable": True, "models": []},
             "qdrant": {"reachable": True, "collections": []},
             "processed_documents": [],
         }):
        rc = cmd_init(SimpleNamespace())
    written = json.loads((tmp_path / "config.json").read_text())
    return rc, written


# ---------------------------------------------------------------------------
# Existing vs. bootstrap combinations (Qdrant x Ollama)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "qdrant_choice,ollama_choice,expected_qdrant_url,expected_ollama_url",
    [
        ("1", "1", "http://existing-qdrant:6333", "http://existing-ollama:11434"),
        ("2", "2", "http://localhost:6333", "http://localhost:11434"),
        ("1", "2", "http://existing-qdrant:6333", "http://localhost:11434"),
        ("2", "1", "http://localhost:6333", "http://existing-ollama:11434"),
    ],
)
def test_existing_vs_bootstrap_combinations(
    tmp_path, qdrant_choice, ollama_choice, expected_qdrant_url, expected_ollama_url
):
    inputs = [qdrant_choice]
    if qdrant_choice == "1":
        inputs.append("")  # accept default Qdrant URL
    inputs.append(ollama_choice)
    if ollama_choice == "1":
        inputs.append("")  # accept default Ollama URL
    inputs += ["", "", "", "", "", "", "", "1"]  # 4 models, top_k, min_score, processed_dir, synthesis=local

    rc, written = _run_init(tmp_path, inputs)

    assert rc == 0
    assert written["qdrant_url"] == expected_qdrant_url
    assert written["ollama_url"] == expected_ollama_url
    assert written["synthesis_backend"] == "local"


# ---------------------------------------------------------------------------
# Synthesis: explicit 3-way choice
# ---------------------------------------------------------------------------

def test_synthesis_none_skips_remote_prompts_and_writes_backend_none(tmp_path):
    inputs = ["1", "", "1", "", "", "", "", "", "", "", "", "3"]
    rc, written = _run_init(tmp_path, inputs)
    assert rc == 0
    assert written["synthesis_backend"] == "none"
    # No remote prompts were consumed — default provider/model/env unchanged.
    assert written["remote_provider"] == "anthropic"
    assert written["remote_model"] == "claude-sonnet-4-6"
    assert written["api_key_env"] == "ANTHROPIC_API_KEY"


def test_synthesis_remote_prompts_for_provider_model_and_api_key_env(tmp_path):
    inputs = [
        "1", "", "1", "", "", "", "", "", "", "", "", "2",
        "openai", "gpt-4o", "OPENAI_API_KEY",
    ]
    rc, written = _run_init(tmp_path, inputs)
    assert rc == 0
    assert written["synthesis_backend"] == "remote"
    assert written["remote_provider"] == "openai"
    assert written["remote_model"] == "gpt-4o"
    assert written["api_key_env"] == "OPENAI_API_KEY"


def test_synthesis_local_needs_no_extra_prompts(tmp_path):
    inputs = ["1", "", "1", "", "", "", "", "", "", "", "", "1"]
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
