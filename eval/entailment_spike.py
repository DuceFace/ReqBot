#!/usr/bin/env python3
"""
eval/entailment_spike.py — WP-34.4 description-grounding entailment spike

Tests whether a lightweight NLI/factual-consistency model can catch Step D.5's
fabricated-description symptom (a `description` invents content that appears
nowhere in its `source_quote`) without flagging normal, faithful paraphrases.
See docs/PHASE34_REQUIREMENTS.md's WP-34.4 section for the full rationale and
docs/PHASE33_REQUIREMENTS.md's WP-33.3 Findings for where the fabrication
categories were first identified.

This mirrors eval/actionability_spike.py's "try a candidate, look at real
results" pattern -- eval-only, no production Step D.5 change (WP-34.4 Non-Goals).

Model: MiniCheck (Bespoke Labs / UPenn, github.com/Liyan06/MiniCheck), the
flan-t5-large checkpoint. Not the same as the `minicheck` PyPI package (an
unrelated formal state-machine model checker that happens to share the name --
install from the GitHub source, not `pip install minicheck`):

  pip install --user --break-system-packages "git+https://github.com/Liyan06/MiniCheck.git"
  python3 -c "import nltk; nltk.download('punkt_tab')"

HHEM (the WP's other suggested candidate) was tried first and rejected: its
custom `trust_remote_code` modeling code is incompatible with this repo's
already-pinned `transformers` version (`AttributeError:
'HHEMv2ForSequenceClassification' object has no attribute
'all_tied_weights_keys'`) -- and downgrading `transformers` to chase HHEM
compatibility risks breaking docling itself, well outside a spike's scope.

Every (source_quote, description) pair below is real, pulled directly from
this repo's own enriched pipeline output (`~/documents/processed/*/`), not
synthetic -- both the known-bad (fabricated) and known-good (faithful
paraphrase) sets. Model weights cache to the default Hugging Face location
(~/.cache/huggingface/hub), never into the repo.

Outputs:
  eval/spike_results/wp_34_4/report.md   — human-readable results + verdict
  eval/spike_results/wp_34_4/results.json — raw per-example scores

Usage:
  python3 eval/entailment_spike.py
  python3 eval/entailment_spike.py --model flan-t5-large
"""

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# (label, source_quote, description, note)
#
# All five pulled directly from this repo's real enriched pipeline output
# (~/documents/processed/*/*_requirements_enriched.jsonl) via a script that
# flagged short/colon-terminated quotes paired with a much longer, low-
# similarity description -- then each candidate was hand-verified against
# its source document to confirm the description genuinely invents content
# absent from source_quote, not just legitimately elaborates on it.
KNOWN_BAD = [
    (
        "afpd_jp3_12_citation",
        "JP 3-12, Cyberspace Operations, February 5, 2013",
        "Provides guidance on cyberspace operations, including requirements for "
        "planning, executing, and assessing the effectiveness of these operations.",
        "WP-33.3 category 1 (reference-list citation misextraction) -- a bare "
        "bibliography entry, description invents specific content ('requirements "
        "for planning, executing, and assessing') that appears nowhere in the citation.",
    ),
    (
        "afpd_dodi_8500_citation",
        "DoDI 8500.01, Cybersecurity, March 14, 2014",
        "Establishes policies and procedures for implementing cybersecurity measures "
        "in accordance with NIST SP 800-53 Rev. 4.",
        "Same pattern as above, same document -- description invents a specific "
        "framework reference ('NIST SP 800-53 Rev. 4') not present in the citation.",
    ),
    (
        "afpd_haf_functionals_fragment",
        "All HAF Functionals, MAJCOMs, DRUs, and FOAs will:",
        "Identify the Protection Level of their cyber and computer/communications "
        "assets and apply integrated defense measures IAW AFI 31-101, Integrated Defense.",
        "WP-33.3 category 3 (truncated colon-terminated fragment) -- description "
        "completes the sentence with specific obligations and a citation invented "
        "wholesale; also a WP-34.2 heading-echo fixture (this exact quote is its "
        "own chunk's section_title_path[-1]), now rejected before Step D.5 in a "
        "fresh ingest, but the historical enriched record is real and demonstrates "
        "the fabrication symptom independent of that fix.",
    ),
    (
        "cjcsi_po_service_principal_fragment",
        "The PO, in conjunction with Service Principal/CIO and AO will:",
        "The PO, in conjunction with Service Principal/CIO and AO will: Address the "
        "operational readiness of cybersecurity solutions and cryptographic products "
        "employed to provide continuous protection to national security information "
        "transmitted via command, control, communications, computers, intelligence, "
        "surveillance, and reconnaissance (C4ISR), information technology (IT), and "
        "weapons systems.",
        "Same fragment-completion pattern as WP-33.3's original 'The MC4EB will:' "
        "example (that exact historical record's fabricated text wasn't reproducible "
        "from currently-available artifacts -- Step D.5 enrichment isn't fully "
        "deterministic -- but this is the same document, same root cause, real data).",
    ),
    (
        "cjcsi_distribution_fabricated_attribution",
        "Distribution: A, B, C",
        "Distribution must be made to A, B, and C as per Reference J-6.",
        "Subtler than the others -- a short administrative line gets a fabricated "
        "attribution ('as per Reference J-6') invented, not present in the quote. "
        "Included as a harder/borderline case, not just the obvious ones.",
    ),
    (
        "afpd_definition_reframed_as_imperative",
        "Cybersecurity - Prevention of damage to, protection of, and restoration of "
        "computers, electronic communications systems, electronic communications "
        "services, wire communication, and electronic communication, including "
        "information contained therein, to ensure its availability, integrity, "
        "authentication, confidentiality, and nonrepudiation.",
        "Implement cybersecurity measures to prevent damage, protect, and restore "
        "computers, electronic communications systems, services, wire communication, "
        "and electronic communication to ensure availability, integrity, "
        "authentication, confidentiality, and nonrepudiation.",
        "Originally miscategorized as known-good in this spike's first draft -- caught "
        "by Codex review, PR #164. The quote's full record has "
        "section_title_path=['Terms']: this is a glossary/definitions entry (WP-33.3 "
        "category 4, background/definitional prose misextracted as a requirement -- "
        "now caught pre-Step-C by WP-34.3's skip_sections fix in a fresh ingest, but "
        "this historical record predates that fix). The description doesn't just "
        "reword the definition -- it invents an imperative obligation ('Implement "
        "cybersecurity measures to...') that the source text, a dictionary-style "
        "definition of what the word 'Cybersecurity' means, never actually states. "
        "Every individual fact carries over, but the obligation/modality itself is "
        "fabricated, which is exactly the failure mode this check exists to catch.",
    ),
]

