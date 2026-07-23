from unittest.mock import MagicMock, patch

import pytest
import requests

from core import synthesis


class _FakeTagsResp:
    def __init__(self, models):
        self._models = models

    def raise_for_status(self):
        pass

    def json(self):
        return {"models": [{"name": m} for m in self._models]}


@patch("core.synthesis.synthesize_local")
@patch("core.synthesis.synthesize_remote")
def test_backend_none_returns_empty_without_calling_local_or_remote(mock_remote, mock_local):
    result = synthesis.synthesize(
        question="What are the password requirements?",
        evidence="[1] ...",
        backend="none",
    )
    assert result == ""
    mock_local.assert_not_called()
    mock_remote.assert_not_called()


@patch("core.synthesis.synthesize_local")
@patch("core.synthesis.synthesize_remote")
def test_backend_local_calls_synthesize_local(mock_remote, mock_local):
    mock_local.return_value = "local answer"
    result = synthesis.synthesize(
        question="q",
        evidence="e",
        backend="local",
        model="llama3.1:8b-instruct-q4_K_M",
        ollama_url="http://localhost:11434",
    )
    assert result == "local answer"
    mock_local.assert_called_once()
    mock_remote.assert_not_called()


@patch("core.synthesis.synthesize_local")
@patch("core.synthesis.synthesize_remote")
def test_backend_remote_calls_synthesize_remote(mock_remote, mock_local):
    mock_remote.return_value = "remote answer"
    result = synthesis.synthesize(
        question="q",
        evidence="e",
        backend="remote",
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key="sk-test",
    )
    assert result == "remote answer"
    mock_remote.assert_called_once()
    mock_local.assert_not_called()


@patch("core.synthesis.synthesize_local")
@patch("core.synthesis.synthesize_remote")
def test_backend_defaults_to_local_for_unrecognized_value(mock_remote, mock_local):
    """Anything that isn't 'remote' or 'none' is treated as local — matches the
    existing if/else fallthrough used throughout the codebase."""
    mock_local.return_value = "local answer"
    result = synthesis.synthesize(question="q", evidence="e", backend="something-unexpected")
    assert result == "local answer"
    mock_local.assert_called_once()
    mock_remote.assert_not_called()


# ---------------------------------------------------------------------------
# synthesize_local(): WP-25.1c — fail clearly instead of auto-pulling
# ---------------------------------------------------------------------------

@patch("subprocess.run")
@patch("ollama.Client")
@patch("requests.get")
def test_synthesize_local_raises_clear_error_when_model_missing(mock_get, mock_client_cls, mock_run):
    mock_get.return_value = _FakeTagsResp(["nomic-embed-text"])

    with pytest.raises(RuntimeError, match="qwen2.5:14b"):
        synthesis.synthesize_local(
            question="q", evidence="e", model="qwen2.5:14b",
            ollama_url="http://localhost:11434",
        )

    mock_client_cls.assert_not_called()  # never reaches generate()
    mock_run.assert_not_called()  # never shells out to `ollama pull` on the user's behalf


@patch("ollama.Client")
@patch("requests.get")
def test_synthesize_local_proceeds_when_model_present(mock_get, mock_client_cls):
    mock_get.return_value = _FakeTagsResp(["qwen2.5:14b"])
    mock_client = MagicMock()
    mock_client.generate.return_value = MagicMock(response="the answer")
    mock_client_cls.return_value = mock_client

    result = synthesis.synthesize_local(
        question="q", evidence="e", model="qwen2.5:14b",
        ollama_url="http://localhost:11434",
    )
    assert result == "the answer"


@patch("ollama.Client")
@patch("requests.get", side_effect=requests.RequestException("connection refused"))
def test_synthesize_local_fails_open_when_presence_check_itself_errors(mock_get, mock_client_cls):
    """A network error during the presence-check shouldn't block synthesis —
    let generate() surface whatever the real problem is, same as before."""
    mock_client = MagicMock()
    mock_client.generate.return_value = MagicMock(response="the answer")
    mock_client_cls.return_value = mock_client

    result = synthesis.synthesize_local(
        question="q", evidence="e", model="qwen2.5:14b",
        ollama_url="http://localhost:11434",
    )
    assert result == "the answer"
