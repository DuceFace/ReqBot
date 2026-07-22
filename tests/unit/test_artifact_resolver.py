"""Unit tests for core/artifact_resolver.py (WP-24.2).

Enriched-over-normalized preference and latest-run-wins resolution, shared by
services/checklist_service.py (single doc_key) and cli/reqbot.py's cmd_reindex
(bulk enumeration).
"""
import os
import time

import pytest

from core.artifact_resolver import resolve_latest_requirement_files, resolve_requirement_file


def _write(path, document_id="doc-hash-abc"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"document_id": "%s", "requirement_id": "REQ-1"}\n' % document_id)


def _age(path, seconds_ago):
    """Set a file's mtime relative to now so mtime-based tie-breaks are deterministic."""
    t = time.time() - seconds_ago
    os.utime(path, (t, t))


def test_prefers_enriched_over_normalized_in_same_run(tmp_path):
    run_dir = tmp_path / "NIST.SP.800-53_20260101_000000"
    normalized = run_dir / "NIST.SP.800-53_requirements_normalized.jsonl"
    enriched = run_dir / "NIST.SP.800-53_requirements_enriched.jsonl"
    _write(normalized)
    _write(enriched)

    result = resolve_latest_requirement_files(tmp_path)

    assert result["NIST.SP.800-53"] == enriched


def test_falls_back_to_normalized_when_enriched_absent(tmp_path):
    run_dir = tmp_path / "NIST.SP.800-53_20260101_000000"
    normalized = run_dir / "NIST.SP.800-53_requirements_normalized.jsonl"
    _write(normalized)

    result = resolve_latest_requirement_files(tmp_path)

    assert result["NIST.SP.800-53"] == normalized


def test_latest_run_wins_across_multiple_runs(tmp_path):
    old_run = tmp_path / "NIST.SP.800-53_20250101_000000"
    new_run = tmp_path / "NIST.SP.800-53_20260101_000000"
    old_enriched = old_run / "NIST.SP.800-53_requirements_enriched.jsonl"
    new_normalized = new_run / "NIST.SP.800-53_requirements_normalized.jsonl"
    _write(old_enriched)
    _write(new_normalized)
    _age(old_enriched, seconds_ago=1000)
    _age(new_normalized, seconds_ago=10)

    result = resolve_latest_requirement_files(tmp_path)

    # A newer normalized file from a later run beats an older enriched file
    # from a previous run.
    assert result["NIST.SP.800-53"] == new_normalized


def test_multiple_documents_resolved_independently(tmp_path):
    doc_a = tmp_path / "AFI17-101_20260101_000000" / "AFI17-101_requirements_normalized.jsonl"
    doc_b = tmp_path / "CNSSI-1253_20260101_000000" / "CNSSI-1253_requirements_enriched.jsonl"
    _write(doc_a)
    _write(doc_b)

    result = resolve_latest_requirement_files(tmp_path)

    assert set(result.keys()) == {"AFI17-101", "CNSSI-1253"}
    assert result["AFI17-101"] == doc_a
    assert result["CNSSI-1253"] == doc_b


def test_resolve_requirement_file_returns_matching_path(tmp_path):
    run_dir = tmp_path / "AFI17-101_20260101_000000"
    enriched = run_dir / "AFI17-101_requirements_enriched.jsonl"
    _write(enriched)

    assert resolve_requirement_file(tmp_path, "AFI17-101") == enriched


def test_resolve_requirement_file_raises_for_unknown_doc_key(tmp_path):
    with pytest.raises(ValueError, match="no_such_doc"):
        resolve_requirement_file(tmp_path, "no_such_doc")
