#!/usr/bin/env python3
"""
eval/build_gold_description_grounding.py — WP-35.1 gold dataset builder

Combines eval/harvest_description_grounding_candidates.py's output with this
WP's hand-verification results (LABELS below) into the final labeled dataset:
eval/gold_description_grounding.jsonl.

Every record in LABELS was checked by hand against its own
section_title_path/parent_context (not just the bare quote/description pair)
before being assigned a label -- see docs/PHASE35_REQUIREMENTS.md's WP-35.1
section for the full reasoning behind each one. The clean_sample entries are
included as-is (faithful) -- WP-35.1's scope explicitly allows the faithful
holdout to stay randomly sampled without the same per-record deliberation the
scarce fabricated examples needed, though all 90 were still skimmed by hand
for anything that looked wrong before being accepted (none did).

Every output record carries a `source` field: `"wp_34_4_spike"` for the 8
records confirmed (via exact source_quote match, see SPIKE_OVERLAP_IDS) to
already exist in eval/entailment_spike.py's own KNOWN_BAD/KNOWN_GOOD proof-
of-concept set, `"wp_35_1_harvest"` for everything genuinely new to this WP.
Found by Codex review on this WP's own PR: half of the first hand-verified
fabricated batch turned out to be WP-34.4 fixtures reused unknowingly, which
would make WP-35.2's sweep circular against the exact set that motivated
building an independent dataset in the first place. WP-35.2 must filter to
`source == "wp_35_1_harvest"` for its real calibration statistics; the
`wp_34_4_spike` records stay in the file as a regression check only (does
the chosen threshold still classify the original cases correctly), not
counted toward catch-rate/false-positive-rate.

Usage:
  python3 eval/build_gold_description_grounding.py
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HARVEST_FILE = _ROOT / "eval" / "spike_results" / "wp_35_1" / "harvest_candidates.json"
OUTPUT_FILE = _ROOT / "eval" / "gold_description_grounding.jsonl"

# requirement_id -> (label, notes). Hand-verified against each record's own
# section_title_path/parent_context during WP-35.1 (2026-07-30/31).
#
# label values:
#   faithful              -- description accurately reflects source_quote
#   fabricated_citation   -- bare reference-list citation, description invents
#                             specific content the citation itself never states
#   fabricated_fragment   -- truncated list-header/item, description invents
#                             content to "complete" it
#   fabricated_other      -- invents a specific attribution/actor/authority not
#                             present in source_quote (subtler than a citation
#                             or a bare fragment)
#   fabricated_modality   -- the WP-35.3 target pattern: factual content is
#                             faithfully carried over, but an obligation/
#                             imperative is invented on top of it
LABELS = {
    "REQ-da2d52df8841": (
        "fabricated_fragment",
        "WP-34.4 known-bad (cjcsi_po_service_principal_fragment). Colon-terminated "
        "list header; description invents the full list of duties. Same document, "
        "chunk 3 -- section_title_path/parent_context weren't captured for this "
        "chunk (an early-document hierarchy gap, not a labeling gap).",
    ),
    "REQ-466a23120b21": (
        "fabricated_citation",
        "WP-34.4 known-bad (afpd_dodi_8500_citation). Bare bibliography entry; "
        "description invents a specific framework reference (NIST SP 800-53 Rev. 4) "
        "absent from the citation. From afpd_17-1.pdf chunk 8 -- a References-list "
        "chunk (see REQ-ddc1112cabc9, REQ-04dd14fe4baf, REQ-5968a12bc1d6, "
        "REQ-44408bbfebbe below, all the same chunk).",
    ),
    "REQ-ddc1112cabc9": (
        "fabricated_citation",
        "New citation-shaped fabrication (not in WP-34.4's original set), same "
        "References-list chunk (afpd_17-1.pdf chunk 8) as REQ-466a23120b21. "
        "Description invents a specific plan requirement ('comprehensive inventory "
        "of all DoD IT systems') the bare citation never states.",
    ),
    "REQ-04dd14fe4baf": (
        "fabricated_citation",
        "WP-34.4 known-bad (afpd_jp3_12_citation). Same References-list chunk as "
        "REQ-466a23120b21.",
    ),
    "REQ-917e508c8a6d": (
        "fabricated_fragment",
        "WP-34.4 known-bad (afpd_haf_functionals_fragment). Also a WP-34.2 "
        "heading-echo case -- section_title_path confirms this exact quote is its "
        "own chunk's heading ('3.14. All HAF Functionals...'), so a fresh ingest "
        "now rejects it before Step D.5 ever runs. Kept here as real historical "
        "evidence of the pattern, same as WP-34.4 treated it.",
    ),
    "REQ-d700d6df28b0": (
        "fabricated_other",
        "Subtler than a bare citation: this record's own source_quote is just "
        "'a. Address the operational readiness...' (the sub-bullet body, no actor "
        "named) -- but the description prepends 'The PO, in conjunction with "
        "Service Principal/CIO and AO will:', an attribution that is real text "
        "elsewhere in the same document (it's REQ-da2d52df8841's own source_quote) "
        "but is absent from *this* record's source_quote. Grounding is evaluated "
        "per-record against that record's own source_quote, so this counts as "
        "invented content by this project's existing standard -- an attribution-"
        "hallucination flavor distinct from both the citation and fragment shapes.",
    ),
    "REQ-409e58971a57": (
        "fabricated_other",
        "WP-34.4 known-bad (cjcsi_distribution_fabricated_attribution). A short "
        "administrative line gets a fabricated attribution ('as per Reference "
        "J-6') invented, not present in the quote.",
    ),
    "REQ-679a055fb375": (
        "faithful",
        "WP-34.4 known-good (dodi_nsa_approved_crypto). Real modal-verb "
        "substitution (will -> must), same facts. Caught by this WP's harvester's "
        "broad modality heuristic (must appears in description, not in quote) -- "
        "exactly the over-catch case docs/PHASE35_REQUIREMENTS.md's WP-35.3 "
        "section warns a naive per-word check would false-positive on. Kept "
        "explicitly as a WP-35.3 fixture per that section's own instruction.",
    ),
    "REQ-757d551b3e59": (
        "fabricated_modality",
        "New, post-fix (NIST.SP.800-125.pdf, ingested fresh during this WP -- "
        "not one of WP-34.4's original documents). source_quote is a noun-phrase "
        "fragment ('better control of OSs to ensure that they meet the "
        "organization's security requirements') with no obligation verb of its "
        "own; description prepends 'Implement', inventing an imperative the quote "
        "never states. Real, current evidence that modality-fabrication is not "
        "yet structurally prevented the way citation/fragment fabrications are.",
    ),
    "REQ-5968a12bc1d6": (
        "fabricated_citation",
        "Same References-list chunk as REQ-466a23120b21 (afpd_17-1.pdf chunk 8). "
        "Description invents a specific interoperability-requirements claim the "
        "bare citation never states. Flagged by the modality heuristic rather "
        "than the fragment heuristic only because 'ensure' happens to appear in "
        "the description and not the quote -- same citation-fabrication shape as "
        "the others from this chunk, not a distinct pattern.",
    ),
    "REQ-44408bbfebbe": (
        "fabricated_citation",
        "Same References-list chunk as REQ-466a23120b21. Description invents "
        "specific charter authority ('responsible for reviewing and approving "
        "requirements') beyond what a bare citation title states.",
    ),
    "REQ-35dfe9353e60": (
        "faithful",
        "Real paraphrase (support -> maintain, condensed) -- same two facts "
        "(complete inventory, includes personnel/equipment/funds). Lives under "
        "section_title_path=['Terms'] in afpd_17-1.pdf, the same glossary/"
        "definitions heading as REQ-a485fe91aa5f below, but this particular "
        "quote already reads as an operational obligation sentence in its own "
        "right ('The agency must support...'), not dictionary-style prose -- "
        "the Terms heading here looks like a docling hierarchy misplacement, not "
        "evidence this is a definition. Two near-duplicate variants existed "
        "across two separate pipeline runs (Step D.5 enrichment isn't fully "
        "deterministic); the more complete variant (retains 'at an appropriate "
        "level of detail') was kept, the other discarded as a duplicate.",
    ),
    "REQ-a485fe91aa5f": (
        "fabricated_modality",
        "WP-34.4 known-bad, originally miscategorized as known-good until "
        "Codex's PR #164 review (afpd_definition_reframed_as_imperative). "
        "section_title_path=['Terms'] confirms this is a genuine glossary "
        "definition; description reframes it as an imperative obligation. This "
        "specific historical record predates WP-34.3's TERMS skip_sections fix.",
    ),
    "REQ-c6d23854cd0b": (
        "fabricated_fragment",
        "New, post-fix (DODI 8410.03.pdf). source_quote is a bare enumerated "
        "list-item topic phrase ('(3) Mean time between failures of network "
        "equipment or connectivity.') with no obligation verb of its own -- "
        "parent_context confirms it's item 3 of a list of SLA topics to address, "
        "not an instruction. Description invents a specific obligation ('must be "
        "measured') the quote never states. Notably this one does *not* end in a "
        "colon, so parse_and_normalize.py's _is_unrepairable_fragment (which only "
        "fires on colon-terminated quotes) would not catch it -- a real gap "
        "worth a future look, out of scope for this WP to fix.",
    ),
    "REQ-efc38d9d853d": (
        "faithful",
        "New, post-fix (DODI 8410.03.pdf). Active-to-passive rephrasing ('meet "
        "all required...' -> '...must be met'); the quote's own wording already "
        "labels the checks as 'required', so asserting they 'must be met' doesn't "
        "invent new content, just makes the existing modality explicit. Another "
        "real over-catch case for the same reason as REQ-679a055fb375 -- kept as "
        "a second WP-35.3 near-synonym/paraphrase fixture.",
    ),
    "REQ-f7a98a6a365d": (
        "fabricated_other",
        "New, post-fix (afi10-2402.pdf) -- found on a re-harvest after this WP's "
        "first commit, once afi10-2402's ingest (still running in the background "
        "at that point) actually finished. source_quote is a complete, real "
        "sentence about BSAs recommending remediation measures; description is "
        "about an entirely different topic (findings-report distribution lists) "
        "found nowhere in the quote or parent_context -- not a citation, not a "
        "truncated fragment, just wholesale topical drift. Distinct from the "
        "other fabricated_other example (REQ-409e58971a57's invented attribution) "
        "but grouped the same way: a specific invented claim with no fragment or "
        "citation shape driving it.",
    ),
    "REQ-cbc6374a655f": (
        "fabricated_modality",
        "New, post-fix (afi10-2402.pdf), same late re-harvest as REQ-f7a98a6a365d. "
        "source_quote names a term via cross-reference to its defining "
        "instructions ('Insider Threat, as defined in DoDD 5205.16... and AFI "
        "16-1402...'), the same definitional-cross-reference shape as "
        "REQ-a485fe91aa5f; description invents 'Implement Insider Threat "
        "Program', an imperative the quote never states.",
    ),
    "REQ-668a74c21bd2": (
        "faithful",
        "New, post-fix (dafman17-1305.pdf), found during the second corpus "
        "expansion (5 more documents, prompted by Codex's PR #166 finding that "
        "the independent fabricated partition was too thin). Another real "
        "modal-verb substitution (will -> must), same facts, same "
        "over-catch shape as REQ-679a055fb375/REQ-efc38d9d853d -- a third "
        "independent WP-35.3 near-synonym/paraphrase fixture, not a duplicate "
        "of either (different document, different verb pair context).",
    ),
}

# requirement_id -> True if this record is a duplicate of one of
# eval/entailment_spike.py's own KNOWN_BAD/KNOWN_GOOD fixtures (confirmed by
# exact source_quote match, not just topical similarity). Found by Codex
# review on this WP's own PR (#166): 8 of the first 15 hand-verified records
# turned out to already exist in WP-34.4's proof-of-concept set -- reusing
# them here as "new" calibration evidence would be circular (WP-35.1 exists
# specifically because that set was never meant to calibrate a threshold, see
# docs/PHASE35_REQUIREMENTS.md's Phase Framing). Kept in the file rather than
# deleted -- real regression value in confirming WP-35.2's chosen threshold
# still classifies the original spike cases correctly -- but marked with
# source="wp_34_4_spike" so WP-35.2's actual calibration sweep can exclude
# them from its catch-rate/false-positive statistics.
SPIKE_OVERLAP_IDS = {
    "REQ-da2d52df8841",  # cjcsi_po_service_principal_fragment
    "REQ-466a23120b21",  # afpd_dodi_8500_citation
    "REQ-04dd14fe4baf",  # afpd_jp3_12_citation
    "REQ-917e508c8a6d",  # afpd_haf_functionals_fragment
    "REQ-409e58971a57",  # cjcsi_distribution_fabricated_attribution
    "REQ-a485fe91aa5f",  # afpd_definition_reframed_as_imperative
    "REQ-679a055fb375",  # dodi_nsa_approved_crypto
    "REQ-35dfe9353e60",  # afpd_ea_inventory
}

# requirement_id -> which description variant to keep, for the one record with
# two near-duplicate enrichment runs (see REQ-35dfe9353e60's note above).
PREFERRED_DESCRIPTION = {
    "REQ-35dfe9353e60": (
        "Agency must maintain a complete inventory of information resources, "
        "including personnel, equipment, and funds, at an appropriate level of detail."
    ),
}


def main() -> None:
    harvest = json.loads(HARVEST_FILE.read_text(encoding="utf-8"))

    by_id: dict[str, dict] = {}
    for bucket in ("citation_fragment_shaped", "modality_shaped"):
        for entry in harvest[bucket]:
            rid = entry["requirement_id"]
            if rid in PREFERRED_DESCRIPTION:
                if entry["description"] != PREFERRED_DESCRIPTION[rid]:
                    continue
            elif rid in by_id and entry["description"] != by_id[rid]["description"]:
                raise SystemExit(
                    f"Duplicate requirement_id {rid} with differing descriptions found in harvest "
                    f"candidates, and it isn't registered in PREFERRED_DESCRIPTION -- hand-pick which "
                    f"description variant to keep (see REQ-35dfe9353e60 for the pattern) before rerunning."
                )
            by_id[rid] = entry

    missing = set(LABELS) - set(by_id)
    if missing:
        raise SystemExit(f"LABELS references requirement_id(s) not found in harvest output: {missing}")
    extra = set(by_id) - set(LABELS)
    if extra:
        raise SystemExit(f"Flagged candidate(s) in harvest output have no hand-verified label: {extra}")

    records = []
    for rid, entry in by_id.items():
        label, notes = LABELS[rid]
        source = "wp_34_4_spike" if rid in SPIKE_OVERLAP_IDS else "wp_35_1_harvest"
        records.append({
            "source_quote": entry["source_quote"],
            "description": entry["description"],
            "label": label,
            "notes": notes,
            "section_title_path": entry["section_title_path"],
            "parent_context": entry["parent_context"],
            "source_pdf": entry["source_pdf"],
            "chunk_id": entry["chunk_id"],
            "requirement_id": rid,
            "run_dir": entry["run_dir"],
            "source": source,
        })

    for entry in harvest["clean_sample"]:
        records.append({
            "source_quote": entry["source_quote"],
            "description": entry["description"],
            "label": "faithful",
            "notes": "Random sample from post-fix clean-pool output (not flagged by either "
                     "fabrication heuristic); skimmed by hand, not individually annotated.",
            "section_title_path": entry["section_title_path"],
            "parent_context": entry["parent_context"],
            "source_pdf": entry["source_pdf"],
            "chunk_id": entry["chunk_id"],
            "requirement_id": entry["requirement_id"],
            "run_dir": entry["run_dir"],
            "source": "wp_35_1_harvest",
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    from collections import Counter
    counts = Counter(r["label"] for r in records)
    print(f"Wrote {len(records)} records to {OUTPUT_FILE}", file=sys.stderr)
    for label, n in sorted(counts.items()):
        print(f"  {label}: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
