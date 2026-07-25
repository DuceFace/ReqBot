"""Unit tests for cmd_evidence's remote_model pass-through (Phase 27, WP-27.2)
and --document-id pass-through (Phase 27, WP-27.3).

The locked WP-27.2 design flagged cmd_evidence as "worth checking" for the same
wrong-model-field bug the API/MCP evidence call sites had -- confirmed it does,
fixed identically here.

WP-27.3 fixed evidence_service.build() itself to resolve caller-facing
doc_key/source_pdf values instead of the internal document_id hash; cmd_evidence
already threaded --document-id straight through to build(), so these tests just
confirm that pass-through still happens and that build()'s ValueError (an
unresolved document_ids value) surfaces as a clear CLI error, not a traceback
or a silent empty result.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cli.reqbot import cmd_evidence

MOCK_RESULT = {
    "query": "access control",
    "timestamp": "2026-07-25T00:00:00Z",
    "group_order": [],
    "groups": {},
    "total_sources": 0,
    "synthesis_text": "",
    "warnings": [],
}


def _args(**overrides):
    defaults = dict(
        query="access control",
        qdrant_url="http://qdrant:6333",
        ollama_url="http://ollama:11434",
        top_k=20,
        output_format="json",
        output_file=None,
        context=False,
        document_ids=[],
        domain_tags=[],
        requirement_types=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_cfg(**overrides):
    cfg = MagicMock()
    cfg.qdrant_url = "http://qdrant:6333"
    cfg.ollama_url = "http://ollama:11434"
    cfg.top_k = 20
    cfg.synthesis_backend = "local"
    cfg.remote_provider = "anthropic"
    cfg.api_key_env = "ANTHROPIC_API_KEY"
    cfg.synthesis_model = "configured-synth-model"
    cfg.remote_model = "configured-remote-model"
    cfg.embedding_model = "configured-embedding-model"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_remote_model_passed_through(capsys):
    mock_cfg = _mock_cfg()
    with (
        patch("cli.reqbot._cfg", mock_cfg),
        patch("services.evidence_service.build", return_value=MOCK_RESULT) as mock_build,
    ):
        rc = cmd_evidence(_args())

    assert rc == 0
    _, kwargs = mock_build.call_args
    assert kwargs["remote_model"] == "configured-remote-model"
    assert kwargs["synthesis_model"] == "configured-synth-model"


def test_document_ids_passed_through():
    mock_cfg = _mock_cfg()
    with (
        patch("cli.reqbot._cfg", mock_cfg),
        patch("services.evidence_service.build", return_value=MOCK_RESULT) as mock_build,
    ):
        rc = cmd_evidence(_args(document_ids=["afi17-101"]))

    assert rc == 0
    _, kwargs = mock_build.call_args
    assert kwargs["document_ids"] == ["afi17-101"]


def test_unknown_document_id_logs_error_not_traceback(caplog):
    """build() raising ValueError for an unresolved document_ids value must
    produce a clear CLI error and rc=1 -- not a traceback, not a silent
    empty evidence pack."""
    mock_cfg = _mock_cfg()
    with (
        patch("cli.reqbot._cfg", mock_cfg),
        patch(
            "services.evidence_service.build",
            side_effect=ValueError("Unknown document_ids: bogus-doc"),
        ),
    ):
        rc = cmd_evidence(_args(document_ids=["bogus-doc"]))

    assert rc == 1
    assert "bogus-doc" in caplog.text
