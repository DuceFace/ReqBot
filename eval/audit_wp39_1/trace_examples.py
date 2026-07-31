#!/usr/bin/env python3
"""WP-39.1: trace the 18 known FRAGMENT examples (orphaned_list_item + dangling_clause,
from eval/audit_wp38_1/labeled_failures.jsonl) through every pipeline stage's actual
on-disk artifacts, to find exactly where parent-stem/main-clause context is present
or already lost.

Joins labeled_failures.jsonl (category/subtype labels) with unbiased_sample.jsonl
(chunk_id, source_pdf, document_id, document_hash_full -- the fields needed to trace)
by requirement_id, per docs/PHASE39_REQUIREMENTS.md's WP-39.1 Scope.

For each example, prints:
  - the label (subtype) and source_quote
  - the full chunk's raw_text (Step B output -- what Step C's own LLM input contained)
  - the chunk's parent_header_text / parent_context (section_parser.py's ancestry)
  - every Step C output record sharing the same chunk_id (extracted_requirements.jsonl)

This is a real, hand-verifiable trace -- not an automated present/absent classifier --
matching WP-38.1's own hand-audit discipline. Output is read and classified by hand,
not scored mechanically, because "is the parent stem present" requires judgment the
same way WP-38.1's category labels did.
"""
import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.artifact_resolver import resolve_requirement_file

PROCESSED_DIR = Path.home() / "documents" / "processed"
FIXTURE_DIR = _ROOT / "eval" / "audit_wp38_1"


def verify_corpus_against_manifest() -> None:
    """Fail loudly if the local corpus has drifted from what
    eval/audit_wp38_1/source_manifest.json was built from -- a re-ingest since then
    can reassign chunk_id values, silently invalidating every downstream trace
    (Codex review, PR #183: this check was described in docs/PHASE39_REQUIREMENTS.md's
    Scope but never actually implemented in this script -- fixed here)."""
    with open(FIXTURE_DIR / "source_manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)

    drifted = []
    for doc_key, info in manifest["documents"].items():
        try:
            req_path = resolve_requirement_file(PROCESSED_DIR, doc_key)
        except ValueError:
            drifted.append(f"{doc_key}: no longer resolvable under {PROCESSED_DIR}")
            continue
        if req_path.name != info["source_file"]:
            drifted.append(f"{doc_key}: latest file is now {req_path.name!r}, manifest has {info['source_file']!r}")
            continue
        actual_hash = hashlib.sha256(req_path.read_bytes()).hexdigest()
        if actual_hash != info["sha256"]:
            drifted.append(f"{doc_key}: sha256 changed since the fixture was built (re-ingested?) -- {req_path}")

    if drifted:
        raise SystemExit(
            "Local corpus has drifted from eval/audit_wp38_1/source_manifest.json -- "
            "chunk_id values in unbiased_sample.jsonl are no longer guaranteed to match "
            "the current on-disk chunks for the affected document(s). Re-match affected "
            "records by document_hash_full + exact source_quote text before trusting any "
            "chunk_id lookup, per this WP's Scope. Drifted:\n  " + "\n  ".join(drifted)
        )


def load_targets() -> dict:
    labels = {}
    with open(FIXTURE_DIR / "labeled_failures.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec["category"] == "FRAGMENT" and rec["subtype"] in (
                "orphaned_list_item", "dangling_clause",
            ):
                labels[rec["requirement_id"]] = rec

    full = {}
    with open(FIXTURE_DIR / "unbiased_sample.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec["requirement_id"] in labels:
                full[rec["requirement_id"]] = rec

    missing = set(labels) - set(full)
    if missing:
        raise SystemExit(f"labeled targets missing from unbiased_sample.jsonl: {missing}")

    merged = {}
    for rid, label_rec in labels.items():
        merged[rid] = {**full[rid], "subtype": label_rec["subtype"]}
    return merged


def resolve_doc_dir(doc_key: str) -> Path:
    """Use the same 'latest run, best tier' resolver reindex/generate_samples.py use --
    not a lexicographic-last glob (Codex review, PR #183: a plain directory-name sort
    doesn't agree with 'latest' in every case and never cross-checked source_manifest.json
    at all; verify_corpus_against_manifest() now does that check before this is called)."""
    return resolve_requirement_file(PROCESSED_DIR, doc_key).parent


def load_chunk(doc_dir: Path, doc_key: str, chunk_id: int) -> dict | None:
    path = doc_dir / f"{doc_key}_chunks.jsonl"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec["chunk_id"] == chunk_id:
                return rec
    return None


def load_step_c_records(doc_dir: Path, doc_key: str, chunk_id: int) -> list[dict]:
    path = doc_dir / f"{doc_key}_extracted_requirements.jsonl"
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("chunk_id") == chunk_id:
                out.append(rec)
    return out


def main():
    verify_corpus_against_manifest()
    targets = load_targets()
    print(f"Tracing {len(targets)} known FRAGMENT examples\n{'=' * 100}\n")

    # _doc_key/source_quote are unconditionally set by generate_samples.py for every
    # record in unbiased_sample.jsonl (confirmed directly: 0/1872 missing either field
    # today) -- but this script is a committed, reusable artifact, not a one-off, so
    # fail loudly with a clear message rather than a bare KeyError/AttributeError if
    # the fixture is ever regenerated without them (Gemini review, PR #183).
    def sort_key(kv):
        rid, rec = kv
        doc_key = rec.get("_doc_key")
        if not doc_key:
            raise SystemExit(f"{rid}: missing _doc_key in unbiased_sample.jsonl record")
        return (rec["subtype"], doc_key)

    for rid, rec in sorted(targets.items(), key=sort_key):
        doc_key = rec["_doc_key"]
        chunk_id = rec["chunk_id"]
        doc_dir = resolve_doc_dir(doc_key)
        target_quote = (rec.get("source_quote") or "").strip()

        print(f"### {rid}  [{rec['subtype']}]  doc={doc_key}  chunk_id={chunk_id}")
        print(f"source_quote: {rec['source_quote']!r}")
        print()

        chunk = load_chunk(doc_dir, doc_key, chunk_id)
        if chunk is None:
            print(f"!! chunk_id={chunk_id} NOT FOUND in {doc_key}_chunks.jsonl")
        else:
            print("--- chunk raw_text ---")
            print(chunk["raw_text"])
            print()
            print(f"parent_header_text: {chunk['parent_header_text']!r}")
            print(f"parent_context: {(chunk['parent_context'] or '')[:200]!r}")

        print()
        step_c = load_step_c_records(doc_dir, doc_key, chunk_id)
        print(f"--- Step C output for this chunk ({len(step_c)} candidate records) ---")
        for c in step_c:
            candidate_quote = (c.get("source_quote") or "").strip()
            marker = " <== THIS EXAMPLE" if candidate_quote == target_quote else ""
            print(f"  {c.get('requirement_id')}: {c.get('source_quote', '')[:110]!r}{marker}")

        print(f"\n{'=' * 100}\n")


if __name__ == "__main__":
    main()
