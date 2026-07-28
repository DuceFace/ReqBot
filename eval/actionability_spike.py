#!/usr/bin/env python3
"""
eval/actionability_spike.py — WP-33.3 actionability self-verification spike

Tests whether stricter Step C prompt wording alone reduces the four (now five)
weak-extraction failure modes found while hand-labeling a random sample of the
live corpus (see docs/PHASE33_REQUIREMENTS.md's WP-33.3 Findings for the full
write-up). Runs a baseline-vs-revised A/B comparison against real Ollama calls
on two chunk sets:

  - "known-bad" chunks: chunks that produced a documented failure mode in the
    original corpus run (reference-list misextraction, boilerplate mandate
    language, a truncated list-header fragment, background/definitional
    prose).
  - "known-good" chunks: chunks that extracted cleanly in the original corpus
    run, used as a regression check -- does the revised prompt introduce new
    problems on chunks that weren't broken to begin with?

This is a directional smoke test, not a quantified precision/recall
evaluation (no fix is being shipped from this spike -- see Reject-If Findings
in docs/PHASE33_REQUIREMENTS.md). Ollama generation is not perfectly
deterministic even at temperature 0.1 on this quantized model -- expect
re-runs to vary in specifics; the qualitative pattern (revised prompt does
not reliably fix, and on multiple independent chunks fabricates *new*
few-shot-example-shaped content) is what matters, not exact counts.

Outputs:
  eval/spike_results/wp_33_3/report.md   — human-readable comparison
  eval/spike_results/wp_33_3/<label>.json — per-chunk raw baseline/revised output

Usage:
  python3 eval/actionability_spike.py --ollama-url http://192.168.90.100:11434
"""

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.profiles import default_profile
from pipeline.llm_extract_requirements import (
    PASS1_PROMPT_TEMPLATE,
    _PASS1_FORMAT_SCHEMA,
    process_chunk,
)

MODEL = "llama3.1:8b-instruct-q4_K_M"

_REVISED_DO_NOT_EXTRACT = """DO NOT extract:
- Definitions or glossary entries
- Document change logs or errata (e.g., "Change X to Y")
- Tables of contents or section headings
- Cross-references to other controls (e.g., "Related controls: AC-2, IA-1")
- General background, context, or informational text
- Reference/bibliography lists of external documents or publications (e.g., a list of \
document titles with dates such as "DoDI 8500.01, Cybersecurity, March 14, 2014") -- this \
applies even when the list is long or spans many lines, not just short examples
- Generic compliance-mandate boilerplate that names no concrete action (e.g., \
"Compliance with this publication is mandatory")

Each extracted source_quote must be a complete, grammatically self-contained statement. \
Do NOT extract a sentence fragment that ends with a colon introducing a list (e.g., \
"...will:") -- if the actual obligation is stated in items below that colon, include \
enough of the list item text in source_quote to state a complete obligation, or skip it \
if the list items are in a different chunk you cannot see."""

REVISED_TEMPLATE = PASS1_PROMPT_TEMPLATE.replace(
    """DO NOT extract:
- Definitions or glossary entries
- Document change logs or errata (e.g., "Change X to Y")
- Tables of contents or section headings
- Cross-references to other controls (e.g., "Related controls: AC-2, IA-1")
- General background, context, or informational text""",
    _REVISED_DO_NOT_EXTRACT,
)
if REVISED_TEMPLATE == PASS1_PROMPT_TEMPLATE:
    raise RuntimeError(
        "REVISED_TEMPLATE substitution failed -- PASS1_PROMPT_TEMPLATE's "
        "'DO NOT extract:' block no longer matches the expected text. "
        "Update the substring above to match its current wording."
    )

# (label, pdf processed-dir name, chunk_id, why it's in this set)
KNOWN_BAD_CHUNKS = [
    ("afpd_references_list", "afpd_17-1_20260727_202422", "afpd_17-1", 8,
     "References section -- category 1, reference-list misextraction"),
    ("afpd_mandatory_boilerplate", "afpd_17-1_20260727_202422", "afpd_17-1", 0,
     "COMPLIANCE...MANDATORY boilerplate -- category 2, vague meta-statement"),
    ("afpd_glossary", "afpd_17-1_20260727_202422", "afpd_17-1", 9,
     "Definitions/Terms section -- category 4, background prose misextraction"),
    ("cjcsi_fragment", "CJCSI 6510.02G_20260727_202900", "CJCSI 6510.02G", 3,
     "'The MC4EB will:' list header -- category 3, truncated fragment"),
]

