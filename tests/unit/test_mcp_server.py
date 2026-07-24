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
    cfg.min_score = 0.07
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
    assert kwargs["min_score"] == cfg.min_score


def test_search_requirements_rejects_top_k_out_of_bounds():
    """Same 1..100 bound /api/ask enforces via Pydantic (api/routes/ask.py) -- unbounded
    top_k lets a caller drive core.ask.retrieve's Qdrant prefetch/fusion limits arbitrarily
    high (Codex review, PR #114), and a negative top_k breaks hits[:top_k] slicing."""
    from mcp_server import server

    with patch("mcp_server.server._config.load", return_value=_mock_cfg()):
        for bad in (0, -5, 101, 100000):
            with pytest.raises(ValueError, match="top_k"):
                server.search_requirements("question", top_k=bad)


def test_search_requirements_accepts_top_k_boundary_values():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.ask_service.ask", return_value={}) as mock_ask,
    ):
        server.search_requirements("question", top_k=1)
        server.search_requirements("question", top_k=100)

    assert mock_ask.call_count == 2


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


# ---------------------------------------------------------------------------
# compare_documents (WP-26.4)
# ---------------------------------------------------------------------------

def test_compare_documents_calls_compare_service_with_resolved_pdfs():
    from mcp_server import server

    cfg = _mock_cfg()
    fake_result = {"query": "AC-2", "mode": "exact", "source_ref": "AC-2", "groups": {}}
    with (
        patch("mcp_server.server._config.load", return_value=cfg),
        patch(
            "mcp_server.server.resolve_source_pdfs",
            return_value={"docA": "docA.pdf", "docB": "docB.pdf"},
        ),
        patch("mcp_server.server.compare_service.compare", return_value=fake_result) as mock_compare,
    ):
        result = server.compare_documents("docA", "docB", "AC-2", top_k=15)

    mock_compare.assert_called_once_with(
        query="AC-2",
        qdrant_url=cfg.qdrant_url,
        ollama_url=cfg.ollama_url,
        top_k=15,
        doc_keys=["docA.pdf", "docB.pdf"],
        embedding_model=cfg.embedding_model,
    )
    assert result["doc_id_1"] == "docA"
    assert result["doc_id_2"] == "docB"
    assert result["doc_pdf_1"] == "docA.pdf"
    assert result["doc_pdf_2"] == "docB.pdf"


def test_compare_documents_falls_back_to_dotpdf_suffix_when_unresolved():
    """resolve_source_pdfs returns '' for an unknown doc_key -- _canonical_source_pdf
    must fall back to doc_key + '.pdf' rather than passing an empty string through."""
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.resolve_source_pdfs", return_value={"docA": "", "docB": ""}),
        patch("mcp_server.server.compare_service.compare", return_value={}) as mock_compare,
    ):
        result = server.compare_documents("docA", "docB", "AC-2")

    assert result["doc_pdf_1"] == "docA.pdf"
    assert result["doc_pdf_2"] == "docB.pdf"
    assert mock_compare.mock_calls[0].kwargs["doc_keys"] == ["docA.pdf", "docB.pdf"]


def test_compare_documents_rejects_top_k_out_of_bounds():
    from mcp_server import server

    with patch("mcp_server.server._config.load", return_value=_mock_cfg()):
        for bad in (0, -5, 101):
            with pytest.raises(ValueError, match="top_k"):
                server.compare_documents("docA", "docB", "AC-2", top_k=bad)


def test_compare_documents_semantic_mode_preserves_provenance_fields():
    from mcp_server import server

    fake_result = {
        "query": "access control",
        "mode": "semantic",
        "ref_order": ["AC-2"],
        "ref_groups": {
            "AC-2": {
                "docA.pdf": {"source_ref": "AC-2", "source_pdf": "docA.pdf", "source_quote": "..."},
            }
        },
        "warnings": [],
    }
    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.resolve_source_pdfs", return_value={}),
        patch("mcp_server.server.compare_service.compare", return_value=fake_result),
    ):
        result = server.compare_documents("docA", "docB", "access control")

    rep = result["ref_groups"]["AC-2"]["docA.pdf"]
    for field in ("source_ref", "source_pdf", "source_quote"):
        assert rep[field]


def test_compare_documents_resolve_failure_does_not_crash_tool():
    """api/routes/compare.py swallows resolve_source_pdfs failures and falls back to
    doc_key + '.pdf' rather than failing the whole comparison -- match that behavior."""
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.resolve_source_pdfs", side_effect=OSError("disk error")),
        patch("mcp_server.server.compare_service.compare", return_value={}) as mock_compare,
    ):
        result = server.compare_documents("docA", "docB", "AC-2")

    assert result["doc_pdf_1"] == "docA.pdf"
    assert result["doc_pdf_2"] == "docB.pdf"
    assert mock_compare.called


