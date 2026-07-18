"""Profile loader for domain-specific pipeline configuration.

Profiles live in profiles/<name>.json at the repo root.
The loader validates required fields, applies defaults for optional fields,
and fails fast with a clear error on unknown or malformed input.
"""

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


def load_profile(name: str) -> dict:
    """Load and validate a named profile from profiles/<name>.json.

    Raises:
        FileNotFoundError — profile file does not exist
        ValueError        — unknown fields, missing required fields, or name mismatch
    """
    profile_path = _PROFILES_DIR / f"{name}.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    with open(profile_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    unknown = set(data.keys()) - _ALL_KNOWN_FIELDS
    if unknown:
        raise ValueError(f"Unknown profile fields: {sorted(unknown)}")

    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required profile fields: {sorted(missing)}")

    if data["name"] != name:
        raise ValueError(
            f"Profile name mismatch: file is '{name}.json' but name field is '{data['name']}'"
        )

    return {**_OPTIONAL_DEFAULTS, **data}


def default_profile() -> dict:
    """Return the cybersecurity profile. Used when --profile is not specified."""
    return load_profile("cybersecurity")
