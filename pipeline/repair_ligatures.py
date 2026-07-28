#!/usr/bin/env python3
"""Standalone repair pass for a known PDF ligature-encoding defect.

Not part of the default ingest pipeline (run_pipeline.py never imports or calls
this) -- it targets one confirmed, document-specific font defect, not general
garbled-text repair. See docs/PHASE32_REQUIREMENTS.md's WP-32.2 findings for the
full investigation: NIST.SP.800-53Ar5.pdf's embedded font has no ToUnicode CMap
entry for its "ti"/"tt"/"ft"/"tf" ligature glyphs, so every extraction backend
(docling, pymupdf, pdfplumber -- confirmed empirically, all three) substitutes a
Private Use Area character instead of the real two-character sequence.

Usage: re-ingest normally through Step B (chunking), then run this against the
resulting *_chunks.jsonl before Step C (LLM extraction) sees it:

    python3 cli/reqbot.py ingest "raw_pdfs/NIST.SP.800-53Ar5.pdf" \\
        --layout-mode docling --no-index
    python3 pipeline/repair_ligatures.py \\
        ~/documents/processed/NIST.SP.800-53Ar5_.../NIST.SP.800-53Ar5_chunks.jsonl
    python3 cli/reqbot.py ingest "raw_pdfs/NIST.SP.800-53Ar5.pdf" --skip-to C \\
        --output-dir ~/documents/processed/NIST.SP.800-53Ar5_...

Input:  a *_chunks.jsonl file (Step B output).
Output: the same file, repaired in place (or to -o/--output if given).
"""

import argparse
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

# Confirmed by direct inspection of NIST.SP.800-53Ar5.pdf's raw extracted text
# (docs/PHASE32_REQUIREMENTS.md, WP-32.2 Findings) -- each codepoint is a
# distinct font glyph ID with no ToUnicode entry, resolved by reading the
# surrounding word context (e.g. U+E001 sits between "a" and "ributes" in
# "attributes").
KNOWN_LIGATURE_REPAIRS: dict[str, str] = {
    "\ue000": "ti",  # ligature glyph, one of five distinct IDs found
    "\ue001": "tt",
    "\ue002": "ft",
    "\ue003": "tt",  # second glyph ID for the same ligature
    "\ue004": "tf",
}


def repair_text(text: str) -> str:
    """Replace known bad ligature codepoints with their real characters."""
    for bad, good in KNOWN_LIGATURE_REPAIRS.items():
        text = text.replace(bad, good)
    return text


def repair_record(record: dict) -> tuple[dict, int]:
    """Repair every string (and list-of-string) field in a chunk record.

    Returns the repaired record and how many characters were replaced, so
    callers can report a real count rather than just "some chunks changed".
    """
    repaired = {}
    replaced = 0
    for key, value in record.items():
        if isinstance(value, str):
            hits = sum(value.count(bad) for bad in KNOWN_LIGATURE_REPAIRS)
            replaced += hits
            repaired[key] = repair_text(value) if hits else value
        elif isinstance(value, list):
            new_list = []
            for v in value:
                if isinstance(v, str):
                    hits = sum(v.count(bad) for bad in KNOWN_LIGATURE_REPAIRS)
                    replaced += hits
                    new_list.append(repair_text(v) if hits else v)
                else:
                    new_list.append(v)
            repaired[key] = new_list
        else:
            repaired[key] = value
    return repaired, replaced


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(records: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(chunks_path: str, output_path: str | None = None) -> str:
    """Repair known ligature corruption in a *_chunks.jsonl file.

    Args:
        chunks_path: Path to the input *_chunks.jsonl (Step B output).
        output_path: Where to write the repaired file. Defaults to
            overwriting chunks_path in place.

    Returns:
        output_path (str) -- the file that was written.
    """
    in_path = Path(chunks_path).resolve()
    out_path = Path(output_path).resolve() if output_path else in_path

    records = load_jsonl(in_path)
    repaired_records = []
    total_replaced = 0
    chunks_touched = 0
    for record in records:
        repaired, replaced = repair_record(record)
        repaired_records.append(repaired)
        if replaced:
            total_replaced += replaced
            chunks_touched += 1

    write_jsonl(repaired_records, out_path)
    log.info(
        "Repaired %d ligature character(s) across %d/%d chunk(s) -- wrote %s",
        total_replaced, chunks_touched, len(records), out_path,
    )
    if total_replaced == 0:
        log.warning(
            "No known-bad ligature characters found -- this file may not need "
            "repair, or may contain a different corruption pattern not covered "
            "by KNOWN_LIGATURE_REPAIRS."
        )
    return str(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Repair known PDF ligature-encoding corruption "
            "(Private Use Area characters) in a *_chunks.jsonl file."
        )
    )
    parser.add_argument("chunks_jsonl", type=str, help="Path to *_chunks.jsonl (Step B output)")
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output path (default: overwrite chunks_jsonl in place)",
    )
    args = parser.parse_args()

    chunks_path = Path(args.chunks_jsonl)
    if not chunks_path.exists():
        log.error("File not found: %s", chunks_path)
        sys.exit(1)

    run(str(chunks_path), args.output)


if __name__ == "__main__":
    main()
