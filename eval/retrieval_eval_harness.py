#!/usr/bin/env python3
"""WP-37.1: Retrieval-quality eval harness.

Measures whether `reqbot ask`'s real, unmodified retrieval path
(core.ask.retrieve() -- hybrid dense+sparse+HyDE, RRF-fused, query-rewritten,
current production defaults) actually surfaces the right requirements for a
real question. Distinct from eval/eval_harness.py, which measures Step C
extraction precision/recall -- this measures search/ask quality, a different
pipeline stage (docs/PHASE37_REQUIREMENTS.md's Phase Framing).

Input:  eval/gold_retrieval_queries.jsonl -- hand-labeled queries, each with
        a hand-verified set of relevant requirement_ids (or an empty set for
        a deliberately off-topic "zero" query). See that file's own `notes`
        field per record for how each label was verified.
Output: recall@k (k=5,10,20) and MRR per query and in aggregate, plus a
        separate report for zero-truth queries (how many results they
        returned, since recall/MRR are undefined when nothing is relevant).

No retrieval code changes happen here -- measurement only (WP-37.1 Non-Goals).
"""
import argparse
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.ask import retrieve  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

K_VALUES = [5, 10, 20]


def load_gold_queries(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def compute_metrics(relevant_ids: set[str], retrieved_ids: list[str]) -> dict:
    """recall@k for each K_VALUES entry, plus MRR (reciprocal rank of the
    first relevant hit). For a query with no relevant_ids (a deliberate
    "zero" query -- nothing in the corpus should match), recall/MRR are
    undefined by definition (0/0); report returned_count instead so the
    caller can judge whether the system correctly returned little/nothing
    rather than confidently surfacing irrelevant results."""
    if not relevant_ids:
        return {"returned_count": len(retrieved_ids)}

    metrics = {}
    for k in K_VALUES:
        top_k_ids = set(retrieved_ids[:k])
        hits = relevant_ids & top_k_ids
        metrics[f"recall@{k}"] = round(len(hits) / len(relevant_ids), 4)

    mrr = 0.0
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_ids:
            mrr = round(1.0 / rank, 4)
            break
    metrics["mrr"] = mrr
    return metrics


def run_harness(
    queries: list[dict],
    *,
    qdrant_url: str,
    ollama_url: str,
    top_k: int = max(K_VALUES),
    min_score: float = 0.02,
    hyde: bool = True,
    no_rewrite: bool = False,
) -> dict:
    """Run every labeled query through the real, unmodified retrieve() path
    and score it. Real production defaults unless a caller explicitly
    overrides them (e.g. for a future WP-37.2 before/after comparison run
    with the same overrides on both sides)."""
    per_query = []
    for q in queries:
        relevant_ids = set(q["relevant_requirement_ids"])
        try:
            result = retrieve(
                q["query"],
                top_k=top_k,
                min_score=min_score,
                hyde=hyde,
                no_rewrite=no_rewrite,
                qdrant_url=qdrant_url,
                ollama_url=ollama_url,
            )
            retrieved_ids = [r["requirement_id"] for r in result["results"]]
            metrics = compute_metrics(relevant_ids, retrieved_ids)
            per_query.append({
                "query_id": q["query_id"],
                "query": q["query"],
                "shape": q["shape"],
                "relevant_count": len(relevant_ids),
                "retrieved_ids": retrieved_ids,
                **metrics,
            })
        except Exception as e:
            log.error("Query %s failed: %s", q["query_id"], e)
            per_query.append({
                "query_id": q["query_id"],
                "query": q["query"],
                "shape": q["shape"],
                "relevant_count": len(relevant_ids),
                "error": str(e),
            })

    non_zero = [r for r in per_query if r["shape"] != "zero" and "error" not in r]
    zero = [r for r in per_query if r["shape"] == "zero" and "error" not in r]

    aggregate = {}
    for k in K_VALUES:
        key = f"recall@{k}"
        vals = [r[key] for r in non_zero if key in r]
        aggregate[f"mean_{key}"] = round(sum(vals) / len(vals), 4) if vals else None
    mrr_vals = [r["mrr"] for r in non_zero if "mrr" in r]
    aggregate["mean_mrr"] = round(sum(mrr_vals) / len(mrr_vals), 4) if mrr_vals else None
    aggregate["non_zero_query_count"] = len(non_zero)
    aggregate["zero_query_count"] = len(zero)
    aggregate["zero_query_mean_returned_count"] = (
        round(sum(r["returned_count"] for r in zero) / len(zero), 2) if zero else None
    )
    aggregate["failed_query_count"] = sum(1 for r in per_query if "error" in r)

    return {"per_query": per_query, "aggregate": aggregate}


def format_report(report: dict) -> str:
    agg = report["aggregate"]
    lines = ["# Retrieval Eval Harness Report (WP-37.1)", ""]
    lines.append("## Aggregate")
    lines.append(f"- Queries scored (non-zero ground truth): {agg['non_zero_query_count']}")
    for k in K_VALUES:
        lines.append(f"- Mean recall@{k}: {agg[f'mean_recall@{k}']}")
    lines.append(f"- Mean MRR: {agg['mean_mrr']}")
    lines.append(f"- Zero-truth queries: {agg['zero_query_count']}, "
                  f"mean results returned: {agg['zero_query_mean_returned_count']}")
    if agg["failed_query_count"]:
        lines.append(f"- **{agg['failed_query_count']} quer(y/ies) failed to run** — see per-query detail")
    lines.append("")
    lines.append("## Per-query")
    lines.append("")
    lines.append("| ID | Shape | Relevant | recall@5 | recall@10 | recall@20 | MRR | Notes |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in report["per_query"]:
        if "error" in r:
            lines.append(f"| {r['query_id']} | {r['shape']} | {r['relevant_count']} | — | — | — | — | ERROR: {r['error']} |")
            continue
        if r["shape"] == "zero":
            lines.append(f"| {r['query_id']} | zero | 0 | — | — | — | — | returned {r['returned_count']} result(s) |")
        else:
            lines.append(
                f"| {r['query_id']} | {r['shape']} | {r['relevant_count']} | "
                f"{r.get('recall@5', '—')} | {r.get('recall@10', '—')} | {r.get('recall@20', '—')} | "
                f"{r.get('mrr', '—')} | |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="WP-37.1: retrieval-quality eval harness")
    parser.add_argument("--gold", default=str(_ROOT / "eval" / "gold_retrieval_queries.jsonl"))
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--top-k", type=int, default=max(K_VALUES))
    parser.add_argument("--min-score", type=float, default=0.02)
    parser.add_argument("--no-hyde", action="store_true", help="Disable HyDE (production default is on)")
    parser.add_argument("--no-rewrite", action="store_true", help="Disable query rewrite (production default is on)")
    parser.add_argument("--output-dir", default=str(_ROOT / "eval" / "spike_results" / "wp_37_1"))
    args = parser.parse_args()

    queries = load_gold_queries(args.gold)
    print(f"Loaded {len(queries)} labeled queries from {args.gold}")

    report = run_harness(
        queries,
        qdrant_url=args.qdrant_url,
        ollama_url=args.ollama_url,
        top_k=args.top_k,
        min_score=args.min_score,
        hyde=not args.no_hyde,
        no_rewrite=args.no_rewrite,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    report_md = format_report(report)
    (out_dir / "report.md").write_text(report_md, encoding="utf-8")

    print(report_md)
    print(f"Wrote {out_dir / 'results.json'} and {out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
