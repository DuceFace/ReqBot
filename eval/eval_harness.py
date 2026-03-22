#!/usr/bin/env python3
"""WP-3 R-3.4 / R-3.5: Eval harness for Step C extraction quality.

Joins a hand-corrected gold JSONL against current Step C extracted output,
performs bipartite matching on source_quote (via rapidfuzz), and reports:

  - Requirement-level precision and recall (fuzzy match on source_quote)
  - source_ref exact-match accuracy (on matched TP pairs)
  - False positive rate
  - Per-document-class breakdown
  - Per-density-tier breakdown
  - Per-chunk match counts (for identifying systematic problem areas)

Match algorithm:
  For each chunk, compare gold_requirements vs. Step C predictions.
  Build a similarity matrix and apply the Hungarian algorithm (linear sum
  assignment) for optimal one-to-one bipartite matching.
  Pairs where similarity >= --threshold are TP; remainder are FP/FN.
  Normalizes whitespace and lowercases before comparison (Opus review).

Usage:
    python3 eval/eval_harness.py \\
        --gold eval/gold_eval_chunks_seeded.jsonl \\
        [--processed-dir ~/documents/processed] \\
        [--threshold 0.80] \\
        [--output eval/results/baseline_wp1.json]

Run from the repo root.

Requires: rapidfuzz (pip3 install rapidfuzz)
"""

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    from rapidfuzz import fuzz
    from rapidfuzz.distance import Levenshtein
except ImportError:
    print("ERROR: rapidfuzz not installed. Run: pip3 install rapidfuzz", file=sys.stderr)
    sys.exit(1)

