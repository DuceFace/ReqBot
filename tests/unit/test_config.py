import json

import pytest

import core.config as cfg


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    """Redirect config paths and strip all REQBOT_* env vars for every test."""
    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "no_config.json")
    monkeypatch.setattr(cfg, "AUTHORITY_REGISTRY_PATH", tmp_path / "no_authority.json")
    for env_var in cfg._ENV_MAP.values():
        monkeypatch.delenv(env_var, raising=False)


def test_defaults_load_without_config_file():
    c = cfg.load()
    assert c.ollama_url == "http://localhost:11434"
    assert c.qdrant_url == "http://localhost:6333"
    assert c.top_k == 20
    assert c.min_score == 0.02
    assert c.synthesis_backend == "local"


def test_config_file_values_override_defaults(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"ollama_url": "http://custom:11434", "top_k": 5}))
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)
    c = cfg.load()
    assert c.ollama_url == "http://custom:11434"
    assert c.top_k == 5
    assert c.qdrant_url == "http://localhost:6333"  # unchanged default


def test_env_var_overrides_config_file(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"ollama_url": "http://from-file:11434"}))
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)
    monkeypatch.setenv("REQBOT_OLLAMA_URL", "http://from-env:11434")
    c = cfg.load()
    assert c.ollama_url == "http://from-env:11434"


def test_unknown_env_var_does_not_crash(monkeypatch):
    monkeypatch.setenv("REQBOT_TOTALLY_UNKNOWN_KEY_XYZ", "ignored")
    c = cfg.load()
    assert c.ollama_url == "http://localhost:11434"


def test_processed_dir_path_is_absolute():
    c = cfg.load()
    assert c.processed_dir_path().is_absolute()


def test_extraction_enrichment_fallback_to_default():
    c = cfg.load()
    assert c.extraction_model == c.default_model
    assert c.enrichment_model == c.default_model


def test_rewrite_model_fallback_to_default():
    c = cfg.load()
    assert c.rewrite_model == c.default_model


def test_rewrite_model_config_file_and_env_var(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"rewrite_model": "from-file-model"}))
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)
    c = cfg.load()
    assert c.rewrite_model == "from-file-model"

    monkeypatch.setenv("REQBOT_REWRITE_MODEL", "from-env-model")
    c = cfg.load()
    assert c.rewrite_model == "from-env-model"


def test_embedding_model_default_is_nomic_embed_text():
    c = cfg.load()
    assert c.embedding_model == "nomic-embed-text"


def test_embedding_model_does_not_fall_back_to_default_model(monkeypatch, tmp_path):
    """embedding_model is independent of default_model (WP-25.6c) — unlike
    extraction/enrichment/rewrite, it must never silently inherit a
    default_model change."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"default_model": "some-other-model"}))
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)
    c = cfg.load()
    assert c.default_model == "some-other-model"
    assert c.embedding_model == "nomic-embed-text"


def test_embedding_model_config_file_and_env_var(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"embedding_model": "from-file-model"}))
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)
    c = cfg.load()
    assert c.embedding_model == "from-file-model"

    monkeypatch.setenv("REQBOT_EMBEDDING_MODEL", "from-env-model")
    c = cfg.load()
    assert c.embedding_model == "from-env-model"


def test_api_key_env_defaults_to_anthropic_api_key():
    c = cfg.load()
    assert c.api_key_env == "ANTHROPIC_API_KEY"


def test_api_key_env_explicit_null_in_config_file_normalizes_to_default(monkeypatch, tmp_path):
    """Phase 27, WP-27.2: api_key_env has no REQBOT_* env mapping, so a
    hand-edited config.json is the only way it gets set. `values.get(key,
    default)` only applies the default when the key is ABSENT -- an explicit
    `null` in the file previously survived as None, and downstream
    os.environ.get(None, "") calls (evidence route/CLI/MCP) would raise
    TypeError instead of falling back to the local synthesis backend."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"api_key_env": None}))
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)
    c = cfg.load()
    assert c.api_key_env == "ANTHROPIC_API_KEY"


def test_api_key_env_config_file_value_respected(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"api_key_env": "OPENAI_API_KEY"}))
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)
    c = cfg.load()
    assert c.api_key_env == "OPENAI_API_KEY"


def test_remote_model_defaults_to_claude_sonnet():
    c = cfg.load()
    assert c.remote_model == "claude-sonnet-4-6"


def test_remote_model_explicit_null_in_config_file_normalizes_to_default(monkeypatch, tmp_path):
    """Consistency fix alongside api_key_env's (Gemini review, PR #120) --
    remote_model had the exact same values.get(key, default) gap."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"remote_model": None}))
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)
    c = cfg.load()
    assert c.remote_model == "claude-sonnet-4-6"


def test_remote_model_config_file_value_respected(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"remote_model": "gpt-4o"}))
    monkeypatch.setattr(cfg, "CONFIG_PATH", config_file)
    c = cfg.load()
    assert c.remote_model == "gpt-4o"
