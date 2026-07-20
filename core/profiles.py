"""Profile loader for domain-specific pipeline configuration.

Profiles live in profiles/<name>.json at the repo root.
The loader validates required fields, applies defaults for optional fields,
and fails fast with a clear error on unknown or malformed input.
"""

import copy
import json
from pathlib import Path

_PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"

REQUIRED_FIELDS = frozenset({"name", "obligation_verbs", "skip_sections", "domain_tags", "requirement_types"})
OPTIONAL_FIELDS = frozenset({"description", "checklist_guidance", "version"})
_ALL_KNOWN_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

_OPTIONAL_DEFAULTS: dict = {
    "description": "",
    "checklist_guidance": {},
    "version": None,
}

_LIST_OF_STRINGS_FIELDS = ("obligation_verbs", "skip_sections", "domain_tags", "requirement_types")
# These fields drive LLM prompt content and validation — an empty list produces a broken prompt
# or silently accepts/rejects everything. skip_sections is intentionally excluded (empty is valid).
_NON_EMPTY_LIST_FIELDS = frozenset({"obligation_verbs", "domain_tags", "requirement_types"})


def _validate_types(data: dict) -> None:
    """Raise ValueError if any field has a wrong type."""
    for field in _LIST_OF_STRINGS_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, list):
            raise ValueError(f"Profile field '{field}' must be a list, got {type(value).__name__}")
        for i, item in enumerate(value):
            if not isinstance(item, str):
                raise ValueError(
                    f"Profile field '{field}[{i}]' must be a string, got {type(item).__name__}"
                )
        if field in _NON_EMPTY_LIST_FIELDS and not value:
            raise ValueError(f"Profile field '{field}' must not be an empty list")

    for str_field in ("name", "description"):
        if str_field in data and not isinstance(data[str_field], str):
            raise ValueError(
                f"Profile field '{str_field}' must be a string, got {type(data[str_field]).__name__}"
            )

    if "version" in data and data["version"] is not None and not isinstance(data["version"], str):
        raise ValueError(
            f"Profile field 'version' must be a string or null, got {type(data['version']).__name__}"
        )

    if "checklist_guidance" in data:
        cg = data["checklist_guidance"]
        if not isinstance(cg, dict):
            raise ValueError(
                f"Profile field 'checklist_guidance' must be an object, got {type(cg).__name__}"
            )
        if "evidence_categories" in cg:
            ec = cg["evidence_categories"]
            if not isinstance(ec, list):
                raise ValueError(
                    "Profile field 'checklist_guidance.evidence_categories' must be a list, "
                    f"got {type(ec).__name__}"
                )
            for i, item in enumerate(ec):
                if not isinstance(item, str):
                    raise ValueError(
                        f"Profile field 'checklist_guidance.evidence_categories[{i}]' "
                        f"must be a string, got {type(item).__name__}"
                    )


def load_profile(name: str) -> dict:
    """Load and validate a named profile from profiles/<name>.json.

    Raises:
        FileNotFoundError — profile file does not exist
        ValueError        — path separators in name, non-object JSON, unknown fields,
                            missing required fields, type errors, or name mismatch
    """
    if "/" in name or "\\" in name:
        raise ValueError(f"Profile name must not contain path separators: '{name}'")

    profile_path = _PROFILES_DIR / f"{name}.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    with open(profile_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Profile must be a JSON object, got {type(raw).__name__}")

    unknown = set(raw.keys()) - _ALL_KNOWN_FIELDS
    if unknown:
        raise ValueError(f"Unknown profile fields: {sorted(unknown)}")

    missing = REQUIRED_FIELDS - set(raw.keys())
    if missing:
        raise ValueError(f"Missing required profile fields: {sorted(missing)}")

    _validate_types(raw)

    if raw["name"] != name:
        raise ValueError(
            f"Profile name mismatch: file is '{name}.json' but name field is '{raw['name']}'"
        )

    return {**copy.deepcopy(_OPTIONAL_DEFAULTS), **raw}


def default_profile() -> dict:
    """Return the cybersecurity profile. Used when --profile is not specified."""
    return load_profile("cybersecurity")


def list_profiles() -> list[str]:
    """Return sorted names of all profiles found in the profiles/ directory."""
    return sorted(p.stem for p in _PROFILES_DIR.glob("*.json") if p.is_file())
