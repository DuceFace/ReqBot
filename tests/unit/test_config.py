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
