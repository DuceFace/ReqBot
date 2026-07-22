"""Unit tests for cmd_ask's --no-hyde threading (WP-24.5 — HyDE default-on).

Mocks core.ask.run directly; no real Ollama/Qdrant calls.
"""
from types import SimpleNamespace
from unittest.mock import patch

from cli.reqbot import cmd_ask


def _args(no_hyde=False):
    return SimpleNamespace(
        question="encryption at rest",
        top_k=20,
        min_score=0.02,
        synthesize=False,
        model=None,
        domain_tags=None,
        requirement_types=None,
        document_ids=None,
        no_rewrite=False,
        rewrite_model="llama3.1:8b-instruct-q4_K_M",
        qdrant_url="http://qdrant:6333",
        ollama_url="http://ollama:11434",
        json_output=False,
        context=False,
        context_collection="grc_context",
        no_hyde=no_hyde,
    )


def test_default_call_enables_hyde():
    with patch("core.ask.run") as mock_run:
        rc = cmd_ask(_args())
    assert rc == 0
    _, kwargs = mock_run.call_args
    assert kwargs["hyde"] is True


def test_no_hyde_disables_hyde():
    with patch("core.ask.run") as mock_run:
        rc = cmd_ask(_args(no_hyde=True))
    assert rc == 0
    _, kwargs = mock_run.call_args
    assert kwargs["hyde"] is False


def test_missing_no_hyde_attribute_defaults_to_hyde_enabled():
    """A Namespace built before this WP (no no_hyde attribute at all) must not
    crash cmd_ask — getattr tolerance, same pattern as no_index in WP-24.3."""
    args = _args()
    del args.no_hyde
    with patch("core.ask.run") as mock_run:
        rc = cmd_ask(args)
    assert rc == 0
    _, kwargs = mock_run.call_args
    assert kwargs["hyde"] is True
