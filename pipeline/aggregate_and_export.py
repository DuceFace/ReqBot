#!/usr/bin/env python3
"""Step E: Aggregate normalized requirements and export final outputs.

Input:  requirements_normalized.jsonl (from Step D)
        Optionally: pages.jsonl, chunks.jsonl, parse_failures.jsonl for stats
Output:
  - final_output.json — complete document with metadata and all requirements
  - stats.json — pipeline metrics (counts, rates, etc.)

This step is deterministic aggregation.
"""

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def load_jsonl(path: Path) -> list[dict]:
    """Load records from a JSONL file. Returns empty list if file doesn't exist."""
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def count_lines(path: Path) -> int:
    """Count non-empty lines in a file."""
    if not path.exists():
        return 0
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def run(requirements_jsonl: str, output_dir: str, source_pdf: str = "") -> dict:
    """Aggregate normalized requirements and write final_output.json and stats.json.

    Callable interface for in-process use by run_pipeline.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        requirements_jsonl: Path to requirements_normalized.jsonl from Step D.
        output_dir:         Directory to write output files into.
        source_pdf:         Original PDF filename for metadata (optional).

    Returns:
        stats dict — the same content written to stats.json.
    """
    reqs_path = Path(requirements_jsonl).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = reqs_path.stem.replace("_requirements_normalized", "")

    pages_path = reqs_path.parent / f"{stem}_pages.jsonl"
    chunks_path = reqs_path.parent / f"{stem}_chunks.jsonl"
    raw_resp_path = reqs_path.parent / f"{stem}_raw_responses.jsonl"
    parse_fail_path = reqs_path.parent / f"{stem}_parse_failures.jsonl"
    norm_fail_path = reqs_path.parent / f"{stem}_normalization_failures.jsonl"

    log.info("Loading normalized requirements from: %s", reqs_path)
    requirements = load_jsonl(reqs_path)
    log.info("Loaded %d requirements", len(requirements))

    page_count = count_lines(pages_path)
    chunk_count = count_lines(chunks_path)
    raw_response_count = count_lines(raw_resp_path)
    parse_failure_count = count_lines(parse_fail_path)
    norm_failure_count = count_lines(norm_fail_path)

    total_chars = 0
    if pages_path.exists():
        pages = load_jsonl(pages_path)
        total_chars = sum(len(p.get("text", "")) for p in pages)

    confidence_values = [r.get("confidence", 0) for r in requirements]
    avg_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0

    tag_counts: Counter = Counter()
    for r in requirements:
        for tag in r.get("domain_tags", []):
            tag_counts[tag] += 1

    tagged_count = sum(1 for r in requirements if r.get("domain_tags"))
    untagged_count = len(requirements) - tagged_count

    type_counts: Counter = Counter()
    for r in requirements:
        type_counts[r.get("requirement_type", "unknown")] += 1

    source_refs = [r.get("source_ref", "") for r in requirements]
    has_source_ref = sum(1 for s in source_refs if s)
    unique_source_refs = len(set(s for s in source_refs if s))

    # Hierarchy coverage (WP-14.3) — meaningful only for Docling-path artifacts
    with_section_path = sum(1 for r in requirements if r.get("section_ref_path"))
    with_parent_context = sum(1 for r in requirements if r.get("parent_context"))
    hierarchy_coverage_pct = round(
        with_section_path / len(requirements) * 100 if requirements else 0.0, 1
    )

    final_output = {
        "metadata": {
            "source_pdf": source_pdf or stem,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_version": "2.0.0",
            "total_requirements": len(requirements),
            "unique_source_refs": unique_source_refs,
        },
        "requirements": requirements,
    }

    reqs_per_1k = (len(requirements) / total_chars * 1000) if total_chars > 0 else 0
    parse_success_rate = (
        (raw_response_count - parse_failure_count) / raw_response_count * 100
        if raw_response_count > 0 else 0
    )

    stats = {
        "pipeline": {
            "pages_extracted": page_count,
            "total_characters": total_chars,
            "chunks_created": chunk_count,
            "chunks_processed_by_llm": raw_response_count,
            "llm_parse_failures": parse_failure_count,
            "llm_parse_success_rate_pct": round(parse_success_rate, 1),
            "normalization_failures": norm_failure_count,
            "requirements_before_normalization": len(requirements) + norm_failure_count,
            "requirements_after_normalization": len(requirements),
            "requirements_per_1000_chars": round(reqs_per_1k, 3),
        },
        "requirements": {
            "total": len(requirements),
            "with_source_ref": has_source_ref,
            "unique_source_refs": unique_source_refs,
            "with_domain_tags": tagged_count,
            "without_domain_tags": untagged_count,
            "average_confidence": round(avg_confidence, 3),
            "domain_tag_distribution": dict(sorted(tag_counts.items())),
            "requirement_type_distribution": dict(sorted(type_counts.items())),
            "hierarchy": {
                "with_section_path": with_section_path,
                "with_parent_context": with_parent_context,
                "hierarchy_coverage_pct": hierarchy_coverage_pct,
            },
        },
    }

    final_path = out_dir / f"{stem}_final_output.json"
    stats_path = out_dir / f"{stem}_stats.json"

    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    log.info("Wrote %s", final_path)

    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    log.info("Wrote %s", stats_path)

    log.info("=== Pipeline Summary ===")
    log.info("Pages: %d | Chunks: %d | Requirements: %d", page_count, chunk_count, len(requirements))
    log.info("Parse success rate: %.1f%%", parse_success_rate)
    log.info("Tagged: %d/%d (%.1f%%)", tagged_count, len(requirements),
             tagged_count / len(requirements) * 100 if requirements else 0)
    log.info("Source refs: %d unique across %d requirements", unique_source_refs, has_source_ref)
    log.info("Domain tags: %s", dict(sorted(tag_counts.items())))
    log.info("Requirement types: %s", dict(sorted(type_counts.items())))

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate normalized requirements into final output"
    )
    parser.add_argument(
        "requirements_jsonl",
        type=str,
        help="Path to requirements_normalized.jsonl from Step D",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: same directory as input)",
    )
    parser.add_argument(
        "--source-pdf",
        type=str,
        default=None,
        help="Original PDF file name (for metadata)",
    )
    args = parser.parse_args()

    reqs_path = Path(args.requirements_jsonl).resolve()
    if not reqs_path.exists():
        log.error("Input file not found: %s", reqs_path)
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve() if args.output_dir else reqs_path.parent
    run(str(reqs_path), str(out_dir), source_pdf=args.source_pdf or "")


if __name__ == "__main__":
    main()
