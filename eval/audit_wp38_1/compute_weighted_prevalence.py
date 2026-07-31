#!/usr/bin/env python3
"""WP-38.1: compute the population-weighted prevalence estimate.

The unbiased sample uses a MIN_PER_DOC=15 floor (generate_samples.py) so
documents smaller than ~88 records (15 / (320/1872)) are over-represented
relative to their true share of the corpus. Reporting the raw flagged/total
ratio from that sample therefore estimates the *sample's* composition, not
the corpus's -- the same class of mistake as PHASE36_REQUIREMENTS.md's
WP-36.2 finding (Codex review, PR #180). This computes both numbers so the
correction is visible, not silently swapped in.

Reads population counts from the committed source_manifest.json by default,
not from the caller's live ~/documents/processed -- the whole point of
committing that manifest was to make this reproducible from the PR's own
artifacts alone, without depending on a local corpus that may differ or be
missing entirely (Codex review, PR #180: the first version of this script
recomputed live and crashed with KeyError on a machine with a different
corpus). Pass --validate-against-live to additionally re-resolve the live
corpus and confirm its record counts and file hashes still match the
manifest -- optional, and only needed if you suspect local drift.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
FAILURE_CATEGORIES = ("FRAGMENT", "OVER_GRAB")


def _validate_against_live(manifest: dict) -> None:
    import sys

    _root = Path(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from core.artifact_resolver import resolve_latest_requirement_files

    import hashlib

    def sha256_file(path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                hasher.update(block)
        return hasher.hexdigest()

    files = resolve_latest_requirement_files(Path.home() / "documents" / "processed")
    mismatches = []
    for doc_key, meta in manifest["documents"].items():
        live_path = files.get(doc_key)
        if live_path is None:
            mismatches.append(f"{doc_key}: not found in live corpus")
            continue
        with open(live_path, encoding="utf-8") as f:
            live_count = sum(1 for _ in f)
        live_hash = sha256_file(live_path)
        if live_count != meta["record_count"] or live_hash != meta["sha256"]:
            mismatches.append(
                f"{doc_key}: manifest={meta['record_count']} records/{meta['sha256'][:12]}.. "
                f"vs live={live_count} records/{live_hash[:12]}.. ({live_path.name})"
            )
    if mismatches:
        print("VALIDATION FAILED -- local corpus differs from the manifest this audit used:")
        for m in mismatches:
            print(f"  {m}")
    else:
        print(f"Validated: local corpus matches the manifest for all {len(manifest['documents'])} documents.")


def _weighted_and_unweighted(by_doc, population, total_population, categories):
    weighted = 0.0
    total_flagged = 0
    total_n = 0
    for doc_key, recs in by_doc.items():
        n = len(recs)
        flagged = sum(1 for r in recs if r["_category"] in categories)
        weight = population[doc_key] / total_population
        weighted += weight * (flagged / n)
        total_flagged += flagged
        total_n += n
    return total_flagged, total_n, weighted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-against-live", action="store_true",
        help="Also re-resolve ~/documents/processed and confirm it matches source_manifest.json.",
    )
    args = parser.parse_args()

    with open(SCRIPT_DIR / "unbiased_sample.jsonl", encoding="utf-8") as f:
        sample = [json.loads(line) for line in f]
    with open(SCRIPT_DIR / "labeled_failures.jsonl", encoding="utf-8") as f:
        labels = {rec["requirement_id"]: rec["category"] for rec in (json.loads(line) for line in f)}
    for rec in sample:
        rec["_category"] = labels.get(rec["requirement_id"], "REAL")

    manifest = json.loads((SCRIPT_DIR / "source_manifest.json").read_text(encoding="utf-8"))
    if args.validate_against_live:
        _validate_against_live(manifest)

    population = {doc_key: meta["record_count"] for doc_key, meta in manifest["documents"].items()}
    total_population = sum(population.values())

    by_doc = defaultdict(list)
    for rec in sample:
        by_doc[rec["_doc_key"]].append(rec)

    print(f"{'document':30s} {'pop':>6s} {'n':>4s} {'flagged':>7s} {'local_rate':>10s} {'weight':>8s}")
    for doc_key, recs in sorted(by_doc.items()):
        n = len(recs)
        flagged = sum(1 for r in recs if r["_category"] in FAILURE_CATEGORIES)
        weight = population[doc_key] / total_population
        print(f"{doc_key:30s} {population[doc_key]:6d} {n:4d} {flagged:7d} {flagged / n:10.1%} {weight:8.1%}")

    print()
    for label, cats in (
        ("Fragment+Over-grab (headline)", FAILURE_CATEGORIES),
        ("Fragment only", ("FRAGMENT",)),
        ("Over-grab only", ("OVER_GRAB",)),
        ("Judgment-requiring only", ("JUDGMENT",)),
    ):
        flagged, n, weighted = _weighted_and_unweighted(by_doc, population, total_population, cats)
        print(f"{label:32s} unweighted={flagged}/{n}={flagged / n:.1%}   weighted={weighted:.1%}")


if __name__ == "__main__":
    main()
