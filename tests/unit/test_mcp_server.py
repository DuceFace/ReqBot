"""Unit tests for mcp_server/server.py (WP-26.2): the get_status MCP tool.

Manual smoke test (real stdio subprocess + real MCP client session, calling
get_status against a live Ollama/Qdrant) was run separately and isn't repeated
here -- these are the fast, no-network unit checks.

mcp is an optional [mcp] extra (pyproject.toml), not in requirements.txt/
requirements-dev.txt -- CI's `test` job installs from those legacy files, not
pyproject.toml's extras, so mcp isn't present there. Skip cleanly rather than
break collection for every other test in the suite when it's absent.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402


def test_module_imports_without_starting_network_services():
    """Importing the module must not touch Ollama/Qdrant/config -- it's collected
    at test-discovery time, before any test has a chance to mock those out."""
    import mcp_server.server as server

    assert server.mcp.name == "reqbot"
    assert callable(server.get_status)
    assert callable(server.run)


def _mock_cfg(**overrides):
    cfg = MagicMock()
    cfg.ollama_url = "http://ollama:11434"
    cfg.qdrant_url = "http://qdrant:6333"
    cfg.processed_dir_path.return_value = "/fake/processed"
    cfg.embedding_model = "cfg-embedding"
    cfg.extraction_model = "cfg-extraction"
    cfg.enrichment_model = "cfg-enrichment"
    cfg.rewrite_model = "cfg-rewrite"
    cfg.synthesis_model = "cfg-synthesis"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_get_status_calls_config_and_status_service():
    from mcp_server import server

    fake_result = {"ollama": {"reachable": True}}
    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()) as mock_load,
        patch("mcp_server.server.status_service.check", return_value=fake_result) as mock_check,
    ):
        result = server.get_status()

    mock_load.assert_called_once()
    mock_check.assert_called_once()
    assert result is fake_result


def test_get_status_passes_configured_model_roles_through():
    from mcp_server import server

    cfg = _mock_cfg()
    with (
        patch("mcp_server.server._config.load", return_value=cfg),
        patch("mcp_server.server.status_service.check", return_value={}) as mock_check,
    ):
        server.get_status()

    _, args, kwargs = mock_check.mock_calls[0]
    called_ollama_url, called_qdrant_url, called_processed_dir, called_models = args
    assert called_ollama_url == cfg.ollama_url
    assert called_qdrant_url == cfg.qdrant_url
    assert called_processed_dir == cfg.processed_dir_path.return_value
    assert called_models == {
        "embedding": "cfg-embedding",
        "extraction": "cfg-extraction",
        "enrichment": "cfg-enrichment",
        "rewrite": "cfg-rewrite",
        "synthesis": "cfg-synthesis",
    }


def test_get_status_config_failure_becomes_structured_mcp_error():
    """A raw exception from core.config.load() must not crash the server -- FastMCP
    wraps any exception raised inside a @mcp.tool() function into a ToolError."""
    from mcp_server import server

    with patch("mcp_server.server._config.load", side_effect=RuntimeError("bad config")):
        with pytest.raises(ToolError):
            asyncio.run(server.mcp.call_tool("get_status", {}))


def test_get_status_service_failure_becomes_structured_mcp_error():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.status_service.check", side_effect=OSError("qdrant unreachable")),
    ):
        with pytest.raises(ToolError):
            asyncio.run(server.mcp.call_tool("get_status", {}))


# ---------------------------------------------------------------------------
# list_documents (WP-26.3)
# ---------------------------------------------------------------------------

def test_list_documents_calls_docs_service_with_processed_dir():
    from mcp_server import server

    cfg = _mock_cfg()
    fake_result = {"docs": [], "total_reqs": 0, "total_docs": 0}
    with (
        patch("mcp_server.server._config.load", return_value=cfg),
        patch("mcp_server.server.docs_service.list_docs", return_value=fake_result) as mock_list,
    ):
        result = server.list_documents()

    mock_list.assert_called_once_with(cfg.processed_dir_path.return_value)
    assert result is fake_result


def test_list_documents_failure_becomes_structured_mcp_error():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.docs_service.list_docs", side_effect=FileNotFoundError("no such dir")),
    ):
        with pytest.raises(ToolError):
            asyncio.run(server.mcp.call_tool("list_documents", {}))


# ---------------------------------------------------------------------------
# search_requirements (WP-26.3)
# ---------------------------------------------------------------------------

def test_search_requirements_calls_ask_service_with_expected_params():
    from mcp_server import server

    cfg = _mock_cfg()
    fake_result = {"query": "x", "results": [], "metadata": {}, "warnings": []}
    with (
        patch("mcp_server.server._config.load", return_value=cfg),
        patch("mcp_server.server.ask_service.ask", return_value=fake_result) as mock_ask,
    ):
        result = server.search_requirements(
            "access control",
            top_k=5,
            document_ids=["docA"],
            domain_tags=["access-control"],
            requirement_types=["shall"],
            context=True,
        )

    assert result is fake_result
    _, args, kwargs = mock_ask.mock_calls[0]
    assert args == ("access control", cfg.qdrant_url, cfg.ollama_url)
    assert kwargs["top_k"] == 5
    assert kwargs["document_ids"] == ["docA"]
    assert kwargs["domain_tags"] == ["access-control"]
    assert kwargs["requirement_types"] == ["shall"]
    assert kwargs["context"] is True
    assert kwargs["embedding_model"] == cfg.embedding_model
    assert kwargs["rewrite_model"] == cfg.rewrite_model


def test_search_requirements_never_synthesizes():
    """Architecture rule: structured retrieval only -- no default LLM synthesis (Non-Goals,
    Section 3). synthesize must always be False regardless of caller input, since this tool
    doesn't even expose a synthesize parameter."""
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.ask_service.ask", return_value={}) as mock_ask,
    ):
        server.search_requirements("question")

    assert mock_ask.mock_calls[0].kwargs["synthesize"] is False