# (label, source_quote, description, note) -- real faithful paraphrases, hand-picked to
# span a range of quote/description similarity (not just near-verbatim echoes, which
# would trivially pass and wouldn't stress-test anything) so a genuine faithful
# *paraphrase* -- not just a copy -- is what's being tested, per the WP's own framing.
KNOWN_GOOD = [
    (
        "cjcsi_ker_reordered",
        "In the event a decertified product would be required to be used beyond the "
        "published cease key dates, then a key extension request (KER) for "
        "decertified product must be submitted.",
        "A key extension request (KER) for decertified product must be submitted if "
        "a decertified product is required to be used beyond the published cease "
        "key dates.",
        "Real paraphrase -- clause order reversed, same facts.",
    ),
    (
        "cjcsi_services_responsibility",
        "Although the responsibility for acquiring, installing, and maintaining "
        "secure communications lies primarily with the Services,",
        "The Services are primarily responsible for acquiring, installing, and "
        "maintaining secure communications.",
        "Real paraphrase -- subordinate clause restated as a main clause.",
    ),
    (
        "afpd_ea_strategy",
        "The EA must also provide a strategy that will enable the agency to support "
        "its current state and also act as the roadmap for transition to its target "
        "environment.",
        "The EA must provide a strategy for supporting current state and "
        "transitioning to target environment.",
        "Real paraphrase -- condensed, same two facts (support current state, "
        "roadmap to target environment).",
    ),
    (
        "afpd_ea_inventory",
        "The agency must support the EA with a complete inventory of agency "
        "information resources, including personnel, equipment, and funds devoted "
        "to information resources management and information technology, at an "
        "appropriate level of detail.",
        "Agency must maintain a complete inventory of information resources, "
        "including personnel, equipment, and funds, at an appropriate level of detail.",
        "Real paraphrase -- condensed, drops a redundant qualifier without changing meaning.",
    ),
    (
        "cjcsi_nsa_coordination",
        "In coordination with the NSA, ensure adjudication of cryptographic issues "
        "that impact joint, allied, or combined interoperability.",
        "Ensure adjudication of cryptographic issues that impact joint, allied, or "
        "combined interoperability in coordination with the NSA.",
        "Real paraphrase -- clause reordered, same facts.",
    ),
    (
        "afpd_transition_processes",
        "These transition processes will include an agency's capital planning and "
        "investment control processes, agency EA planning processes, and agency "
        "systems life cycle methodologies.",
        "Transition processes include capital planning, investment control, EA "
        "planning, and systems life cycle methodologies.",
        "Real paraphrase -- condensed list, same four items.",
    ),
    (
        "cjcsi_key_support_declaration",
        "Per this memorandum, I declare key support for (system) is no longer required.",
        "The system administrator declares that key support for (system) is no "
        "longer required.",
        "Real paraphrase with a mild inferential step ('I' -> 'the system "
        "administrator', consistent with the memo's actual signatory role in this "
        "document) -- an intentionally harder edge case, not just a safe rewording.",
    ),
    (
        "afpd_iaw_expansion",
        "The organizations to which this instruction applies must act IAW its "
        "policy objectives and in compliance with reference (b).",
        "The organizations to which this instruction applies must act in accordance "
        "with its policy objectives and in compliance with reference (b).",
        "Near-verbatim -- only abbreviation expansion (IAW -> in accordance with).",
    ),
    (
        "dodi_nsa_approved_crypto",
        "DoD Components will use only NSA-approved cryptographic products to "
        "protect classified and/or sensitive national security information "
        "processed and transmitted over National Security Systems (NSS).",
        "DoD Components must use only NSA-approved cryptographic products to "
        "protect classified and/or sensitive national security information "
        "processed and transmitted over National Security Systems (NSS).",
        "Near-verbatim -- only a modal-verb substitution (will -> must).",
    ),
]


