#!/usr/bin/env python3
"""WP-40: run the expanded gold query set through the WP-37.1 harness, classify
every miss/over-grab via eval/failure_classifier.py, and report category
prevalence plus a specific, evidenced WP-41 recommendation.

No retrieval code changes -- measurement/diagnosis only (WP-40 Non-Goals).
"""
import argparse
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.failure_classifier import CorpusIndex, build_prevalence_report  # noqa: E402
from eval.retrieval_eval_harness import load_gold_queries, run_harness  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def format_report(report: dict) -> str:
    lines = ["# WP-40 Failure Classification Report", ""]
    agg = report["harness_report"]["aggregate"]
    lines.append("## Harness aggregate (expanded ~50-query set)")
    for k in ("mean_recall@5", "mean_recall@10", "mean_recall@20", "mean_mrr"):
        lines.append(f"- {k}: {agg.get(k)}")
    lines.append(f"- non-zero queries scored: {agg['non_zero_query_count']}")
    lines.append(f"- zero-truth queries: {agg['zero_query_count']}, mean results returned: {agg['zero_query_mean_returned_count']}")
    if agg["failed_query_count"]:
        lines.append(f"- **{agg['failed_query_count']} quer(y/ies) failed to run**")
    lines.append("")

    lines.append("## Category prevalence")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|---|---|")
    for cat, count in report["category_prevalence"].items():
        lines.append(f"| {cat} | {count} |")
    lines.append("")
    sub = report["extraction_failure_sub_counts"]
    lines.append(f"- extraction_failure sub-counts: (a) absent_from_corpus={sub['a_absent_from_corpus']}, "
                  f"(b) never_extracted={sub['b_never_extracted']}")
    lines.append(f"- zero-truth queries never reporting empty: {report['zero_truth_never_reports_empty']}")
    lines.append("")

    lines.append("## Miss classifications (detail)")
    lines.append("")
    lines.append("| query_id | requirement_id | category | evidence |")
    lines.append("|---|---|---|---|")
    for m in report["miss_classifications"]:
        lines.append(f"| {m['query_id']} | {m.get('requirement_id')} | {m.get('category')} | {m['evidence']} |")
    lines.append("")

    lines.append("## Over-grab findings")
    lines.append("")
    lines.append("| query_id | requirement_id | rank | evidence |")
    lines.append("|---|---|---|---|")
    for og in report["over_grab_classifications"]:
        lines.append(f"| {og.get('query_id', '?')} | {og['requirement_id']} | {og['rank']} | {og['evidence']} |")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    from core import config as _config

    cfg = _config.load()
    parser = argparse.ArgumentParser(description="WP-40: failure classification report")
    parser.add_argument("--gold", default=str(_ROOT / "eval" / "gold_retrieval_queries.jsonl"))
    parser.add_argument("--qdrant-url", default=cfg.qdrant_url)
    parser.add_argument("--ollama-url", default=cfg.ollama_url)
    parser.add_argument("--output-dir", default=str(_ROOT / "eval" / "spike_results" / "wp_40_baseline_refresh"))
    args = parser.parse_args()

    queries = load_gold_queries(args.gold)
    print(f"Loaded {len(queries)} labeled queries from {args.gold}")

    print("Running WP-37.1 harness (unmodified) against the full expanded set...")
    harness_report = run_harness(queries, qdrant_url=args.qdrant_url, ollama_url=args.ollama_url)

    print("Loading current corpus index for classification...")
    corpus = CorpusIndex.load(cfg.processed_dir_path())

    print("Classifying every miss/over-grab (this makes additional retrieve() calls)...")
    report = build_prevalence_report(
        queries, corpus, qdrant_url=args.qdrant_url, ollama_url=args.ollama_url,
        harness_report=harness_report,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "classification_results.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report_md = format_report(report)
    (out_dir / "classification_report.md").write_text(report_md, encoding="utf-8")

    print(report_md)
    print(f"Wrote {out_dir / 'classification_results.json'} and {out_dir / 'classification_report.md'}")


if __name__ == "__main__":
    main()
