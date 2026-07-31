"""Unit tests for core/artifact_resolver.py (WP-24.2).

Enriched-over-normalized preference and latest-run-wins resolution, shared by
services/checklist_service.py (single doc_key) and cli/reqbot.py's cmd_reindex
(bulk enumeration).
"""
import os
import time
from pathlib import Path

import pytest

from core.artifact_resolver import (
    doc_key_from_extracted_path,
    doc_key_from_requirements_path,
    resolve_latest_requirement_files,
    resolve_requirement_file,
)


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


def test_prefers_gated_over_enriched_and_normalized_in_same_run(tmp_path):
    # WP-35.4: gated is enriched output that additionally passed the
    # description-grounding check -- strictly more trustworthy when present.
    run_dir = tmp_path / "NIST.SP.800-53_20260101_000000"
    normalized = run_dir / "NIST.SP.800-53_requirements_normalized.jsonl"
    enriched = run_dir / "NIST.SP.800-53_requirements_enriched.jsonl"
    gated = run_dir / "NIST.SP.800-53_requirements_gated.jsonl"
    _write(normalized)
    _write(enriched)
    _write(gated)

    result = resolve_latest_requirement_files(tmp_path)

    assert result["NIST.SP.800-53"] == gated


def test_falls_back_to_enriched_when_gated_absent(tmp_path):
    run_dir = tmp_path / "NIST.SP.800-53_20260101_000000"
    enriched = run_dir / "NIST.SP.800-53_requirements_enriched.jsonl"
    _write(enriched)

    result = resolve_latest_requirement_files(tmp_path)

    assert result["NIST.SP.800-53"] == enriched


def test_falls_back_to_enriched_when_gated_is_stale_within_same_run(tmp_path):
    # Codex review, PR #169: a run directory can be reused across multiple
    # invocations (e.g. `--skip-to D --skip-description-gate`, or a failed
    # Step D.6) -- if that rerun regenerates enriched without regenerating
    # gated, the old gated file now describes a stale, inconsistent version
    # of the data and must not be preferred just because it's a "better" tier.
    run_dir = tmp_path / "NIST.SP.800-53_20260101_000000"
    gated = run_dir / "NIST.SP.800-53_requirements_gated.jsonl"
    enriched = run_dir / "NIST.SP.800-53_requirements_enriched.jsonl"
    _write(gated)
    _age(gated, seconds_ago=100)
    _write(enriched)  # regenerated after gated, by a rerun that skipped D.6

    result = resolve_latest_requirement_files(tmp_path)

    assert result["NIST.SP.800-53"] == enriched


def test_falls_back_to_normalized_when_both_gated_and_enriched_are_stale(tmp_path):
    run_dir = tmp_path / "NIST.SP.800-53_20260101_000000"
    gated = run_dir / "NIST.SP.800-53_requirements_gated.jsonl"
    enriched = run_dir / "NIST.SP.800-53_requirements_enriched.jsonl"
    normalized = run_dir / "NIST.SP.800-53_requirements_normalized.jsonl"
    _write(gated)
    _write(enriched)
    _age(gated, seconds_ago=100)
    _age(enriched, seconds_ago=100)
    _write(normalized)  # regenerated after both -- a plain --skip-to D rerun

    result = resolve_latest_requirement_files(tmp_path)

    assert result["NIST.SP.800-53"] == normalized


def test_newer_enriched_beats_older_gated_across_runs(tmp_path):
    old_run = tmp_path / "NIST.SP.800-53_20250101_000000"
    new_run = tmp_path / "NIST.SP.800-53_20260101_000000"
    old_gated = old_run / "NIST.SP.800-53_requirements_gated.jsonl"
    new_enriched = new_run / "NIST.SP.800-53_requirements_enriched.jsonl"
    _write(old_gated)
    _write(new_enriched)
    _age(old_gated, seconds_ago=1000)
    _age(new_enriched, seconds_ago=10)

    result = resolve_latest_requirement_files(tmp_path)

    # A newer enriched file from a later run beats an older gated file from a
    # previous run -- "latest run wins" still dominates preference.
    assert result["NIST.SP.800-53"] == new_enriched


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


# ---------------------------------------------------------------------------
# doc_key_from_requirements_path / doc_key_from_extracted_path — anchored
# suffix stripping, not a broad substring replace (Codex PR #92 review)
# ---------------------------------------------------------------------------

def test_doc_key_from_requirements_path_handles_embedded_suffix_substring():
    # PDF literally named "policy_requirements_normalized_v1.pdf" — the
    # substring "_requirements_normalized" appears once mid-stem and once as
    # the real trailing suffix. Only the trailing one may be stripped.
    path = Path("policy_requirements_normalized_v1_requirements_normalized.jsonl")
    assert doc_key_from_requirements_path(path) == "policy_requirements_normalized_v1"


def test_doc_key_from_requirements_path_enriched_suffix():
    path = Path("AFI17-101_requirements_enriched.jsonl")
    assert doc_key_from_requirements_path(path) == "AFI17-101"


def test_doc_key_from_requirements_path_gated_suffix():
    path = Path("AFI17-101_requirements_gated.jsonl")
    assert doc_key_from_requirements_path(path) == "AFI17-101"


def test_doc_key_from_extracted_path_handles_embedded_suffix_substring():
    # PDF literally named "policy_extracted_requirements_v1.pdf".
    path = Path("policy_extracted_requirements_v1_extracted_requirements.jsonl")
    assert doc_key_from_extracted_path(path) == "policy_extracted_requirements_v1"


def test_doc_key_from_extracted_path_normal_case():
    path = Path("AFI17-101_extracted_requirements.jsonl")
    assert doc_key_from_extracted_path(path) == "AFI17-101"
