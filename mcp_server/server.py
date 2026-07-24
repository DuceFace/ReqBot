"""ReqBot MCP server (WP-26.2). Thin FastMCP wrapper over services/, same as api/routes/.

Started via `reqbot mcp`, stdio transport only (locked in WP-26.1). Tool functions raise
plain exceptions on failure -- FastMCP wraps any exception raised inside a @mcp.tool()
function into a structured mcp.server.fastmcp.exceptions.ToolError for the client, so
there's no need to catch and re-wrap here.
"""
from mcp.server.fastmcp import FastMCP

from core import config as _config
from services import status_service

mcp = FastMCP("reqbot")


@mcp.tool()
def get_status() -> dict:
    """Report ReqBot's configured service URLs, model roles, and Ollama/Qdrant reachability."""
    cfg = _config.load()
    return status_service.check(
        cfg.ollama_url,
        cfg.qdrant_url,
        cfg.processed_dir_path(),
        {
            "embedding": cfg.embedding_model,
            "extraction": cfg.extraction_model,
            "enrichment": cfg.enrichment_model,
            "rewrite": cfg.rewrite_model,
            "synthesis": cfg.synthesis_model,
        },
    )


def run() -> None:
    """Entry point for `reqbot mcp` -- runs the server over stdio and blocks."""
    mcp.run(transport="stdio")
