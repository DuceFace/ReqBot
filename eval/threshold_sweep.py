#!/usr/bin/env python3
"""
eval/threshold_sweep.py — WP-35.2 threshold calibration sweep

Scores every (source_quote, description) pair in
eval/gold_description_grounding.jsonl with MiniCheck (the same model/
checkpoint WP-34.4's spike used) and sweeps a range of support_prob
thresholds, reporting false-positive rate (faithful descriptions wrongly
rejected) vs. catch rate (fabricated descriptions correctly rejected) per
threshold -- the same shape as pipeline/parse_and_normalize.py's own
documented QUOTE_GROUNDING_THRESHOLD sweep (WP-32.1).

Primary statistics are computed only against source == "wp_35_1_harvest"
records -- the 8 source == "wp_34_4_spike" records are exact duplicates of
WP-34.4's own proof-of-concept fixtures and are excluded from the sweep
itself to avoid the circularity WP-35.1's own review found (Codex, PR #166):
counting the spike's own examples toward this WP's "independent" catch rate
would inflate it artificially. They're still scored and checked separately
as a regression test (does the chosen threshold still classify them
correctly), matching docs/PHASE35_REQUIREMENTS.md's WP-35.2 Scope.

That same Scope section also requires this script to report per-subtype
breakdowns and an explicit confident-vs-provisional call, not just an
aggregate number -- the wp_35_1_harvest partition has only 8 independent
fabricated examples (3 citation, 1 fragment, 2 modality, 2 other), thin
enough that a single record flipping catch/miss moves the aggregate catch
rate by 12.5 points and the fragment subtype (1 example) cannot support a
subtype-specific threshold with any real confidence.

Outputs:
  eval/spike_results/wp_35_2/report.md    — human-readable sweep + verdict
  eval/spike_results/wp_35_2/results.json — raw per-record scores + sweep table

Usage:
  python3 eval/threshold_sweep.py
  python3 eval/threshold_sweep.py --model flan-t5-large
"""

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

GOLD_FILE = _ROOT / "eval" / "gold_description_grounding.jsonl"

# Candidate thresholds to sweep -- support_prob is MiniCheck's own 0-1
# continuous score, so a fixed 0.05 grid (not derived from the data) is used
# rather than midpoints between observed scores, matching the "declare
# reasonable candidates up front, then let real evidence pick one" approach
# QUOTE_GROUNDING_THRESHOLD's own sweep took (archive/PHASE32_REQUIREMENTS.md).
THRESHOLD_CANDIDATES = [round(i * 0.05, 2) for i in range(1, 20)]  # 0.05 .. 0.95

FABRICATED_LABELS = {
    "fabricated_citation", "fabricated_fragment", "fabricated_modality", "fabricated_other",
}


def _fmt_rate(rate: float | None) -> str:
    """Format a rate that's None when its partition (faithful/fabricated) is empty."""
    return f"{rate:.1%}" if rate is not None else "N/A (empty partition)"


