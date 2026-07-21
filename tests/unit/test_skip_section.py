"""Unit tests for WP-23.4 skip-section helpers."""
import pytest

from pipeline.chunk_text import (
    _normalize_heading,
    _should_skip_chunk,
    _should_skip_section,
)

# ---------------------------------------------------------------------------
# _normalize_heading
# ---------------------------------------------------------------------------

def test_normalize_lowercase():
    assert _normalize_heading("GLOSSARY") == "glossary"


def test_normalize_strips_surrounding_whitespace():
    assert _normalize_heading("  Glossary  ") == "glossary"


def test_normalize_collapses_internal_whitespace():
    assert _normalize_heading("Table  of   Contents") == "table of contents"


def test_normalize_strips_numeric_prefix():
    assert _normalize_heading("1.2.3 Glossary") == "glossary"


def test_normalize_strips_single_level_numeric_prefix():
    assert _normalize_heading("4. References") == "references"


def test_normalize_strips_lettered_prefix():
    assert _normalize_heading("A. Acronyms") == "acronyms"


def test_normalize_strips_named_prefix_attachment():
    result = _normalize_heading("Attachment 1 - Glossary of References and Supporting Information")
    assert result.startswith("glossary")


def test_normalize_strips_named_prefix_appendix():
    result = _normalize_heading("Appendix A. Definitions")
    assert result.startswith("definitions")


def test_normalize_strips_named_prefix_annex():
    result = _normalize_heading("Annex B: Abbreviations")
    assert result.startswith("abbreviations")


def test_normalize_plain_heading_unchanged():
    assert _normalize_heading("Glossary") == "glossary"


# ---------------------------------------------------------------------------
# _should_skip_section
# ---------------------------------------------------------------------------

CYBERSECURITY_SKIPS = [
    "GLOSSARY", "REFERENCES", "ACRONYMS",
    "DEFINITIONS", "ABBREVIATIONS", "TABLE OF CONTENTS",
]


def test_exact_match():
    assert _should_skip_section(["Glossary"], CYBERSECURITY_SKIPS)


def test_case_insensitive_match():
    assert _should_skip_section(["glossary"], CYBERSECURITY_SKIPS)
    assert _should_skip_section(["GLOSSARY"], CYBERSECURITY_SKIPS)


def test_whitespace_normalized_match():
    assert _should_skip_section(["  Glossary  "], CYBERSECURITY_SKIPS)


def test_heading_starts_with_skip_phrase():
    # "Glossary of References and Supporting Information" starts with "glossary"
    assert _should_skip_section(
        ["Glossary of References and Supporting Information"],
        CYBERSECURITY_SKIPS,
    )


def test_heading_with_named_prefix_stripped():
    # After stripping "Attachment 1 -", heading starts with "glossary"
    assert _should_skip_section(
        ["Attachment 1 - Glossary of References and Supporting Information"],
        CYBERSECURITY_SKIPS,
    )


def test_nested_path_parent_matches():
    # Parent heading matches; child shouldn't matter
    assert _should_skip_section(["Glossary", "Terms and Phrases"], CYBERSECURITY_SKIPS)


def test_nested_path_child_matches():
    # Parent is innocuous; child heading matches
    assert _should_skip_section(["Attachment 1", "Glossary"], CYBERSECURITY_SKIPS)


def test_references_exact():
    assert _should_skip_section(["References"], CYBERSECURITY_SKIPS)


def test_acronyms_exact():
    assert _should_skip_section(["Acronyms"], CYBERSECURITY_SKIPS)


def test_definitions_exact():
    assert _should_skip_section(["Definitions"], CYBERSECURITY_SKIPS)


def test_no_match_unrelated_section():
    assert not _should_skip_section(["Access Control"], CYBERSECURITY_SKIPS)
    assert not _should_skip_section(["3.1 Authentication Requirements"], CYBERSECURITY_SKIPS)


def test_no_match_body_text_contains_skip_term():
    # section_title_path carries heading text only; this tests a heading that
    # happens to mention a skip word but is not a skip section
    assert not _should_skip_section(
        ["Cross-References to NIST Controls"],
        ["REFERENCES"],
    )


