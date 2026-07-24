from pathlib import Path
from unittest.mock import patch

import pytest

from services.ask_service import ask

SAMPLE_RESULT = {
    "score": 0.9,
    "requirement_id": "REQ-abc123def456",
    "source_quote": "Systems must enforce access control.",
    "source_ref": "1.1",
}


def _make_retrieve_result(results=None, synthesis_text="", retrieval_ms=10.0):
    results = results or []
    return {
        "results": results,
        "total": len(results),
        "synthesis_text": synthesis_text,
        "expanded_query": "",
        "retrieval_ms": retrieval_ms,
    }


@patch("core.ask.retrieve")
def test_returns_canonical_shape(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result()
    resp = ask("test question", "http://qdrant:6333", "http://ollama:11434")
    assert set(resp.keys()) == {"query", "filters", "results", "metadata", "warnings"}


@patch("core.ask.retrieve")
def test_metadata_keys_complete(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result()
    resp = ask("test", "http://qdrant:6333", "http://ollama:11434")
    assert {"top_k", "result_count", "retrieval_ms", "synthesis"} <= set(resp["metadata"].keys())


@patch("core.ask.retrieve")
def test_result_count_matches_results_length(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result(results=[SAMPLE_RESULT] * 3)
    resp = ask("test", "http://qdrant:6333", "http://ollama:11434")
    assert resp["metadata"]["result_count"] == 3
    assert len(resp["results"]) == 3


@patch("core.ask.retrieve")
def test_filters_populated_when_document_ids_passed(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result()
    resp = ask("test", "http://qdrant:6333", "http://ollama:11434", document_ids=["doc-1"])
    assert resp["filters"]["document_id"] == ["doc-1"]
    mock_retrieve.assert_called_once()
    _, kwargs = mock_retrieve.call_args
    assert kwargs["document_ids"] == ["doc-1"]


@patch("core.ask.retrieve")
def test_filters_none_when_not_passed(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result()
    resp = ask("test", "http://qdrant:6333", "http://ollama:11434")
    assert resp["filters"]["document_id"] is None
    assert resp["filters"]["domain_tag"] is None
    assert resp["filters"]["requirement_type"] is None


@patch("core.ask.retrieve")
def test_top_k_passed_to_retrieve(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result()
    ask("test", "http://qdrant:6333", "http://ollama:11434", top_k=5)
    _, kwargs = mock_retrieve.call_args
    assert kwargs["top_k"] == 5


@patch("core.ask.retrieve")
def test_synthesis_none_when_synthesis_text_empty(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result(synthesis_text="")
    resp = ask("test", "http://qdrant:6333", "http://ollama:11434")
    assert resp["metadata"]["synthesis"] is None


@patch("core.ask.retrieve")
def test_synthesis_passes_through_when_present(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result(synthesis_text="Generated answer here.")
    resp = ask("test", "http://qdrant:6333", "http://ollama:11434", synthesize=True)
    assert resp["metadata"]["synthesis"] == "Generated answer here."


@patch("core.ask.retrieve")
def test_empty_results_is_valid_response(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result(results=[])
    resp = ask("no match query", "http://qdrant:6333", "http://ollama:11434")
    assert resp["results"] == []
    assert resp["metadata"]["result_count"] == 0


@patch("core.ask.retrieve")
def test_result_order_preserved(mock_retrieve):
    ordered = [dict(SAMPLE_RESULT, score=s) for s in (0.9, 0.7, 0.5)]
    mock_retrieve.return_value = _make_retrieve_result(results=ordered)
    resp = ask("test", "http://qdrant:6333", "http://ollama:11434")
    assert [r["score"] for r in resp["results"]] == [0.9, 0.7, 0.5]


@patch("core.ask.retrieve")
def test_runtime_error_propagates(mock_retrieve):
    mock_retrieve.side_effect = RuntimeError("Qdrant unavailable")
    with pytest.raises(RuntimeError):
        ask("test", "http://qdrant:6333", "http://ollama:11434")


@patch("core.ask.retrieve")
def test_value_error_propagates(mock_retrieve):
    """Phase 27, WP-27.1: an unknown document_ids value raises ValueError from
    retrieve() -- ask_service must not swallow or reshape it."""
    mock_retrieve.side_effect = ValueError("Unknown document_ids: bad-doc")
    with pytest.raises(ValueError, match="bad-doc"):
        ask("test", "http://qdrant:6333", "http://ollama:11434", document_ids=["bad-doc"])


@patch("core.ask.retrieve")
def test_processed_dir_passed_to_retrieve(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result()
    ask(
        "test", "http://qdrant:6333", "http://ollama:11434",
        document_ids=["afi17-101"], processed_dir=Path("/fake/processed"),
    )
    _, kwargs = mock_retrieve.call_args
    assert kwargs["processed_dir"] == Path("/fake/processed")


@patch("core.ask.retrieve")
def test_hyde_defaults_to_true(mock_retrieve):
    """WP-24.5: HyDE is default-on retrieval augmentation, not opt-in."""
    mock_retrieve.return_value = _make_retrieve_result()
    ask("test", "http://qdrant:6333", "http://ollama:11434")
    _, kwargs = mock_retrieve.call_args
    assert kwargs["hyde"] is True


@patch("core.ask.retrieve")
def test_hyde_false_is_forwarded(mock_retrieve):
    mock_retrieve.return_value = _make_retrieve_result()
    ask("test", "http://qdrant:6333", "http://ollama:11434", hyde=False)
    _, kwargs = mock_retrieve.call_args
    assert kwargs["hyde"] is False
