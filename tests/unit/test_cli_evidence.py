"""Unit tests for cmd_evidence's remote_model pass-through (Phase 27, WP-27.2).

The locked WP-27.2 design flagged cmd_evidence as "worth checking" for the same
wrong-model-field bug the API/MCP evidence call sites had -- confirmed it does,
fixed identically here.
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
