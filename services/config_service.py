"""Config service — read/write access to ~/.config/reqbot/config.json.

Single shared write path for both `cli/reqbot.py`'s `cmd_init()` and the
settings API (`api/routes/config.py`), matching this project's rule that CLI
and API never each maintain their own copy of a mutation (WP-29.3).

Field-level write restrictions (e.g. hiding `processed_dir`/`authority_registry`
from the settings screen) are enforced one layer up, in the API route's
Pydantic request model — `update_config()` here accepts any field `cmd_init()`
itself needs to persist.
"""
import dataclasses
import json
import os

from core import config as _config

# The set of keys actually persisted to config.json — mirrors _config._DEFAULTS,
# not core.config.ReqBotConfig's full field list. `authority` is deliberately
# excluded: it's computed at load time from a separate authority.json registry,
# never written into config.json itself.
_WRITABLE_FIELDS = set(_config._DEFAULTS)


def get_config() -> dict:
    """Return effective config values plus which fields are currently env-overridden.

    env_overridden lists fields whose effective value came from a REQBOT_* env
    var this process run, per core.config._ENV_MAP — those values win over
    config.json until the env var is unset, so the settings screen needs to
    know which fields it would be futile to edit.
    """
    cfg = _config.load()
    env_overridden = sorted(
        key for key, env_var in _config._ENV_MAP.items()
        if os.environ.get(env_var) is not None
    )
    return {
        "config": dataclasses.asdict(cfg),
        "env_overridden": env_overridden,
    }


def update_config(partial: dict) -> dict:
    """Partial-merge `partial` into config.json and write it back.

    Reads the current config.json (or the hardcoded defaults if the file
    doesn't exist yet), overlays only the keys present in `partial`, and
    writes the result back with the same chmod(0o600) restrictive
    permissions `cmd_init()` already uses. Never touches keys it wasn't
    given, so callers can save a single field without knowing every other
    field's current value.

    Raises ValueError if `partial` contains a key that isn't a real config
    field (typo protection — actual value validation/bounds enforcement is
    the API route's job, not this shared service's).
    """
    unknown = set(partial) - _WRITABLE_FIELDS
    if unknown:
        raise ValueError(f"Unknown config field(s): {', '.join(sorted(unknown))}")

    if _config.CONFIG_PATH.exists():
        try:
            current = json.loads(_config.CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            current = dict(_config._DEFAULTS)
    else:
        current = dict(_config._DEFAULTS)

    current.update(partial)

    _config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _config.CONFIG_PATH.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    _config.CONFIG_PATH.chmod(0o600)

    return get_config()
