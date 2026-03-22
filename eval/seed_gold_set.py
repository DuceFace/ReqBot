#!/usr/bin/env python3
"""WP-3 R-3.2: Seed gold_requirements from existing Step C output.

Reads a gold_eval_chunks.jsonl produced by select_eval_chunks.py (which has
empty gold_requirements arrays), looks up the matching
*_extracted_requirements.jsonl for each record, and populates
gold_requirements with the Step C extractions as a starting point for
hand-correction.

R-3.2 says: "start from existing Step C output and correct errors — do not
extract from scratch."  This script performs the join; no LLM calls are made.

Only fields relevant to the Pass 1 gold target are carried over:
  {source_quote, source_ref}

Records whose Step C output file cannot be found are written with an empty
gold_requirements and a corrector_notes warning so they can be handled
manually.

Usage:
    python3 eval/seed_gold_set.py [--gold eval/gold_eval_chunks.jsonl] \
        [--output eval/gold_eval_chunks_seeded.jsonl] \
        [--processed-dir ~/documents/processed]

Run from the repo root.
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def glob_escape(s: str) -> str:
    return s.replace("[", "[[]").replace("?", "[?]")


def find_most_recent_dir(processed_dir: Path, stem: str) -> Path | None:
    """Return the most recently timestamped output dir for a stem."""
    candidates = sorted(
        processed_dir.glob(f"{glob_escape(stem)}_????????_??????"),
        reverse=True,
    )
    for d in candidates:
        if (d / f"{stem}_extracted_requirements.jsonl").exists():
            return d
    return None


def load_step_c_by_chunk(reqs_path: Path) -> dict[int, list[dict]]:
    """Return {chunk_id: [{"source_quote": ..., "source_ref": ...}, ...]} from Step C JSONL.

    Only carries the two Pass 1 fields — description, domain_tags, etc. are
    enrichment fields and are out of scope for the gold eval (R-3.3).
    Uses Step C extracted output (pre-normalization) per Codex note on R-4.2.
    """
    by_chunk: dict[int, list[dict]] = defaultdict(list)
    if not reqs_path.exists():
        return by_chunk
    try:
        with open(reqs_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cid = rec.get("chunk_id")
                if cid is None:
                    continue
                sq = rec.get("source_quote", "").strip()
                sr = rec.get("source_ref", "").strip()
                # Only include records with at least a non-empty source_quote
                if sq:
                    by_chunk[int(cid)].append({
                        "source_quote": sq,
                        "source_ref": sr,
                    })
    except OSError as e:
        log.warning("Could not read %s: %s", reqs_path, e)
    return by_chunk


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed gold_requirements from Step C output for WP-3 curation"
    )
    parser.add_argument(
        "--gold",
        default="eval/gold_eval_chunks.jsonl",
        help="Input gold JSONL from select_eval_chunks.py (default: eval/gold_eval_chunks.jsonl)",
    )
    parser.add_argument(
        "--output",
        default="eval/gold_eval_chunks_seeded.jsonl",
        help="Output seeded JSONL for hand-correction (default: eval/gold_eval_chunks_seeded.jsonl)",
    )
    parser.add_argument(
        "--processed-dir",
        default=None,
        help="Pipeline processed output directory (default: ~/documents/processed or config value)",
    )
    args = parser.parse_args()

    gold_path = Path(args.gold)
    if not gold_path.exists():
        log.error("Gold file not found: %s — run select_eval_chunks.py first", gold_path)
        sys.exit(1)

    # Resolve processed dir
    if args.processed_dir:
        processed_dir = Path(args.processed_dir).expanduser().resolve()
    else:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            import config as _cfg_mod
            cfg = _cfg_mod.load()
            processed_dir = cfg.processed_dir_path()
        except Exception:
            processed_dir = Path("~/documents/processed").expanduser().resolve()

    if not processed_dir.exists():
        log.error("Processed directory not found: %s", processed_dir)
        sys.exit(1)

    # Load gold records
    gold_records: list[dict] = []
    with open(gold_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    gold_records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    log.info("Loaded %d gold chunk records from %s", len(gold_records), gold_path)

    # Cache Step C output per stem (avoid re-reading the same file for each chunk).
    # Use processed_run_dir pinned at selection time (P1 fix, Codex review) so
    # re-ingest of a document does not silently change what the seeder reads.
    # Falls back to find_most_recent_dir only for gold records that predate the fix.
    step_c_cache: dict[str, dict[int, list[dict]]] = {}
    missing_stems: set[str] = set()

    stats = {"seeded": 0, "empty_model_output": 0, "missing_file": 0}
    out_records: list[dict] = []

    for rec in gold_records:
        stem = rec.get("stem", "")
        chunk_id = rec.get("chunk_id")

        if stem not in step_c_cache:
            pinned_dir = rec.get("processed_run_dir")
            if pinned_dir:
                out_dir: Path | None = Path(pinned_dir)
                if not out_dir.exists():
                    log.warning(
                        "Pinned processed_run_dir no longer exists for '%s': %s — "
                        "falling back to most-recent discovery",
                        stem, pinned_dir,
                    )
                    out_dir = find_most_recent_dir(processed_dir, stem)
            else:
                out_dir = find_most_recent_dir(processed_dir, stem)

            if out_dir is None:
                missing_stems.add(stem)
                step_c_cache[stem] = {}
            else:
                reqs_path = out_dir / f"{stem}_extracted_requirements.jsonl"
                step_c_cache[stem] = load_step_c_by_chunk(reqs_path)
                log.debug(
                    "Loaded Step C output for '%s': %d chunks with requirements",
                    stem, len(step_c_cache[stem]),
                )

        by_chunk = step_c_cache[stem]
        reqs = by_chunk.get(int(chunk_id) if chunk_id is not None else -1, [])

        out_rec = dict(rec)
        if stem in missing_stems:
            out_rec["gold_requirements"] = []
            out_rec["corrector_notes"] = (
                "[SEED ERROR] Step C output file not found for this document. "
                "Requires manual extraction from chunk_text."
            )
            stats["missing_file"] += 1
        elif not reqs:
            out_rec["gold_requirements"] = []
            # Preserve any existing notes; add a marker if chunk produced nothing
            existing_notes = out_rec.get("corrector_notes", "")
            if not existing_notes:
                out_rec["corrector_notes"] = (
                    "[MODEL: empty] Step C produced no requirements for this chunk. "
                    "Verify this is correct (zero-density chunk) or add missing ones."
                )
            stats["empty_model_output"] += 1
        else:
            out_rec["gold_requirements"] = reqs
            stats["seeded"] += 1

        out_records.append(out_rec)

    if missing_stems:
        log.warning(
            "Step C output not found for %d stem(s): %s",
            len(missing_stems), sorted(missing_stems),
        )

    # Write seeded output
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for rec in out_records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    log.info("Wrote %d seeded records to %s", len(out_records), out_path)
    log.info(
        "Seeding stats — seeded: %d  empty model output: %d  missing file: %d",
        stats["seeded"], stats["empty_model_output"], stats["missing_file"],
    )
    log.info(
        "Next step: hand-correct %s, then run eval_harness.py", out_path
    )


if __name__ == "__main__":
    main()
