"""ReqBot MCP server (WP-26.2). Thin FastMCP wrapper over services/, same as api/routes/.

Started via `reqbot mcp`, stdio transport only (locked in WP-26.1). Tool functions raise
plain exceptions on failure -- FastMCP wraps any exception raised inside a @mcp.tool()
function into a structured mcp.server.fastmcp.exceptions.ToolError for the client, so
there's no need to catch and re-wrap here.
"""
import os

from mcp.server.fastmcp import FastMCP

from core import config as _config
from services import (
    ask_service,
    checklist_service,
    compare_service,
    docs_service,
    evidence_service,
    status_service,
    trace_service,
)
from services.docs_service import resolve_source_pdfs

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


def _canonical_source_pdf(doc_key: str, resolved: dict[str, str]) -> str:
    """Return canonical source_pdf; fall back to doc_key + '.pdf' if unresolved.

    Mirrors api/routes/compare.py's _canonical -- same doc_key -> source_pdf
    resolution a caller needs to interpret compare_documents' groups/ref_groups.
    """
    pdf = resolved.get(doc_key, "")
    if pdf:
        return pdf
    if doc_key.lower().endswith(".pdf"):
        return doc_key
    return doc_key + ".pdf"


@mcp.tool()
def compare_documents(doc_id_1: str, doc_id_2: str, topic: str, top_k: int = 10) -> dict:
    """Compare requirements from two documents on a topic (control ID or free-text query).

    Returns doc_pdf_1/doc_pdf_2 (canonical source_pdf values) alongside the echoed
    doc_id_1/doc_id_2. For a control ID, mode is "exact" with a source_ref and a
    groups dict keyed by source_pdf. For free text, mode is "semantic" with
    ref_order/ref_groups -- use doc_pdf_1/doc_pdf_2 to see which source_ref values
    appear in both documents, only doc1, or only doc2.
    """
    if not 1 <= top_k <= 100:
        raise ValueError(f"top_k must be between 1 and 100, got {top_k}")

    cfg = _config.load()

    try:
        resolved = resolve_source_pdfs(cfg.processed_dir_path(), [doc_id_1, doc_id_2])
    except Exception:
        resolved = {}

    doc_pdf_1 = _canonical_source_pdf(doc_id_1, resolved)
    doc_pdf_2 = _canonical_source_pdf(doc_id_2, resolved)

    result = compare_service.compare(
        query=topic,
        qdrant_url=cfg.qdrant_url,
        ollama_url=cfg.ollama_url,
        top_k=top_k,
        doc_keys=[doc_pdf_1, doc_pdf_2],
        embedding_model=cfg.embedding_model,
    )
    result["doc_id_1"] = doc_id_1
    result["doc_id_2"] = doc_id_2
    result["doc_pdf_1"] = doc_pdf_1
    result["doc_pdf_2"] = doc_pdf_2
    return result


@mcp.tool()
def map_evidence(
    topic: str,
    domain_tags: list[str] | None = None,
    requirement_types: list[str] | None = None,
    synthesize: bool = False,
    top_k: int = 10,
) -> dict:
    """Build a compliance evidence pack for a topic, grouped by control ID (source_ref).

    Each group carries its representative requirement, all matching sources, and
    (when synthesize=True and a remote synthesis backend/API key is configured) an
    executive-summary synthesis_text. Falls back to the local backend silently if
    the configured remote backend has no API key set -- same behavior as /evidence.
    """
    if not 1 <= top_k <= 100:
        raise ValueError(f"top_k must be between 1 and 100, got {top_k}")

    cfg = _config.load()

    syn_backend = cfg.synthesis_backend
    syn_provider = cfg.remote_provider
    syn_api_key = ""
    if syn_backend == "remote":
        syn_api_key = os.environ.get(cfg.api_key_env, "")
        if not syn_api_key:
            syn_backend = "local"

    return evidence_service.build(
        query=topic,
        qdrant_url=cfg.qdrant_url,
        ollama_url=cfg.ollama_url,
        top_k=top_k,
        show_context=False,
        document_ids=None,
        domain_tags=domain_tags or None,
        requirement_types=requirement_types or None,
        synthesize=synthesize,
        synthesis_backend=syn_backend,
        synthesis_model=cfg.synthesis_model,
        provider=syn_provider,
        api_key=syn_api_key,
        embedding_model=cfg.embedding_model,
    )


@mcp.tool()
def generate_checklist(doc_key: str, profile: str = "cybersecurity") -> dict:
    """Generate a source-backed compliance checklist for one indexed document.

    Returns the full checklist envelope from checklist_service.generate(): items
    carry a stable CHK- id, source_quote/source_ref provenance, confidence, review
    flags/reasons, and the profile that produced them. No file export (CSV/JSON/
    Markdown/XLSX) and no assessor-field editing over MCP -- use the CLI/API/GUI
    export paths for that.
    """
    cfg = _config.load()
    return checklist_service.generate(cfg.processed_dir_path(), doc_key, profile)


def run() -> None:
    """Entry point for `reqbot mcp` -- runs the server over stdio and blocks."""
    mcp.run(transport="stdio")
