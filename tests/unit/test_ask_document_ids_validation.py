"""Unit tests for core/ask.py's document_ids validation (Phase 27, WP-27.1).

A stale/typo'd document_ids value must raise a clear error instead of silently
producing an empty/reduced result set. Validation is done against the live
grc_requirements Qdrant collection -- not the processed_dir JSONL directory
(Codex review, PR #119): a document can be indexed while its JSONL lives
outside the configured processed_dir (reqbot ingest --output-dir, reqbot index
<arbitrary path>), so the collection is the only reliable source of truth for
"is this actually searchable".
"""
from unittest.mock import MagicMock, patch

import pytest

from core import ask as core_ask


def _mock_client(counts: dict[str, int]):
    """Build a QdrantClient mock whose .count() looks up the single exact
    source_pdf value each call checks (resolve_document_ids checks candidates
    one at a time, not as a combined MatchAny, so it can tell which candidate
    actually matched -- Codex review, PR #119)."""
    client = MagicMock()

    def _count(collection_name, count_filter, exact):
        match_value = count_filter.must[0].match.value
        result = MagicMock()
        result.count = counts.get(match_value, 0)
        return result

    client.count.side_effect = _count
    return client


# ---------------------------------------------------------------------------
# core.ask.resolve_document_ids
# ---------------------------------------------------------------------------

def test_resolve_document_ids_accepts_doc_key_when_source_pdf_has_pdf_suffix():
    """Real source_pdf is 'afi17-101.pdf' -- bare value alone doesn't match, but
    value + '.pdf' does, and only the confirmed-matching form is resolved to."""
    client = _mock_client({"afi17-101.pdf": 5})
    resolved, unknown = core_ask.resolve_document_ids(client, ["afi17-101"])
    assert resolved == ["afi17-101.pdf"]
    assert unknown == []


def test_resolve_document_ids_accepts_full_source_pdf_form():
    client = _mock_client({"afi17-101.pdf": 5})
    resolved, unknown = core_ask.resolve_document_ids(client, ["afi17-101.pdf"])
    assert resolved == ["afi17-101.pdf"]
    assert unknown == []


def test_resolve_document_ids_does_not_append_pdf_suffix_when_exact_value_already_matches():
    """Codex review, PR #119: if Qdrant's real source_pdf has no .pdf suffix
    (e.g. stored as 'afi17-101'), resolving to 'afi17-101.pdf' anyway would
    make retrieve() filter on a value that doesn't exist -- silently empty
    results, the exact bug this validation exists to prevent. The bare value
    must be checked -- and used -- before ever trying the .pdf-suffixed form."""
    client = _mock_client({"afi17-101": 5})  # no ".pdf" entry
    resolved, unknown = core_ask.resolve_document_ids(client, ["afi17-101"])
    assert resolved == ["afi17-101"]
    assert unknown == []


def test_resolve_document_ids_rejects_unknown_value():
    client = _mock_client({"afi17-101.pdf": 5})
    resolved, unknown = core_ask.resolve_document_ids(client, ["not-a-real-doc"])
    assert resolved == []
    assert unknown == ["not-a-real-doc"]


def test_resolve_document_ids_does_not_fabricate_for_unknown_values():
    """Unlike api/routes/compare.py's _canonical(), an unresolved value must
    never be silently accepted -- it must land in the unknown list."""
    client = _mock_client({})
    resolved, unknown = core_ask.resolve_document_ids(client, ["totally-bogus"])
    assert resolved == []
    assert unknown == ["totally-bogus"]


def test_resolve_document_ids_stops_after_first_matching_candidate():
    """When the bare value matches, the .pdf-suffixed form must never be
    queried -- confirms early-break, not a blind check-both-then-guess."""
    client = _mock_client({"afi17-101": 5})
    core_ask.resolve_document_ids(client, ["afi17-101"])
    assert client.count.call_count == 1


def test_resolve_document_ids_uses_exact_count():
    """A false 'not found' would wrongly reject a real document -- must use
    exact=True, not the faster approximate mode."""
    client = _mock_client({"afi17-101.pdf": 1})
    core_ask.resolve_document_ids(client, ["afi17-101"])
    _, kwargs = client.count.call_args
    assert kwargs["exact"] is True


def test_resolve_document_ids_prefers_exact_value_over_pdf_suffixed_candidate():
    """If both 'afi17-101' and 'afi17-101.pdf' happen to exist as distinct
    source_pdf values, the exact caller-supplied value takes precedence over
    the guessed .pdf-suffixed form."""
    client = _mock_client({"afi17-101": 3, "afi17-101.pdf": 7})
    resolved, unknown = core_ask.resolve_document_ids(client, ["afi17-101"])
    assert resolved == ["afi17-101"]
    assert unknown == []


def test_resolve_document_ids_mixed_valid_and_invalid():
    client = _mock_client({"afi17-101.pdf": 5})
    resolved, unknown = core_ask.resolve_document_ids(client, ["afi17-101", "bogus-doc"])
    assert resolved == ["afi17-101.pdf"]
    assert unknown == ["bogus-doc"]


# ---------------------------------------------------------------------------
# retrieve()'s validation gate
# ---------------------------------------------------------------------------

def test_unknown_document_ids_raises_before_any_ollama_call():
    with (
        patch("core.ask.QdrantClient", return_value=_mock_client({})),
        patch("core.ask.ollama.Client") as mock_ollama_client,
    ):
        with pytest.raises(ValueError, match="bad-doc"):
            core_ask.retrieve("test question", document_ids=["bad-doc"])

    mock_ollama_client.assert_not_called()


def test_multiple_unknown_document_ids_all_named_in_error():
    with patch("core.ask.QdrantClient", return_value=_mock_client({})):
        with pytest.raises(ValueError) as exc_info:
            core_ask.retrieve(
                "test question", document_ids=["bad-doc-1", "bad-doc-2"],
            )

    assert "bad-doc-1" in str(exc_info.value)
    assert "bad-doc-2" in str(exc_info.value)


def test_valid_document_ids_pass_validation_and_proceed():
    """Once validation passes, retrieve() proceeds normally -- confirmed by
    short-circuiting with a sentinel exception right after the gate."""

    class _PastValidation(Exception):
        pass

    with (
        patch("core.ask.QdrantClient", return_value=_mock_client({"afi17-101.pdf": 3})),
        patch("core.ask.ollama.Client", side_effect=_PastValidation),
    ):
        with pytest.raises(_PastValidation):
            core_ask.retrieve("test question", document_ids=["afi17-101"])


def test_empty_document_ids_skips_validation_entirely():
    class _PastValidation(Exception):
        pass

    mock_client = _mock_client({})
    with (
        patch("core.ask.QdrantClient", return_value=mock_client),
        patch("core.ask.ollama.Client", side_effect=_PastValidation),
    ):
        with pytest.raises(_PastValidation):
            core_ask.retrieve("test question", document_ids=None)

    mock_client.count.assert_not_called()
