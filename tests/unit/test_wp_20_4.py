"""WP-20.4: domain_profile field in normalized JSONL and Qdrant payload."""
import json
from pathlib import Path

from core.profiles import load_profile
from pipeline.embed_and_index import build_payload
from pipeline.parse_and_normalize import run as normalize_run

_CYBER_PROFILE = load_profile("cybersecurity")
_TEST_DOMAIN_PROFILE = load_profile("test-domain")

_BASE_EXTRACTED = {
    "requirement_id": "R-1",
    "source_quote": "Systems must enforce role-based access control policies.",
    "source_ref": "1.1",
    "description": "Enforce role-based access control for all system users.",
    "requirement_type": "technical-control",
    "domain_tags": ["access-control"],
    "chunk_id": None,
    "confidence": 0.9,
}


def _write_jsonl(path: Path, records: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# parse_and_normalize — domain_profile written to JSONL
# ---------------------------------------------------------------------------

def test_normalize_writes_domain_profile_cybersecurity(tmp_path):
    req_path = tmp_path / "doc_extracted_requirements.jsonl"
    _write_jsonl(req_path, [_BASE_EXTRACTED])
    out_dir = tmp_path / "out"
    normalize_run(
        str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir),
        profile=_CYBER_PROFILE,
    )
    records = _read_jsonl(out_dir / "doc_requirements_normalized.jsonl")
    assert len(records) == 1
    assert records[0]["domain_profile"] == "cybersecurity"


def test_normalize_writes_domain_profile_test_domain(tmp_path):
    req = dict(
        _BASE_EXTRACTED,
        domain_tags=["test-tag"],
        requirement_type="test-type",
    )
    req_path = tmp_path / "doc_extracted_requirements.jsonl"
    _write_jsonl(req_path, [req])
    out_dir = tmp_path / "out"
    normalize_run(
        str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir),
        profile=_TEST_DOMAIN_PROFILE,
    )
    records = _read_jsonl(out_dir / "doc_requirements_normalized.jsonl")
    assert len(records) == 1
    assert records[0]["domain_profile"] == "test-domain"


def test_normalize_default_profile_writes_cybersecurity(tmp_path):
    """Omitting profile= (None) must default to cybersecurity and tag records accordingly."""
    req_path = tmp_path / "doc_extracted_requirements.jsonl"
    _write_jsonl(req_path, [_BASE_EXTRACTED])
    out_dir = tmp_path / "out"
    normalize_run(
        str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir),
        # profile not passed — exercises the None → default_profile() path
    )
    records = _read_jsonl(out_dir / "doc_requirements_normalized.jsonl")
    assert len(records) == 1
    assert records[0]["domain_profile"] == "cybersecurity"


# ---------------------------------------------------------------------------
# build_payload — domain_profile in Qdrant payload
# ---------------------------------------------------------------------------

def test_build_payload_includes_domain_profile():
    req = {
        "requirement_id": "REQ-abc123",
        "document_id": "doc1",
        "source_pdf": "test.pdf",
        "source_ref": "1.1",
        "domain_tags": ["access-control"],
        "requirement_type": "technical-control",
        "source_quote": "Systems must enforce RBAC.",
        "description": "Enforce RBAC.",
        "page_start": 1,
        "page_end": 1,
        "confidence": 0.9,
        "chunk_id": 0,
        "section_ref_path": [],
        "section_title_path": [],
        "parent_section_ref": None,
        "parent_context": None,
        "child_section_refs": [],
        "domain_profile": "cybersecurity",
        "schema_version": "1",
        "pipeline_version": "1",
        "extraction_model": "test-model",
        "run_timestamp": "2026-07-18T00:00:00Z",
    }
    payload = build_payload(req, "nomic-embed-text", 768)
    assert payload["domain_profile"] == "cybersecurity"


def test_build_payload_fallback_cybersecurity_for_pre_phase20_records():
    """Records without domain_profile (pre-Phase-20) must return 'cybersecurity', not null."""
    req = {
        "requirement_id": "REQ-legacy",
        "document_id": "doc1",
        "source_pdf": "old.pdf",
        "source_ref": "1.1",
        "domain_tags": [],
        "requirement_type": "",
        "source_quote": "Old requirement text.",
        "description": "An old requirement.",
        "page_start": None,
        "page_end": None,
        "confidence": 0.8,
        "chunk_id": None,
        # No domain_profile key — pre-Phase-20 record
    }
    payload = build_payload(req, "nomic-embed-text", 768)
    assert payload["domain_profile"] == "cybersecurity"
