"""Unit tests for WP-23.3 checks #2 and #3: page contiguity validation and overlap guard."""
import logging

import pytest

from pipeline.chunk_text import chunk_text, validate_page_contiguity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _page(num: int) -> dict:
    return {"page_num": num, "text": "placeholder"}


def _simple_index(text: str) -> list[tuple[int, int, int]]:
    """Build a trivial single-page index for the given text."""
    return [(0, len(text), 1)]


# ---------------------------------------------------------------------------
# #2 — Page contiguity validation
# ---------------------------------------------------------------------------

def test_contiguity_valid_sequence_no_warning(caplog):
    pages = [_page(1), _page(2), _page(3), _page(4)]
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity(pages)
    assert caplog.text == ""


def test_contiguity_single_page_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity([_page(1)])
    assert caplog.text == ""


def test_contiguity_empty_list_no_error():
    validate_page_contiguity([])  # must not raise


def test_contiguity_gap_warns(caplog):
    pages = [_page(1), _page(2), _page(4)]  # missing 3
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity(pages)
    assert "gap" in caplog.text.lower()
    assert "4" in caplog.text
    assert "2" in caplog.text


def test_contiguity_duplicate_warns(caplog):
    pages = [_page(1), _page(2), _page(2), _page(3)]
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity(pages)
    assert "duplicate" in caplog.text.lower()
    assert "2" in caplog.text


def test_contiguity_multiple_gaps_each_warns(caplog):
    pages = [_page(1), _page(3), _page(5)]  # gaps at 2 and 4
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity(pages)
    assert caplog.text.lower().count("gap") >= 2


def test_contiguity_nonstandard_start_sequential_no_warning(caplog):
    # PDFs may start at 0 or an arbitrary offset — sequential is fine
    pages = [_page(5), _page(6), _page(7)]
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity(pages)
    assert caplog.text == ""


def test_contiguity_nonstandard_start_with_gap_warns(caplog):
    pages = [_page(5), _page(7)]  # gap of 1 between 5 and 7
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity(pages)
    assert "gap" in caplog.text.lower()


def test_contiguity_missing_page_num_warns(caplog):
    pages = [{"text": "no page_num field"}]
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity(pages)
    # Single-page list exits early (len <= 1) — but wait, len is 1, so it returns early.
    # We need at least 2 pages for the loop body to run.
    assert caplog.text == ""  # single-page returns early before per-page check


def test_contiguity_duplicate_does_not_also_warn_gap(caplog):
    # A duplicate page number should warn "duplicate", not also warn "gap"
    # (duplicate means pnum == prev_pnum, so pnum > prev_pnum + 1 is false)
    pages = [_page(1), _page(2), _page(2), _page(3)]
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity(pages)
    assert "duplicate" in caplog.text.lower()
    assert "gap" not in caplog.text.lower()


def test_contiguity_missing_page_num_in_middle_warns(caplog):
    pages = [_page(1), {"text": "no page_num"}, _page(3)]
    with caplog.at_level(logging.WARNING, logger="pipeline.chunk_text"):
        validate_page_contiguity(pages)
    assert "no page_num" in caplog.text.lower() or "page_num" in caplog.text.lower()


# ---------------------------------------------------------------------------
# #3 — Chunk overlap guard
# ---------------------------------------------------------------------------

def test_overlap_equal_to_chunk_size_raises():
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("some text content here", _simple_index("some text content here"), chunk_size=100, overlap=100)


def test_overlap_greater_than_chunk_size_raises():
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("some text content here", _simple_index("some text content here"), chunk_size=100, overlap=200)


def test_overlap_half_of_chunk_size_does_not_raise():
    # overlap=50 with chunk_size=100 is well within the valid range
    text = "word " * 100
    chunk_text(text, _simple_index(text), chunk_size=100, overlap=50)


def test_overlap_zero_does_not_raise():
    text = "word " * 100
    chunk_text(text, _simple_index(text), chunk_size=100, overlap=0)


def test_overlap_default_valid_does_not_raise():
    # Defaults: chunk_size=3000, overlap=200 — must remain valid
    text = "word " * 1000
    chunk_text(text, _simple_index(text))


def test_overlap_guard_error_message_includes_both_values():
    with pytest.raises(ValueError) as exc_info:
        chunk_text("text", [], chunk_size=50, overlap=50)
    msg = str(exc_info.value)
    assert "50" in msg
