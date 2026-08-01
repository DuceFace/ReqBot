# ReqBot Phase 40 — Retrieval Quality: Baseline Refresh & Failure Classification

**Status:** Locked (drafted 2026-08-01; source: direct conversation with Tyler after WP-39.2 merged
— see Phase Framing below)
**Date:** 2026-08-01
**Preceded by:** Phase 39 (Parent-Stem Context Loss Audit & Reconstruction) — WP-39.1/WP-39.2 both
complete (`docs/PHASE39_REQUIREMENTS.md`). Also directly builds on Phase 37 (Retrieval Quality: Eval
Harness & Contextual Chunk Embeddings) — this phase reuses, not rebuilds, WP-37.1's harness and gold
query set.
**Followed by:** Not decided in advance — this phase's entire purpose is to produce the evidence that
decides WP-41's direction (reranker, table serialization / `STEM_NEVER_EXTRACTED`, Over-Grab
Precision, or something else). See §5.

---

## Status

This table is the live source of truth for Phase 40 WP status — update it here when the WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-40 — Retrieval Quality Baseline Refresh & Failure Classification | Complete |

---

## 1. Phase Framing

Phases 32-39 have all been **single-failure-shape fixes**: find one concrete, evidenced problem
(fabricated quotes, extraction fragments, parent-stem loss), scope a WP around it, fix it, measure
it. That approach has worked, but it optimizes for whichever failure shape is currently *visible* —
not necessarily the one costing the most real answer quality. Tyler's framing, directly: ReqBot's
core function is extracting the right requirements and retrieving them reliably for a real question;
the next WP should be chosen because the evidence says it's the biggest lever, not because it's the
most recently-noticed edge case.

**This isn't starting from zero — Phase 37 already built most of the needed infrastructure, checked
directly before writing this doc rather than assumed:**

- `eval/gold_retrieval_queries.jsonl` (16 hand-verified queries, 82 relevant `requirement_id`
  references, narrow/broad/zero-truth shapes) and `eval/retrieval_eval_harness.py` (real recall@5/
  recall@10/recall@20/MRR against production, unmodified `core.ask.retrieve()`) already exist.
- WP-37.1 already measured a real baseline (`eval/spike_results/wp_37_1/`): narrow queries strong
  (recall@5 = 0.9643, MRR = 1.0), broad/thematic queries weak (recall@5 = 0.2626, MRR = 0.6667 —
  barely half the relevant requirements found even at top-20), and — a finding this phase directly
  builds on — the system **never reports "no relevant results"** for a genuinely off-topic query;
  all 4 zero-truth queries returned a full 20 results with scores not obviously distinguishable from
  a real match's.
