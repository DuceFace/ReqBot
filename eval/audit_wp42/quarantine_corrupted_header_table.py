#!/usr/bin/env python3
"""WP-42: quarantine the non-verbatim records from afi17-203's corrupted-header table.

docs/PHASE42_REQUIREMENTS.md documents a residual, out-of-scope defect: Docling's own
table-structure model merges the caption of afi17-203's "Table 3.2. Incident Handling
and Support Activities" into every header cell (confirmed directly against the raw PDF,
not introduced by this project's code). Feeding Step C this cleaner-but-still-header-
confused table caused it to synthesize records that aren't verbatim substrings of their
chunk text -- light paraphrases of real table content, not wild fabrication (the worst
case, an echoed few-shot example, was already caught and rejected by the existing
WP-32.1 grounding gate). Tyler's call (2026-08-02): the project principle is
source_quote must be verbatim source text, full stop -- a paraphrase may be a fine
*description*, never a *source_quote*. Exclude these specifically rather than loosen or
touch the shared grounding threshold.

Updated once (2026-08-02) after a second WP-42 fix: the initial chunk_text.py change
re-exported this table's full markdown on every one of the multiple chunks HybridChunker
splits it across (Codex review, PR #189), so the whole document was re-ingested a second
time and this script's target run directory / ids were refreshed to match. The table now
appears exactly once (chunk_id=50, up from the never-deduplicated original), and produces
2 non-verbatim records instead of the first run's 3 -- same known defect, re-measured
against corrected input.

Run once, by hand, against the specific re-ingested run this WP produced. Not part of
the regular pipeline -- this is a one-off, documented data curation step for a known,
narrow, already-diagnosed residual, not a general-purpose filter.
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

GATED_PATH = Path(
    "/home/coder/documents/processed/afi17-203_20260802_021910/afi17-203_requirements_gated.jsonl"
)
QUARANTINE_IDS = {"REQ-42109df01628", "REQ-8d7abe4ebef4"}


def main() -> None:
    if not GATED_PATH.exists():
        raise SystemExit(f"Not found: {GATED_PATH}")

    records = [json.loads(line) for line in GATED_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = [r for r in records if r["requirement_id"] not in QUARANTINE_IDS]
    removed = [r for r in records if r["requirement_id"] in QUARANTINE_IDS]

    if len(removed) != len(QUARANTINE_IDS):
        found = {r["requirement_id"] for r in removed}
        missing = QUARANTINE_IDS - found
        raise SystemExit(f"Expected to remove {len(QUARANTINE_IDS)}, found {len(removed)}. Missing: {missing}")

    for r in removed:
        print(f"QUARANTINED: {r['requirement_id']} (chunk {r['chunk_id']}) — {r['source_quote']!r}")

    with open(GATED_PATH, "w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(kept)} records (was {len(records)}) to {GATED_PATH}")


if __name__ == "__main__":
    main()