def load_gold() -> list[dict]:
    records = []
    with open(GOLD_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _load_scorer(model_name: str):
    from minicheck.minicheck import MiniCheck
    t0 = time.time()
    scorer = MiniCheck(model_name=model_name)
    print(f"Loaded MiniCheck ({model_name}) in {time.time() - t0:.1f}s", file=sys.stderr)
    return scorer


def score_records(records: list[dict], scorer) -> list[dict]:
    docs = [r["source_quote"] for r in records]
    claims = [r["description"] for r in records]
    _, raw_prob, _, _ = scorer.score(docs=docs, claims=claims)
    scored = []
    for r, prob in zip(records, raw_prob):
        scored.append({**r, "support_prob": round(prob, 4)})
    return scored


def sweep(scored_records: list[dict], thresholds: list[float]) -> list[dict]:
    """False-positive rate vs. catch rate per threshold, wp_35_1_harvest only."""
    harvest_records = [r for r in scored_records if r["source"] == "wp_35_1_harvest"]
    faithful = [r for r in harvest_records if r["label"] == "faithful"]
    fabricated = [r for r in harvest_records if r["label"] in FABRICATED_LABELS]

    table = []
    for t in thresholds:
        false_positives = [r for r in faithful if r["support_prob"] < t]
        caught = [r for r in fabricated if r["support_prob"] < t]
        by_subtype = {}
        for label in sorted(FABRICATED_LABELS):
            subtype_records = [r for r in fabricated if r["label"] == label]
            subtype_caught = [r for r in subtype_records if r["support_prob"] < t]
            by_subtype[label] = {
                "n": len(subtype_records),
                "caught": len(subtype_caught),
            }
        table.append({
            "threshold": t,
            "false_positive_rate": len(false_positives) / len(faithful) if faithful else None,
            "false_positive_count": len(false_positives),
            "faithful_n": len(faithful),
            "catch_rate": len(caught) / len(fabricated) if fabricated else None,
            "catch_count": len(caught),
            "fabricated_n": len(fabricated),
            "by_subtype": by_subtype,
        })
    return table


# Diminishing-returns threshold pick, not blind catch-rate maximization -- an
# earlier version of this script picked whatever threshold first hit 100%
# catch rate and it chose 0.95, which "catches" the single hardest fabricated
# example at the cost of a 58.7% false-positive rate (54/92 faithful
# descriptions wrongly rejected). That's a real result worth keeping in the
# swept table, but a threshold no one would actually want to run in
# production -- exactly the kind of "diminishing returns" case
# QUOTE_GROUNDING_THRESHOLD's own documented sweep (pipeline/parse_and_
# normalize.py, WP-32.1) explicitly reasons about ("pushing to 80 nearly
# triples the false-positive rate for comparatively little extra coverage").
#
# Rule: among thresholds whose false-positive rate stays at or below
# fp_rate_cap, pick the one with the highest catch rate (ties broken toward
# the lower/more conservative threshold). 10% is a judgment call, not derived
# from the data -- roughly "no more than 1 in 10 real faithful descriptions
# gets wrongly rejected," a defensible ceiling for something that will run
# unattended in production.
FP_RATE_CAP = 0.10


def select_threshold(table: list[dict], fp_rate_cap: float = FP_RATE_CAP) -> dict:
    """Pick a threshold row from sweep()'s table via the diminishing-returns rule above.

    Guards against an empty faithful or fabricated partition (both rates
    would be None in that case, per sweep()'s own None-on-empty convention)
    rather than crashing on a None comparison.
    """
    within_cap = [
        row for row in table
        if row["false_positive_rate"] is not None and row["false_positive_rate"] <= fp_rate_cap
    ]
    candidates = within_cap or table
    return max(
        candidates,
        key=lambda row: (
            row["catch_rate"] if row["catch_rate"] is not None else -1.0,
            -row["threshold"],
        ),
    )


def margin_analysis(scored_records: list[dict], threshold: float) -> dict:
    """How close is each classification at `threshold` to flipping?

    Surfaces whether the chosen threshold's catch/accept decisions sit on a
    knife's edge -- found by Codex review on this WP's own PR (#167): one of
    the 7 harvest-partition fabricated records caught at threshold=0.85
    scores 0.8421, a margin of only 0.0079. Reporting the aggregate catch
    rate alone (7/8) makes that catch look as solid as any other; it isn't.
    """
    harvest = [r for r in scored_records if r["source"] == "wp_35_1_harvest"]
    fabricated = [r for r in harvest if r["label"] in FABRICATED_LABELS]
    faithful = [r for r in harvest if r["label"] == "faithful"]

    caught = [r for r in fabricated if r["support_prob"] < threshold]
    missed = [r for r in fabricated if r["support_prob"] >= threshold]
    accepted = [r for r in faithful if r["support_prob"] >= threshold]

    # Smallest margin on the "correct" side of the cutoff in each direction --
    # the catch/accept that would flip first under the smallest score change.
    narrowest_catch = min(caught, key=lambda r: threshold - r["support_prob"], default=None)
    narrowest_accept = min(accepted, key=lambda r: r["support_prob"] - threshold, default=None)

    return {
        "threshold": threshold,
        "narrowest_catch": (
            {
                "requirement_id": narrowest_catch["requirement_id"],
                "label": narrowest_catch["label"],
                "support_prob": narrowest_catch["support_prob"],
                "margin": round(threshold - narrowest_catch["support_prob"], 4),
            }
            if narrowest_catch else None
        ),
        "narrowest_accept": (
            {
                "requirement_id": narrowest_accept["requirement_id"],
                "label": narrowest_accept["label"],
                "support_prob": narrowest_accept["support_prob"],
                "margin": round(narrowest_accept["support_prob"] - threshold, 4),
            }
            if narrowest_accept else None
        ),
        "missed_fabricated_n": len(missed),
    }


def regression_check(scored_records: list[dict], threshold: float) -> dict:
    spike_records = [r for r in scored_records if r["source"] == "wp_34_4_spike"]
    results = []
    all_correct = True
    for r in spike_records:
        predicted_reject = r["support_prob"] < threshold
        should_reject = r["label"] in FABRICATED_LABELS
        correct = predicted_reject == should_reject
        all_correct = all_correct and correct
        results.append({
            "requirement_id": r["requirement_id"], "label": r["label"],
            "support_prob": r["support_prob"], "predicted_reject": predicted_reject,
            "should_reject": should_reject, "correct": correct,
        })
    return {"threshold": threshold, "all_correct": all_correct, "records": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="WP-35.2 threshold calibration sweep")
    parser.add_argument("--model", default="flan-t5-large")
    args = parser.parse_args()

    records = load_gold()
    scorer = _load_scorer(args.model)
    scored = score_records(records, scorer)

    thresholds = THRESHOLD_CANDIDATES
    table = sweep(scored, thresholds)
    chosen = select_threshold(table)
    chosen_threshold = chosen["threshold"]

    regression = regression_check(scored, chosen_threshold)
    margins = margin_analysis(scored, chosen_threshold)

    out_dir = _ROOT / "eval" / "spike_results" / "wp_35_2"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "model": args.model,
        "thresholds_swept": thresholds,
        "sweep_table": table,
        "chosen_threshold": chosen_threshold,
        "regression_check": regression,
        "margin_analysis": margins,
        "scored_records": scored,
    }
    (out_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    harvest_fabricated_n = table[0]["fabricated_n"] if table else 0
    harvest_faithful_n = table[0]["faithful_n"] if table else 0
    provisional = harvest_fabricated_n < 20  # thin-data threshold, documented in report

    lines = [
        "# WP-35.2 Threshold Calibration Sweep",
        "",
        "Generated by `eval/threshold_sweep.py`. See `docs/PHASE35_REQUIREMENTS.md`'s WP-35.2 "
        "section for the full scope and reasoning. Primary statistics below are computed only "
        "against `source == \"wp_35_1_harvest\"` records; `wp_34_4_spike` records are checked "
        "separately as a regression test, not counted here (WP-35.1's Codex-found circularity fix).",
        "",
        f"**Model:** MiniCheck ({args.model})",
        f"**Independent (wp_35_1_harvest) partition:** {harvest_fabricated_n} fabricated, "
        f"{harvest_faithful_n} faithful",
        "",
        "## Confidence call",
        "",
    ]
    if provisional:
        lines += [
            f"**PROVISIONAL, not a confident production calibration.** Only {harvest_fabricated_n} "
            "independent fabricated examples exist (see docs/PHASE35_REQUIREMENTS.md's WP-35.1 "
            "Findings -- a second corpus-expansion attempt confirmed this is a real data-scarcity "
            "finding, not insufficient search). A single record flipping catch/miss moves the "
            f"aggregate catch rate by "
            f"{(100 / harvest_fabricated_n if harvest_fabricated_n else 0):.1f} points. "
            "Per-subtype breakdowns "
            "below are even thinner (as low as 1 example) and must not be read as calibrated "
            "subtype-specific thresholds. The threshold chosen below is a reasonable, evidence-based "
            "pick given what exists today, not a number WP-35.4 should treat as final without "
            "acknowledging this caveat.",
            "",
        ]
    else:
        lines += [
            f"Confident: {harvest_fabricated_n} independent fabricated examples is enough scale "
            "for the aggregate statistics below to be treated as a real calibration, not just a "
            "proof of concept.",
            "",
        ]

    MARGIN_SENSITIVITY = 0.02  # a catch/accept within this of the cutoff counts as fragile
    nc = margins["narrowest_catch"]
    na = margins["narrowest_accept"]
    if nc and nc["margin"] <= MARGIN_SENSITIVITY:
        lines += [
            f"**Sensitive, not just thin: the narrowest catch at `{chosen_threshold}` is "
            f"`{nc['requirement_id']}` (`{nc['label']}`) at support_prob={nc['support_prob']}, a "
            f"margin of only {nc['margin']}.** A sub-one-point shift in that single score would drop "
            f"catch rate from {chosen['catch_count']}/{chosen['fabricated_n']} to "
            f"{chosen['catch_count'] - 1}/{chosen['fabricated_n']} — found by Codex review on this "
            "WP's own PR (#167): reporting only the aggregate catch rate makes this catch look as "
            "solid as any other, and it isn't.",
            "",
        ]
    if na and na["margin"] <= MARGIN_SENSITIVITY:
        lines += [
            f"The narrowest correctly-accepted faithful record is `{na['requirement_id']}` "
            f"(support_prob={na['support_prob']}, margin {na['margin']}) — also close enough to the "
            "cutoff to be worth naming, though it doesn't change the caveat above.",
            "",
        ]

    one_step_up = next(
        (row for row in table if row["threshold"] > chosen_threshold), None
    )
    # What a naive "maximize catch rate, ignore cost" rule would have picked
    # on *this* run's actual sweep table -- computed from the real data, not
    # hardcoded to the default flan-t5-large run's numbers, so this paragraph
    # stays accurate if --model changes the score distribution (Codex, PR #167).
    naive_pick = max(table, key=lambda row: (
        row["catch_rate"] if row["catch_rate"] is not None else -1.0, -row["threshold"],
    ))
    naive_caveat = ""
    if naive_pick["threshold"] != chosen_threshold:
        naive_caveat = (
            f" A naive \"maximize catch rate\" rule instead picks `{naive_pick['threshold']}` on "
            f"this run's data, which does reach {_fmt_rate(naive_pick['catch_rate'])} catch rate but "
            f"at a {_fmt_rate(naive_pick['false_positive_rate'])} false-positive rate -- not a "
            "threshold anyone would want to run in production."
        )
    lines += [
        f"## Chosen threshold: `support_prob < {chosen_threshold}` → reject",
        "",
        f"Selection rule: highest catch rate among thresholds with false-positive rate ≤ "
        f"{FP_RATE_CAP:.0%} (see `eval/threshold_sweep.py`'s own `select_threshold()` for the "
        "reasoning; this mirrors `QUOTE_GROUNDING_THRESHOLD`'s own documented diminishing-returns "
        f"reasoning, `pipeline/parse_and_normalize.py`, WP-32.1).{naive_caveat}",
        "",
        f"- False-positive rate: {_fmt_rate(chosen['false_positive_rate'])} "
        f"({chosen['false_positive_count']}/{chosen['faithful_n']} faithful wrongly rejected)",
        f"- Catch rate: {_fmt_rate(chosen['catch_rate'])} "
        f"({chosen['catch_count']}/{chosen['fabricated_n']} fabricated correctly rejected)",
    ]
    if one_step_up is not None:
        lines.append(
            f"- One step up (`{one_step_up['threshold']}`) would move catch rate to "
            f"{_fmt_rate(one_step_up['catch_rate'])} but false-positive rate to "
            f"{_fmt_rate(one_step_up['false_positive_rate'])} -- excluded by the cap above."
        )
    lines += [
        "",
        "### Per-subtype catch rate at the chosen threshold",
        "",
        "| Subtype | n | Caught | Catch rate |",
        "|---|---|---|---|",
    ]
    for label in sorted(FABRICATED_LABELS):
        s = chosen["by_subtype"][label]
        rate = f"{s['caught']}/{s['n']}" if s["n"] else "n=0"
        lines.append(f"| `{label}` | {s['n']} | {s['caught']} | {rate} |")

    lines += [
        "",
        "### Regression check against WP-34.4's original spike fixtures (`wp_34_4_spike`, n=8)",
        "",
        f"All 8 correctly classified at this threshold: **{regression['all_correct']}**",
        "",
        "| requirement_id | label | support_prob | predicted | correct |",
        "|---|---|---|---|---|",
    ]
    for r in regression["records"]:
        pred = "reject" if r["predicted_reject"] else "accept"
        lines.append(
            f"| {r['requirement_id']} | {r['label']} | {r['support_prob']} | {pred} | "
            f"{r['correct']} |"
        )

    lines += [
        "",
        "## Full sweep table (wp_35_1_harvest only)",
        "",
        "| threshold | FP rate | FP count | catch rate | catch count |",
        "|---|---|---|---|---|",
    ]
    for row in table:
        lines.append(
            f"| {row['threshold']} | {_fmt_rate(row['false_positive_rate'])} | "
            f"{row['false_positive_count']}/{row['faithful_n']} | {_fmt_rate(row['catch_rate'])} | "
            f"{row['catch_count']}/{row['fabricated_n']} |"
        )

    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_dir / 'report.md'}", file=sys.stderr)
    print(f"Chosen threshold: {chosen_threshold} (provisional={provisional})", file=sys.stderr)


if __name__ == "__main__":
    main()
