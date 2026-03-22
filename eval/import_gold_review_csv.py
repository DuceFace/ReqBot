#!/usr/bin/env python3
"""WP-3.3: Import human-reviewed CSV back into gold eval JSONL.

Reads:
  eval/gold_eval_chunks_review.csv     — human-edited review file from Excel
  eval/gold_eval_chunks_curated.jsonl  — existing curated JSONL (merge base)

Writes:
  eval/gold_eval_chunks_curated.jsonl  — updated gold set (in-place by default)

Behavior:
  - Rows where review_status == "skip" are left unchanged in the JSONL.
  - All other rows update gold_requirements from curated_requirements_json.
  - corrector_notes is updated for all non-skip rows.
  - Rows in the JSONL not present in the CSV are preserved unchanged.
  - Fails clearly on malformed JSON or invalid requirement schema.

Validation rules for each requirement object:
  - Must be a JSON object (not a string, number, etc.)
  - Allowed fields: source_quote, source_ref (no others)
  - source_quote: required, non-empty string
  - source_ref: optional string (may be empty)

Usage:
    python3 eval/import_gold_review_csv.py [--dry-run] [--strict] [options]

    --dry-run   Validate CSV and report what would change; do not write output.
    --strict    Abort on the first validation error instead of collecting all errors.

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

# Only these fields are permitted inside a gold requirement object
_ALLOWED_REQ_FIELDS = {"source_quote", "source_ref"}


class _ValidationError(Exception):
    """Raised when a CSV row fails validation."""


def _validate_requirement(req: object, row_num: int, req_idx: int) -> dict:
    """Validate and normalize one requirement object.

    Returns a clean dict with exactly source_quote and source_ref.
    Raises _ValidationError on any problem.
    """
    if not isinstance(req, dict):
        raise _ValidationError(
            f"Row {row_num}, requirement[{req_idx}]: expected a JSON object, "
            f"got {type(req).__name__!r}"
        )

    extra = set(req.keys()) - _ALLOWED_REQ_FIELDS
    if extra:
        raise _ValidationError(
            f"Row {row_num}, requirement[{req_idx}]: unexpected fields {sorted(extra)} — "
            f"only 'source_quote' and 'source_ref' are allowed"
        )

    quote = req.get("source_quote")
    if not isinstance(quote, str) or not quote.strip():
        raise _ValidationError(
            f"Row {row_num}, requirement[{req_idx}]: "
            f"source_quote must be a non-empty string"
        )

    ref = req.get("source_ref", "")
    if not isinstance(ref, str):
        raise _ValidationError(
            f"Row {row_num}, requirement[{req_idx}]: source_ref must be a string"
        )

    return {"source_quote": quote.strip(), "source_ref": ref}


def _parse_curated_requirements(cell: str, row_num: int) -> list[dict]:
    """Parse and validate the curated_requirements_json cell.

    Returns a list of validated requirement dicts.
    Raises _ValidationError on any problem.
    """
    cell = cell.strip()
    if not cell or cell == "[]":
        return []

    try:
        data = json.loads(cell)
    except json.JSONDecodeError as e:
        raise _ValidationError(
            f"Row {row_num}, curated_requirements_json: invalid JSON — {e}\n"
            f"  Value (first 300 chars): {cell[:300]!r}"
        )

    if not isinstance(data, list):
        raise _ValidationError(
            f"Row {row_num}, curated_requirements_json: expected a JSON array, "
            f"got {type(data).__name__!r}"
        )

    return [_validate_requirement(r, row_num, i) for i, r in enumerate(data)]


def _load_curated_jsonl(path: Path) -> dict[tuple[str, int], dict]:
    """Load the curated JSONL into an ordered dict keyed by (source_pdf, chunk_id).

    Returns empty dict (not an error) if the file does not exist yet.
    """
    records: dict[tuple[str, int], dict] = {}
    if not path.exists():
        log.warning("Curated JSONL not found: %s — starting from empty", path)
        return records
    try:
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    log.warning("Skipping malformed JSON at line %d: %s", lineno, e)
                    continue
                try:
                    chunk_id = int(rec.get("chunk_id", -1))
                except (TypeError, ValueError):
                    log.warning("Skipping record with invalid chunk_id at line %d", lineno)
                    continue
                key = (rec.get("source_pdf", ""), chunk_id)
                records[key] = rec
    except OSError as e:
        log.error("Cannot read %s: %s", path, e)
        sys.exit(1)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import human-reviewed CSV back into gold eval JSONL"
    )
    parser.add_argument(
        "--csv-file",
        default="eval/gold_eval_chunks_review.csv",
        help="Input CSV file (default: eval/gold_eval_chunks_review.csv)",
    )
    parser.add_argument(
        "--curated-file",
        default="eval/gold_eval_chunks_curated.jsonl",
        help="Curated JSONL to update (default: eval/gold_eval_chunks_curated.jsonl)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSONL path (default: same as --curated-file, i.e. in-place)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate CSV and report changes; do not write output",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on the first validation error (default: collect all errors then fail)",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    curated_path = Path(args.curated_file)
    out_path = Path(args.output) if args.output else curated_path

    if not csv_path.exists():
        log.error("CSV file not found: %s", csv_path)
        sys.exit(1)

    # Load the existing JSONL as the merge base (preserves order and unreviewed records)
    curated = _load_curated_jsonl(curated_path)
    log.info("Loaded %d existing records from %s", len(curated), curated_path)

    # Parse and validate every row in the CSV
    errors: list[str] = []
    # updates: keys to apply, with validated requirements and notes
    updates: dict[tuple[str, int], dict] = {}
    n_skipped = 0
    n_missing = 0

    _REQUIRED_CSV_COLS = {"source_pdf", "chunk_id", "curated_requirements_json"}

    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)

            if reader.fieldnames is None:
                log.error("CSV appears to be empty: %s", csv_path)
                sys.exit(1)

            missing_cols = _REQUIRED_CSV_COLS - set(reader.fieldnames)
            if missing_cols:
                log.error(
                    "CSV is missing required columns: %s", sorted(missing_cols)
                )
                sys.exit(1)

            for row_num, row in enumerate(reader, start=2):  # row 1 is header
                status = (row.get("review_status") or "").strip().lower()
                if status == "skip":
                    n_skipped += 1
                    continue

                source_pdf = (row.get("source_pdf") or "").strip()

                # Excel sometimes converts integers to floats (e.g. "23" → "23.0")
                raw_chunk_id = (row.get("chunk_id") or "").strip()
                try:
                    chunk_id = int(float(raw_chunk_id))
                except (ValueError, TypeError):
                    msg = (
                        f"Row {row_num}: invalid chunk_id {raw_chunk_id!r} "
                        f"(source_pdf={source_pdf!r})"
                    )
                    if args.strict:
                        log.error(msg)
                        sys.exit(1)
                    errors.append(msg)
                    continue

                key = (source_pdf, chunk_id)
                if key not in curated:
                    log.warning(
                        "Row %d: (%s, chunk_id=%d) not found in JSONL — skipping",
                        row_num, source_pdf, chunk_id,
                    )
                    n_missing += 1
                    continue

                cell = (row.get("curated_requirements_json") or "").strip()
                try:
                    reqs = _parse_curated_requirements(cell, row_num)
                except _ValidationError as e:
                    if args.strict:
                        log.error("%s", e)
                        sys.exit(1)
                    errors.append(str(e))
                    continue

                updates[key] = {
                    "gold_requirements": reqs,
                    "corrector_notes": (row.get("corrector_notes") or "").strip(),
                }

    except OSError as e:
        log.error("Cannot read %s: %s", csv_path, e)
        sys.exit(1)

    # Report all collected validation errors
    if errors:
        log.error("Validation failed — %d error(s) found:", len(errors))
        for err in errors:
            log.error("  %s", err)
        log.error("Fix the CSV and re-run. No output written.")
        sys.exit(1)

    log.info(
        "CSV parsed: %d rows to update, %d skipped (review_status=skip), "
        "%d not found in JSONL",
        len(updates), n_skipped, n_missing,
    )

    if args.dry_run:
        log.info("Dry run — no files written. Changes that would be applied:")
        for key, upd in sorted(updates.items()):
            source_pdf, chunk_id = key
            orig_n = len(curated[key].get("gold_requirements", []))
            new_n = len(upd["gold_requirements"])
            delta = f"{orig_n} → {new_n}" if orig_n != new_n else f"{new_n} (unchanged count)"
            log.info("  %s chunk_id=%-4d  requirements: %s", source_pdf, chunk_id, delta)
        return

    # Apply updates (in-memory; curated dict still has original data until we write)
    n_req_changes = 0
    for key, upd in updates.items():
        orig_n = len(curated[key].get("gold_requirements", []))
        new_n = len(upd["gold_requirements"])
        if orig_n != new_n:
            n_req_changes += 1
        curated[key]["gold_requirements"] = upd["gold_requirements"]
        curated[key]["corrector_notes"] = upd["corrector_notes"]

    # Write output JSONL in original insertion order
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for rec in curated.values():
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    log.info(
        "Wrote %d records to %s "
        "(%d chunks updated, %d with requirement count changes)",
        len(curated), out_path, len(updates), n_req_changes,
    )
    log.info(
        "Re-export to CSV anytime with: python3 eval/export_gold_review_csv.py"
    )


if __name__ == "__main__":
    main()
