#!/usr/bin/env python3
"""WP-38.2: verify the new/changed Step D rejection rules against WP-38.1's
own hand-labeled audit fixture (eval/audit_wp38_1/), per the gate in
docs/PHASE38_REQUIREMENTS.md's WP-38.2 section.

Confirms, against all 333 records in eval/audit_wp38_1/unbiased_sample.jsonl:
  1. None of the 284 confirmed-real records get rejected by any current rule
     (no regression -- the single most important check).
  2. For each fragment subtype, whether its targeted rule now catches it
     (colon_too_long -> _is_unrepairable_fragment, orphaned_list_item ->
     _is_orphaned_list_item, dangling_clause -> _is_dangling_clause) -- and
     FAILS if the catch count drops below the committed baseline below (Codex
     review, PR #181: an earlier version only checked for false positives, so
     a rule silently breaking or being deleted entirely would still exit 0).
  3. malformed_garbled (explicitly out of scope) and all over_grab/judgment
     records are correctly left untouched by every rule -- confirms scope
     discipline, not accidental over-reach.

This is a real pipeline function-level check (imports and calls the actual
rule functions), not a re-implementation of the rules' logic.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.parse_and_normalize import (
    _is_dangling_clause,
    _is_heading_echo,
    _is_orphaned_list_item,
    _is_unrepairable_fragment,
)

FIXTURE_DIR = _ROOT / "eval" / "audit_wp38_1"

# Committed floor for each targeted subtype's catch count, from the real
# results recorded in docs/PHASE38_REQUIREMENTS.md's WP-38.2 Findings. A drop
# below these means a rule regressed or was broken/removed -- fails the
# script rather than just printing a lower number (Codex review, PR #181).
MIN_CATCH_BASELINE = {
    "colon_too_long": 3,
    "orphaned_list_item": 3,
    "dangling_clause": 1,
}


def rejected_by(rec: dict) -> str | None:
    """Return the name of the first current rule that rejects this record's
    source_quote, or None if no rule fires. Mirrors run()'s actual check
    order in pipeline/parse_and_normalize.py."""
    quote = rec.get("source_quote") or ""
    section_path = rec.get("section_title_path") or []
    if _is_heading_echo(quote, section_path):
        return "heading_echo"
    if _is_unrepairable_fragment(quote):
        return "unrepairable_fragment"
    if _is_orphaned_list_item(quote):
        return "orphaned_list_item"
    if _is_dangling_clause(quote):
        return "dangling_clause"
    return None


def main():
    sample = [json.loads(l) for l in open(FIXTURE_DIR / "unbiased_sample.jsonl")]
    labels = {
        json.loads(l)["requirement_id"]: (json.loads(l)["category"], json.loads(l)["subtype"])
        for l in open(FIXTURE_DIR / "labeled_failures.jsonl")
    }

    real_regressions = []
    subtype_results: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    scope_violations = []

    for rec in sample:
        req_id = rec["requirement_id"]
        category, subtype = labels.get(req_id, ("REAL", None))
        rule_hit = rejected_by(rec)

        if category == "REAL":
            if rule_hit is not None:
                real_regressions.append((req_id, rule_hit))
            continue

        subtype_results[subtype].append((req_id, rule_hit))

        if category in ("OVER_GRAB", "JUDGMENT") or subtype == "malformed_garbled":
            if rule_hit is not None:
                scope_violations.append((req_id, category, subtype, rule_hit))

    print(f"Real records checked: {sum(1 for r in sample if labels.get(r['requirement_id'], ('REAL',))[0] == 'REAL')}")
    print(f"Real regressions (MUST be 0): {len(real_regressions)}")
    for req_id, rule in real_regressions:
        print(f"  !! REGRESSION: {req_id} rejected by {rule}")

    print()
    print("Fragment subtype coverage (targeted rule catch rate):")
    target_rule = {
        "colon_too_long": "unrepairable_fragment",
        "orphaned_list_item": "orphaned_list_item",
        "dangling_clause": "dangling_clause",
        "malformed_garbled": None,  # explicitly out of scope
    }
    coverage_regressions = []
    for subtype, expected_rule in target_rule.items():
        results = subtype_results.get(subtype, [])
        matched = sum(1 for _, hit in results if hit == expected_rule)
        if expected_rule is None:
            print(f"  {subtype:20s} {matched}/{len(results)} correctly left untouched (out of scope)")
        else:
            print(f"  {subtype:20s} {matched}/{len(results)} caught by its targeted rule")
            baseline = MIN_CATCH_BASELINE[subtype]
            if matched < baseline:
                coverage_regressions.append((subtype, matched, baseline))
        for req_id, hit in results:
            if expected_rule is None:
                status = "OK (untouched)" if hit is None else f"SCOPE VIOLATION (hit={hit})"
            else:
                status = "CAUGHT" if hit == expected_rule else f"missed (hit={hit})"
            print(f"      {req_id}: {status}")

    print()
    print(f"Scope violations -- over_grab/judgment/malformed_garbled caught (MUST be 0): {len(scope_violations)}")
    for req_id, category, subtype, rule in scope_violations:
        print(f"  !! SCOPE VIOLATION: {req_id} ({category}/{subtype}) rejected by {rule}")

    print()
    print(f"Coverage regressions -- catch count below committed baseline (MUST be 0): {len(coverage_regressions)}")
    for subtype, matched, baseline in coverage_regressions:
        print(f"  !! COVERAGE REGRESSION: {subtype} caught {matched}, baseline is {baseline}")

    print()
    if real_regressions or scope_violations or coverage_regressions:
        print("FAILED: regressions, scope violations, or coverage regressions found.")
        sys.exit(1)
    print("PASSED: no regressions on real records, no scope violations, no coverage regressions.")


if __name__ == "__main__":
    main()
