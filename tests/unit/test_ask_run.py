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


def _fake_retrieve_result(warnings=None):
    return {
        "results": [SAMPLE_RESULT],
        "total": 1,
        "synthesis_text": "",
        "expanded_query": "",
        "retrieval_ms": 5.0,
        "warnings": warnings or [],
    }


def test_embedding_mismatch_warning_printed_in_text_mode(capsys):
    """WP-25.6c: run() surfaces retrieve()'s warnings (e.g. embedding-model
    mismatch) in its normal text-output mode."""
    warning_text = "3 of 10 results were indexed with a different embedding model"
    with patch("core.ask.retrieve", return_value=_fake_retrieve_result(warnings=[warning_text])):
        core_ask.run("test question")

    captured = capsys.readouterr()
    assert warning_text in captured.out


def test_no_warnings_key_prints_nothing_extra(capsys):
    """A retrieve() result with no warnings must not print a stray '[!]' line."""
    with patch("core.ask.retrieve", return_value=_fake_retrieve_result()):
        core_ask.run("test question")

    captured = capsys.readouterr()
    assert "[!]" not in captured.out


def test_disabled_synthesis_warning_goes_to_stderr_with_json_output(capsys):
    fake_cfg = SimpleNamespace(
        synthesis_backend="none",
        remote_provider="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        synthesis_model="local-model",
        remote_model="remote-model",
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
        synthesis_model="local-model",
        remote_model="remote-model",
    )
    with patch("core.config.load", return_value=fake_cfg), \
         patch("core.ask.retrieve", return_value=_fake_retrieve_result()):
        core_ask.run("test question", synthesize=True, json_output=True)

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed == [SAMPLE_RESULT]
    assert "falling back to local" in captured.err.lower()
    assert "falling back to local" not in captured.out.lower()
