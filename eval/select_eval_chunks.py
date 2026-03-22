#!/usr/bin/env python3
"""WP-3 R-3.1 / R-3.3: Stratified chunk selection for gold evaluation set.

Scans the processed directory for all *_chunks.jsonl files, classifies each
chunk by document class and requirement density, then produces a stratified
sample suitable for hand-correction.

Output schema per record (R-3.3):
  {
    "source_pdf":        str,   # e.g. "NIST.SP.800-53r5.pdf"
    "stem":              str,   # e.g. "NIST.SP.800-53r5"
    "processed_run_dir": str,   # absolute path to the exact timestamped run dir — pinned
    "chunk_id":          int,
    "chunk_text":        str,
    "page_start":        int,
    "page_end":          int,
    "document_class":    str,   # "nist_sp" | "dodi_dodm" | "afi_daf" | "unclassified"
    "density_tier":      str,   # "zero" | "medium" | "high"
    "density_count":     int,   # number of Step C requirements for this chunk
    "gold_requirements": [],    # empty — populated by seed_gold_set.py
    "corrector_notes":   ""
  }

processed_run_dir is pinned at selection time so that seed_gold_set.py and
eval_harness.py always load artifacts from the exact same processed run,
even if the document is re-ingested later (P1 fix, Codex review).

Usage:
    python3 eval/select_eval_chunks.py [--processed-dir ~/documents/processed] \
        [--output eval/gold_eval_chunks.jsonl] [--target 400] [--seed 42]

Run from the repo root.
"""

import argparse
import json
import logging
import math
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argparse validators (pattern from reqbot.py / ask.py)
# ---------------------------------------------------------------------------

def _positive_int(value: str) -> int:
    """Argparse type: integer that must be > 0."""
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}")
    if iv <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return iv


def _non_negative_int(value: str) -> int:
    """Argparse type: integer that must be >= 0."""
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}")
    if iv < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return iv


# ---------------------------------------------------------------------------
# Document class classification patterns
# R-3.1: three target classes — NIST SP prose, DODI/DoDM tables, AFI/DAF prose
# Anything else → "unclassified" (flagged but excluded from stratified sample)
# ---------------------------------------------------------------------------
_CLASS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("nist_sp",   re.compile(r"^nist[._]sp[._]",             re.IGNORECASE)),
    ("dodi_dodm", re.compile(r"^do(di|dm)",                  re.IGNORECASE)),
    # No \b — stems like afi10-2402 have a digit immediately after the prefix
    ("afi_daf",   re.compile(r"^(afi|afman|afpd|dafman|dafpam)", re.IGNORECASE)),
]

# Density tier thresholds (R-3.1: high / medium / zero requirement density)
_TIER_THRESHOLDS = [
    ("zero",   0,  0),   # exactly 0 requirements
    ("medium", 1,  3),   # 1–3 requirements
    ("high",   4, 999),  # 4+ requirements
]

# Target proportion per density tier within each class
# Zero is important: that's where false-positive measurement lives (Opus review)
_TIER_WEIGHTS = {"zero": 0.25, "medium": 0.35, "high": 0.40}


def classify_document(stem: str) -> str:
    """Return document class label for a given PDF stem."""
    for label, pattern in _CLASS_PATTERNS:
        if pattern.match(stem):
            return label
    return "unclassified"


def density_tier(count: int) -> str:
    """Map requirement count → density tier label."""
    for tier, lo, hi in _TIER_THRESHOLDS:
        if lo <= count <= hi:
            return tier
    return "high"


def find_most_recent_dir(processed_dir: Path, stem: str) -> Path | None:
    """Return the most recently created output dir for a given PDF stem.

    Dirs follow the naming convention: {stem}_{YYYYMMDD}_{HHMMSS}
    Only consider dirs where a *_chunks.jsonl file actually exists.
    """
    candidates = sorted(
        processed_dir.glob(f"{glob_escape(stem)}_????????_??????"),
        reverse=True,  # most recent first (lexicographic on timestamp suffix)
    )
    for d in candidates:
        if (d / f"{stem}_chunks.jsonl").exists():
            return d
    return None


