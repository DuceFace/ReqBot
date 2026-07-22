"""WP-24.3 — confirm --full-extraction and pass1_only are fully removed from
pipeline/run_pipeline.py (the legacy single-pass Step C path had no supported
use case; run() always uses Pass 1 mode now)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pipeline.llm_extract_requirements as llm_extract_requirements
import pipeline.run_pipeline as run_pipeline


def test_full_extraction_flag_removed_from_cli_help(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--help"])
    with pytest.raises(SystemExit):
        run_pipeline.main()
    assert "--full-extraction" not in capsys.readouterr().out


def test_run_pipeline_run_no_longer_accepts_pass1_only_kwarg(tmp_path):
    with pytest.raises(TypeError):
        run_pipeline.run(str(tmp_path / "doc.pdf"), str(tmp_path), pass1_only=True)


def test_llm_extract_run_no_longer_accepts_pass1_only_kwarg(tmp_path):
    with pytest.raises(TypeError):
        llm_extract_requirements.run(
            str(tmp_path / "chunks.jsonl"), str(tmp_path), pass1_only=True
        )


def test_legacy_prompt_template_constant_removed():
    assert not hasattr(llm_extract_requirements, "PROMPT_TEMPLATE")