def test_search_requirements_warnings_pass_through():
    from mcp_server import server

    fake_result = {
        "results": [],
        "warnings": ["embedding model mismatch: configured nomic-embed-text, indexed other-model"],
    }
    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.ask_service.ask", return_value=fake_result),
    ):
        result = server.search_requirements("question")

    assert result["warnings"] == fake_result["warnings"]


def test_search_requirements_service_failure_becomes_structured_mcp_error():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.ask_service.ask", side_effect=RuntimeError("ollama unreachable")),
    ):
        with pytest.raises(ToolError):
            asyncio.run(server.mcp.call_tool("search_requirements", {"question": "x"}))


# ---------------------------------------------------------------------------
# trace_requirement (WP-26.3)
# ---------------------------------------------------------------------------

def test_trace_requirement_calls_trace_service():
    from mcp_server import server

    cfg = _mock_cfg()
    fake_result = {"requirement": {}, "cross_matches": [], "context_text": None}
    with (
        patch("mcp_server.server._config.load", return_value=cfg),
        patch("mcp_server.server.trace_service.trace", return_value=fake_result) as mock_trace,
    ):
        result = server.trace_requirement("REQ-abc123", include_context=True)

    mock_trace.assert_called_once_with("REQ-abc123", cfg.qdrant_url, show_context=True)
    assert result is fake_result


def test_trace_requirement_provenance_fields_present():
    from mcp_server import server

    fake_requirement = {
        "requirement_id": "REQ-abc123",
        "source_pdf": "NIST.SP.800-53r5.pdf",
        "source_ref": "AC-3",
        "source_quote": "The organization shall enforce approved authorizations...",
        "document_id": "NIST.SP.800-53r5",
    }
    fake_result = {"requirement": fake_requirement, "cross_matches": [], "context_text": None}
    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.trace_service.trace", return_value=fake_result),
    ):
        result = server.trace_requirement("REQ-abc123")

    for field in ("requirement_id", "source_pdf", "source_ref", "source_quote"):
        assert result["requirement"][field], f"missing/empty provenance field: {field}"


def test_trace_requirement_unknown_id_becomes_structured_mcp_error():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch(
            "mcp_server.server.trace_service.trace",
            side_effect=ValueError("Requirement not found: REQ-does-not-exist"),
        ),
    ):
        with pytest.raises(ToolError):
            asyncio.run(
                server.mcp.call_tool("trace_requirement", {"requirement_id": "REQ-does-not-exist"})
            )


def test_trace_requirement_service_failure_becomes_structured_mcp_error():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.trace_service.trace", side_effect=RuntimeError("Could not connect to Qdrant")),
    ):
        with pytest.raises(ToolError):
            asyncio.run(
                server.mcp.call_tool("trace_requirement", {"requirement_id": "REQ-x"})
            )