def glob_escape(s: str) -> str:
    """Minimal glob escaping for square brackets and question marks in stems."""
    return s.replace("[", "[[]").replace("?", "[?]")


def load_density_counts(out_dir: Path, stem: str) -> dict[int, int]:
    """Return {chunk_id: requirement_count} from *_extracted_requirements.jsonl.

    Falls back to empty dict if the file doesn't exist (chunk gets density 'zero').
    NOTE: We use Step C output (pre-normalization) per Codex R-4.2 reasoning —
    Step D's global dedup alters per-chunk counts and must not be used here.
    """
    reqs_path = out_dir / f"{stem}_extracted_requirements.jsonl"
    counts: dict[int, int] = defaultdict(int)
    if not reqs_path.exists():
        return counts
    try:
        with open(reqs_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cid = rec.get("chunk_id")
                    if cid is not None:
                        counts[int(cid)] += 1
                except (json.JSONDecodeError, ValueError):
                    pass
    except OSError as e:
        log.warning("Could not read %s: %s", reqs_path, e)
    return counts


def load_chunks(
    chunks_path: Path,
    stem: str,
    out_dir: Path,
    density_counts: dict[int, int],
) -> list[dict]:
    """Read a *_chunks.jsonl and return annotated chunk records.

    out_dir is stored as processed_run_dir so downstream scripts (seeder,
    harness) can load artifacts from the exact same run rather than
    re-discovering "most recent" (P1 fix, Codex review).
    """
    records = []
    processed_run_dir = str(out_dir.resolve())
    doc_class = classify_document(stem)
    try:
        with open(chunks_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cid = chunk.get("chunk_id")
                if cid is None:
                    continue
                count = density_counts.get(int(cid), 0)
                records.append({
                    "stem": stem,
                    "source_pdf": f"{stem}.pdf",
                    "processed_run_dir": processed_run_dir,
                    "chunk_id": int(cid),
                    "chunk_text": chunk.get("text", ""),
                    "page_start": chunk.get("page_start", 1),
                    "page_end": chunk.get("page_end", 1),
                    "document_class": doc_class,
                    "density_tier": density_tier(count),
                    "density_count": count,
                    "gold_requirements": [],
                    "corrector_notes": "",
                })
    except OSError as e:
        log.warning("Could not read %s: %s", chunks_path, e)
    return records


def discover_stems(processed_dir: Path) -> list[str]:
    """Return sorted list of unique PDF stems found in processed_dir."""
    stems: set[str] = set()
    for d in processed_dir.iterdir():
        if not d.is_dir():
            continue
        # Expect: {stem}_{YYYYMMDD}_{HHMMSS}  (last two parts are date+time)
        parts = d.name.rsplit("_", 2)
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            stems.add(parts[0])
    return sorted(stems)


def stratified_sample(
    pool: list[dict],
    target: int,
    rng: random.Random,
) -> list[dict]:
    """Stratified sample of `target` chunks across (document_class, density_tier).

    Allocates slots proportionally:
      - Equal share per document class
      - Within each class, weighted by _TIER_WEIGHTS
    Unclassified chunks are excluded and reported separately.
    """
    target_classes = ["nist_sp", "dodi_dodm", "afi_daf"]

    # Split pool by class and tier
    by_class_tier: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    unclassified: list[dict] = []
    for rec in pool:
        cls = rec["document_class"]
        if cls == "unclassified":
            unclassified.append(rec)
        else:
            by_class_tier[cls][rec["density_tier"]].append(rec)

    if unclassified:
        stems = {r["stem"] for r in unclassified}
        log.warning(
            "%d chunks from %d unclassified document(s) excluded from stratified sample: %s",
            len(unclassified), len(stems), sorted(stems),
        )

    # Ceiling division so 400/3 → 134 per class (399 floor would cap at 399)
    per_class = math.ceil(target / len(target_classes))
    selected: list[dict] = []

    for cls in target_classes:
        tier_pool = by_class_tier[cls]
        total_available = sum(len(v) for v in tier_pool.values())
        if total_available == 0:
            log.warning("No chunks found for class '%s' — skipping", cls)
            continue

        cls_alloc = min(per_class, total_available)
        cls_selected: list[dict] = []

        for tier in ["zero", "medium", "high"]:
            tier_chunks = tier_pool.get(tier, [])
            if not tier_chunks:
                continue
            tier_alloc = max(1, round(cls_alloc * _TIER_WEIGHTS[tier]))
            tier_alloc = min(tier_alloc, len(tier_chunks))
            cls_selected.extend(rng.sample(tier_chunks, tier_alloc))

        # Top up to cls_alloc if rounding left us short
        already = {(r["stem"], r["chunk_id"]) for r in cls_selected}
        remaining = [r for r in pool if r["document_class"] == cls
                     and (r["stem"], r["chunk_id"]) not in already]
        shortfall = cls_alloc - len(cls_selected)
        if shortfall > 0 and remaining:
            cls_selected.extend(rng.sample(remaining, min(shortfall, len(remaining))))

        log.info(
            "Class %-12s — available: %4d  selected: %4d  "
            "(zero=%d medium=%d high=%d)",
            cls, total_available, len(cls_selected),
            sum(1 for r in cls_selected if r["density_tier"] == "zero"),
            sum(1 for r in cls_selected if r["density_tier"] == "medium"),
            sum(1 for r in cls_selected if r["density_tier"] == "high"),
        )
        selected.extend(cls_selected)

    return selected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stratified chunk selection for WP-3 gold evaluation set"
    )
    parser.add_argument(
        "--processed-dir",
        default=None,
        help="Pipeline processed output directory (default: ~/documents/processed or config value)",
    )
    parser.add_argument(
        "--output",
        default="eval/gold_eval_chunks.jsonl",
        help="Output JSONL file path (default: eval/gold_eval_chunks.jsonl)",
    )
    parser.add_argument(
        "--target",
        type=_positive_int,
        default=400,
        help="Target number of chunks to select (default: 400; R-3.1 range: 300–500)",
    )
    parser.add_argument(
        "--seed",
        type=_positive_int,
        default=42,
        help="Random seed for reproducible sampling (default: 42)",
    )
    parser.add_argument(
        "--min-chunk-len",
        type=_non_negative_int,
        default=200,
        help="Minimum chunk text length to include (default: 200 chars)",
    )
    args = parser.parse_args()

    # Resolve processed dir
    if args.processed_dir:
        processed_dir = Path(args.processed_dir).expanduser().resolve()
    else:
        # Try config, fall back to default
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

    log.info("Scanning processed dir: %s", processed_dir)

    # Discover all stems and load chunks
    stems = discover_stems(processed_dir)
    log.info("Found %d unique document stems", len(stems))

    all_chunks: list[dict] = []
    for stem in stems:
        out_dir = find_most_recent_dir(processed_dir, stem)
        if out_dir is None:
            log.debug("No valid output dir for stem '%s' — skipping", stem)
            continue
        chunks_path = out_dir / f"{stem}_chunks.jsonl"
        if not chunks_path.exists():
            log.debug("No chunks file for stem '%s' — skipping", stem)
            continue
        density_counts = load_density_counts(out_dir, stem)
        chunks = load_chunks(chunks_path, stem, out_dir, density_counts)
        # Filter short chunks (likely noise)
        chunks = [c for c in chunks if len(c["chunk_text"]) >= args.min_chunk_len]
        all_chunks.extend(chunks)
        log.debug("Stem %-40s → %d chunks", stem, len(chunks))

    log.info("Total eligible chunks: %d", len(all_chunks))
    if not all_chunks:
        log.error("No chunks found — check --processed-dir path")
        sys.exit(1)

    # Stratified sample
    rng = random.Random(args.seed)
    selected = stratified_sample(all_chunks, args.target, rng)
    # Shuffle so output isn't grouped by class
    rng.shuffle(selected)

    # Write output
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for rec in selected:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    log.info("Wrote %d chunk records to %s", len(selected), out_path)
    log.info(
        "Density breakdown — zero: %d  medium: %d  high: %d",
        sum(1 for r in selected if r["density_tier"] == "zero"),
        sum(1 for r in selected if r["density_tier"] == "medium"),
        sum(1 for r in selected if r["density_tier"] == "high"),
    )
    log.info("Next step: run eval/seed_gold_set.py to populate gold_requirements from Step C output")


if __name__ == "__main__":
    main()
