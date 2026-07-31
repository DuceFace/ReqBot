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
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PROCESSED_DIR = Path.home() / "documents" / "processed"
FIXTURE_DIR = _ROOT / "eval" / "audit_wp38_1"


def load_targets() -> dict:
    labels = {}
    with open(FIXTURE_DIR / "labeled_failures.jsonl", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["category"] == "FRAGMENT" and rec["subtype"] in (
                "orphaned_list_item", "dangling_clause",
            ):
                labels[rec["requirement_id"]] = rec

    full = {}
    with open(FIXTURE_DIR / "unbiased_sample.jsonl", encoding="utf-8") as f:
        for line in f:
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
    candidates = sorted(PROCESSED_DIR.glob(f"{doc_key}_*"))
    if not candidates:
        raise SystemExit(f"No processed directory found for doc_key={doc_key!r}")
    return candidates[-1]


def load_chunk(doc_dir: Path, doc_key: str, chunk_id: int) -> dict | None:
    path = doc_dir / f"{doc_key}_chunks.jsonl"
    with open(path, encoding="utf-8") as f:
        for line in f:
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
            rec = json.loads(line)
            if rec.get("chunk_id") == chunk_id:
                out.append(rec)
    return out


def main():
    targets = load_targets()
    print(f"Tracing {len(targets)} known FRAGMENT examples\n{'=' * 100}\n")

    for rid, rec in sorted(targets.items(), key=lambda kv: (kv[1]["subtype"], kv[1]["_doc_key"])):
        doc_key = rec["_doc_key"]
        chunk_id = rec["chunk_id"]
        doc_dir = resolve_doc_dir(doc_key)

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
            marker = " <== THIS EXAMPLE" if c.get("source_quote", "").strip() == rec["source_quote"].strip() else ""
            print(f"  {c.get('requirement_id')}: {c.get('source_quote', '')[:110]!r}{marker}")

        print(f"\n{'=' * 100}\n")


if __name__ == "__main__":
    main()