def _load_scorer(model_name: str):
    from minicheck.minicheck import MiniCheck
    t0 = time.time()
    scorer = MiniCheck(model_name=model_name)
    print(f"Loaded MiniCheck ({model_name}) in {time.time() - t0:.1f}s", file=sys.stderr)
    return scorer


def main() -> None:
    parser = argparse.ArgumentParser(description="WP-34.4 entailment spike")
    parser.add_argument(
        "--model", default="flan-t5-large",
        help="MiniCheck checkpoint name (default: flan-t5-large -- the smallest, "
             "CPU-friendly option; see github.com/Liyan06/MiniCheck for others).",
    )
    args = parser.parse_args()

    scorer = _load_scorer(args.model)

    all_examples = [("known_bad", *ex) for ex in KNOWN_BAD] + [("known_good", *ex) for ex in KNOWN_GOOD]
    docs = [ex[2] for ex in all_examples]
    claims = [ex[3] for ex in all_examples]

    pred_label, raw_prob, _, _ = scorer.score(docs=docs, claims=claims)

    results = []
    for (group, label, quote, description, note), pred, prob in zip(all_examples, pred_label, raw_prob):
        results.append({
            "group": group, "label": label,
            "source_quote": quote, "description": description, "note": note,
            "pred_supported": bool(pred), "support_prob": round(prob, 4),
        })

    out_dir = _ROOT / "eval" / "spike_results" / "wp_34_4"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    # False negative: a known-bad (fabricated) pair the model calls supported.
    # False positive: a known-good (faithful) pair the model calls unsupported.
    false_negatives = [r for r in results if r["group"] == "known_bad" and r["pred_supported"]]
    false_positives = [r for r in results if r["group"] == "known_good" and not r["pred_supported"]]
    n_bad = len(KNOWN_BAD)
    n_good = len(KNOWN_GOOD)

    lines = [
        "# WP-34.4 Entailment Spike — MiniCheck Results",
        "",
        "Generated by `eval/entailment_spike.py`. See `docs/PHASE34_REQUIREMENTS.md`'s "
        "WP-34.4 section for interpretation. Every pair below is real, pulled from this "
        "repo's own enriched pipeline output, not synthetic.",
        "",
        f"**Model:** MiniCheck ({args.model})",
        f"**Known-bad (fabricated) set:** {n_bad} real examples, "
        f"{len(false_negatives)} missed (false negative rate: {len(false_negatives) / n_bad:.0%})",
        f"**Known-good (faithful) set:** {n_good} real examples, "
        f"{len(false_positives)} wrongly flagged (false positive rate: {len(false_positives) / n_good:.0%})",
        "",
        "## Known-bad (fabricated) — should score LOW / unsupported",
        "",
    ]
    for r in results:
        if r["group"] != "known_bad":
            continue
        verdict = "**MISSED (false negative)**" if r["pred_supported"] else "caught"
        lines.append(f"### {r['label']} — {verdict}")
        lines.append(f"support_prob={r['support_prob']}, pred_supported={r['pred_supported']}")
        lines.append(f"- QUOTE: {r['source_quote']!r}")
        lines.append(f"- DESC: {r['description']!r}")
        lines.append(f"- {r['note']}")
        lines.append("")
    lines.append("## Known-good (faithful) — should score HIGH / supported")
    lines.append("")
    for r in results:
        if r["group"] != "known_good":
            continue
        verdict = "**WRONGLY FLAGGED (false positive)**" if not r["pred_supported"] else "passed"
        lines.append(f"### {r['label']} — {verdict}")
        lines.append(f"support_prob={r['support_prob']}, pred_supported={r['pred_supported']}")
        lines.append(f"- QUOTE: {r['source_quote']!r}")
        lines.append(f"- DESC: {r['description']!r}")
        lines.append(f"- {r['note']}")
        lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_dir / 'report.md'}", file=sys.stderr)
    print(
        f"False negative rate: {len(false_negatives)}/{n_bad} | "
        f"False positive rate: {len(false_positives)}/{n_good}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
