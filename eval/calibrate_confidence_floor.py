#!/usr/bin/env python3
"""WP-41: zero-truth confidence-floor calibration.

Sweeps candidate min_score thresholds against a SINGLE retrieve() draw per
query (top_k=100, min_score=0), then applies each threshold as pure
post-processing on that one draw -- not a separate live call per threshold.
Comparing thresholds via separate live calls would confound the comparison
with HyDE's unseeded stochasticity (eval/retrieval_eval_harness.py's own
docstring; same lesson WP-40's Codex PR #187 review already established for
eval/failure_classifier.py).

Reports, for every candidate threshold: how many of the 8 zero-truth queries
correctly return nothing, and the recall@5/10 impact on every other bucket
(especially Q-B05, whose real relevant results score as low as 0.033-0.09) --
the real trade-off, not a single cherry-picked number.
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import config as _config  # noqa: E402
from core.ask import retrieve  # noqa: E402

LARGE_POOL_TOP_K = 100
PRODUCTION_TOP_K = 20
CANDIDATE_THRESHOLDS = [0.02, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]


def fetch_pools(queries: list, *, qdrant_url: str, ollama_url: str) -> dict:
    pools = {}
    for q in queries:
        try:
            result = retrieve(
                q["query"], top_k=LARGE_POOL_TOP_K, min_score=0, hyde=True,
                qdrant_url=qdrant_url, ollama_url=ollama_url,
            )
            pools[q["query_id"]] = result["results"]
            print(f"  fetched {q['query_id']} ({len(result['results'])} candidates)")
        except Exception as e:
            print(f"  FAILED {q['query_id']}: {e}")
            pools[q["query_id"]] = None
    return pools


def sweep(queries: list, pools: dict) -> list:
    rows = []
    for threshold in CANDIDATE_THRESHOLDS:
        zero_correct = 0
        zero_total = 0
        per_shape_recall5: dict = {}
        per_shape_recall10: dict = {}
        qb05_recall5 = None
        failed = 0
        for q in queries:
            pool = pools.get(q["query_id"])
            if pool is None:
                failed += 1
                continue
            filtered_ids = [r["requirement_id"] for r in pool if r["score"] >= threshold]

            if q["shape"] == "zero":
                zero_total += 1
                if len(filtered_ids) == 0:
                    zero_correct += 1
                continue

            relevant = set(q.get("relevant_requirement_ids", []))
            if not relevant:
                continue
            r5 = len(relevant & set(filtered_ids[:5])) / len(relevant)
            r10 = len(relevant & set(filtered_ids[:PRODUCTION_TOP_K])) / len(relevant)
            per_shape_recall5.setdefault(q["shape"], []).append(r5)
            per_shape_recall10.setdefault(q["shape"], []).append(r10)
            if q["query_id"] == "Q-B05":
                qb05_recall5 = r5

        row = {
            "threshold": threshold,
            "zero_truth_correct": f"{zero_correct}/{zero_total}",
            "qb05_recall@5": qb05_recall5,
            "failed_queries": failed,
        }
        for shape, vals in per_shape_recall5.items():
            row[f"mean_{shape}_recall@5"] = round(sum(vals) / len(vals), 4)
        for shape, vals in per_shape_recall10.items():
            row[f"mean_{shape}_recall@10"] = round(sum(vals) / len(vals), 4)
        rows.append(row)
    return rows


def format_report(rows: list) -> str:
    shapes = sorted({k.replace("mean_", "").replace("_recall@5", "") for r in rows for k in r if k.startswith("mean_") and k.endswith("recall@5")})
    lines = ["# WP-41 Zero-Truth Confidence-Floor Calibration Sweep", ""]
    header = ["threshold", "zero_truth_correct", "qb05_recall@5"] + [f"{s}_recall@5" for s in shapes]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for row in rows:
        cells = [
            str(row["threshold"]), row["zero_truth_correct"],
            str(row.get("qb05_recall@5")),
        ] + [str(row.get(f"mean_{s}_recall@5", "—")) for s in shapes]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## recall@10 by bucket")
    lines.append("")
    header10 = ["threshold"] + [f"{s}_recall@10" for s in shapes]
    lines.append("| " + " | ".join(header10) + " |")
    lines.append("|" + "---|" * len(header10))
    for row in rows:
        cells = [str(row["threshold"])] + [str(row.get(f"mean_{s}_recall@10", "—")) for s in shapes]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    cfg = _config.load()
    gold_path = _ROOT / "eval" / "gold_retrieval_queries.jsonl"
    with open(gold_path, encoding="utf-8") as f:
        queries = [json.loads(line) for line in f if line.strip()]
    print(f"Loaded {len(queries)} queries from {gold_path}")

    print("Fetching one pool per query (top_k=100, min_score=0)...")
    pools = fetch_pools(queries, qdrant_url=cfg.qdrant_url, ollama_url=cfg.ollama_url)

    print("Sweeping candidate thresholds...")
    rows = sweep(queries, pools)

    out_dir = _ROOT / "eval" / "spike_results" / "wp_41_confidence_calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sweep_results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    report_md = format_report(rows)
    (out_dir / "sweep_report.md").write_text(report_md, encoding="utf-8")

    print(report_md)
    print(f"Wrote {out_dir / 'sweep_results.json'} and {out_dir / 'sweep_report.md'}")


if __name__ == "__main__":
    main()
