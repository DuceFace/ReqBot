"""Unit tests for core/ask.py's retrieve() document_ids validation gate (Phase 27, WP-27.1).

A stale/typo'd document_ids value must raise a clear error instead of silently
producing an empty/reduced result set. Validation happens before any Ollama/Qdrant
call (fail fast, no wasted embedding work), and a value is only accepted if it
resolves against core.artifact_resolver.resolve_document_ids() -- never fabricated.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from core import ask as core_ask


def test_unknown_document_ids_raises_before_any_ollama_call():
    with (
        patch("core.ask._artifact_resolver.resolve_document_ids", return_value=([], ["bad-doc"])),
        patch("core.ask.ollama.Client") as mock_ollama_client,
    ):
        with pytest.raises(ValueError, match="bad-doc"):
            core_ask.retrieve(
                "test question", document_ids=["bad-doc"], processed_dir=Path("/fake/processed"),
            )

    mock_ollama_client.assert_not_called()


def test_multiple_unknown_document_ids_all_named_in_error():
    with patch(
        "core.ask._artifact_resolver.resolve_document_ids",
        return_value=([], ["bad-doc-1", "bad-doc-2"]),
    ):
        with pytest.raises(ValueError) as exc_info:
            core_ask.retrieve(
                "test question",
                document_ids=["bad-doc-1", "bad-doc-2"],
                processed_dir=Path("/fake/processed"),
            )

    assert "bad-doc-1" in str(exc_info.value)
    assert "bad-doc-2" in str(exc_info.value)


def test_document_ids_without_processed_dir_raises_clear_error():
    with pytest.raises(ValueError, match="processed_dir"):
        core_ask.retrieve("test question", document_ids=["afi17-101"], processed_dir=None)


def test_valid_document_ids_pass_validation_and_use_resolved_values():
    """Once validation passes, retrieve() proceeds using the resolved (canonical
    source_pdf) values, not the raw caller input -- confirmed by short-circuiting
    with a sentinel exception right after the validation gate."""

    class _PastValidation(Exception):
        pass

    with (
        patch(
            "core.ask._artifact_resolver.resolve_document_ids",
            return_value=(["afi17-101.pdf"], []),
        ) as mock_resolve,
        patch("core.ask.ollama.Client", side_effect=_PastValidation),
    ):
        with pytest.raises(_PastValidation):
            core_ask.retrieve(
                "test question", document_ids=["afi17-101"], processed_dir=Path("/fake/processed"),
            )

    mock_resolve.assert_called_once_with(Path("/fake/processed"), ["afi17-101"])


def test_empty_document_ids_skips_validation_entirely():
    """No document_ids filter -- no reason to touch artifact_resolver at all."""

    class _PastValidation(Exception):
        pass

    with (
        patch("core.ask._artifact_resolver.resolve_document_ids") as mock_resolve,
        patch("core.ask.ollama.Client", side_effect=_PastValidation),
    ):
        with pytest.raises(_PastValidation):
            core_ask.retrieve("test question", document_ids=None, processed_dir=None)

    mock_resolve.assert_not_called()