- WP-37.2 already tried the cheap version of contextual embeddings (metadata prefix: document title +
  section path + `parent_context`) and measured a real **regression** (mean recall@5 −0.088, MRR
  −0.13), reverted, not deployed — with an evidenced hypothesis (this corpus's section headings
  describe procedural structure, not topic). This rules out re-attempting that specific approach as a
  WP-41 candidate; only the LLM-generated-context version (Anthropic's full technique) remains
  untested, and only if the failure classification below says embedding-miss is a significant category
  at all.

**What's changed since WP-37.1's baseline was measured (2026-07-31), checked directly today:**

- Phase 38 (extraction-precision rule extensions) and WP-39.2 (parent-stem reconstruction) both
  merged after WP-37.1's baseline was taken — that baseline is stale and needs refreshing before it's
  trusted for anything.
- **`reqbot reindex` alone is not enough to reflect either change (Codex review, PR #186, verified
  real).** `reindex` only re-embeds whatever's currently on disk in each document's
  `_requirements_normalized.jsonl`/`_requirements_enriched.jsonl` — it does not re-run Step D. Both
  Phase 38 and WP-39.2 explicitly deferred reprocessing the real production corpus as part of their
  own scope (WP-39.2's Non-Goals: "not re-ingesting or reindexing the full production corpus... matching
  WP-38.2's own precedent"). Checked directly: **0 of the 18 real processed `_requirements_normalized.jsonl`
  files on disk today have a `parent_stem` field at all.** A baseline built from a plain `reqbot
  reindex` would silently still be measuring pre-Phase-38/pre-WP-39.2 data while being reported as a
  "post-WP-39.2" refresh — the pre-step below now reflects this.
- Corpus/index state, checked live via `reqbot status`/`reqbot docs` while drafting this doc (not
  trusted from any written-down number, per `CLAUDE.md`): Qdrant's `grc_requirements` collection has
  1,876 points; `reqbot docs` (latest-run-wins) reports 1,872 requirements across 13 documents — a
  small (4-point) drift, likely from a document reprocessed today during WP-39.2's live pipeline
  verification (in a scratch copy, not the real corpus — confirmed above). Needs a fresh, *reprocessed*
  `reqbot reindex` and confirmed match before the baseline refresh, same discipline WP-37.1 itself
  established.

**What's genuinely new in this phase, not covered by WP-37.1/37.2:**

- WP-37.1 measured aggregate recall/MRR and a narrow-vs-broad-vs-zero-truth split — it did not
  systematically classify *why* each specific miss happened. WP-37.2's own Findings did one
  single-example root-cause investigation (`REQ-e41d286c83f4`, Q-B02) by hand, as a one-off — not a
  repeatable classification applied to every miss.
- The gold query set's 16 queries don't deliberately cover parent-child/context queries or
  table-derived requirement queries at all — exactly the two failure shapes Phase 39's own work
  (parent-stem reconstruction, garbled-table detection) targets, so the existing set can't measure
  whether that work actually helped end-to-end retrieval, only whether the reconstruction logic
  itself is correct in isolation (WP-39.2's own retrieval-similarity spot-check, on 10 examples, not
  full query-level recall).

## 2. Goals

1. **Refresh the baseline.** Re-run WP-37.1's exact harness, unmodified, against current `main` (post
   Phase 38, post WP-39.2) — real numbers, not assumed to still hold.
2. **Build a failure-classification layer on top of the existing harness**, not a separate one:
   for every miss (a labeled-relevant `requirement_id` that doesn't make the evaluated top-k) and
   every clear over-grab (an irrelevant result ranking above a correct one), classify the *cause* into
   one of 8 categories — extraction failure, missing context, table serialization, embedding miss,
   ranking miss, over-grab, query/filter issue, zero-truth/confidence failure — grounded in real
   pipeline artifacts for each case, not intuition. See Scope below for operational definitions.
3. **Expand the gold query set from 16 to roughly 50**, deliberately across 6 coverage buckets
   (narrow/exact, broad/thematic, parent-child/context, table-derived, zero-truth/off-topic,
   messy-PDF/over-grab) — not grown randomly — using the same hand-verification discipline WP-37.1's
   original 16 already established (every `relevant_requirement_id` individually checked against real
   source text; an LLM-generated candidate is never an accepted label on its own).
4. **Produce a category-prevalence report that makes WP-41's direction a data-driven decision**, not
   an assumed one: reranking if ranking-miss dominates and the right requirements are already in the
   candidate pool; `STEM_NEVER_EXTRACTED`/table serialization if extraction/context misses dominate;
   Over-Grab Precision if over-grab dominates; something not yet on anyone's list if the data says so.

## 3. Non-Goals

- **No retrieval code changes in this WP.** Measurement and diagnosis only, same as WP-37.1's own
  non-goal — Tyler's explicit instruction. Whatever WP-41 turns out to be is a separate WP, scoped
  from this one's findings.
- **No reranker implementation.** A candidate WP-41 direction if the classification shows the right
  requirements are present in a larger candidate pool but ranked too low — not built here regardless
  of what the data shows.
- **No HyDE or query-rewrite prompt changes.** Both are measured *as they currently behave*
  (production defaults, same as WP-37.1) — re-tuning them is a candidate WP-41 direction if
  query/filter issues turn out to be a significant category, not a change made in this WP.
- **No `STEM_NEVER_EXTRACTED`/`GARBLED_TABLE` fix, no table-structure-aware serialization change.**
  Candidate WP-41 direction if extraction failure/missing context/table serialization dominate the
  classification — WP-39.2 explicitly deferred these; this phase decides whether that deferral still
  looks right at the classification-prevalence level, not just the 18-example level WP-39.1 traced.
- **No Over-Grab Precision fix** (open since Phase 38, `docs/PHASE38_REQUIREMENTS.md`'s Backlog).
  Same reasoning — a candidate WP-41 direction, not built here.
- **No re-attempt of contextual chunk embeddings**, cheap or LLM-generated version. WP-37.2 already
  measured the cheap version as a real regression; the LLM-generated version is, at most, a candidate
  WP-41 direction contingent on this phase's embedding-miss prevalence — not assumed useful and not
  attempted here regardless.
- **Not a claim that ~50 queries is a statistically rigorous or exhaustive sample.** Same honest
  caveat WP-37.1/35.1/35.2 already carry for their own small hand-verified sets — a real, deliberately
  structured baseline instrument, expected to keep growing, not a final number.

---

## 4. Work Packages

### WP-40 — Retrieval Quality Baseline Refresh & Failure Classification

**Source:** Tyler's direct framing, 2026-08-01, immediately after WP-39.2 merged — shift from
single-failure-shape fixes to end-to-end retrieval-quality measurement, to decide WP-41 by evidence
rather than by whichever edge case is currently loudest.

**Problem:** WP-37.1's retrieval-quality baseline (narrow strong, broad weak, zero-truth never
correctly reported) predates both Phase 38's extraction-precision fixes and WP-39.2's parent-stem
reconstruction, and was never broken down by *cause* — a WP-41 chosen from it today would be a guess
about which of several plausible mechanisms (extraction, context loss, table garbling, embedding
mismatch, ranking, over-grab, query rewrite, confidence calibration) is actually responsible for the
broad-query and zero-truth weaknesses it measured.

**Scope:**

- **Pre-step: reprocess the corpus through Step D, then confirm index freshness.** `reqbot reindex`
  alone only re-embeds whatever's already on disk — it does not re-run Step D, so it cannot by itself
  produce a baseline that reflects Phase 38's rejection-rule changes or WP-39.2's reconstruction
  (Codex review, PR #186: confirmed 0/18 real processed documents currently have a `parent_stem`
  field). Re-run Step D (`run_pipeline.run(pdf_path, output_dir, skip_to="D", skip_enrichment=True)`,
  or the equivalent CLI path) for each of the 13 documents against their *existing*
  `_extracted_requirements.jsonl`/`_chunks.jsonl` — no re-extraction, no Docling, no fresh LLM calls
  needed for this specifically, since Step D is deterministic and WP-39.2's reconstruction is free
  (runs unconditionally before the `--skip-enrichment` check per its own design) — then `reqbot
  reindex`. Confirm via direct Qdrant inspection (not just exit code, same discipline as WP-37.1's own
  pre-step) that `grc_requirements`'s point count matches `reqbot docs`'s total, *and* spot-check that
  at least one reprocessed document's normalized JSONL now has non-empty `parent_stem` on a record
  known to need it, before trusting anything measured against it as "post-WP-39.2."
- **Re-run WP-37.1's exact harness, unmodified**, against current `main` — same 16 queries, same
  labels, same production `retrieve()` defaults (HyDE on, query rewrite on, `top_k=20`,
  `min_score=0.02`). Report the refreshed baseline plainly, including a direct before/after comparison
  against WP-37.1's original numbers (did Phase 38/WP-39.2 move anything, even though neither targeted
  retrieval directly) — before doing any further work on top of it.
- **Expand the gold query set to ~50**, deliberately built across 6 buckets, each hand-verified
  against real corpus text (never an unchecked LLM-generated label):
  - Narrow/exact (WP-37.1's existing shape).
  - Broad/thematic (WP-37.1's existing shape).
  - **Parent-child/context** — queries whose correct answer is (or, pre-WP-39.2, was) exactly the
    kind of fragment WP-39.1 traced; a natural source is that same 18-example fixture
    (Codex review, PR #186: corrected path — the FRAGMENT-labeled records live in
    `eval/audit_wp38_1/labeled_failures.jsonl`, joined against `eval/audit_wp38_1/unbiased_sample.jsonl`
    by `requirement_id` for chunk/document context, exactly as `eval/audit_wp39_1/trace_examples.py`'s
    own `FIXTURE_DIR` does; `eval/audit_wp39_1/` itself holds only the tracing/classification scripts,
    no `labeled_failures.jsonl` of its own — confirmed directly, the original path here was wrong),
    reframed as retrieval queries rather than extraction-precision examples.
  - **Table-derived** — queries whose correct answer sits in or near a `GARBLED_TABLE`-pattern chunk
    (WP-39.1's 2 known examples plus new ones found while building this bucket).
  - Zero-truth/off-topic (WP-37.1's existing shape, expanded).
  - **Messy-PDF/over-grab** — queries where a known-problematic extraction (over-broad, duplicated, or
    otherwise imprecise per Phase 38's Over-Grab Precision backlog note) is likely to surface
    incorrectly.
- **When hand-labeling each query, also check the raw source document/chunk text directly, not just
  the existing requirement corpus, for content relevant to the query with no corresponding
  `requirement_id` at all** (Codex review, PR #186, verified real: `requirement_id` is only assigned
  after a record survives Step D's `valid_reqs.append()` — confirmed directly against
  `pipeline/parse_and_normalize.py` — so a query set built only from `relevant_requirement_ids` can
  detect an already-known record disappearing from top-k, but structurally cannot detect content Step
  C never extracted at all; extraction-failure prevalence would otherwise be systematically
  undercounted). Record any such find as a query-level `unextracted_relevant_content` note (document,
  location/quote, brief description) alongside `relevant_requirement_ids` — this is a distinct signal
  from a ranked-away ID and feeds extraction-failure prevalence directly, not through the recall
  metric. Concentrate this check on the broad/thematic and table-derived buckets, where genuinely
  unextracted content is most likely to hide.
- **Define and apply the failure-classification layer.** Starting operational definitions below —
  calibrate against real misses during the audit, the same way every category boundary in this
  project's prior audits (WP-38.1, WP-39.1) was calibrated rather than assumed correct on the first
  pass:
  1. **Extraction failure** — either (a) an expected `requirement_id` whose content is confirmed
     absent from a Step C/D record for the relevant chunk (checked directly against
     `*_extracted_requirements.jsonl` and `*_normalization_failures.jsonl`, same artifacts WP-39.1's
     `trace_examples.py` already knows how to read), or (b) a query's `unextracted_relevant_content`
     note from the labeling step above — genuinely unextracted source content with no `requirement_id`
     to even place in the gold set. Report the two sub-counts separately: (a) alone would understate
     true prevalence (see the labeling-methodology note above), so the combined count, not just (a), is
     what should drive the WP-41 recommendation.
  2. **Missing context** — the record exists but is a decontextualized fragment (WP-38.1/39.1's
     FRAGMENT shape) that either has no `parent_stem` despite looking like a WP-39.2 candidate, or is
     one of the categories WP-39.2 explicitly deferred (`STEM_NEVER_EXTRACTED`).
  3. **Table serialization** — the record's `source_quote`/chunk `raw_text` matches WP-39.1's
     confirmed `GARBLED_TABLE` signature (flattened `"Column = Value"` run-on text).
  4. **Embedding miss** — the record is well-formed (none of 1-3 apply) and absent even from a
     generously-sized candidate pool, re-checked with **`top_k` raised (e.g. to 100) *and*
     `min_score=0`, not `top_k` alone** (Codex review, PR #186, verified real: `core.ask.retrieve()`
     applies `min_score` filtering *before* the `top_k` trim — confirmed directly at
     `core/ask.py`'s `hits = [r for r in hits if r.score >= min_score]` running ahead of
     `hits = hits[:top_k]` — so a relevant record scoring just under the production `0.02` floor
     would still be silently absent from a "top-100" pool call that didn't also disable the floor,
     and get mislabeled as an embedding miss when it's actually a threshold/confidence-calibration
     problem, category 8) — a genuine semantic/vocabulary mismatch between query and indexed text.
  5. **Ranking miss** — the record *is* present in that larger, floor-disabled candidate pool but
     outside the evaluated top-k *at the production `min_score`* — retrievable, just not well-ranked.
     The category that would justify a reranker. **If a record is only found once `min_score=0` is
     set** (i.e. its production-default score is below the `0.02` floor), classify it under category 8
     instead — its absence is a threshold-calibration symptom, not an ordering one, even though it's
     technically "present in the larger pool."
  6. **Over-grab** — a wrong/irrelevant result ranks in top-k, possibly displacing a correct one;
     diagnosed per surfaced result, not per missing ID (ties to Phase 38's Over-Grab Precision
     backlog).
  7. **Query/filter issue** — the query-rewrite or HyDE step's transformation actively drifts from
     query intent, or an active `domain_tags`/`requirement_type` filter wrongly excludes a valid
     result — checked by comparing raw-query retrieval against production `retrieve()` for the
     specific miss.
  8. **Zero-truth/confidence failure** — two symptoms of the same underlying miscalibration, both
     counted here: (a) query-level, for the zero-truth bucket — does the system fail to signal "no
     good match" the way WP-37.1 already found it does universally; (b) per-record, from category 5
     above — a relevant record whose fused score falls below the production `min_score=0.02` floor
     and is dropped rather than surfaced, even though it's a real match.
- **Report category prevalence** (counts and which query buckets each concentrates in) and state a
  specific, evidenced WP-41 recommendation — not a menu of equally-weighted options.

**Non-goals:** see Phase Non-Goals above — no retrieval code changes, no reranker, no prompt changes,
no extraction/table/over-grab fixes, no re-attempted contextual embeddings; measurement and diagnosis
only.

**Tests/verification:**

- Unit tests for the failure-classifier logic against synthetic examples of each of the 8 categories
  (same discipline as WP-37.1's harness-math unit tests — proving the classification logic is correct
  independent of any specific real miss).
- The real deliverable is the classification report itself, run against the live, refreshed corpus —
  fundamentally a measurement WP, same shape as WP-37.1/WP-35.1/WP-35.2's own verification.
- Every new gold-query label hand-verified against real corpus text before being trusted, same
  discipline as WP-37.1's original 16.
- Full `pytest` suite and `ruff check .` clean throughout.

**Gate:** Corpus reprocessed through Step D (confirmed via a non-empty `parent_stem` spot-check, not
just a matching point count) and reindexed before measuring anything; WP-37.1's harness re-run
unmodified against current `main` with a real refreshed baseline reported (including a direct
before/after vs. WP-37.1's original numbers); gold query set expanded from 16 to ~50 with deliberate
coverage across all 6 named buckets, every label hand-verified against real source text including a
check for unextracted-but-relevant content with no `requirement_id`; every miss/over-grab across the
expanded set classified into one of the 8 categories using the operational definitions above
(calibrated against real examples, not applied blindly), extraction-failure reported as both sub-counts
(missing `requirement_id` vs. genuinely unextracted content); category prevalence reported; a specific,
evidenced WP-41 recommendation stated; no retrieval code changed; full test suite and `ruff check .`
clean.

**Findings:**

**Pre-step (corpus reprocess + reindex).** Reprocessed all 13 real corpus documents through Step D
only (`run_pipeline.run(pdf_path, out_dir, skip_to="D", skip_enrichment=True, skip_description_gate=True)`,
against each doc's existing `_extracted_requirements.jsonl`/`_chunks.jsonl` — no Docling, no fresh LLM
calls) directly into each document's already-winning run directory. `_freshest_acceptable_tier()`
(Codex PR #169's own mtime-fallback logic) correctly fell through every doc's stale gated/enriched
tier to the freshly-regenerated normalized tier once its mtime became newest — confirmed live for all
13 docs via `resolve_latest_requirement_files()` before and after. `reqbot reindex` afterward: Qdrant
`grc_requirements` went from 1,876 to **1,856** points, matching `reqbot docs`'s total exactly.
`parent_stem` spot-checked directly in the live Qdrant payload (not just the JSONL) — 201/1,856
records now carry a non-empty `parent_stem`. Point count moving 1872→1856 (16 fewer requirements) is
itself a real finding, not noise — see below.

**Baseline refresh (WP-37.1's original 16 queries, unmodified).** Re-ran `eval/retrieval_eval_harness.py`
exactly as WP-37.1 left it, against current `main`, post-reprocess:

| | narrow recall@5 | narrow MRR | broad recall@5 | broad MRR |
|---|---|---|---|---|
| WP-37.1 (2026-07-31) | 0.9643 | 1.0 | 0.2626 | 0.6667 |
| WP-40 refresh (2026-08-01) | 0.8571 | 1.0 | 0.184 | 0.7667 |

Aggregate (all 12 non-zero queries): mean recall@5 0.6719→0.5767, mean recall@10 0.739→0.663, mean
recall@20 0.8129→0.7363, mean MRR 0.8611→0.9028. Zero-truth queries: still 4/4 return a full 20
results at production `min_score` — the "never signals no match" finding WP-37.1 first made is
**unchanged** by Phase 38 or WP-39.2.

The narrow-query recall@5 drop (0.9643→0.8571) is a **real regression, not noise**: sanity-checking
the 16 original queries' `relevant_requirement_ids` against the reprocessed corpus found 2 of them
(`Q-N03`'s `REQ-19f5e7133b96`, `Q-N04`'s `REQ-cbc6374a655f`) no longer exist at all. Both are now
rejected during Step D with new error reasons (`unrepairable_fragment_quote`,
`orphaned_list_item_quote`) that didn't reject them before Phase 38's rule extensions merged — a
previously-correct fragment (part of `Q-N03`'s deliberately-4-part fragmented answer) and a
previously-correct orphaned list item (`Q-N04`'s Insider Threat Program citation) are now silently
gone. Broad-query MRR *improved* (0.6667→0.7667) despite recall@5 dropping slightly, consistent with
WP-39.2's reconstruction helping some already-found results rank better without pulling in new ones.

**Failure classification (expanded ~50-query set, full results:
`eval/spike_results/wp_40_baseline_refresh/classification_report.md`).** Gold set expanded from 16 to
**45** queries across all 6 buckets (11 narrow, 8 broad, 8 zero-truth, 8 parent-child/context, 5
table-derived, 5 messy-PDF/over-grab), every label hand-verified against real corpus text via live
`retrieve()` calls before being trusted (same discipline as the original 16) — see
`eval/gold_retrieval_queries.jsonl`'s per-query `notes` field for each one's verification method.
Harness aggregate across the full 45: mean recall@5 0.582, recall@10 0.6538, recall@20 0.7106, mean
MRR 0.7238 (37 non-zero queries; not directly comparable to the 16-query numbers above — a different,
larger, and harder query set by design).

55 misses + 19 over-grabs classified into the 8 categories:

| Category | Count (all 45 queries) | Count (excl. Q-B05) |
|---|---|---|
| ranking_miss | 18 | 9 |
| missing_context | 10 | 7 |
| extraction_failure | 9 (7a absent-from-corpus, 2b never-extracted) | 9 |
| embedding_miss | 8 | 3 |
| table_serialization | 5 | 5 |
| query_filter_issue | 5 | 3 |
| zero_truth_confidence_failure (per-record) | 0 | 0 |
| **over_grab** | **19** | — |

`Q-B05` ("risk assessment and risk management process requirements", 29 relevant IDs — WP-37.1's own
largest, weakest broad query) alone accounts for 19/55 misses (mostly `ranking_miss` and
`embedding_miss`). Reporting both columns because a single heavy query shouldn't silently set the
whole phase's conclusion — `ranking_miss` still ties for the largest category (9) even with `Q-B05`
excluded, so the finding holds independent of that one query.

Separately, **all 8 zero-truth queries** still return a full 20 results at production `min_score`
(`zero_truth_never_reports_empty: true`) — the query-level symptom of category 8, unchanged since
WP-37.1, and not reflected in the `0` per-record count above (that `0` means no *relevant* record was
found only-below-floor in this run's misses, a different and narrower symptom).

**WP-41 recommendation: reranker, with two smaller companion items.**

1. **Primary: a reranker is the best-evidenced single lever.** `ranking_miss` is the largest or
   tied-largest miss category both including and excluding `Q-B05`, and `over_grab` (19 findings) is
   the single largest finding of any kind — both are exactly what a reranker over a larger initial
   candidate pool addresses: pull correctly-present-but-low-ranked results up, push
   duplicate/near-duplicate/descriptive-background results (the `over_grab` evidence is dominated by
   same-chunk duplicate fragments, plus a handful of genuinely non-prescriptive "descriptive
   background" text outranking the real answer) down. `embedding_miss` (8, 3 excl. `Q-B05`) is the
   *smallest* well-formed-record category — corroborating WP-37.2's own finding that the embedding
   representation itself isn't the biggest lever right now, so LLM-generated contextual embeddings
   should stay lower priority than reranking.
2. **Companion (small, fix-shaped, not a new feature): investigate the Phase 38 fragment-rejection
   regression found above** (`Q-N03`/`Q-N04`'s 2 dropped IDs, plus `Q-C04`/`Q-C05`/`Q-C06`'s 5
   additional confirmed-gone WP-38.1 FRAGMENT examples — 7 total real, evidenced extraction_failure
   sub-case (a) instances, all previously-correct records now rejected by `unrepairable_fragment_quote`
   or `orphaned_list_item_quote`). This is a regression to fix, not a scope decision — not the same
   thing as the `STEM_NEVER_EXTRACTED`/table-serialization *enhancement* work already on the Candidate
   WP-41 list.
3. **Companion (small, targeted): the zero-truth/confidence-floor problem is unchanged and remains
   serious for a compliance tool** — 8/8 zero-truth queries still return 20 results indistinguishable
   in count from a real match. Independent of whatever WP-41 becomes for ranking, this deserves its
   own explicit fix (recalibrated `min_score` and/or an explicit low-confidence signal), not further
   deferral.

`missing_context` (10, 7 excl. `Q-B05`) + `table_serialization` (5) together are real and sizable
(WP-40 also found 3 *new* `GARBLED_TABLE` chunks beyond WP-39.1's original 2, and confirmed 21 garbled
chunks total across 5 documents when scanning the whole corpus — a bigger problem than previously
known) but individually smaller than `ranking_miss` — `STEM_NEVER_EXTRACTED`/table-structure-aware
serialization work is real and evidenced, just not the top-ranked lever this round.

---

## 5. Candidate WP-41 Directions (not decided here)

Explicitly not chosen by this phase — listed so the connection between WP-40's findings and WP-41's
eventual scope is traceable, not implicit:

- **Reranker** (`docs/TODO_future_improvements.txt`'s RETRIEVAL EXPERIMENTS item 1) — if ranking-miss
  dominates: right requirements present in a larger candidate pool, just not well-ranked.
- **`STEM_NEVER_EXTRACTED` / table-structure-aware serialization** (WP-39.2's own deferred backlog,
  `docs/PHASE39_REQUIREMENTS.md`'s Backlog) — if extraction failure / missing context / table
  serialization dominate.
- **Over-Grab Precision** (`docs/PHASE38_REQUIREMENTS.md`'s Backlog) — if over-grab dominates.
- **LLM-generated contextual embeddings** (WP-37.2's own suggested follow-up, contingent on avoiding
  the procedural-vs-topical-framing mistake that sank the cheap version) — only if embedding-miss is
  significant *and* the mechanism looks like WP-37.2's hypothesis rather than something else.
- Anything else the classification surfaces that isn't on this list yet — the whole point of this
  phase is not pre-committing to one of the above before the evidence exists.
- **New, found by WP-40: a Phase 38 fragment-rejection regression** — `unrepairable_fragment_quote`/
  `orphaned_list_item_quote` now reject 7 confirmed real, previously-correct records (2 from the
  original 16-query baseline alone). A bug-fix-shaped follow-up, not the `STEM_NEVER_EXTRACTED`
  enhancement item above — see WP-40's Findings.

**Recommendation (see WP-40 Findings for full evidence): reranker is the primary WP-41 direction**,
with the Phase 38 regression fix and the zero-truth/confidence-floor fix as small, independent
companion items.

---

## 6. Success Gate

- [x] Corpus reprocessed through Step D (not just `reindex`) and confirmed via a non-empty
      `parent_stem` spot-check before any measurement is trusted as "post-WP-39.2." (201/1,856
      records, confirmed live in Qdrant payload.)
- [x] WP-37.1's harness re-run unmodified against current `main`; a real, refreshed baseline reported
      with a direct before/after comparison against WP-37.1's original numbers.
- [x] Gold query set expanded from 16 to 45 (~50), deliberately covering all 6 named buckets, every
      label hand-verified against real corpus text — including a check for relevant source content
      with no `requirement_id` at all (2 table-derived queries' `unextracted_relevant_content`).
- [x] Every miss/over-grab across the expanded set classified into one of the 8 named categories,
      using operational definitions calibrated against real examples during the audit; extraction
      failure reported as both sub-counts (7 missing-from-corpus, 2 genuinely unextracted).
- [x] Category prevalence reported and a specific, evidenced WP-41 recommendation stated (reranker,
      primary) — not a menu of untested options.
- [x] No retrieval code changed in this phase (only `eval/`, `docs/`, and `tests/` touched).
- [x] Full `pytest` suite and `ruff check .` clean throughout.

---

## 7. Guardrails

- No retrieval-quality claim ships without being checked against the real (refreshed) harness first —
  same discipline Phase 37 itself established.
- Every gold-query label — old or newly added — must be hand-verified against real corpus text; an
  LLM-generated candidate is a starting point to check, never an accepted label on its own.
- Every failure-category assignment must cite the specific artifact/check that justified it (which
  file, which field, which score) — not an intuitive guess at which of the 8 categories a miss
  "feels like."
- One phase, one measurement — this phase produces evidence and a recommendation; it does not also
  start implementing whatever that recommendation turns out to be. WP-41 is a separate, explicitly
  scoped WP.
