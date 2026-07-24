"""Unit tests for mcp_server/server.py (WP-26.2): the get_status MCP tool.

Manual smoke test (real stdio subprocess + real MCP client session, calling
get_status against a live Ollama/Qdrant) was run separately and isn't repeated
here -- these are the fast, no-network unit checks.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError


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
