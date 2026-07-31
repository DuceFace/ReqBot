#!/usr/bin/env python3
"""WP-38.1: check each hand-labeled failure from the unbiased sample against the
*actual* current rejection logic (_is_heading_echo, _is_unrepairable_fragment,
skip_sections) to classify: real gap (should fire but doesn't), not covered by
design, or already-caught (would indicate a labeling mistake on my part).
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.parse_and_normalize import (
    _is_heading_echo,
    _is_unrepairable_fragment,
    UNREPAIRABLE_FRAGMENT_MAX_WORDS,
)

SKIP_SECTIONS = {
    "GLOSSARY", "REFERENCES", "ACRONYMS", "DEFINITIONS",
    "ABBREVIATIONS", "TABLE OF CONTENTS", "TERMS",
}

# (requirement_id: (category, subtype)) -- category is FRAGMENT/OVER_GRAB/JUDGMENT.
# subtype is the specific sub-shape from PHASE38_REQUIREMENTS.md's Findings
# (Fragment sub-shapes / Over-grab sub-shapes breakdown) -- needed so WP-38.2's
# regression gate can mechanically check "did the new rule reject its own
# targeted subtype without touching the others" instead of only the broad
# category (Codex review, PR #180).
LABELS = {
    "REQ-4aeeff50f15b": ("FRAGMENT", "dangling_clause"),
    "REQ-626b98fef9aa": ("FRAGMENT", "orphaned_list_item"),
    "REQ-c6aeb8df528b": ("FRAGMENT", "orphaned_list_item"),
    "REQ-c62e41aaf181": ("FRAGMENT", "dangling_clause"),
    "REQ-8105d9acb410": ("FRAGMENT", "dangling_clause"),
    "REQ-97e6e5483093": ("FRAGMENT", "colon_too_long"),
    "REQ-acfbd747b576": ("OVER_GRAB", "descriptive_background"),
    "REQ-7707aff8b904": ("JUDGMENT", "aup_rights_notice"),
    "REQ-ccc5664adcfe": ("OVER_GRAB", "descriptive_background"),
    "REQ-d3a496d3736c": ("OVER_GRAB", "descriptive_background"),
    "REQ-1cc75ab1ae84": ("FRAGMENT", "dangling_clause"),
    "REQ-c0b7725c82c0": ("OVER_GRAB", "reference_only"),
    "REQ-80b348b0a989": ("FRAGMENT", "malformed_garbled"),
    "REQ-3097aa5d306c": ("FRAGMENT", "orphaned_list_item"),
    "REQ-c6d23854cd0b": ("FRAGMENT", "orphaned_list_item"),
    "REQ-48f549669bb2": ("FRAGMENT", "orphaned_list_item"),
    "REQ-9c62641ac103": ("OVER_GRAB", "reference_only"),
    "REQ-7464da5820b8": ("FRAGMENT", "orphaned_list_item"),
    "REQ-cf527f39c8d7": ("FRAGMENT", "orphaned_list_item"),
    "REQ-a22b2ca5ab90": ("FRAGMENT", "colon_too_long"),
    "REQ-01a7421e8e0a": ("JUDGMENT", "self_contained_list_item"),
    "REQ-c77b59621281": ("OVER_GRAB", "reference_only"),
    "REQ-189d6285eaa2": ("OVER_GRAB", "descriptive_background"),
    "REQ-4dd90b6e3a71": ("OVER_GRAB", "descriptive_background"),
    "REQ-cf2bc6e8a365": ("OVER_GRAB", "descriptive_background"),
    "REQ-c9fb01a1de64": ("JUDGMENT", "declarative_state_possibly_truncated"),
    "REQ-02d473ff8f30": ("FRAGMENT", "malformed_garbled"),
    "REQ-82e9ae53ebf9": ("JUDGMENT", "deictic_reference"),
    "REQ-98c330f9de2e": ("OVER_GRAB", "descriptive_background"),
    "REQ-a63a80e9a6b1": ("OVER_GRAB", "descriptive_background"),
    "REQ-ed3c56de4287": ("FRAGMENT", "malformed_garbled"),
    "REQ-9de207b16791": ("OVER_GRAB", "descriptive_background"),
    "REQ-4523443092b8": ("FRAGMENT", "orphaned_list_item"),
    "REQ-9266f0704b0e": ("FRAGMENT", "colon_too_long"),
    "REQ-364e0be72ebb": ("FRAGMENT", "orphaned_list_item"),
    "REQ-e0471aa64a63": ("FRAGMENT", "orphaned_list_item"),
    "REQ-aea8a2e1e69a": ("OVER_GRAB", "descriptive_background"),
    "REQ-1ec810edd48d": ("JUDGMENT", "descriptive_procedural"),
    "REQ-a8fe726802ab": ("OVER_GRAB", "descriptive_background"),
    "REQ-5c349cdc3656": ("FRAGMENT", "orphaned_list_item"),
    "REQ-17290369ef3b": ("FRAGMENT", "malformed_garbled"),
    "REQ-68e7c7d2ba86": ("FRAGMENT", "orphaned_list_item"),
    "REQ-1b1071c8d317": ("FRAGMENT", "dangling_clause"),
    "REQ-cc458f334808": ("OVER_GRAB", "reference_only"),
    "REQ-e41d286c83f4": ("OVER_GRAB", "examples_of"),
    "REQ-51cf63d9379f": ("OVER_GRAB", "descriptive_background"),
    "REQ-46276198bffc": ("OVER_GRAB", "descriptive_background"),
    "REQ-9700722b04cd": ("FRAGMENT", "dangling_clause"),
    "REQ-db943fb3ade5": ("OVER_GRAB", "acknowledgment_template"),
}

SAMPLE_PATH = Path(__file__).parent / "unbiased_sample.jsonl"


def main():
    records = {}
    with open(SAMPLE_PATH) as f:
        for line in f:
            rec = json.loads(line)
            records[rec.get("requirement_id")] = rec

    rows = []
    for req_id, (category, subtype) in LABELS.items():
        rec = records.get(req_id)
        if rec is None:
            print(f"WARNING: {req_id} not found in unbiased_sample.jsonl")
            continue
        quote = rec.get("source_quote") or ""
        section_path = rec.get("section_title_path") or []
        heading_echo = _is_heading_echo(quote, section_path)
        unrepairable = _is_unrepairable_fragment(quote)
        word_count = len(quote.strip().split())
        ends_colon = quote.strip().endswith(":")
        heading_upper = {h.upper() for h in section_path}
        in_skip_sections = bool(heading_upper & SKIP_SECTIONS)

        if heading_echo or unrepairable:
            rule_status = "SHOULD_BE_CAUGHT_BUT_ISNT (labeling error? survived despite matching a rule)"
        elif ends_colon and word_count > UNREPAIRABLE_FRAGMENT_MAX_WORDS:
            rule_status = "REAL_GAP (colon-terminated fragment, exceeds 25-word cap)"
        elif in_skip_sections:
            rule_status = "REAL_GAP (section is in skip_sections vocab but record wasn't filtered)"
        else:
            rule_status = "NOT_COVERED_BY_DESIGN (no current rule targets this shape)"

        rows.append({
            "requirement_id": req_id,
            "doc_key": rec.get("_doc_key"),
            "category": category,
            "subtype": subtype,
            "word_count": word_count,
            "ends_colon": ends_colon,
            "heading_echo": heading_echo,
            "unrepairable_fragment": unrepairable,
            "in_skip_sections": in_skip_sections,
            "section_title_path": section_path,
            "rule_status": rule_status,
            "quote": quote,
        })

    with open(Path(__file__).parent / "labeled_failures.jsonl", "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    # Summary
    from collections import Counter
    cat_counts = Counter(r["category"] for r in rows)
    subtype_counts = Counter((r["category"], r["subtype"]) for r in rows)
    rule_counts = Counter(r["rule_status"].split(" (")[0] for r in rows)
    print(f"Total labeled failures checked: {len(rows)}")
    print(f"By category: {dict(cat_counts)}")
    print("By subtype:")
    for (cat, subtype), n in sorted(subtype_counts.items()):
        print(f"  {cat:10s} {subtype:35s} {n}")
    print(f"By rule status: {dict(rule_counts)}")
    print()
    for r in rows:
        if r["rule_status"].startswith("SHOULD_BE_CAUGHT"):
            print(f"!! {r['requirement_id']} ({r['doc_key']}): {r['rule_status']}")
            print(f"   quote: {r['quote'][:150]}")


if __name__ == "__main__":
    main()