KNOWN_GOOD_CHUNKS = [
    ("cjcsi_chunk0_regression", "CJCSI 6510.02G_20260727_202900", "CJCSI 6510.02G", 0,
     "2 clean baseline requirements -- regression check"),
    ("cjcsi_chunk8_regression", "CJCSI 6510.02G_20260727_202900", "CJCSI 6510.02G", 8,
     "6 clean baseline requirements -- regression check"),
    ("cjcsi_chunk12_regression", "CJCSI 6510.02G_20260727_202900", "CJCSI 6510.02G", 12,
     "1 clean baseline requirement -- regression check"),
]


def _get_chunk(chunks_path: Path, chunk_id: int) -> dict | None:
    if not chunks_path.exists():
        return None
    with open(chunks_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if c["chunk_id"] == chunk_id:
                return c
    return None


def _run_one(chunk: dict, template: str, ollama_url: str, profile: dict) -> dict:
    obligation_verbs_str = ", ".join(profile["obligation_verbs"])
    filled = template.replace("{obligation_verbs}", obligation_verbs_str)
    _, valid_reqs, failure = process_chunk(
        chunk, MODEL, ollama_url, timeout=120,
        prompt_template=filled, json_schema=_PASS1_FORMAT_SCHEMA,
        valid_domain_tags=profile["domain_tags"],
        valid_requirement_types=profile["requirement_types"],
    )
    return {
        "count": len(valid_reqs),
        "quotes": [r["source_quote"] for r in valid_reqs],
        "failure": failure,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="WP-33.3 actionability spike A/B test")
    parser.add_argument(
        "--ollama-url", default="http://localhost:11434",
        help="Ollama API base URL. Defaults to localhost, which resolves to this "
             "container, not a real Ollama host -- always pass this explicitly "
             "(matches every other pipeline script's convention).",
    )
    parser.add_argument(
        "--processed-dir", default=str(Path.home() / "documents/processed"),
        help="Directory holding <doc>_chunks.jsonl (default: ~/documents/processed)",
    )
    args = parser.parse_args()

    processed = Path(args.processed_dir)
    profile = default_profile()
    out_dir = _ROOT / "eval" / "spike_results" / "wp_33_3"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_results = []
    for group_name, targets in [("known_bad", KNOWN_BAD_CHUNKS), ("known_good", KNOWN_GOOD_CHUNKS)]:
        for label, run_dir, stem, chunk_id, note in targets:
            chunks_path = processed / run_dir / f"{stem}_chunks.jsonl"
            chunk = _get_chunk(chunks_path, chunk_id)
            if chunk is None:
                print(f"SKIP {label}: chunk {chunk_id} not found in {chunks_path}", file=sys.stderr)
                continue
            print(f"Running {label} (chunk_id={chunk_id})...", file=sys.stderr)
            baseline = _run_one(chunk, PASS1_PROMPT_TEMPLATE, args.ollama_url, profile)
            revised = _run_one(chunk, REVISED_TEMPLATE, args.ollama_url, profile)
            record = {
                "label": label, "group": group_name, "chunk_id": chunk_id,
                "stem": stem, "note": note,
                "baseline": baseline, "revised": revised,
            }
            all_results.append(record)
            (out_dir / f"{label}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    report_lines = [
        "# WP-33.3 Actionability Spike — Prompt A/B Test Results",
        "",
        "Generated by `eval/actionability_spike.py`. See "
        "`docs/PHASE33_REQUIREMENTS.md`'s WP-33.3 Findings for interpretation "
        "and the full hand-labeled corpus analysis this smoke test supports.",
        "",
        "**Caveat:** Ollama generation is not perfectly deterministic even at "
        "temperature 0.1 on this quantized model -- re-running this script will "
        "not reproduce these exact quotes/counts. The qualitative pattern is "
        "the evidence, not the specific numbers.",
        "",
    ]
    for r in all_results:
        report_lines.append(f"## {r['label']} ({r['group']}, chunk_id={r['chunk_id']})")
        report_lines.append(f"\n{r['note']}\n")
        for tname in ("baseline", "revised"):
            res = r[tname]
            report_lines.append(f"**{tname.upper()}: {res['count']} requirement(s)**")
            for q in res["quotes"]:
                report_lines.append(f"- {q!r}")
            report_lines.append("")
    (out_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Wrote {out_dir / 'report.md'}", file=sys.stderr)


if __name__ == "__main__":
    main()
