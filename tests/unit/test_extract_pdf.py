"""Unit tests for WP-23.3 check #1: low-text page detection in extract_pdf_to_text.py."""
import logging

from pipeline.extract_pdf_to_text import _LOW_TEXT_THRESHOLD, warn_low_text_pages


def _page(num: int, text: str) -> dict:
    return {"page_num": num, "text": text}


def test_empty_page_list_returns_zero():
    assert warn_low_text_pages([]) == 0


def test_single_normal_page_returns_zero():
    assert warn_low_text_pages([_page(1, "A" * 200)]) == 0


def test_single_low_text_page_returns_one():
    assert warn_low_text_pages([_page(1, "Hi")]) == 1


def test_empty_text_page_counted_as_low():
    assert warn_low_text_pages([_page(1, "")]) == 1


def test_whitespace_only_page_counted_as_low():
    # Strip removes whitespace; effective length is 0
    assert warn_low_text_pages([_page(1, "   \n\t  ")]) == 1


def test_threshold_boundary_exactly_at_threshold_is_not_low():
    pages = [_page(1, "A" * _LOW_TEXT_THRESHOLD)]
    assert warn_low_text_pages(pages) == 0


def test_threshold_boundary_one_below_is_low():
    pages = [_page(1, "A" * (_LOW_TEXT_THRESHOLD - 1))]
    assert warn_low_text_pages(pages) == 1


def test_mixed_pages_counts_correctly():
    pages = [
        _page(1, "A" * 200),   # normal
        _page(2, ""),           # low
        _page(3, "tiny"),       # low
        _page(4, "B" * 200),   # normal
    ]
    assert warn_low_text_pages(pages) == 2


def test_all_low_text_pages():
    pages = [_page(i, "x") for i in range(1, 6)]
    assert warn_low_text_pages(pages) == 5


def test_low_text_emits_warning(caplog):
    pages = [_page(1, "short")]
    with caplog.at_level(logging.WARNING, logger="pipeline.extract_pdf_to_text"):
        warn_low_text_pages(pages)
    assert "low" in caplog.text.lower()
    assert "1" in caplog.text  # page number appears


def test_low_text_emits_summary_warning(caplog):
    pages = [_page(1, "short"), _page(2, "A" * 200)]
    with caplog.at_level(logging.WARNING, logger="pipeline.extract_pdf_to_text"):
        warn_low_text_pages(pages)
    # Both the per-page warning and summary warning should appear
    assert caplog.text.count("WARNING") >= 2


def test_normal_pages_emit_no_warning(caplog):
    pages = [_page(i, "A" * 200) for i in range(1, 4)]
    with caplog.at_level(logging.WARNING, logger="pipeline.extract_pdf_to_text"):
        warn_low_text_pages(pages)
    assert caplog.text == ""


def test_page_without_page_num_field_still_warns():
    pages = [{"text": "x"}]
    count = warn_low_text_pages(pages)
    assert count == 1


def test_page_without_text_field_counted_as_low():
    pages = [{"page_num": 1}]
    assert warn_low_text_pages(pages) == 1
