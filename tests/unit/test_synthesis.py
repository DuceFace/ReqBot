from unittest.mock import patch

from core import synthesis


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
