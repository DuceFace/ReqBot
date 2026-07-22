"""Regression test for parse_and_normalize.py's normalized-filename derivation
(Codex PR #92 follow-up review — sibling of the enrich_requirements.py fix).

A broad `.replace("_extracted_requirements", "")` on the extracted-requirements
JSONL's stem would collapse every occurrence of that substring, not just the
trailing one — so a PDF whose own stem happens to contain
"_extracted_requirements" (e.g. "policy_extracted_requirements_v1.pdf")
produced a mangled normalized filename whose doc_key no longer matched the
real *_chunks.jsonl file, silently breaking context indexing for that
document. The fix reuses core.artifact_resolver.doc_key_from_extracted_path()
(anchored suffix strip) instead.
"""
import json
from pathlib import Path

import pipeline.parse_and_normalize as normalize_mod

_REQ = {
    "source_quote": "Systems shall implement access controls.",
    "source_ref": "T-1",
    "domain_tags": ["access-control"],
    "requirement_type": "policy",
    "description": "",
    "chunk_id": None,
}


def test_normalized_filename_preserves_pdf_stem_containing_extracted_substring(tmp_path):
    # Simulates a PDF literally named "policy_extracted_requirements_v1.pdf" —
    # the resulting extracted-requirements JSONL's stem contains
    # "_extracted_requirements" twice: once as part of the original filename,
    # once as the real suffix.
    stem = "policy_extracted_requirements_v1"
    reqs_file = tmp_path / f"{stem}_extracted_requirements.jsonl"
    reqs_file.write_text(json.dumps(_REQ) + "\n", encoding="utf-8")

    chunks_file = tmp_path / f"{stem}_chunks.jsonl"
    chunks_file.write_text("", encoding="utf-8")

    out = normalize_mod.run(str(reqs_file), str(chunks_file), "", str(tmp_path))

    # Must preserve the full original stem, not collapse the embedded
    # "_extracted_requirements" substring found earlier in the filename —
    # this is what lets the real *_chunks.jsonl file still be found by doc_key.
    assert Path(out).name == f"{stem}_requirements_normalized.jsonl"
