"""Regression test for enrich_requirements.py's enriched-filename derivation
(Codex PR #92 review, WP-24.3 follow-up).

A broad `.replace("_requirements_normalized", "")` on the normalized JSONL's
stem would collapse every occurrence of that substring, not just the trailing
one — so a PDF whose own stem happens to contain "_requirements_normalized"
(e.g. "policy_requirements_normalized_v1.pdf") produced a mangled enriched
filename whose doc_key no longer matched the real *_chunks.jsonl file,
silently breaking context indexing for that document (ask --context / trace
--context). The fix reuses core.artifact_resolver.doc_key_from_requirements_path()
(anchored suffix strip) instead.
"""
import json
from pathlib import Path
from unittest.mock import patch

import requests

import pipeline.enrich_requirements as enrich_mod

_BASE_REQ = {
    "requirement_id": "REQ-abc123",
    "source_quote": "Systems shall restrict access.",
    "source_ref": "T-1",
    "description": "",
    "domain_tags": [],
    "requirement_type": "",
    "chunk_id": 1,
    "page_start": 1,
    "page_end": 1,
    "confidence": 0.9,
    "document_id": "abcd1234",
    "document_hash_full": "abcd1234abcd1234",
    "source_pdf": "policy_requirements_normalized_v1.pdf",
    "schema_version": "2.0",
    "pipeline_version": "1.0",
    "extraction_model": "test-model",
    "run_timestamp": "2026-01-01T00:00:00Z",
    "section_ref_path": [],
    "section_title_path": [],
    "parent_section_ref": None,
    "parent_context": None,
    "child_section_refs": [],
}


def test_enriched_filename_preserves_pdf_stem_containing_normalized_substring(tmp_path):
    # Simulates a PDF literally named "policy_requirements_normalized_v1.pdf" —
    # the resulting normalized JSONL's stem contains "_requirements_normalized"
    # twice: once as part of the original filename, once as the real suffix.
    stem = "policy_requirements_normalized_v1"
    norm_file = tmp_path / f"{stem}_requirements_normalized.jsonl"
    norm_file.write_text(json.dumps(_BASE_REQ) + "\n", encoding="utf-8")

    fake_resp = type("R", (), {"raise_for_status": lambda self: None})()

    with (
        patch.object(enrich_mod, "_enrich_batch", return_value=[
            {"description": "d", "domain_tags": ["access-control"], "requirement_type": "policy"}
        ]),
        patch.object(requests, "get", return_value=fake_resp),
    ):
        enriched_path = enrich_mod.run(
            str(norm_file), str(tmp_path),
            model="test-model",
            ollama_url="http://localhost:11434",
        )

    # Must preserve the full original stem, not collapse the embedded
    # "_requirements_normalized" substring found earlier in the filename.
    assert Path(enriched_path).name == f"{stem}_requirements_enriched.jsonl"


def test_cached_enrichment_does_not_drop_freshly_reconstructed_parent_stem(tmp_path):
    """WP-39.2 regression (Codex review, PR #185): a requirement already present in
    the enrichment resume-cache (from a prior run, before this run's reconstruction
    updated the normalized file) must still get this run's parent_stem/embedding_text
    -- not have them silently dropped in favor of the stale cached record, which
    predates reconstruction and has neither field.
    """
    doc_key = "cachetest"
    norm_file = tmp_path / f"{doc_key}_requirements_normalized.jsonl"
    norm_records = [
        {**_BASE_REQ, "requirement_id": "REQ-cached", "source_quote": "(3) Restrain competition.", "chunk_id": 2, "source_pdf": f"{doc_key}.pdf"},
    ]
    with open(norm_file, "w", encoding="utf-8") as f:
        for r in norm_records:
            f.write(json.dumps(r) + "\n")

    # Auxiliary Step C / chunks data so reconstruction actually finds a stem.
    step_c_file = tmp_path / f"{doc_key}_extracted_requirements.jsonl"
    with open(step_c_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"chunk_id": 2, "source_quote": "Information will not be classified in order to:"}) + "\n")
        f.write(json.dumps({"chunk_id": 2, "source_quote": "(3) Restrain competition."}) + "\n")

    # Pre-existing enriched cache from a run *before* reconstruction existed: has
    # description/domain_tags/requirement_type for this requirement_id (same model,
    # so it's treated as already-done and skipped) but no parent_stem/embedding_text.
    enriched_file = tmp_path / f"{doc_key}_requirements_enriched.jsonl"
    cached_record = {
        **norm_records[0],
        "description": "Cached description",
        "domain_tags": ["access-control"],
        "requirement_type": "policy",
        "enrichment_model": "test-model",
    }
    with open(enriched_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(cached_record) + "\n")

    fake_resp = type("R", (), {"raise_for_status": lambda self: None})()
    with patch.object(requests, "get", return_value=fake_resp):
        enriched_path = enrich_mod.run(
            str(norm_file), str(tmp_path),
            model="test-model",
            ollama_url="http://localhost:11434",
        )

    with open(enriched_path, encoding="utf-8") as f:
        result = json.loads(f.readline())

    # Cached enrichment fields preserved (no LLM call needed -- proves the cache
    # was actually used, not bypassed).
    assert result["description"] == "Cached description"
    assert result["domain_tags"] == ["access-control"]
    # Freshly reconstructed fields NOT dropped by the cached record.
    assert result["parent_stem"] == "Information will not be classified in order to:"
    assert result["embedding_text"] == "Information will not be classified in order to:\n(3) Restrain competition."


def test_run_survives_reconstruction_failure_without_losing_llm_enrichment(tmp_path):
    """WP-39.2 regression (Codex review, PR #185): run()'s own defensive call to
    apply_parent_stem_reconstruction() must not share fate with LLM enrichment -- a
    reconstruction failure (e.g. a malformed auxiliary JSONL) shouldn't propagate up
    and get misclassified by run_pipeline.py's caller as an *enrichment* failure,
    discarding otherwise-successful LLM output over an unrelated problem.
    """
    norm_file = tmp_path / "reconfail_requirements_normalized.jsonl"
    norm_file.write_text(json.dumps({**_BASE_REQ, "requirement_id": "REQ-x", "source_pdf": "reconfail.pdf"}) + "\n", encoding="utf-8")

    fake_resp = type("R", (), {"raise_for_status": lambda self: None})()
    with (
        patch.object(enrich_mod, "apply_parent_stem_reconstruction", side_effect=RuntimeError("malformed auxiliary JSONL")),
        patch.object(enrich_mod, "_enrich_batch", return_value=[
            {"description": "d", "domain_tags": ["access-control"], "requirement_type": "policy"}
        ]),
        patch.object(requests, "get", return_value=fake_resp),
    ):
        enriched_path = enrich_mod.run(
            str(norm_file), str(tmp_path),
            model="test-model",
            ollama_url="http://localhost:11434",
        )

    with open(enriched_path, encoding="utf-8") as f:
        result = json.loads(f.readline())
    # LLM enrichment still completed despite the reconstruction failure.
    assert result["description"] == "d"
