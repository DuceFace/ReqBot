#!/usr/bin/env python3
"""
eval/harvest_description_grounding_candidates.py — WP-35.1 candidate harvester

Scans every enriched pipeline run under ~/documents/processed/*/ and flags
(source_quote, description) pairs likely to be one of the two known
fabrication shapes found during WP-34.4's spike, plus a random sample of
unflagged ("clean") pairs as faithful-holdout candidates.

This produces *candidates* for hand review, not the final labeled dataset --
per WP-35.1's scope (docs/PHASE35_REQUIREMENTS.md), each flagged record still
needs its section_title_path/parent_context checked by hand before it can be
labeled and folded into eval/gold_description_grounding.jsonl. Mirrors the
same two-step process (structural heuristic -> hand verification) that
produced eval/entailment_spike.py's original 15 examples, scaled up.

Heuristics (deliberately broad -- a haystack net for hand review, not a
production classifier):

- citation_fragment_shaped: a short and/or colon-terminated source_quote
  (same shape as parse_and_normalize.py's _is_unrepairable_fragment) paired
  with a much longer, low-similarity description -- the WP-33.3
  category-1/3 shape (bare citations, truncated list headers).
- modality_shaped: description contains a profiles/cybersecurity.json
  obligation_verbs term that doesn't appear anywhere in source_quote -- the
  WP-34.4/Codex-found category-4 shape (definitional prose reframed as an
  imperative). Deliberately broad/literal (no synonym grouping or POS check
  -- that nuance is WP-35.3's actual design problem, not this harvester's).

Records already flagged citation_fragment_shaped are not also considered for
modality_shaped (avoids double-counting the same record under two subtypes).

Each run directory is tagged pre_fix or post_fix by comparing its own
timestamp suffix against FIX_CUTOFF -- the merge time of the last of
WP-34.1/34.2/34.3 (the structural fixes this phase's own candidates need to
be understood against). All 5 locally-processed runs that existed before this
WP predate every one of those merges.

Usage:
  python3 eval/harvest_description_grounding_candidates.py
  python3 eval/harvest_description_grounding_candidates.py --clean-sample 60
"""

import argparse
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rapidfuzz import fuzz  # noqa: E402

from pipeline.parse_and_normalize import normalize_text  # noqa: E402

PROCESSED_DIR = Path.home() / "documents" / "processed"

# Merge time of WP-34.3 (cae34c6, 2026-07-30 14:12), the last of the three
# structural fixes (WP-34.1/34.2/34.3) a "post-fix" run needs to reflect.
FIX_CUTOFF = datetime(2026, 7, 30, 14, 12)

FRAGMENT_MAX_WORDS = 20
FRAGMENT_LENGTH_RATIO = 2.0
FRAGMENT_MAX_SIMILARITY = 45

_OBLIGATION_VERBS = json.loads(
    (_ROOT / "profiles" / "cybersecurity.json").read_text(encoding="utf-8")
)["obligation_verbs"]


def _run_timestamp(run_dir: Path) -> datetime | None:
    """Parse the YYYYMMDD_HHMMSS suffix off a processed/<doc>_<ts> dir name."""
    m = re.search(r"_(\d{8}_\d{6})$", run_dir.name)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")


def _is_citation_fragment_shaped(quote: str, description: str) -> bool:
    stripped = quote.strip()
    quote_words = stripped.split()
    is_short_or_colon = stripped.endswith(":") or len(quote_words) <= FRAGMENT_MAX_WORDS
    if not is_short_or_colon:
        return False
    desc_words = description.strip().split()
    is_much_longer = len(desc_words) >= FRAGMENT_LENGTH_RATIO * max(len(quote_words), 1)
    if not is_much_longer:
        return False
    similarity = fuzz.token_sort_ratio(normalize_text(quote), normalize_text(description))
    return similarity < FRAGMENT_MAX_SIMILARITY


def _obligation_words_in(text: str) -> set[str]:
    normalized = normalize_text(text)
    found = set()
    for verb in _OBLIGATION_VERBS:
        if re.search(r"\b" + re.escape(verb) + r"\b", normalized):
            found.add(verb)
    return found


def _is_modality_shaped(quote: str, description: str) -> bool:
    desc_only = _obligation_words_in(description) - _obligation_words_in(quote)
    return bool(desc_only)


def harvest(clean_sample_size: int) -> dict:
    citation_fragment: list[dict] = []
    modality: list[dict] = []
    clean_pool: list[dict] = []
    seen: set[tuple] = set()

    run_dirs = sorted(p for p in PROCESSED_DIR.iterdir() if p.is_dir())
    for run_dir in run_dirs:
        ts = _run_timestamp(run_dir)
        fix_status = "unknown" if ts is None else ("post_fix" if ts >= FIX_CUTOFF else "pre_fix")
        enriched_files = list(run_dir.glob("*_requirements_enriched.jsonl"))
        if not enriched_files:
            continue
        with open(enriched_files[0], encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                quote = rec.get("source_quote") or ""
                description = rec.get("description") or ""
                if not quote or not description:
                    continue
                dedup_key = (rec.get("source_pdf"), rec.get("chunk_id"), quote, description)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                entry = {
                    "requirement_id": rec.get("requirement_id"),
                    "source_quote": quote,
                    "description": description,
                    "section_title_path": rec.get("section_title_path") or [],
                    "parent_context": rec.get("parent_context"),
                    "source_pdf": rec.get("source_pdf"),
                    "chunk_id": rec.get("chunk_id"),
                    "run_dir": run_dir.name,
                    "fix_status": fix_status,
                }

                if _is_citation_fragment_shaped(quote, description):
                    entry["flag_type"] = "citation_fragment_shaped"
                    citation_fragment.append(entry)
                elif _is_modality_shaped(quote, description):
                    entry["flag_type"] = "modality_shaped"
                    modality.append(entry)
                else:
                    clean_pool.append(entry)

    post_fix_clean = [e for e in clean_pool if e["fix_status"] == "post_fix"]
    rng = random.Random(35_1)
    sample_pool = post_fix_clean if post_fix_clean else clean_pool
    clean_sample = rng.sample(sample_pool, k=min(clean_sample_size, len(sample_pool)))

    return {
        "citation_fragment_shaped": citation_fragment,
        "modality_shaped": modality,
        "clean_sample": clean_sample,
        "totals": {
            "runs_scanned": len(run_dirs),
            "records_scanned": len(seen),
            "citation_fragment_shaped": len(citation_fragment),
            "modality_shaped": len(modality),
            "clean_pool": len(clean_pool),
            "clean_pool_post_fix": len(post_fix_clean),
            "clean_sample": len(clean_sample),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="WP-35.1 candidate harvester")
    parser.add_argument("--clean-sample", type=int, default=90, dest="clean_sample")
    args = parser.parse_args()

    result = harvest(args.clean_sample)

    out_dir = _ROOT / "eval" / "spike_results" / "wp_35_1"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "harvest_candidates.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(result["totals"], indent=2), file=sys.stderr)
    print(f"Wrote {out_dir / 'harvest_candidates.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
