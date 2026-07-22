"""Regression tests for core/ask.py's run() warning routing (Codex PR #90 follow-up).

`run()` prints a couple of "falling back"/"disabled" notices when synthesis
config isn't fully usable. With --json, stdout must stay valid JSON — these
notices must go to stderr, not stdout.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from core import ask as core_ask

SAMPLE_RESULT = {
    "score": 0.9,
    "requirement_id": "REQ-abc123",
    "source_quote": "Systems must enforce access control.",
    "source_ref": "1.1",
}


def _fake_retrieve_result():
    return {
        "results": [SAMPLE_RESULT],
        "total": 1,
        "synthesis_text": "",
        "expanded_query": "",
        "retrieval_ms": 5.0,
    }


def test_disabled_synthesis_warning_goes_to_stderr_with_json_output(capsys):
    fake_cfg = SimpleNamespace(
        synthesis_backend="none",
        remote_provider="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
    )
    with patch("core.config.load", return_value=fake_cfg), \
         patch("core.ask.retrieve", return_value=_fake_retrieve_result()):
        core_ask.run("test question", synthesize=True, json_output=True)

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)  # stdout must be valid JSON, nothing else mixed in
    assert parsed == [SAMPLE_RESULT]
    assert "disabled" in captured.err.lower()
    assert "disabled" not in captured.out.lower()


def test_remote_missing_api_key_warning_goes_to_stderr_with_json_output(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake_cfg = SimpleNamespace(
        synthesis_backend="remote",
        remote_provider="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
    )
    with patch("core.config.load", return_value=fake_cfg), \
         patch("core.ask.retrieve", return_value=_fake_retrieve_result()):
        core_ask.run("test question", synthesize=True, json_output=True)

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed == [SAMPLE_RESULT]
    assert "falling back to local" in captured.err.lower()
    assert "falling back to local" not in captured.out.lower()
