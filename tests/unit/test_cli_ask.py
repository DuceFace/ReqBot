"""Unit tests for cmd_ask's --no-hyde threading (WP-24.5 — HyDE default-on) and
model resolution (WP-25.6b — synthesis/rewrite model must come from config when
not passed explicitly, not a hardcoded literal).

Mocks core.ask.run directly; no real Ollama/Qdrant calls.
"""
from types import SimpleNamespace
from unittest.mock import patch

from cli.reqbot import cmd_ask


def _args(no_hyde=False, model=None, rewrite_model="llama3.1:8b-instruct-q4_K_M"):
    return SimpleNamespace(
        question="encryption at rest",
        top_k=20,
        min_score=0.02,
        synthesize=False,
        model=model,
        domain_tags=None,
        requirement_types=None,
        document_ids=None,
        no_rewrite=False,
        rewrite_model=rewrite_model,
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


def test_no_model_flag_falls_back_to_configured_synthesis_model():
    """WP-25.6b: --model omitted must resolve to _cfg.synthesis_model, not the
    hardcoded core.ask.DEFAULT_SYNTHESIS_MODEL literal."""
    mock_cfg = SimpleNamespace(
        synthesis_model="configured-synth-model",
        rewrite_model="configured-rewrite-model",
        embedding_model="configured-embedding-model",
    )
    with patch("cli.reqbot._cfg", mock_cfg), patch("core.ask.run") as mock_run:
        rc = cmd_ask(_args(model=None, rewrite_model=None))
    assert rc == 0
    _, kwargs = mock_run.call_args
    assert kwargs["model"] == "configured-synth-model"


def test_explicit_model_flag_overrides_config():
    mock_cfg = SimpleNamespace(
        synthesis_model="configured-synth-model",
        rewrite_model="configured-rewrite-model",
        embedding_model="configured-embedding-model",
    )
    with patch("cli.reqbot._cfg", mock_cfg), patch("core.ask.run") as mock_run:
        rc = cmd_ask(_args(model="explicit-model"))
    assert rc == 0
    _, kwargs = mock_run.call_args
    assert kwargs["model"] == "explicit-model"


def test_no_rewrite_model_flag_falls_back_to_configured_rewrite_model():
    """WP-25.6b: --rewrite-model omitted must resolve to _cfg.rewrite_model."""
    mock_cfg = SimpleNamespace(
        synthesis_model="configured-synth-model",
        rewrite_model="configured-rewrite-model",
        embedding_model="configured-embedding-model",
    )
    with patch("cli.reqbot._cfg", mock_cfg), patch("core.ask.run") as mock_run:
        rc = cmd_ask(_args(rewrite_model=None))
    assert rc == 0
    _, kwargs = mock_run.call_args
    assert kwargs["rewrite_model"] == "configured-rewrite-model"


def test_explicit_rewrite_model_flag_overrides_config():
    mock_cfg = SimpleNamespace(
        synthesis_model="configured-synth-model",
        rewrite_model="configured-rewrite-model",
        embedding_model="configured-embedding-model",
    )
    with patch("cli.reqbot._cfg", mock_cfg), patch("core.ask.run") as mock_run:
        rc = cmd_ask(_args(rewrite_model="explicit-rewrite-model"))
    assert rc == 0
    _, kwargs = mock_run.call_args
    assert kwargs["rewrite_model"] == "explicit-rewrite-model"


def test_unknown_document_ids_logs_clear_error_not_crash():
    """Phase 27, WP-27.1: cmd_ask's broad except Exception already catches
    ValueError and logs it -- confirm that path produces a clean rc=1, not an
    unhandled traceback, and that the bad key is visible in the log."""
    mock_cfg = SimpleNamespace(
        synthesis_model="configured-synth-model",
        rewrite_model="configured-rewrite-model",
        embedding_model="configured-embedding-model",
    )
    with (
        patch("cli.reqbot._cfg", mock_cfg),
        patch("core.ask.run", side_effect=ValueError("Unknown document_ids: bad-doc")),
        patch("cli.reqbot.log") as mock_log,
    ):
        rc = cmd_ask(_args())
    assert rc == 1
    logged = " ".join(str(c) for c in mock_log.error.call_args)
    assert "bad-doc" in logged
