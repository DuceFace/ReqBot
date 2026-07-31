#!/usr/bin/env python3
"""WP-38.1: compute the population-weighted prevalence estimate.

The unbiased sample uses a MIN_PER_DOC=15 floor (generate_samples.py) so
documents smaller than ~88 records (15 / (320/1872)) are over-represented
relative to their true share of the corpus. Reporting the raw flagged/total
ratio from that sample therefore estimates the *sample's* composition, not
the corpus's -- the same class of mistake as PHASE36_REQUIREMENTS.md's
WP-36.2 finding (Codex review, PR #180). This computes both numbers so the
correction is visible, not silently swapped in.
"""
import json
from collections import defaultdict
from pathlib import Path

from core.artifact_resolver import resolve_latest_requirement_files

SCRIPT_DIR = Path(__file__).parent
FAILURE_CATEGORIES = ("FRAGMENT", "OVER_GRAB")
ALL_CATEGORIES = ("FRAGMENT", "OVER_GRAB", "JUDGMENT")


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
    sample = [json.loads(l) for l in open(SCRIPT_DIR / "unbiased_sample.jsonl")]
    labels = {
        json.loads(l)["requirement_id"]: json.loads(l)["category"]
        for l in open(SCRIPT_DIR / "labeled_failures.jsonl")
    }
    for rec in sample:
        rec["_category"] = labels.get(rec["requirement_id"], "REAL")

    files = resolve_latest_requirement_files(Path.home() / "documents" / "processed")
    population = {doc_key: sum(1 for _ in open(path)) for doc_key, path in files.items()}
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
