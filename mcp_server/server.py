"""ReqBot MCP server (WP-26.2). Thin FastMCP wrapper over services/, same as api/routes/.

Started via `reqbot mcp`, stdio transport only (locked in WP-26.1). Tool functions raise
plain exceptions on failure -- FastMCP wraps any exception raised inside a @mcp.tool()
function into a structured mcp.server.fastmcp.exceptions.ToolError for the client, so
there's no need to catch and re-wrap here.
"""
from mcp.server.fastmcp import FastMCP

from core import config as _config
from services import ask_service, docs_service, status_service, trace_service

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


@mcp.tool()
def list_documents() -> dict:
    """List indexed documents: doc_key, source PDF, requirement count, chunking mode, run date,
    and domain profile for each. Call this before search_requirements/trace_requirement to see
    what's actually in the corpus."""
    cfg = _config.load()
    return docs_service.list_docs(cfg.processed_dir_path())


@mcp.tool()
def search_requirements(
    question: str,
    top_k: int = 20,
    document_ids: list[str] | None = None,
    domain_tags: list[str] | None = None,
    requirement_types: list[str] | None = None,
    context: bool = False,
) -> dict:
    """Search requirements and return ranked, source-backed hits with provenance and warnings.

    Structured retrieval only -- no LLM synthesis is ever performed by this tool (synthesis
    stays optional and separately labeled per Phase 26's architecture rules, on other tools
    that intentionally support it). Pass a returned result's requirement_id to
    trace_requirement for full provenance on one hit.
    """
    # Same bound /api/ask enforces via Pydantic's Field(ge=1, le=100) (api/routes/ask.py) --
    # that's interface-boundary input validation, not shared core/ask.py business logic, so
    # each interface owning its own copy is the existing pattern, not a rule violation.
    # Unbounded top_k isn't just "large": core.ask.retrieve derives Qdrant prefetch/fusion
    # limits from it (prefetch_limit = max(100, top_k * 5)), and a negative top_k breaks
    # hits[:top_k] slicing (Python slices from the end instead of limiting count).
    if not 1 <= top_k <= 100:
        raise ValueError(f"top_k must be between 1 and 100, got {top_k}")

    cfg = _config.load()
    return ask_service.ask(
        question,
        cfg.qdrant_url,
        cfg.ollama_url,
        top_k=top_k,
        min_score=cfg.min_score,
        embedding_model=cfg.embedding_model,
        rewrite_model=cfg.rewrite_model,
        domain_tags=domain_tags,
        requirement_types=requirement_types,
        document_ids=document_ids,
        context=context,
        synthesize=False,
    )


@mcp.tool()
def trace_requirement(requirement_id: str, include_context: bool = False) -> dict:
    """Retrieve full provenance for one known requirement_id: the full payload (source_quote,
    source_ref, document/page/section metadata), cross-framework matches sharing the same
    source_ref in other documents, and optionally the surrounding source chunk text."""
    cfg = _config.load()
    return trace_service.trace(requirement_id, cfg.qdrant_url, show_context=include_context)


def run() -> None:
    """Entry point for `reqbot mcp` -- runs the server over stdio and blocks."""
    mcp.run(transport="stdio")
