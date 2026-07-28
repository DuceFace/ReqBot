import json
from pathlib import Path

import pytest

import core.profiles as profiles_mod
from core.profiles import REQUIRED_FIELDS, default_profile, load_profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_profile(directory: Path, data: dict) -> None:
    name = data.get("name", "test")
    (directory / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture()
def profile_dir(tmp_path, monkeypatch):
    """Redirect the loader to a fresh temp directory for isolation."""
    monkeypatch.setattr(profiles_mod, "_PROFILES_DIR", tmp_path)
    return tmp_path


_MINIMAL_VALID = {
    "name": "test",
    "obligation_verbs": ["shall", "must"],
    "skip_sections": ["GLOSSARY"],
    "domain_tags": ["access-control"],
    "requirement_types": ["policy"],
}


# ---------------------------------------------------------------------------
# Cybersecurity profile round-trip
# ---------------------------------------------------------------------------

def test_load_cybersecurity_returns_dict():
    result = load_profile("cybersecurity")
    assert isinstance(result, dict)


def test_cybersecurity_all_required_fields_present():
    result = load_profile("cybersecurity")
    for field in REQUIRED_FIELDS:
        assert field in result, f"Missing required field: {field}"


# WP-33.1: these five pairs of tests are structural, not incidental, now -- each
# module's VALID_DOMAIN_TAGS/VALID_REQUIREMENT_TYPES (or cli/console.py's
# differently-named equivalents) is itself derived from core.profiles.default_profile()
# at import time, not an independently hardcoded copy. Kept as explicit tests anyway,
# as a regression guard against a future accidental re-hardcoding in any one file.

def test_cybersecurity_domain_tags_match_pipeline_constants():
    from pipeline.llm_extract_requirements import VALID_DOMAIN_TAGS
    result = load_profile("cybersecurity")
    assert result["domain_tags"] == VALID_DOMAIN_TAGS


def test_cybersecurity_requirement_types_match_pipeline_constants():
    from pipeline.llm_extract_requirements import VALID_REQUIREMENT_TYPES
    result = load_profile("cybersecurity")
    assert result["requirement_types"] == VALID_REQUIREMENT_TYPES


def test_enrich_requirements_domain_tags_match_profile():
    from pipeline.enrich_requirements import VALID_DOMAIN_TAGS
    result = load_profile("cybersecurity")
    assert result["domain_tags"] == VALID_DOMAIN_TAGS


def test_enrich_requirements_requirement_types_match_profile():
    from pipeline.enrich_requirements import VALID_REQUIREMENT_TYPES
    result = load_profile("cybersecurity")
    assert result["requirement_types"] == VALID_REQUIREMENT_TYPES


def test_core_ask_domain_tags_match_profile():
    from core.ask import VALID_DOMAIN_TAGS
    result = load_profile("cybersecurity")
    assert set(result["domain_tags"]) == VALID_DOMAIN_TAGS


def test_core_ask_requirement_types_match_profile():
    from core.ask import VALID_REQUIREMENT_TYPES
    result = load_profile("cybersecurity")
    assert set(result["requirement_types"]) == VALID_REQUIREMENT_TYPES


def test_cli_console_domain_tags_match_profile():
    from cli.console import _DOMAIN_TAGS
    result = load_profile("cybersecurity")
    assert set(result["domain_tags"]) == _DOMAIN_TAGS


def test_cli_console_requirement_types_match_profile():
    from cli.console import _VALID_REQUIREMENT_TYPES
    result = load_profile("cybersecurity")
    assert set(result["requirement_types"]) == _VALID_REQUIREMENT_TYPES


def test_parse_and_normalize_no_longer_has_dead_vocabulary_constants():
    """WP-33.1: these were unused (not referenced anywhere in the file or
    imported anywhere else in the repo) -- deleted outright rather than kept as
    unused profile-derived constants, unlike the other four files above."""
    import pipeline.parse_and_normalize as pan
    assert not hasattr(pan, "VALID_DOMAIN_TAGS")
    assert not hasattr(pan, "VALID_REQUIREMENT_TYPES")


def test_cybersecurity_obligation_verbs_is_nonempty_list():
    result = load_profile("cybersecurity")
    assert isinstance(result["obligation_verbs"], list)
    assert len(result["obligation_verbs"]) > 0


def test_cybersecurity_skip_sections_is_nonempty_list():
    result = load_profile("cybersecurity")
    assert isinstance(result["skip_sections"], list)
    assert len(result["skip_sections"]) > 0


def test_default_profile_returns_cybersecurity():
    result = default_profile()
    assert result["name"] == "cybersecurity"


# ---------------------------------------------------------------------------
# Loader contract — error cases
# ---------------------------------------------------------------------------

def test_nonexistent_profile_raises_file_not_found(profile_dir):
    with pytest.raises(FileNotFoundError, match="nonexistent"):
        load_profile("nonexistent")


@pytest.mark.parametrize("missing_field", list(REQUIRED_FIELDS))
def test_missing_required_field_raises_value_error(profile_dir, missing_field):
    data = {k: v for k, v in _MINIMAL_VALID.items() if k != missing_field}
    _write_profile(profile_dir, data)
    with pytest.raises(ValueError, match=missing_field):
        load_profile("test")


def test_unknown_field_raises_value_error(profile_dir):
    data = {**_MINIMAL_VALID, "surprise_field": "oops"}
    _write_profile(profile_dir, data)
    with pytest.raises(ValueError, match="surprise_field"):
        load_profile("test")


def test_name_mismatch_raises_value_error(profile_dir):
    data = {**_MINIMAL_VALID, "name": "wrong-name"}
    # File must be test.json, but name field says wrong-name
    (profile_dir / "test.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        load_profile("test")


# ---------------------------------------------------------------------------
# Loader contract — type validation
# ---------------------------------------------------------------------------

def test_non_object_json_raises_value_error(profile_dir):
    (profile_dir / "test.json").write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_profile("test")


@pytest.mark.parametrize("field", ["obligation_verbs", "skip_sections", "domain_tags", "requirement_types"])
def test_list_field_not_a_list_raises_value_error(profile_dir, field):
    data = {**_MINIMAL_VALID, field: "not-a-list"}
    _write_profile(profile_dir, data)
    with pytest.raises(ValueError, match=field):
        load_profile("test")


@pytest.mark.parametrize("field", ["obligation_verbs", "skip_sections", "domain_tags", "requirement_types"])
def test_list_field_contains_non_string_raises_value_error(profile_dir, field):
    data = {**_MINIMAL_VALID, field: ["valid", 42]}
    _write_profile(profile_dir, data)
    with pytest.raises(ValueError, match=field):
        load_profile("test")


def test_checklist_guidance_not_dict_raises_value_error(profile_dir):
    data = {**_MINIMAL_VALID, "checklist_guidance": ["not", "a", "dict"]}
    _write_profile(profile_dir, data)
    with pytest.raises(ValueError, match="checklist_guidance"):
        load_profile("test")


def test_checklist_guidance_evidence_categories_not_list_raises_value_error(profile_dir):
    data = {**_MINIMAL_VALID, "checklist_guidance": {"evidence_categories": "policy"}}
    _write_profile(profile_dir, data)
    with pytest.raises(ValueError, match="evidence_categories"):
        load_profile("test")


def test_path_separator_in_name_raises_value_error(profile_dir):
    with pytest.raises(ValueError, match="path separators"):
        load_profile("../etc/passwd")


def test_checklist_guidance_not_mutated_across_loads(profile_dir):
    _write_profile(profile_dir, _MINIMAL_VALID)
    result1 = load_profile("test")
    result1["checklist_guidance"]["injected"] = True
    result2 = load_profile("test")
    assert "injected" not in result2["checklist_guidance"]


# ---------------------------------------------------------------------------
# Loader contract — optional field defaults
# ---------------------------------------------------------------------------

def test_optional_fields_default_when_absent(profile_dir):
    _write_profile(profile_dir, _MINIMAL_VALID)
    result = load_profile("test")
    assert result["description"] == ""
    assert result["checklist_guidance"] == {}
    assert result["version"] is None


def test_optional_fields_preserved_when_present(profile_dir):
    data = {**_MINIMAL_VALID, "description": "A test domain", "version": "2.0"}
    _write_profile(profile_dir, data)
    result = load_profile("test")
    assert result["description"] == "A test domain"
    assert result["version"] == "2.0"
