import json
from pathlib import Path

from pipeline.parse_and_normalize import build_chunk_text_map, compute_stable_id, run


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


SAMPLE_EXTRACTED = {
    "requirement_id": "R-1",
    "source_quote": "Systems must enforce role-based access control policies.",
    "source_ref": "1.1",
    "description": "Enforce role-based access control for all system users.",
    "requirement_type": "technical-control",
    "domain_tags": ["access-control"],
    "chunk_id": None,
    "confidence": 0.9,
}


def test_stable_id_is_deterministic():
    id1 = compute_stable_id("docabc123", "1.1", "Systems must enforce RBAC.", None, "technical-control", "Enforce RBAC.")
    id2 = compute_stable_id("docabc123", "1.1", "Systems must enforce RBAC.", None, "technical-control", "Enforce RBAC.")
    assert id1 == id2
    assert id1.startswith("REQ-")


def test_stable_id_differs_for_different_quotes():
    id1 = compute_stable_id("doc123", "1.1", "Quote A here.", None, "technical-control", "Desc A")
    id2 = compute_stable_id("doc123", "1.1", "Quote B here.", None, "technical-control", "Desc B")
    assert id1 != id2


def test_dedup_collapses_exact_quote(tmp_path):
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    _write_jsonl(req_path, [SAMPLE_EXTRACTED, SAMPLE_EXTRACTED])
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    records = _read_jsonl(out_dir / "test_requirements_normalized.jsonl")
    assert len(records) == 1


def test_source_quote_required_gate(tmp_path):
    req = dict(SAMPLE_EXTRACTED, source_quote="")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    _write_jsonl(req_path, [req])
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["error"] == "empty_source_quote"


def test_hierarchy_fields_populated(tmp_path):
    chunk = {
        "chunk_id": 42,
        "page_start": 1, "page_end": 2,
        # Must actually contain SAMPLE_EXTRACTED's source_quote (WP-32.1's grounding
        # check) -- this test verifies hierarchy metadata propagation, not grounding,
        # so the chunk text just needs to be realistic enough not to trip that check.
        "text": "1.1 Systems must enforce role-based access control policies.",
        "section_ref_path": ["1", "1.1"],
        "section_title_path": ["Access Control", "Auth Requirements"],
        "parent_header_text": "Access Control",
        "parent_context": "Section 1. Access Control. All systems must enforce RBAC.",
        "document_id": "abc123",
        "source_pdf": "TEST.pdf",
    }
    req = dict(SAMPLE_EXTRACTED, chunk_id=42)
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [chunk])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    records = _read_jsonl(out_dir / "test_requirements_normalized.jsonl")
    assert len(records) == 1
    r = records[0]
    assert r["section_ref_path"] == ["1", "1.1"]
    assert r["section_title_path"] == ["Access Control", "Auth Requirements"]
    assert r["parent_section_ref"] == "1"
    assert r["parent_context"] == "Section 1. Access Control. All systems must enforce RBAC."


def test_optional_hierarchy_defaults_to_empty(tmp_path):
    req = dict(SAMPLE_EXTRACTED, chunk_id=None)
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    _write_jsonl(req_path, [req])
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    records = _read_jsonl(out_dir / "test_requirements_normalized.jsonl")
    assert len(records) == 1
    r = records[0]
    assert r["section_ref_path"] == []
    assert r["section_title_path"] == []
    assert r["parent_section_ref"] is None
    assert r["parent_context"] is None
    assert r["child_section_refs"] == []


def test_empty_input_produces_empty_output(tmp_path):
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    req_path.write_text("")
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []


def test_all_records_missing_source_quote(tmp_path):
    reqs = [dict(SAMPLE_EXTRACTED, source_quote="") for _ in range(3)]
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    _write_jsonl(req_path, reqs)
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 3


# WP-32.1: build_chunk_text_map + the quote-grounding gate in run(). See
# docs/PHASE32_REQUIREMENTS.md for the corpus-wide investigation (21.55% of
# indexed requirements failed this check; confirmed genuine Step C fabrication,
# not a chunking bug) that motivated this and ruled out exact-substring matching
# in favor of fuzz.partial_ratio.

def test_build_chunk_text_map():
    chunks = [
        {"chunk_id": 1, "text": "First chunk text."},
        {"chunk_id": 2, "text": "Second chunk text."},
    ]
    assert build_chunk_text_map(chunks) == {1: "First chunk text.", 2: "Second chunk text."}


def _chunk(chunk_id: int, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "page_start": 1, "page_end": 1,
        "text": text,
        "section_ref_path": [], "section_title_path": [],
        "parent_header_text": None, "parent_context": None,
        "document_id": "abc123", "source_pdf": "TEST.pdf",
    }


def test_grounded_quote_passes(tmp_path):
    chunk_text = "3.2.1 All systems shall enforce role-based access control policies for every user."
    req = dict(SAMPLE_EXTRACTED, chunk_id=1, source_quote="Systems must enforce role-based access control policies.")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, chunk_text)])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert len(_read_jsonl(out_dir / "test_requirements_normalized.jsonl")) == 1
    assert _read_jsonl(out_dir / "test_normalization_failures.jsonl") == []


def test_reformatted_quote_still_passes(tmp_path):
    # Reproduces the WP-32.1 calibration finding: tabular/reflowed source text
    # (e.g. NIST.SP.800-53Ar5's assessment-procedure tables) can reformat a real
    # quote enough that exact substring matching would wrongly reject it.
    chunk_text = "AU-16(2)  Cross-Organizational Auditing.  Sharing of Audit Information."
    req = dict(SAMPLE_EXTRACTED, chunk_id=1, source_quote="Cross-Organizational Auditing | Sharing of Audit Information.")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, chunk_text)])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert len(_read_jsonl(out_dir / "test_requirements_normalized.jsonl")) == 1


def test_fabricated_quote_rejected(tmp_path):
    # Reproduces the exact confirmed WP-32.1 case: chunk text is an unrelated
    # document introduction, quote is fabricated password-policy content that
    # doesn't appear anywhere in it.
    chunk_text = (
        "An information system is a discrete set of information resources "
        "organized for the collection, processing, maintenance, use, sharing, "
        "dissemination, or disposition of information."
    )
    req = dict(
        SAMPLE_EXTRACTED, chunk_id=1,
        source_quote="shall conform to NIST SP 800-63B guidelines. Minimum password length is 12 characters.",
    )
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, chunk_text)])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["error"] == "quote_not_grounded_in_chunk"
    assert "grounding_score" in failures[0]


def test_missing_chunk_passes_through_unchecked(tmp_path):
    # chunk_id 999 doesn't exist in chunks.jsonl -- can't verify, so don't reject.
    req = dict(SAMPLE_EXTRACTED, chunk_id=999, source_quote="Completely unverifiable quote text.")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, "Some unrelated chunk text.")])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert len(_read_jsonl(out_dir / "test_requirements_normalized.jsonl")) == 1