def test_compare_documents_service_failure_becomes_structured_mcp_error():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.resolve_source_pdfs", return_value={}),
        patch("mcp_server.server.compare_service.compare", side_effect=ValueError("No requirements found")),
    ):
        with pytest.raises(ToolError):
            asyncio.run(
                server.mcp.call_tool(
                    "compare_documents",
                    {"doc_id_1": "docA", "doc_id_2": "docB", "topic": "AC-2"},
                )
            )


# ---------------------------------------------------------------------------
# map_evidence (WP-26.4)
# ---------------------------------------------------------------------------

def test_map_evidence_calls_evidence_service_with_expected_params():
    from mcp_server import server

    cfg = _mock_cfg(synthesis_backend="local")
    fake_result = {"query": "x", "groups": {}, "group_order": [], "total_sources": 0, "synthesis_text": ""}
    with (
        patch("mcp_server.server._config.load", return_value=cfg),
        patch("mcp_server.server.evidence_service.build", return_value=fake_result) as mock_build,
    ):
        result = server.map_evidence(
            "access control",
            domain_tags=["access-control"],
            requirement_types=["shall"],
            synthesize=True,
            top_k=25,
        )

    assert result is fake_result
    _, args, kwargs = mock_build.mock_calls[0]
    assert kwargs["query"] == "access control"
    assert kwargs["qdrant_url"] == cfg.qdrant_url
    assert kwargs["ollama_url"] == cfg.ollama_url
    assert kwargs["top_k"] == 25
    assert kwargs["show_context"] is False
    assert kwargs["document_ids"] is None
    assert kwargs["domain_tags"] == ["access-control"]
    assert kwargs["requirement_types"] == ["shall"]
    assert kwargs["synthesize"] is True
    assert kwargs["synthesis_model"] == cfg.synthesis_model
    assert kwargs["embedding_model"] == cfg.embedding_model


def test_map_evidence_rejects_top_k_out_of_bounds():
    from mcp_server import server

    with patch("mcp_server.server._config.load", return_value=_mock_cfg()):
        for bad in (0, -1, 101):
            with pytest.raises(ValueError, match="top_k"):
                server.map_evidence("question", top_k=bad)


def test_map_evidence_falls_back_to_local_when_remote_key_missing():
    """Mirrors api/routes/evidence.py: if synthesis_backend is 'remote' but the
    configured api_key_env isn't set, silently fall back to 'local' rather than
    failing the whole evidence request."""
    from mcp_server import server

    cfg = _mock_cfg(synthesis_backend="remote", remote_provider="anthropic", api_key_env="ANTHROPIC_API_KEY")
    with (
        patch("mcp_server.server._config.load", return_value=cfg),
        patch.dict("os.environ", {}, clear=False),
        patch("mcp_server.server.evidence_service.build", return_value={}) as mock_build,
    ):
        import os as _os
        _os.environ.pop("ANTHROPIC_API_KEY", None)
        server.map_evidence("question")

    assert mock_build.mock_calls[0].kwargs["synthesis_backend"] == "local"
    assert mock_build.mock_calls[0].kwargs["api_key"] == ""


def test_map_evidence_uses_remote_backend_when_key_present():
    from mcp_server import server

    cfg = _mock_cfg(synthesis_backend="remote", remote_provider="anthropic", api_key_env="ANTHROPIC_API_KEY")
    with (
        patch("mcp_server.server._config.load", return_value=cfg),
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-fake"}),
        patch("mcp_server.server.evidence_service.build", return_value={}) as mock_build,
    ):
        server.map_evidence("question")

    assert mock_build.mock_calls[0].kwargs["synthesis_backend"] == "remote"
    assert mock_build.mock_calls[0].kwargs["api_key"] == "sk-fake"
    assert mock_build.mock_calls[0].kwargs["provider"] == "anthropic"


def test_map_evidence_grouped_output_preserves_sources_and_warnings():
    from mcp_server import server

    fake_result = {
        "query": "x",
        "groups": {
            "AC-2": {
                "source_ref": "AC-2",
                "representative": {"source_ref": "AC-2", "source_quote": "..."},
                "sources": [{"source_ref": "AC-2", "source_pdf": "docA.pdf"}],
                "context_text": None,
            }
        },
        "group_order": ["AC-2"],
        "total_sources": 1,
        "synthesis_text": "",
        "warnings": ["1 of 1 results were indexed with a different embedding model"],
    }
    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.evidence_service.build", return_value=fake_result),
    ):
        result = server.map_evidence("question")

    assert result["groups"]["AC-2"]["sources"] == fake_result["groups"]["AC-2"]["sources"]
    assert result["warnings"] == fake_result["warnings"]


