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


def test_cybersecurity_domain_tags_match_pipeline_constants():
    from pipeline.llm_extract_requirements import VALID_DOMAIN_TAGS
    result = load_profile("cybersecurity")
    assert result["domain_tags"] == VALID_DOMAIN_TAGS


def test_cybersecurity_requirement_types_match_pipeline_constants():
    from pipeline.llm_extract_requirements import VALID_REQUIREMENT_TYPES
    result = load_profile("cybersecurity")
    assert result["requirement_types"] == VALID_REQUIREMENT_TYPES


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