try:
    from scipy.optimize import linear_sum_assignment
    import numpy as np
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize whitespace and lowercase for fuzzy comparison."""
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def similarity(a: str, b: str) -> float:
    """Rapidfuzz token_sort_ratio similarity in [0, 1].

    token_sort_ratio handles word-order variation common in
    regulatory paraphrases. Result divided by 100 to normalize to [0, 1].
    """
    return fuzz.token_sort_ratio(normalize_text(a), normalize_text(b)) / 100.0


def bipartite_match(
    gold: list[str],
    pred: list[str],
    threshold: float,
) -> list[tuple[int, int, float]]:
    """Optimal bipartite matching of gold vs. predicted source_quotes.

    Returns list of (gold_idx, pred_idx, similarity) for accepted pairs.
    Uses scipy linear_sum_assignment when available; falls back to greedy.

    One-to-one: each gold and each prediction is matched at most once.
    Only pairs with similarity >= threshold are accepted (Codex R-3.4 note).
    """
    if not gold or not pred:
        return []

    # Build similarity matrix (gold × pred)
    sim_matrix = [
        [similarity(g, p) for p in pred]
        for g in gold
    ]

    if _SCIPY_AVAILABLE:
        # Hungarian algorithm: maximise total similarity
        import numpy as np
        cost = np.array(sim_matrix)
        row_ind, col_ind = linear_sum_assignment(-cost)  # negate to maximise
        pairs = [
            (int(r), int(c), sim_matrix[r][c])
            for r, c in zip(row_ind, col_ind)
            if sim_matrix[r][c] >= threshold
        ]
    else:
        # Greedy fallback: take highest-similarity pair, remove both, repeat
        log.debug("scipy not available — using greedy bipartite matching")
        pairs = []
        available_gold = set(range(len(gold)))
        available_pred = set(range(len(pred)))
        # Collect all candidate pairs above threshold, sorted by similarity desc
        candidates = sorted(
            [
                (sim_matrix[gi][pi], gi, pi)
                for gi in available_gold
                for pi in available_pred
                if sim_matrix[gi][pi] >= threshold
            ],
            reverse=True,
        )
        for sim_val, gi, pi in candidates:
            if gi in available_gold and pi in available_pred:
                pairs.append((gi, pi, sim_val))
                available_gold.discard(gi)
                available_pred.discard(pi)

    return pairs


# ---------------------------------------------------------------------------
# Loading predictions from Step C output files
# ---------------------------------------------------------------------------

def glob_escape(s: str) -> str:
    return s.replace("[", "[[]").replace("?", "[?]")


def find_most_recent_dir(processed_dir: Path, stem: str) -> Path | None:
    candidates = sorted(
        processed_dir.glob(f"{glob_escape(stem)}_????????_??????"),
        reverse=True,
    )
    for d in candidates:
        if (d / f"{stem}_extracted_requirements.jsonl").exists():
            return d
    return None


def load_predictions_by_chunk(reqs_path: Path) -> dict[int, list[dict]]:
    """Return {chunk_id: [{source_quote, source_ref}, ...]} from Step C JSONL."""
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
                sq = rec.get("source_quote", "").strip()
                sr = rec.get("source_ref", "").strip()
                if cid is not None and sq:
                    by_chunk[int(cid)].append({
                        "source_quote": sq,
                        "source_ref": sr,
                    })
    except OSError as e:
        log.warning("Could not read %s: %s", reqs_path, e)
    return by_chunk


# ---------------------------------------------------------------------------
# Per-chunk evaluation
# ---------------------------------------------------------------------------

def eval_chunk(
    gold_reqs: list[dict],
    pred_reqs: list[dict],
    threshold: float,
) -> dict:
    """Evaluate one chunk. Returns match stats dict."""
    gold_quotes = [r.get("source_quote", "") for r in gold_reqs]
    pred_quotes = [r.get("source_quote", "") for r in pred_reqs]

    matched_pairs = bipartite_match(gold_quotes, pred_quotes, threshold)
    tp = len(matched_pairs)
    fp = len(pred_reqs) - tp
    fn = len(gold_reqs) - tp

    # source_ref accuracy on TP pairs
    ref_correct = 0
    for gi, pi, _ in matched_pairs:
        gold_ref = gold_reqs[gi].get("source_ref", "").strip()
        pred_ref = pred_reqs[pi].get("source_ref", "").strip()
        if gold_ref and pred_ref and gold_ref == pred_ref:
            ref_correct += 1
        elif not gold_ref:
            # Gold has no ref — can't penalise (don't count as error or correct)
            pass

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "ref_correct": ref_correct,
        "ref_total_tp": tp,  # denominator for source_ref accuracy
        "gold_count": len(gold_reqs),
        "pred_count": len(pred_reqs),
    }


def safe_div(num: float, den: float, default: float = 0.0) -> float:
    return num / den if den > 0 else default


def aggregate_metrics(rows: list[dict]) -> dict:
    tp = sum(r["tp"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    fn = sum(r["fn"] for r in rows)
    ref_correct = sum(r["ref_correct"] for r in rows)
    ref_total = sum(r["ref_total_tp"] for r in rows)
    total_pred = sum(r["pred_count"] for r in rows)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    fpr = safe_div(fp, total_pred)  # FP / total predictions
    f1 = safe_div(2 * precision * recall, precision + recall)
    ref_accuracy = safe_div(ref_correct, ref_total)
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "source_ref_accuracy": round(ref_accuracy, 4),
        "chunks_evaluated": len(rows),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="WP-3 eval harness: precision/recall for Step C extraction"
    )
    parser.add_argument(
        "--gold",
        default="eval/gold_eval_chunks_seeded.jsonl",
        help="Hand-corrected gold JSONL (default: eval/gold_eval_chunks_seeded.jsonl)",
    )
    parser.add_argument(
        "--processed-dir",
        default=None,
        help="Pipeline processed output directory (default: ~/documents/processed or config)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.80,
        help="Fuzzy match similarity threshold for TP classification (default: 0.80)",
    )
    parser.add_argument(
        "--output",
        default="eval/results/baseline_wp1.json",
        help="Output JSON results file (default: eval/results/baseline_wp1.json)",
    )
    parser.add_argument(
        "--verbose-chunks",
        action="store_true",
        help="Include per-chunk detail in the output JSON",
    )
    args = parser.parse_args()

    if not _SCIPY_AVAILABLE:
        log.warning(
            "scipy not installed — using greedy bipartite matching. "
            "Results may differ slightly from optimal. "
            "Install with: pip3 install scipy"
        )

    gold_path = Path(args.gold)
    if not gold_path.exists():
        log.error("Gold file not found: %s", gold_path)
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

    log.info("Loaded %d gold records from %s", len(gold_records), gold_path)

    # Cache predictions per stem
    pred_cache: dict[str, dict[int, list[dict]]] = {}
    missing_stems: set[str] = set()

    # Per-chunk results
    chunk_results: list[dict] = []

    for rec in gold_records:
        stem = rec.get("stem", "")
        chunk_id = int(rec.get("chunk_id", -1))
        doc_class = rec.get("document_class", "unknown")
        density_tier = rec.get("density_tier", "unknown")
        gold_reqs = rec.get("gold_requirements", [])

        if stem not in pred_cache:
            out_dir = find_most_recent_dir(processed_dir, stem)
            if out_dir is None:
                missing_stems.add(stem)
                pred_cache[stem] = {}
            else:
                reqs_path = out_dir / f"{stem}_extracted_requirements.jsonl"
                pred_cache[stem] = load_predictions_by_chunk(reqs_path)

        pred_reqs = pred_cache[stem].get(chunk_id, [])

        stats = eval_chunk(gold_reqs, pred_reqs, args.threshold)
        chunk_results.append({
            "source_pdf": rec.get("source_pdf", ""),
            "stem": stem,
            "chunk_id": chunk_id,
            "document_class": doc_class,
            "density_tier": density_tier,
            **stats,
        })

    if missing_stems:
        log.warning(
            "Step C output not found for %d stem(s): %s",
            len(missing_stems), sorted(missing_stems),
        )

    # Aggregate metrics overall
    overall = aggregate_metrics(chunk_results)

    # Per document class
    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in chunk_results:
        by_class[r["document_class"]].append(r)
    per_class = {cls: aggregate_metrics(rows) for cls, rows in sorted(by_class.items())}

    # Per density tier
    by_tier: dict[str, list[dict]] = defaultdict(list)
    for r in chunk_results:
        by_tier[r["density_tier"]].append(r)
    per_tier = {tier: aggregate_metrics(rows) for tier, rows in sorted(by_tier.items())}

    # Print summary to stdout
    print("\n" + "=" * 60)
    print("EVAL HARNESS RESULTS")
    print(f"Gold file:      {gold_path}")
    print(f"Processed dir:  {processed_dir}")
    print(f"Match threshold: {args.threshold}")
    if not _SCIPY_AVAILABLE:
        print("Matching:       greedy (scipy not available)")
    else:
        print("Matching:       bipartite / Hungarian")
    print("=" * 60)
    print(f"\nOVERALL ({overall['chunks_evaluated']} chunks)")
    print(f"  Precision:          {overall['precision']:.1%}")
    print(f"  Recall:             {overall['recall']:.1%}")
    print(f"  F1:                 {overall['f1']:.1%}")
    print(f"  False Positive Rate:{overall['false_positive_rate']:.1%}")
    print(f"  source_ref accuracy:{overall['source_ref_accuracy']:.1%}")
    print(f"  TP={overall['tp']}  FP={overall['fp']}  FN={overall['fn']}")

    print("\nPER DOCUMENT CLASS")
    for cls, m in per_class.items():
        print(
            f"  {cls:<14} P={m['precision']:.1%}  R={m['recall']:.1%}  "
            f"F1={m['f1']:.1%}  FPR={m['false_positive_rate']:.1%}  "
            f"ref_acc={m['source_ref_accuracy']:.1%}  "
            f"chunks={m['chunks_evaluated']}"
        )

    print("\nPER DENSITY TIER")
    for tier, m in per_tier.items():
        print(
            f"  {tier:<8} P={m['precision']:.1%}  R={m['recall']:.1%}  "
            f"F1={m['f1']:.1%}  FPR={m['false_positive_rate']:.1%}  "
            f"chunks={m['chunks_evaluated']}"
        )

    # Identify worst-performing chunks (useful during curation)
    print("\nWORST CHUNKS (by combined FP+FN, top 10)")
    worst = sorted(chunk_results, key=lambda r: r["fp"] + r["fn"], reverse=True)[:10]
    for r in worst:
        print(
            f"  {r['stem'][:40]:<40}  chunk={r['chunk_id']:4d}  "
            f"fp={r['fp']}  fn={r['fn']}  "
            f"class={r['document_class']}  tier={r['density_tier']}"
        )
    print()

    # Build output JSON
    output = {
        "gold_file": str(gold_path),
        "processed_dir": str(processed_dir),
        "threshold": args.threshold,
        "matching": "bipartite/hungarian" if _SCIPY_AVAILABLE else "greedy",
        "overall": overall,
        "per_document_class": per_class,
        "per_density_tier": per_tier,
    }
    if args.verbose_chunks:
        output["per_chunk"] = chunk_results

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    log.info("Results written to %s", out_path)


if __name__ == "__main__":
    main()
