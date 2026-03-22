#!/usr/bin/env python3
"""WP-3.3: Export gold eval chunks to CSV for Excel-based human review.

Reads:
  eval/gold_eval_chunks_curated.jsonl   — working gold set (curated_requirements_json)
  eval/gold_eval_chunks_seeded.jsonl    — original seeded set (seeded_requirements_pretty)

Writes:
  eval/gold_eval_chunks_review.csv

Columns:
  review_status              — set to "done" when reviewed, "skip" to leave unchanged on import
  source_pdf                 — e.g. "NIST.SP.800-53r5.pdf"
  document_class             — nist_sp | dodi_dodm | afi_daf
  density_tier               — zero | medium | high
  processed_run_dir          — pinned artifact path (read-only reference)
  chunk_id                   — integer chunk index within document
  page_start                 — starting page in source PDF
  page_end                   — ending page in source PDF
  chunk_text                 — verbatim chunk text (read-only reference)
  seeded_requirements_pretty — human-readable display of original Step C output (read-only)
  curated_requirements_json  — JSON array; edit this column to correct requirements
  corrector_notes            — free-text notes on non-obvious decisions

Workflow:
  1. Run this script to produce the CSV.
  2. Open in Excel, review chunk_text vs seeded_requirements_pretty.
  3. Edit curated_requirements_json to correct requirements.
     Format: [{"source_quote": "...", "source_ref": "..."}]
     Use [] for chunks with no real requirements.
  4. Set review_status to "done" for each reviewed row (or "skip" to leave unchanged).
  5. Run eval/import_gold_review_csv.py to write corrections back to JSONL.

Usage:
    python3 eval/export_gold_review_csv.py [options]

Run from the repo root.
"""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

CSV_COLUMNS = [
    "review_status",
    "source_pdf",
    "document_class",
    "density_tier",
    "processed_run_dir",
    "chunk_id",
    "page_start",
    "page_end",
    "chunk_text",
    "seeded_requirements_pretty",
    "curated_requirements_json",
    "corrector_notes",
]


def format_requirements_pretty(reqs: list[dict]) -> str:
    """Format requirements as human-readable text for the reference column."""
    if not reqs:
        return "(none)"
    lines = []
    for i, req in enumerate(reqs, 1):
        quote = req.get("source_quote", "").strip()
        ref = req.get("source_ref", "").strip()
        lines.append(f"[{i}] {quote}")
        if ref:
            lines.append(f"    ref: {ref}")
    return "\n".join(lines)


def load_jsonl(path: Path) -> dict[tuple[str, int], dict]:
    """Load JSONL into an ordered dict keyed by (source_pdf, chunk_id).

    Preserves file order so export and import use the same ordering.
    """
    records: dict[tuple[str, int], dict] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    log.warning("Skipping malformed JSON at %s line %d: %s", path, lineno, e)
                    continue
                try:
                    chunk_id = int(rec.get("chunk_id", -1))
                except (TypeError, ValueError):
                    log.warning("Skipping record with invalid chunk_id at %s line %d", path, lineno)
                    continue
                key = (rec.get("source_pdf", ""), chunk_id)
                records[key] = rec
    except OSError as e:
        log.error("Cannot read %s: %s", path, e)
        sys.exit(1)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export gold eval chunks to CSV for human review"
    )
    parser.add_argument(
        "--curated-file",
        default="eval/gold_eval_chunks_curated.jsonl",
        help="Curated JSONL (default: eval/gold_eval_chunks_curated.jsonl)",
    )
    parser.add_argument(
        "--seeded-file",
        default="eval/gold_eval_chunks_seeded.jsonl",
        help="Original seeded JSONL for read-only reference column "
             "(default: eval/gold_eval_chunks_seeded.jsonl)",
    )
    parser.add_argument(
        "--output",
        default="eval/gold_eval_chunks_review.csv",
        help="Output CSV path (default: eval/gold_eval_chunks_review.csv)",
    )
    args = parser.parse_args()

    curated_path = Path(args.curated_file)
    seeded_path = Path(args.seeded_file)
    out_path = Path(args.output)

    if not curated_path.exists():
        log.error("Curated file not found: %s", curated_path)
        sys.exit(1)

    # Load seeded for the read-only reference column (warn but don't fail if absent)
    seeded_records: dict[tuple[str, int], dict] = {}
    if seeded_path.exists():
        seeded_records = load_jsonl(seeded_path)
        log.info("Loaded %d seeded records from %s", len(seeded_records), seeded_path)
    else:
        log.warning(
            "Seeded file not found (%s) — seeded_requirements_pretty column will be empty",
            seeded_path,
        )

    curated_records = load_jsonl(curated_path)
    log.info("Loaded %d curated records from %s", len(curated_records), curated_path)

    if not curated_records:
        log.error("No records found in %s", curated_path)
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # utf-8-sig writes a BOM so Excel opens the file correctly without an import wizard
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()

        # Sort: document_class → source_pdf → chunk_id for a consistent review order
        sorted_keys = sorted(
            curated_records.keys(),
            key=lambda k: (
                curated_records[k].get("document_class", ""),
                k[0],   # source_pdf
                k[1],   # chunk_id
            ),
        )

        for key in sorted_keys:
            rec = curated_records[key]
            seeded_rec = seeded_records.get(key, {})
            seeded_reqs = seeded_rec.get("gold_requirements", [])
            curated_reqs = rec.get("gold_requirements", [])

            writer.writerow({
                "review_status": "",
                "source_pdf": rec.get("source_pdf", ""),
                "document_class": rec.get("document_class", ""),
                "density_tier": rec.get("density_tier", ""),
                "processed_run_dir": rec.get("processed_run_dir", ""),
                "chunk_id": rec.get("chunk_id", ""),
                "page_start": rec.get("page_start", ""),
                "page_end": rec.get("page_end", ""),
                "chunk_text": rec.get("chunk_text", ""),
                "seeded_requirements_pretty": format_requirements_pretty(seeded_reqs),
                "curated_requirements_json": json.dumps(curated_reqs, ensure_ascii=False),
                "corrector_notes": rec.get("corrector_notes", ""),
            })

    log.info("Wrote %d rows to %s", len(sorted_keys), out_path)
    log.info("")
    log.info("Next steps:")
    log.info("  1. Open %s in Excel", out_path)
    log.info("  2. For each row: read chunk_text, compare seeded_requirements_pretty")
    log.info("  3. Edit curated_requirements_json to correct — format:")
    log.info('     [{"source_quote": "...", "source_ref": "..."}]')
    log.info("     Use [] for chunks with no real requirements")
    log.info('  4. Set review_status to "done"; use "skip" to leave a row unchanged')
    log.info("  5. Run: python3 eval/import_gold_review_csv.py")


if __name__ == "__main__":
    main()
