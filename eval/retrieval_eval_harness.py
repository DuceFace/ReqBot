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

CAUTION for WP-37.2's before/after comparison (Codex review, PR #177, verified
real): core.ask.generate_hyde_hypothesis() samples at temperature=0.3 with no
seed, so HyDE's third RRF leg differs slightly between separate runs of the
*same* query against the *same* index. A single-run recall delta between a
before/after pair could therefore partly reflect HyDE sampling noise, not the
embedding change under test. Mitigate by either running with hyde=False for
the controlled comparison (isolates the change being measured, at the cost of
not reflecting real hyde=True production behavior) or by running N>=3 repeats
per side and comparing distributions rather than single point estimates --
not fixed here, since caching/seeding HyDE would mean changing core/ask.py's
retrieval logic itself, out of this WP's own Non-Goals. See
docs/PHASE37_REQUIREMENTS.md's WP-37.2 Scope.
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

    # A query can have relevant_count == 0 without shape == "zero": WP-40's
    # eval/gold_retrieval_queries.jsonl uses this for known-unextracted
    # content (unextracted_relevant_content, sub-case (b) -- no
    # requirement_id ever existed to score against, unlike a "zero" query,
    # which is deliberately off-topic and correctly expected to return
    # nothing). compute_metrics() returns no recall/mrr keys for these
    # (Codex review, PR #189, on a local re-review of the WP-42 fix):
    # counting them in non_zero_query_count while they contribute nothing to
    # the mean silently overstated how many queries were actually scored --
    # the same shape of bug already fixed for Q-T01/Q-T03 there, just for
    # queries where restoring a real id isn't possible because none ever
    # existed. Split into a third, explicitly-reported bucket instead.
    non_zero = [
        r for r in per_query
        if r["shape"] != "zero" and "error" not in r and r["relevant_count"] > 0
    ]
    zero = [r for r in per_query if r["shape"] == "zero" and "error" not in r]
    unscored = [
        r for r in per_query
        if r["shape"] != "zero" and "error" not in r and r["relevant_count"] == 0
    ]

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
    aggregate["unscored_query_count"] = len(unscored)
    aggregate["unscored_query_ids"] = [r["query_id"] for r in unscored]
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
    if agg["unscored_query_count"]:
        lines.append(
            f"- **{agg['unscored_query_count']} quer(y/ies) with no scorable ground truth** "
            f"(non-zero shape, but no known-relevant id — e.g. unextracted content, not a "
            f"rankable miss): {', '.join(agg['unscored_query_ids'])}"
        )
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


def _positive_int(value: str) -> int:
    """Argparse type: integer that must be > 0."""
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: '{value}'")
    if iv <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return iv


def _non_negative_float(value: str) -> float:
    """Argparse type: float that must be >= 0."""
    try:
        fv = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid float value: '{value}'")
    if fv < 0:
        raise argparse.ArgumentTypeError("must be a non-negative number")
    return fv


def main() -> None:
    # Load config for qdrant/ollama-url and min-score defaults -- same pattern as
    # core/ask.py's own main(), so this harness works out of the box against
    # whatever ~/.config/reqbot/config.json already points at (Gemini review, PR #177).
    # top-k is deliberately NOT config-driven (see its own default below): this
    # harness's recall@10/@20 correctness depends on top-k never being smaller
    # than max(K_VALUES), which a lower configured default could silently violate.
    try:
        from core import config as _config
        _cfg = _config.load()
        _default_qdrant_url = _cfg.qdrant_url
        _default_ollama_url = _cfg.ollama_url
        _default_min_score = _cfg.min_score
    except Exception as e:
        log.warning("Could not load config defaults (%s) — using hardcoded defaults", e)
        _default_qdrant_url = "http://localhost:6333"
        _default_ollama_url = "http://localhost:11434"
        _default_min_score = 0.02

    parser = argparse.ArgumentParser(description="WP-37.1: retrieval-quality eval harness")
    parser.add_argument("--gold", default=str(_ROOT / "eval" / "gold_retrieval_queries.jsonl"))
    parser.add_argument("--qdrant-url", default=_default_qdrant_url)
    parser.add_argument("--ollama-url", default=_default_ollama_url)
    parser.add_argument("--top-k", type=_positive_int, default=max(K_VALUES))
    parser.add_argument("--min-score", type=_non_negative_float, default=_default_min_score)
    parser.add_argument("--no-hyde", action="store_true", help="Disable HyDE (production default is on)")
    parser.add_argument("--no-rewrite", action="store_true", help="Disable query rewrite (production default is on)")
    parser.add_argument("--output-dir", default=str(_ROOT / "eval" / "spike_results" / "wp_37_1"))
    args = parser.parse_args()

    if args.top_k < max(K_VALUES):
        parser.error(
            f"--top-k must be at least {max(K_VALUES)} (recall@{max(K_VALUES)} would silently "
            f"compute against a truncated candidate set otherwise)"
        )

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

    # A transient Qdrant/Ollama failure on even one query silently shrinks every
    # aggregate's denominator -- the report still looks like a complete, valid
    # run unless this exits nonzero (Codex review, PR #177).
    failed = report["aggregate"]["failed_query_count"]
    if failed:
        log.error("%d/%d quer(y/ies) failed to run -- report is incomplete", failed, len(queries))
        sys.exit(1)


if __name__ == "__main__":
    main()
