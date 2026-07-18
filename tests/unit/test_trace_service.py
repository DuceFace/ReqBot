from unittest.mock import MagicMock, patch

import pytest

from services.trace_service import trace

SAMPLE_PAYLOAD = {
    "requirement_id": "REQ-abc123def456",
    "source_quote": "Systems must enforce role-based access control.",
    "source_ref": "1.1",
    "document_id": "doc-abc123",
    "source_pdf": "TEST_DOC.pdf",
    "chunk_id": None,
}


def _make_point(payload: dict) -> MagicMock:
    pt = MagicMock()
    pt.payload = payload
    return pt


@patch("qdrant_client.QdrantClient")
def test_returns_canonical_shape(mock_qdrant_cls):
    mock_client = MagicMock()
    mock_qdrant_cls.return_value = mock_client
    mock_client.scroll.side_effect = [
        ([_make_point(SAMPLE_PAYLOAD)], None),
        ([], None),
    ]
    result = trace("REQ-abc123def456", "http://qdrant:6333")
    assert set(result.keys()) == {"requirement", "cross_matches", "context_text"}
    assert result["context_text"] is None


@patch("qdrant_client.QdrantClient")
def test_value_error_for_unknown_req_id(mock_qdrant_cls):
    mock_client = MagicMock()
    mock_qdrant_cls.return_value = mock_client
    mock_client.scroll.return_value = ([], None)
    with pytest.raises(ValueError, match="not found"):
        trace("REQ-nonexistent", "http://qdrant:6333")


@patch("qdrant_client.QdrantClient")
def test_cross_matches_key_always_present(mock_qdrant_cls):
    mock_client = MagicMock()
    mock_qdrant_cls.return_value = mock_client
    mock_client.scroll.side_effect = [
        ([_make_point(SAMPLE_PAYLOAD)], None),
        ([], None),
    ]
    result = trace("REQ-abc123def456", "http://qdrant:6333")
    assert "cross_matches" in result
    assert isinstance(result["cross_matches"], list)


@patch("qdrant_client.QdrantClient")
def test_cross_matches_empty_when_no_source_ref(mock_qdrant_cls):
    mock_client = MagicMock()
    mock_qdrant_cls.return_value = mock_client
    payload = {**SAMPLE_PAYLOAD, "source_ref": ""}
    mock_client.scroll.return_value = ([_make_point(payload)], None)
    result = trace("REQ-abc123def456", "http://qdrant:6333")
    assert result["cross_matches"] == []
    assert mock_client.scroll.call_count == 1


@patch("qdrant_client.QdrantClient")
def test_cross_matches_populated_from_other_doc(mock_qdrant_cls):
    mock_client = MagicMock()
    mock_qdrant_cls.return_value = mock_client
    other_payload = {
        "requirement_id": "REQ-other999",
        "source_ref": "1.1",
        "document_id": "doc-other",
        "source_quote": "Other document same section.",
    }
    mock_client.scroll.side_effect = [
        ([_make_point(SAMPLE_PAYLOAD)], None),
        ([_make_point(SAMPLE_PAYLOAD), _make_point(other_payload)], None),
    ]
    result = trace("REQ-abc123def456", "http://qdrant:6333")
    assert len(result["cross_matches"]) == 1
    assert result["cross_matches"][0]["document_id"] == "doc-other"


@patch("qdrant_client.QdrantClient")
def test_domain_profile_defaults_to_cybersecurity(mock_qdrant_cls):
    mock_client = MagicMock()
    mock_qdrant_cls.return_value = mock_client
    payload = {k: v for k, v in SAMPLE_PAYLOAD.items()}  # no domain_profile key
    mock_client.scroll.side_effect = [
        ([_make_point(payload)], None),
        ([], None),
    ]
    result = trace("REQ-abc123def456", "http://qdrant:6333")
    assert result["requirement"]["domain_profile"] == "cybersecurity"


@patch("qdrant_client.QdrantClient")
def test_domain_profile_null_falls_back_to_cybersecurity(mock_qdrant_cls):
    mock_client = MagicMock()
    mock_qdrant_cls.return_value = mock_client
    payload = {**SAMPLE_PAYLOAD, "domain_profile": None}
    mock_client.scroll.side_effect = [
        ([_make_point(payload)], None),
        ([], None),
    ]
    result = trace("REQ-abc123def456", "http://qdrant:6333")
    assert result["requirement"]["domain_profile"] == "cybersecurity"


@patch("qdrant_client.QdrantClient")
def test_domain_profile_stored_value_returned(mock_qdrant_cls):
    mock_client = MagicMock()
    mock_qdrant_cls.return_value = mock_client
    payload = {**SAMPLE_PAYLOAD, "domain_profile": "privacy"}
    mock_client.scroll.side_effect = [
        ([_make_point(payload)], None),
        ([], None),
    ]
    result = trace("REQ-abc123def456", "http://qdrant:6333")
    assert result["requirement"]["domain_profile"] == "privacy"


@patch("qdrant_client.QdrantClient")
def test_runtime_error_on_connection_failure(mock_qdrant_cls):
    mock_qdrant_cls.side_effect = Exception("Connection refused")
    with pytest.raises(RuntimeError, match="Could not connect"):
        trace("REQ-abc123def456", "http://qdrant:6333")
