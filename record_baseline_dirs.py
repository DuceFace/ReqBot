#!/usr/bin/env python3
"""WP-14.4 pre-step: record baseline artifact directories before re-ingest.

Writes docs/phase14_baseline_dirs.txt with one row per processed directory,
including the requirement count from the best available JSONL (enriched >
normalized). Run once before starting WP-14.4 re-ingestion.

Usage:
    python3 record_baseline_dirs.py
"""

import json
import sys
from pathlib import Path

PROCESSED_DIR = Path.home() / "documents" / "processed"
OUTPUT_FILE = Path(__file__).resolve().parent / "docs" / "phase14_baseline_dirs.txt"


def count_requirements(dir_path: Path) -> tuple[int, str]:
    """Return (count, source_file_name) from best available JSONL in dir."""
    for pattern in ("*_requirements_enriched.jsonl", "*_requirements_normalized.jsonl"):
        candidates = sorted(dir_path.glob(pattern))
        if candidates:
            path = candidates[-1]
            count = sum(1 for line in path.read_text().splitlines() if line.strip())
            return count, path.name
    return 0, "(no requirements file)"


def parse_stem(dir_name: str) -> str:
    """Extract document stem by stripping trailing _YYYYMMDD_HHMMSS."""
    parts = dir_name.rsplit("_", 2)
    if len(parts) == 3 and len(parts[1]) == 8 and len(parts[2]) == 6:
        try:
            int(parts[1])
            int(parts[2])
            return parts[0]
        except ValueError:
            pass
    return dir_name


def main() -> None:
    if not PROCESSED_DIR.exists():
        print(f"ERROR: {PROCESSED_DIR} does not exist", file=sys.stderr)
        sys.exit(1)

    dirs = sorted(d for d in PROCESSED_DIR.iterdir() if d.is_dir())
    if not dirs:
        print("ERROR: no directories found in processed dir", file=sys.stderr)
        sys.exit(1)

    rows = []
    total_reqs = 0
    for d in dirs:
        count, src = count_requirements(d)
        total_reqs += count
        rows.append((d.name, parse_stem(d.name), count, src))

    lines = [
        "# Phase 14 Baseline Artifact Snapshot",
        "# Recorded before WP-14.4 re-ingest",
        "# Format: directory | doc_stem | req_count | source_file",
        "#",
        f"# Total directories: {len(dirs)}",
        f"# Total requirements: {total_reqs}",
        "#",
    ]
    for dir_name, stem, count, src in rows:
        lines.append(f"{dir_name} | {stem} | {count} | {src}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(rows)} entries to {OUTPUT_FILE}")
    print(f"Total baseline requirements: {total_reqs:,}")


if __name__ == "__main__":
    main()
