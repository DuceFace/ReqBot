"""Unit test for WP-42 (Codex review, PR #189): call_ollama pins an explicit
num_ctx instead of relying on whatever the Ollama server happens to default
to -- matters more now that chunk_text.py can put a whole table's markdown
into a single chunk."""
from unittest.mock import MagicMock, patch

from pipeline.llm_extract_requirements import OLLAMA_NUM_CTX, call_ollama


def test_call_ollama_sends_pinned_num_ctx():
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "{}"}
    mock_response.raise_for_status.return_value = None

    with patch("pipeline.llm_extract_requirements.requests.post", return_value=mock_response) as mock_post:
        call_ollama("some prompt", "llama3.1:8b-instruct-q4_K_M", "http://localhost:11434")

    sent_payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
    assert sent_payload["options"]["num_ctx"] == OLLAMA_NUM_CTX
