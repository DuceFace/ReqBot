#!/usr/bin/env python3
"""WP-38.1: generate the two audit samples (discovery pool + unbiased prevalence
sample) from the current, freshest-per-document requirements files.

Uses core.artifact_resolver.resolve_latest_requirement_files() — the same
"latest run, best tier" resolution reindex itself uses — so this audit reads
exactly what the live pipeline currently produces per document, not stale or
hand-picked files.

Two outputs, written under eval/audit_wp38_1/:
  - discovery_candidates.jsonl: heuristic-narrowed pool, for *finding* examples
    of each failure shape efficiently. NOT used for the prevalence number.
  - unbiased_sample.jsonl: stratified-by-document random sample, independent
    of the discovery heuristic, used for the actual prevalence estimate.
"""
import hashlib
import json
import random
from pathlib import Path

from core.artifact_resolver import resolve_latest_requirement_files

SEED = 3801  # fixed for reproducibility (Phase 38, WP-1)
TARGET_SAMPLE_SIZE = 320
MIN_PER_DOC = 15

OUT_DIR = Path(__file__).parent


def load_records(path: Path, doc_key: str) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rec["_doc_key"] = doc_key
            rec["_source_file"] = str(path)
            records.append(rec)
    return records


def is_discovery_candidate(rec: dict) -> list[str]:
    """Return the list of heuristic signals that fired (empty = not a candidate)."""
    quote = (rec.get("source_quote") or "").strip()
    if not quote:
        return []
    words = quote.split()
    word_count = len(words)
    signals = []

    if word_count <= 8:
        signals.append("short_quote")

    if not quote.rstrip().endswith((".", "!", "?", ";")):
        signals.append("no_terminal_punctuation")

    if quote.isupper() and word_count <= 10:
        signals.append("all_caps_short")
    elif quote.istitle() and word_count <= 6:
        signals.append("title_case_short")

    definition_openers = (
        "this section", "the term", "for purposes of", "for the purpose of",
        "definitions", "means ", " means", "refers to", "is defined as",
        "as used in this",
    )
    ql = quote.lower()
    if any(ql.startswith(o) or o in ql[:40] for o in definition_openers):
        signals.append("definition_opener")

    return signals


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main():
    random.seed(SEED)
    files = resolve_latest_requirement_files(Path.home() / "documents" / "processed")
    print(f"Resolved {len(files)} documents (latest run, best tier):")

    all_records = []
    per_doc_counts = {}
    manifest_docs = {}
    for doc_key, path in sorted(files.items()):
        recs = load_records(path, doc_key)
        all_records.extend(recs)
        per_doc_counts[doc_key] = len(recs)
        manifest_docs[doc_key] = {
            "source_file": path.name,
            "record_count": len(recs),
            "sha256": _sha256_file(path),
        }
        print(f"  {doc_key:30s} {path.name:45s} {len(recs)}")

    total = len(all_records)
    print(f"\nTotal records across {len(files)} documents: {total}")

    # Source population isn't committed to the repo (it lives outside it, in
    # ~/documents/processed, and can change on re-ingest) -- a manifest of
    # per-document file names, record counts, and content hashes at least lets
    # a future reader verify whether their local corpus matches the one this
    # audit actually drew from, even without the raw population itself being
    # pinned in git (Codex review, PR #180).
    with open(OUT_DIR / "source_manifest.json", "w") as f:
        json.dump({
            "seed": SEED,
            "total_records": total,
            "documents": manifest_docs,
        }, f, indent=2, sort_keys=True)

    # --- Discovery pool: heuristic-narrowed, full corpus ---
    discovery = []
    for rec in all_records:
        signals = is_discovery_candidate(rec)
        if signals:
            rec_out = dict(rec)
            rec_out["_signals"] = signals
            discovery.append(rec_out)
    print(f"Discovery pool: {len(discovery)} candidates ({len(discovery) / total:.1%} of corpus)")

    with open(OUT_DIR / "discovery_candidates.jsonl", "w") as f:
        for rec in discovery:
            f.write(json.dumps(rec) + "\n")

    # --- Unbiased sample: stratified by document, independent of discovery heuristic ---
    # Proportional allocation with a floor per doc, scaled to hit ~TARGET_SAMPLE_SIZE.
    raw_alloc = {
        k: max(MIN_PER_DOC, round(TARGET_SAMPLE_SIZE * (v / total)))
        for k, v in per_doc_counts.items()
    }
    # Cap each doc's allocation at its own record count (can't sample more than exists).
    alloc = {k: min(v, per_doc_counts[k]) for k, v in raw_alloc.items()}

    by_doc: dict[str, list[dict]] = {}
    for rec in all_records:
        by_doc.setdefault(rec["_doc_key"], []).append(rec)

    all_chosen = []
    for doc_key, n in sorted(alloc.items()):
        pool = by_doc[doc_key]
        chosen = random.sample(pool, n)
        all_chosen.extend(chosen)

    with open(OUT_DIR / "unbiased_sample.jsonl", "w") as f:
        for rec in all_chosen:
            f.write(json.dumps(rec) + "\n")

    print(f"\nUnbiased stratified sample: {len(all_chosen)} records across {len(alloc)} documents")
    for doc_key, n in sorted(alloc.items()):
        print(f"  {doc_key:30s} {n} / {per_doc_counts[doc_key]}")
    print(f"\nSeed used: {SEED} (reproducible)")


if __name__ == "__main__":
    main()