def test_empty_skip_sections_never_skips():
    assert not _should_skip_section(["Glossary"], [])
    assert not _should_skip_section(["References"], [])


def test_empty_section_path_never_skips():
    assert not _should_skip_section([], CYBERSECURITY_SKIPS)


def test_both_empty_no_error():
    assert not _should_skip_section([], [])


def test_none_skip_sections_treated_as_empty():
    # _should_skip_section(path, None) — callers may pass None
    # The function signature takes list[str] but guard handles falsy values
    assert not _should_skip_section(["Glossary"], [])


@pytest.mark.parametrize("heading,expected", [
    ("Glossary",                                          True),
    ("References",                                        True),
    ("Acronyms and Abbreviations",                        True),   # starts with "acronyms"
    ("Definitions",                                       True),
    ("Table of Contents",                                 True),
    ("Introduction",                                      False),
    ("Scope",                                             False),
    ("1.1 Purpose",                                       False),
    ("Incident Response Procedures",                      False),  # contains no skip phrase
])
def test_parametrized_common_headings(heading, expected):
    assert _should_skip_section([heading], CYBERSECURITY_SKIPS) == expected


# ---------------------------------------------------------------------------
# P2 — blank skip-section entries must not match everything
# ---------------------------------------------------------------------------

def test_empty_string_entry_does_not_skip():
    assert not _should_skip_section(["Access Control"], [""])


def test_whitespace_only_entry_does_not_skip():
    assert not _should_skip_section(["Access Control"], ["   "])


def test_mixed_blank_and_valid_entry_still_matches_valid():
    # The blank entry is dropped; "GLOSSARY" still matches
    assert _should_skip_section(["Glossary"], ["", "GLOSSARY"])


def test_all_blank_entries_never_skip():
    assert not _should_skip_section(["Glossary"], ["", "   "])


# ---------------------------------------------------------------------------
# P1 — _should_skip_chunk: per-item ancestry, conservative bias
# ---------------------------------------------------------------------------

class _MockItem:
    def __init__(self, self_ref):
        self.self_ref = self_ref


class _MockChunk:
    class _Meta:
        def __init__(self, items):
            self.doc_items = items
    def __init__(self, items):
        self.meta = self._Meta(items)


def _anc(section_title_path):
    return {
        "section_title_path": section_title_path,
        "section_ref_path": [],
        "parent_header_text": None,
        "parent_context": None,
    }


def test_skip_chunk_all_body_in_glossary():
    chunk = _MockChunk([_MockItem("#/1"), _MockItem("#/2")])
    ancestry = {"#/1": _anc(["Glossary"]), "#/2": _anc(["Glossary"])}
    assert _should_skip_chunk(chunk, ancestry, ["GLOSSARY"])


def test_skip_chunk_mixed_sections_keeps_chunk():
    # One body item is under Access Control (not skipped) → keep the whole chunk
    chunk = _MockChunk([_MockItem("#/1"), _MockItem("#/2")])
    ancestry = {"#/1": _anc(["Access Control"]), "#/2": _anc(["Glossary"])}
    assert not _should_skip_chunk(chunk, ancestry, ["GLOSSARY"])


def test_skip_chunk_missing_ancestry_keeps_chunk():
    # #/2 not in item_ancestry → conservative: keep
    chunk = _MockChunk([_MockItem("#/1"), _MockItem("#/2")])
    ancestry = {"#/1": _anc(["Glossary"])}
    assert not _should_skip_chunk(chunk, ancestry, ["GLOSSARY"])


def test_skip_chunk_item_without_self_ref_keeps_chunk():
    class _NoRef:
        self_ref = None
    chunk = _MockChunk([_NoRef()])
    assert not _should_skip_chunk(chunk, {}, ["GLOSSARY"])


def test_skip_chunk_empty_body_items_keeps_chunk():
    chunk = _MockChunk([])
    assert not _should_skip_chunk(chunk, {}, ["GLOSSARY"])


def test_skip_chunk_no_skip_sections_never_skips():
    chunk = _MockChunk([_MockItem("#/1")])
    ancestry = {"#/1": _anc(["Glossary"])}
    assert not _should_skip_chunk(chunk, ancestry, [])
