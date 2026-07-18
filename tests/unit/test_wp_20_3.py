"""WP-20.3 unit tests — profile-aware pipeline integration.

Verifies that profile vocabulary (domain_tags, requirement_types, obligation_verbs)
flows correctly through Step C (llm_extract_requirements), Step D.5 (enrich_requirements),
and run_pipeline. These tests do NOT call Ollama or the filesystem pipeline — they
test the plumbing in isolation.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pipeline.enrich_requirements as enrich_mod
import pipeline.llm_extract_requirements as extract_mod
import pipeline.parse_and_normalize as normalize_mod
from core.profiles import load_profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CYBER_PROFILE = load_profile("cybersecurity")

_TEST_DOMAIN_PROFILE = load_profile("test-domain")


# ---------------------------------------------------------------------------
# Test profile: test-domain.json loads cleanly (plumbing validation)
# ---------------------------------------------------------------------------

def test_test_domain_profile_loads():
    p = load_profile("test-domain")
    assert p["name"] == "test-domain"
    assert p["domain_tags"] == ["test-tag-alpha", "test-tag-beta"]
    assert p["requirement_types"] == ["policy", "guidance"]


def test_test_domain_profile_has_required_fields():
    from core.profiles import REQUIRED_FIELDS
    p = load_profile("test-domain")
    for field in REQUIRED_FIELDS:
        assert field in p, f"Missing: {field}"


# ---------------------------------------------------------------------------
# Step C: validate_requirement uses profile domain tags and requirement types
# ---------------------------------------------------------------------------

def test_validate_requirement_accepts_profile_tag():
    req = {
        "source_quote": "Systems shall implement test-tag-alpha controls.",
        "source_ref": "T-1",
        "domain_tags": ["test-tag-alpha"],
        "requirement_type": "policy",
        "description": "",
    }
    result = extract_mod.validate_requirement(
        req,
        valid_domain_tags=_TEST_DOMAIN_PROFILE["domain_tags"],
        valid_requirement_types=_TEST_DOMAIN_PROFILE["requirement_types"],
    )
    assert result is not None
    assert result["domain_tags"] == ["test-tag-alpha"]
    assert result["requirement_type"] == "policy"


def test_validate_requirement_rejects_cybersecurity_tag_under_test_profile():
    req = {
        "source_quote": "Systems shall implement access controls.",
        "source_ref": "T-2",
        "domain_tags": ["access-control"],  # valid for cybersecurity, not for test-domain
        "requirement_type": "policy",
        "description": "",
    }
    result = extract_mod.validate_requirement(
        req,
        valid_domain_tags=_TEST_DOMAIN_PROFILE["domain_tags"],
        valid_requirement_types=_TEST_DOMAIN_PROFILE["requirement_types"],
    )
    assert result is not None
    assert result["domain_tags"] == []  # filtered out — not in test-domain tags


def test_validate_requirement_rejects_unknown_type_under_test_profile():
    req = {
        "source_quote": "Systems shall implement controls.",
        "source_ref": "T-3",
        "domain_tags": ["test-tag-alpha"],
        "requirement_type": "technical-control",  # valid for cybersecurity, not test-domain
        "description": "",
    }
    result = extract_mod.validate_requirement(
        req,
        valid_domain_tags=_TEST_DOMAIN_PROFILE["domain_tags"],
        valid_requirement_types=_TEST_DOMAIN_PROFILE["requirement_types"],
    )
    assert result is not None
    assert result["requirement_type"] == ""  # cleared — not in test-domain types


def test_validate_requirement_cybersecurity_profile_unchanged():
    req = {
        "source_quote": "The system shall enforce access control policies.",
        "source_ref": "AC-3",
        "domain_tags": ["access-control"],
        "requirement_type": "technical-control",
        "description": "",
    }
    result = extract_mod.validate_requirement(
        req,
        valid_domain_tags=_CYBER_PROFILE["domain_tags"],
        valid_requirement_types=_CYBER_PROFILE["requirement_types"],
    )
    assert result is not None
    assert result["domain_tags"] == ["access-control"]
    assert result["requirement_type"] == "technical-control"


# ---------------------------------------------------------------------------
# Step C: obligation_verbs and domain_tags injected into prompt templates
# ---------------------------------------------------------------------------

def test_pass1_template_substitutes_obligation_verbs():
    verbs = ", ".join(_TEST_DOMAIN_PROFILE["obligation_verbs"])
    result = extract_mod.PASS1_PROMPT_TEMPLATE.replace("{obligation_verbs}", verbs)
    assert "shall, must" in result
    assert "{obligation_verbs}" not in result


def test_prompt_template_substitutes_obligation_verbs_and_domain_tags():
    verbs = ", ".join(_TEST_DOMAIN_PROFILE["obligation_verbs"])
    tags = ", ".join(_TEST_DOMAIN_PROFILE["domain_tags"])
    result = (
        extract_mod.PROMPT_TEMPLATE
        .replace("{obligation_verbs}", verbs)
        .replace("{domain_tags_list}", tags)
    )
    assert "shall, must" in result
    assert "test-tag-alpha" in result
    assert "{obligation_verbs}" not in result
    assert "{domain_tags_list}" not in result


def test_cybersecurity_profile_substitution_contains_expected_verbs():
    verbs = ", ".join(_CYBER_PROFILE["obligation_verbs"])
    result = extract_mod.PASS1_PROMPT_TEMPLATE.replace("{obligation_verbs}", verbs)
    assert "shall" in result
    assert "enforce" in result
    assert "maintain" in result


def test_cybersecurity_profile_substitution_contains_expected_tags():
    verbs = ", ".join(_CYBER_PROFILE["obligation_verbs"])
    tags = ", ".join(_CYBER_PROFILE["domain_tags"])
    result = (
        extract_mod.PROMPT_TEMPLATE
        .replace("{obligation_verbs}", verbs)
        .replace("{domain_tags_list}", tags)
    )
    assert "access-control" in result
    assert "incident-response" in result
    assert "training-and-awareness" in result


# ---------------------------------------------------------------------------
# Step D.5: _validate_enrichment uses profile domain tags and requirement types
# ---------------------------------------------------------------------------

def test_validate_enrichment_accepts_profile_tag():
    raw = {
        "description": "Test requirement.",
        "domain_tags": ["test-tag-beta"],
        "requirement_type": "guidance",
    }
    result = enrich_mod._validate_enrichment(
        raw,
        valid_domain_tags=_TEST_DOMAIN_PROFILE["domain_tags"],
        valid_requirement_types=_TEST_DOMAIN_PROFILE["requirement_types"],
    )
    assert result["domain_tags"] == ["test-tag-beta"]
    assert result["requirement_type"] == "guidance"


def test_validate_enrichment_rejects_cybersecurity_tag_under_test_profile():
    raw = {
        "description": "Test requirement.",
        "domain_tags": ["audit-and-logging"],  # valid cybersecurity tag
        "requirement_type": "technical-control",  # valid cybersecurity type
    }
    result = enrich_mod._validate_enrichment(
        raw,
        valid_domain_tags=_TEST_DOMAIN_PROFILE["domain_tags"],
        valid_requirement_types=_TEST_DOMAIN_PROFILE["requirement_types"],
    )
    assert result["domain_tags"] == []
    assert result["requirement_type"] == ""


def test_validate_enrichment_cybersecurity_profile_unchanged():
    raw = {
        "description": "MFA must be enforced.",
        "domain_tags": ["authentication-and-identity"],
        "requirement_type": "technical-control",
    }
    result = enrich_mod._validate_enrichment(
        raw,
        valid_domain_tags=_CYBER_PROFILE["domain_tags"],
        valid_requirement_types=_CYBER_PROFILE["requirement_types"],
    )
    assert result["domain_tags"] == ["authentication-and-identity"]
    assert result["requirement_type"] == "technical-control"


# ---------------------------------------------------------------------------
# run_pipeline: profile_name flows through to step C and D.5
# ---------------------------------------------------------------------------

def test_run_pipeline_passes_profile_to_step_c(tmp_path):
    """run_pipeline.run() loads the named profile and passes it to llm_extract_requirements.run()."""
    from pipeline import run_pipeline

    captured = {}

    def fake_step_c(chunks_jsonl, output_dir, **kwargs):
        captured["profile"] = kwargs.get("profile")
        # Write minimal output file so pipeline can continue
        out = Path(output_dir) / "doc_extracted_requirements.jsonl"
        out.write_text("", encoding="utf-8")
        return str(out)

    def fake_step_d(reqs_jsonl, chunks_jsonl, pdf_path, output_dir, **kwargs):
        norm = Path(output_dir) / "doc_requirements_normalized.jsonl"
        norm.write_text("", encoding="utf-8")
        return str(norm)

    def fake_step_e(jsonl, output_dir, source_pdf):
        pass

    # Provide a minimal chunks.jsonl so Step C is called
    chunks = tmp_path / "doc_chunks.jsonl"
    chunks.write_text('{"chunk_id": 1, "text": "test"}\n', encoding="utf-8")

    with (
        patch.object(run_pipeline, "run", wraps=run_pipeline.run),
        patch("pipeline.extract_pdf_to_text.run"),
        patch("pipeline.chunk_text.run", return_value=str(chunks)),
        patch("pipeline.llm_extract_requirements.run", side_effect=fake_step_c),
        patch("pipeline.parse_and_normalize.run", side_effect=fake_step_d),
        patch("pipeline.aggregate_and_export.run", side_effect=fake_step_e),
    ):
        # We need a fake PDF to exist
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4")

        run_pipeline.run(
            str(fake_pdf),
            str(tmp_path),
            skip_enrichment=True,
            profile_name="test-domain",
        )

    assert captured.get("profile") is not None
    assert captured["profile"]["name"] == "test-domain"
    assert captured["profile"]["domain_tags"] == ["test-tag-alpha", "test-tag-beta"]


# ---------------------------------------------------------------------------
# Review-round fixes — Gemini: empty list validation in core/profiles.py
# ---------------------------------------------------------------------------

def test_empty_obligation_verbs_raises():
    import json as _json
    import tempfile

    from core.profiles import load_profile as _load

    bad = {
        "name": "bad-profile",
        "obligation_verbs": [],
        "skip_sections": [],
        "domain_tags": ["test-tag-alpha"],
        "requirement_types": ["policy"],
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", dir="/home/coder/grc-ai-system/profiles",
        delete=False, prefix="bad-profile"
    ) as f:
        _json.dump(bad, f)
        tmp_name = Path(f.name).stem  # e.g. "bad-profileXXXXXX"

    try:
        import pytest
        with pytest.raises(ValueError, match="obligation_verbs"):
            _load(tmp_name)
    finally:
        Path(f.name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Review-round fixes — Codex P2 #1: parse_and_normalize uses profile tags
# ---------------------------------------------------------------------------

def test_parse_normalize_uses_profile_domain_tags(tmp_path):
    """Step D must filter against the active profile's tags, not the hardcoded cybersecurity set."""
    req = {
        "source_quote": "Systems shall implement test-tag-alpha controls.",
        "source_ref": "T-1",
        "domain_tags": ["test-tag-alpha", "access-control"],
        "requirement_type": "policy",
        "description": "",
        "chunk_id": None,
    }
    reqs_file = tmp_path / "doc_extracted_requirements.jsonl"
    reqs_file.write_text(json.dumps(req) + "\n", encoding="utf-8")

    chunks_file = tmp_path / "doc_chunks.jsonl"
    chunks_file.write_text("", encoding="utf-8")

    out = normalize_mod.run(str(reqs_file), str(chunks_file), "", str(tmp_path), profile=_TEST_DOMAIN_PROFILE)

    records = [json.loads(line) for line in Path(out).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == 1
    assert "test-tag-alpha" in records[0]["domain_tags"], "test-domain tag should pass through Step D"
    assert "access-control" not in records[0]["domain_tags"], "cybersecurity tag should be filtered in test-domain run"


def test_parse_normalize_uses_profile_requirement_types(tmp_path):
    """Step D must accept only requirement_types listed in the active profile."""
    req_valid = {
        "source_quote": "Systems shall implement policy controls.",
        "source_ref": "T-1",
        "domain_tags": ["test-tag-alpha"],
        "requirement_type": "guidance",  # valid in test-domain
        "description": "",
        "chunk_id": None,
    }
    req_invalid_type = {
        "source_quote": "Systems must enforce technical controls.",
        "source_ref": "T-2",
        "domain_tags": ["test-tag-beta"],
        "requirement_type": "technical-control",  # valid for cybersecurity, NOT test-domain
        "description": "",
        "chunk_id": None,
    }
    reqs_file = tmp_path / "doc_extracted_requirements.jsonl"
    reqs_file.write_text(
        json.dumps(req_valid) + "\n" + json.dumps(req_invalid_type) + "\n", encoding="utf-8"
    )
    chunks_file = tmp_path / "doc_chunks.jsonl"
    chunks_file.write_text("", encoding="utf-8")

    out = normalize_mod.run(str(reqs_file), str(chunks_file), "", str(tmp_path), profile=_TEST_DOMAIN_PROFILE)

    records = [json.loads(line) for line in Path(out).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == 2
    by_ref = {r["source_ref"]: r for r in records}
    assert by_ref["T-1"]["requirement_type"] == "guidance"
    assert by_ref["T-2"]["requirement_type"] == "", "technical-control must be cleared under test-domain profile"


# ---------------------------------------------------------------------------
# Review-round fixes — Codex P2 #2: enrichment cache invalidated on profile change
# ---------------------------------------------------------------------------

_BASE_NORM_REQ = {
    "requirement_id": "REQ-cachetest000001",
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
    "source_pdf": "test.pdf",
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


def test_enrichment_cache_bypassed_on_profile_change(tmp_path):
    """A cache record stamped with 'cybersecurity' must be re-enriched under 'test-domain'."""
    norm_file = tmp_path / "doc_requirements_normalized.jsonl"
    norm_file.write_text(json.dumps(_BASE_NORM_REQ) + "\n", encoding="utf-8")

    cached = {
        **_BASE_NORM_REQ,
        "description": "Old cached enrichment.",
        "domain_tags": ["access-control"],
        "requirement_type": "policy",
        "enrichment_model": "test-model",
        "enrichment_profile": "cybersecurity",
    }
    enriched_file = tmp_path / "doc_requirements_enriched.jsonl"
    enriched_file.write_text(json.dumps(cached) + "\n", encoding="utf-8")

    enrich_calls: list = []

    def fake_batch(batch, model, url, timeout, *, valid_tags_str, valid_types_str, valid_domain_tags, valid_requirement_types):
        enrich_calls.extend(batch)
        return [{"description": "new", "domain_tags": ["test-tag-alpha"], "requirement_type": "guidance"}]

    import requests as _requests
    fake_resp = type("R", (), {"raise_for_status": lambda self: None})()

    with (
        patch.object(enrich_mod, "_enrich_batch", side_effect=fake_batch),
        patch.object(_requests, "get", return_value=fake_resp),
    ):
        enrich_mod.run(
            str(norm_file), str(tmp_path),
            model="test-model",
            ollama_url="http://localhost:11434",
            profile=_TEST_DOMAIN_PROFILE,
        )

    assert len(enrich_calls) == 1, "Cache should be bypassed when profile changes"
    assert enrich_calls[0]["requirement_id"] == "REQ-cachetest000001"

    out_records = [json.loads(line) for line in enriched_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert out_records[0].get("enrichment_profile") == "test-domain"


def test_enrichment_cache_honored_when_profile_matches(tmp_path):
    """A cache record stamped with the active profile must NOT be re-enriched."""
    norm_file = tmp_path / "doc_requirements_normalized.jsonl"
    norm_file.write_text(json.dumps(_BASE_NORM_REQ) + "\n", encoding="utf-8")

    cached = {
        **_BASE_NORM_REQ,
        "description": "Cached enrichment.",
        "domain_tags": ["test-tag-alpha"],
        "requirement_type": "policy",
        "enrichment_model": "test-model",
        "enrichment_profile": "test-domain",
    }
    enriched_file = tmp_path / "doc_requirements_enriched.jsonl"
    enriched_file.write_text(json.dumps(cached) + "\n", encoding="utf-8")

    enrich_calls: list = []

    def fake_batch(batch, *args, **kwargs):
        enrich_calls.extend(batch)
        return [{"description": "new", "domain_tags": [], "requirement_type": ""}]

    import requests as _requests
    fake_resp = type("R", (), {"raise_for_status": lambda self: None})()

    with (
        patch.object(enrich_mod, "_enrich_batch", side_effect=fake_batch),
        patch.object(_requests, "get", return_value=fake_resp),
    ):
        enrich_mod.run(
            str(norm_file), str(tmp_path),
            model="test-model",
            ollama_url="http://localhost:11434",
            profile=_TEST_DOMAIN_PROFILE,
        )

    assert len(enrich_calls) == 0, "Cache should be honored when model and profile both match"


# ---------------------------------------------------------------------------
# Review-round fixes — Codex P2 #3: PROMPT_TEMPLATE requirement_types_list
# ---------------------------------------------------------------------------

def test_prompt_template_substitutes_requirement_types():
    types_str = ", ".join(_TEST_DOMAIN_PROFILE["requirement_types"])
    result = (
        extract_mod.PROMPT_TEMPLATE
        .replace("{obligation_verbs}", ", ".join(_TEST_DOMAIN_PROFILE["obligation_verbs"]))
        .replace("{domain_tags_list}", ", ".join(_TEST_DOMAIN_PROFILE["domain_tags"]))
        .replace("{requirement_types_list}", types_str)
    )
    assert "policy, guidance" in result
    assert "{requirement_types_list}" not in result


def test_cybersecurity_profile_requirement_types_in_prompt():
    result = (
        extract_mod.PROMPT_TEMPLATE
        .replace("{obligation_verbs}", ", ".join(_CYBER_PROFILE["obligation_verbs"]))
        .replace("{domain_tags_list}", ", ".join(_CYBER_PROFILE["domain_tags"]))
        .replace("{requirement_types_list}", ", ".join(_CYBER_PROFILE["requirement_types"]))
    )
    assert "technical-control" in result
    assert "procedural-control" in result
    assert "{requirement_types_list}" not in result