def test_map_evidence_service_failure_becomes_structured_mcp_error():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.evidence_service.build", side_effect=RuntimeError("ollama unreachable")),
    ):
        with pytest.raises(ToolError):
            asyncio.run(server.mcp.call_tool("map_evidence", {"topic": "x"}))


# ---------------------------------------------------------------------------
# generate_checklist (WP-26.5)
# ---------------------------------------------------------------------------

def _fake_checklist_envelope():
    return {
        "format": "reqbot-checklist",
        "format_version": "1.0",
        "generated_at": "2026-07-24T00:00:00+00:00",
        "generator": {"tool": "reqbot", "command": "reqbot checklist --doc docA --profile cybersecurity"},
        "document": {"document_id": "docA", "source_pdf": "docA.pdf"},
        "profile": "cybersecurity",
        "summary": {"total_items": 1, "items_requiring_review": 0},
        "items": [
            {
                "checklist_item_id": "CHK-abc123",
                "requirement_ids": ["REQ-1"],
                "domain_tags": ["access-control"],
                "source_ref": "AC-2",
                "page_refs": [3],
                "section_title_path": ["3", "3.1"],
                "source_quote": "The organization shall...",
                "audit_question": "",
                "evidence_to_request": [],
                "generation_notes": "",
                "assessor_notes": "",
                "status": "not-started",
                "confidence": 0.9,
                "requires_human_review": False,
                "review_reasons": [],
            }
        ],
    }


def test_generate_checklist_calls_checklist_service_with_doc_key_and_profile():
    from mcp_server import server

    cfg = _mock_cfg()
    fake_result = _fake_checklist_envelope()
    with (
        patch("mcp_server.server._config.load", return_value=cfg),
        patch("mcp_server.server.checklist_service.generate", return_value=fake_result) as mock_generate,
    ):
        result = server.generate_checklist("docA", profile="cybersecurity")

    mock_generate.assert_called_once_with(cfg.processed_dir_path.return_value, "docA", "cybersecurity")
    assert result is fake_result


def test_generate_checklist_defaults_profile_to_cybersecurity():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.checklist_service.generate", return_value={}) as mock_generate,
    ):
        server.generate_checklist("docA")

    assert mock_generate.mock_calls[0].args[2] == "cybersecurity"


def test_generate_checklist_envelope_preserves_required_top_level_fields():
    from mcp_server import server

    fake_result = _fake_checklist_envelope()
    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.checklist_service.generate", return_value=fake_result),
    ):
        result = server.generate_checklist("docA")

    for field in ("format", "format_version", "generated_at", "generator", "document", "profile", "summary", "items"):
        assert field in result, f"missing top-level field: {field}"


def test_generate_checklist_items_preserve_provenance_and_review_fields():
    from mcp_server import server

    fake_result = _fake_checklist_envelope()
    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch("mcp_server.server.checklist_service.generate", return_value=fake_result),
    ):
        result = server.generate_checklist("docA")

    item = result["items"][0]
    for field in (
        "checklist_item_id",
        "requirement_ids",
        "source_ref",
        "source_quote",
        "confidence",
        "requires_human_review",
        "review_reasons",
    ):
        assert field in item, f"missing item field: {field}"
    assert item["checklist_item_id"] == "CHK-abc123"
    assert item["source_quote"] == "The organization shall..."


def test_generate_checklist_invalid_doc_key_becomes_structured_mcp_error():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch(
            "mcp_server.server.checklist_service.generate",
            side_effect=ValueError("No requirements file found for doc_key: docZ"),
        ),
    ):
        with pytest.raises(ToolError):
            asyncio.run(server.mcp.call_tool("generate_checklist", {"doc_key": "docZ"}))


def test_generate_checklist_invalid_profile_becomes_structured_mcp_error():
    from mcp_server import server

    with (
        patch("mcp_server.server._config.load", return_value=_mock_cfg()),
        patch(
            "mcp_server.server.checklist_service.generate",
            side_effect=FileNotFoundError("Profile not found: profiles/bogus.json"),
        ),
    ):
        with pytest.raises(ToolError):
            asyncio.run(
                server.mcp.call_tool("generate_checklist", {"doc_key": "docA", "profile": "bogus"})
            )
