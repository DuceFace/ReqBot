"""Unit tests for WP-23.5: recovered_truncated flag on Step C truncation recovery."""
import json
from unittest.mock import patch

from pipeline.llm_extract_requirements import extract_json_array, process_chunk

# ---------------------------------------------------------------------------
# extract_json_array — return type is (list | None, bool)
# ---------------------------------------------------------------------------

_VALID_ITEM = {"source_quote": "Systems shall encrypt data at rest.", "source_ref": "3.1"}


def _make_valid_item(**overrides):
    item = dict(_VALID_ITEM)
    item.update(overrides)
    return item


def test_strategy1_clean_parse_returns_false():
    raw = json.dumps([_VALID_ITEM])
    result, recovered = extract_json_array(raw)
    assert isinstance(result, list)
    assert recovered is False


def test_strategy1_wrapped_requirements_returns_false():
    raw = json.dumps({"requirements": [_VALID_ITEM]})
    result, recovered = extract_json_array(raw)
    assert isinstance(result, list)
    assert recovered is False


def test_strategy1_markdown_fences_returns_false():
    raw = "```json\n" + json.dumps([_VALID_ITEM]) + "\n```"
    result, recovered = extract_json_array(raw)
    assert isinstance(result, list)
    assert recovered is False


def test_strategy2_prefix_text_returns_false():
    raw = "Here is the result:\n" + json.dumps([_VALID_ITEM])
    result, recovered = extract_json_array(raw)
    assert isinstance(result, list)
    assert recovered is False


def test_strategy3_truncated_array_returns_true():
    item1 = json.dumps(_VALID_ITEM)
    item2_start = '{"source_quote": "incomplete'
    raw = f"[{item1}, {item2_start}"
    result, recovered = extract_json_array(raw)
    assert result is not None
    assert len(result) == 1
    assert recovered is True


def test_strategy3_multiple_complete_objects_recovered():
    item = json.dumps(_VALID_ITEM)
    raw = f"[{item}, {item}, {item[:-1]}"  # third object truncated mid-close
    result, recovered = extract_json_array(raw)
    assert result is not None
    assert len(result) == 2
    assert recovered is True


def test_complete_parse_failure_returns_none_false():
    raw = "This is not JSON at all."
    result, recovered = extract_json_array(raw)
    assert result is None
    assert recovered is False


def test_empty_array_returns_false():
    result, recovered = extract_json_array("[]")
    assert result == []
    assert recovered is False


# ---------------------------------------------------------------------------
# process_chunk — recovered_truncated flag on output requirements
# ---------------------------------------------------------------------------

def _make_chunk(chunk_id: int = 1, text: str = "Some regulatory text.") -> dict:
    return {"chunk_id": chunk_id, "text": text}


def _fake_ollama_response(payload: list) -> str:
    return json.dumps(payload)


def _run_process_chunk(raw_response: str):
    chunk = _make_chunk()
    with patch("pipeline.llm_extract_requirements.call_ollama", return_value=raw_response):
        return process_chunk(chunk, model="test", base_url="http://localhost:11434", timeout=30)


def test_process_chunk_normal_parse_no_flag():
    raw = json.dumps([_make_valid_item()])
    _, reqs, failure = _run_process_chunk(raw)
    assert failure is None
    assert len(reqs) == 1
    assert "recovered_truncated" not in reqs[0]


def test_process_chunk_truncated_recovery_sets_flag():
    item = _make_valid_item()
    truncated_raw = "[" + json.dumps(item) + ", {\"source_quote\": \"incomplete"
    _, reqs, failure = _run_process_chunk(truncated_raw)
    assert failure is None
    assert len(reqs) == 1
    assert reqs[0].get("recovered_truncated") is True


def test_process_chunk_truncated_all_reqs_flagged():
    item1 = _make_valid_item(source_ref="3.1")
    item2 = _make_valid_item(source_ref="3.2")
    item3_start = '{"source_quote": "cut off'
    raw = "[" + json.dumps(item1) + ", " + json.dumps(item2) + ", " + item3_start
    _, reqs, failure = _run_process_chunk(raw)
    assert len(reqs) == 2
    assert all(r.get("recovered_truncated") is True for r in reqs)


def test_process_chunk_parse_failure_no_flag():
    _, reqs, failure = _run_process_chunk("not json at all")
    assert failure is not None
    assert reqs == []


def test_process_chunk_empty_array_no_flag():
    _, reqs, failure = _run_process_chunk("[]")
    assert failure is None
    assert reqs == []
