# ReqBot Phase 41 — Context Recovery Fixes & Confidence Calibration

**Status:** Locked (drafted 2026-08-01; source: direct conversation with Tyler after WP-40 merged)
**Date:** 2026-08-01
**Preceded by:** Phase 40 (Retrieval Quality: Baseline Refresh & Failure Classification) —
`docs/PHASE40_REQUIREMENTS.md`, complete. This phase implements 2 of WP-40's 3 recommended
directions (the small companion items); the reranker (WP-40's primary recommendation) and the
definitional-content-retrievability question are both deferred — see Phase 40's §8 Backlog.
**Followed by:** Not decided. The reranker and the definitional-content question remain open,
tracked in Phase 40's Backlog.

---

## Status

| WP | Status |
|---|---|
| WP-41 — Context Recovery Fixes & Confidence Calibration | Complete |

---

## 1. Phase Framing

Tyler's direction after WP-40 merged: start with the two small companion items WP-40 flagged (a
fragment-rejection/context-loss regression and the zero-truth confidence-floor problem), not the
reranker — the reranker needs its own scoping conversation (almost certainly a new dependency, a
stop-and-ask item). "We could maybe throw in the two other small fixes you mentioned earlier" —
bundling both into one WP.

**What scoping this WP actually found, corrected from WP-40's own framing:** WP-40's Findings called
this "a Phase 38 fragment-rejection regression" affecting 7 records. Investigating it for this WP
found that framing was overstated in two different ways:

- **2 of the 7 are not losses at all.** `REQ-19f5e7133b96` (DODI 5200.44) and `REQ-97e6e5483093`
  (DODI 5200.44) are both colon-terminated governing clauses for a numbered list — `_is_unrepairable_fragment()`
  correctly rejects them (they carry no obligation content of their own), and WP-39.2's own
  reconstruction already attaches their exact text as `parent_stem` on the surviving child records
  (`REQ-11f2bd0fb495` and `REQ-42f23541de6c`/`REQ-4d5ff25165d2` respectively — confirmed directly).
  The content isn't lost; the two WP-37.1 gold queries that referenced the old, now-removed
  governing-clause ids (`Q-N03`, `Q-C05`) are simply pointing at stale ids. This is a gold-label fix,
  not a pipeline fix.
- **4 of the 7 (one whole afi10-2402 list) are a genuine, complete loss, but the rejection is working
  exactly as WP-38.2 designed it.** `_is_orphaned_list_item()` correctly identifies
  `"<Term>, as defined in <citation>."` shapes as pure definitional cross-references with no
  independent obligation — calibrated through multiple review rounds specifically to reject this
  shape. Loosening it would undo that work. This is a real product question (should non-obligation
  definitional content be retrievable at all, and how), not a bug — tracked in Phase 40's §8
  Backlog, **explicitly not fixed by this WP**.
- **1 (`REQ-1b1071c8d317`, afi17-203) is a genuine, well-evidenced, in-scope bug** — see WP-41's Scope
  below. This is the one real "context recovery" fix this phase makes.

**A second, more precise finding while diagnosing that 1 real case:** it isn't a missing fallback —
`pipeline/enrich_requirements.py`'s `_find_heading_stem()` (WP-39.2's own "reconstruction step 3")
already exists, is already unit-tested (`tests/unit/test_parent_stem_reconstruction.py`'s
`test_regression_all_18_known_examples`, the `REQ-1b1071c8d317` case), and *correctly* reconstructs
this exact record's parent_stem from its chunk's `parent_header_text` when called directly. But it
can never run in the real pipeline: `pipeline/parse_and_normalize.py`'s Step D rejects any
`_is_dangling_clause()` quote outright (`dangling_clause_quote`), and `apply_parent_stem_reconstruction()`
only ever processes records that already survived Step D. The two pieces of logic — WP-38.2's
rejection and WP-39.2's recovery for the exact same shape — were built and reviewed separately and
never actually run against each other on real data until WP-40's Step D reprocess. This is an
ordering bug between two already-shipped, already-correct-in-isolation pieces of code, not a design
question — see Scope below for the fix.

## 2. Goals

1. Fix the 2 mislabeled gold queries (`Q-N03`, `Q-C05`) so they reference the current,
   parent_stem-carrying ids instead of the removed governing-clause ids.
2. Fix the Step D / reconstruction ordering bug so `_find_heading_stem()`'s already-correct,
   already-tested logic actually gets to run on real dangling-clause records with a recoverable
   heading, instead of being unreachable dead code in the live pipeline.
3. Calibrate the zero-truth/confidence-floor problem with real evidence — sweep candidate
   `min_score` values (or a relative-confidence signal, if a flat threshold can't work) against the
   full 45-query gold set from `eval/gold_retrieval_queries.jsonl`, and apply whatever the data
   actually supports, not an assumed number.

## 3. Non-Goals

- **No reranker.** WP-40's primary recommendation, deferred — needs its own scoping conversation
  (likely a new dependency). Tracked in Phase 40's §8 Backlog.
- **No change to the definitional-content-retrievability question** (the 4 afi10-2402
  `orphaned_list_item_quote` rejections). A real product question, not decided here — tracked in
  Phase 40's §8 Backlog. `_is_orphaned_list_item()` itself is not touched by this WP.
- **No other WP-38/WP-38.2 rejection rule changes** beyond the one specific, evidenced ordering fix
  in Scope below. `_is_unrepairable_fragment()`, `_is_heading_echo()`, and the rest of
  `_is_orphaned_list_item()`'s own logic are untouched.
- **No STEM_NEVER_EXTRACTED / table-structure-aware serialization work** — still a separate,
  larger candidate WP-41 direction per Phase 40's §5/§8 (21 `GARBLED_TABLE` chunks now confirmed
  across 5 documents), not this WP's scope.
- **Not a claim that the zero-truth calibration produces a perfect fix.** If the sweep shows no
  single `min_score` cleanly separates zero-truth noise from genuine weak matches (a real
  possibility given `Q-B05`'s relevant results scoring as low as 0.033), report that honestly and
  recommend what WP-42 (or a later revisit) should try instead, rather than forcing an imperfect
  threshold into production and calling it solved.

---

## 4. Work Packages

### WP-41 — Context Recovery Fixes & Confidence Calibration

**Source:** Tyler's direction, 2026-08-01, immediately after WP-40 merged: start with the two small
companion items, not the reranker.

**Scope:**

- **Gold-label fix.** In `eval/gold_retrieval_queries.jsonl`: `Q-N03`'s `relevant_requirement_ids`
  drops `REQ-19f5e7133b96` (no longer exists, content is on `REQ-11f2bd0fb495`'s `parent_stem`, no id
  change needed there since the child record itself is unaffected); `Q-C05`'s
  `relevant_requirement_ids` changes from `[REQ-97e6e5483093]` to the 2 surviving child records that
  now carry its exact text as `parent_stem` (`REQ-42f23541de6c`, `REQ-4d5ff25165d2`). Both changes
  documented with a note explaining the correction (not a silent edit — same discipline as every
  other gold-label change this project has made).
- **Step D / reconstruction ordering fix**, `pipeline/parse_and_normalize.py`'s `_is_dangling_clause()`
  rejection branch (~line 764): before rejecting, check whether the chunk's own
  `parent_header_text` (already loaded into `hierarchy` earlier in the same loop iteration, no new
  I/O) is non-empty. If it is, don't reject — let the record survive as a normal Step D output;
  `apply_parent_stem_reconstruction()` (already called unconditionally after Step D, already gated on
  this exact `_is_dangling_clause()` check via `_find_heading_stem()`) will then correctly attach it
  as `parent_stem`, exactly as `test_regression_all_18_known_examples` already proves it should. If
  `parent_header_text` is empty/missing, reject as before (unchanged behavior — this only affects the
  specific case that's actually recoverable).
- **Zero-truth confidence-floor calibration.** New one-off script (or extension of
  `eval/retrieval_eval_harness.py`) that sweeps a range of candidate `min_score` values against the
  full 45-query gold set, reporting for each candidate: (a) how many of the 8 zero-truth queries
  correctly return 0 results, (b) the recall@5/10/20 impact on every other bucket (does raising the
  floor cut real relevant results, especially `Q-B05`-shaped weak matches). Report the real
  trade-off curve, not a single cherry-picked number. If a flat `min_score` can't cleanly separate
  the two without a real recall cost, say so and propose the actual next step (e.g., a relative
  score-gap signal) rather than forcing a threshold change that doesn't really fix the problem.
  Apply whatever the evidence supports as the new default in `core/config.py`/`~/.config/reqbot/config.json`'s
  schema default, or explicitly recommend no change with the evidence for why.

**Non-goals:** see Phase Non-Goals above.

**Tests/verification:**

- `tests/unit/test_parent_stem_reconstruction.py`'s existing `test_regression_all_18_known_examples`
  must still pass unmodified (it already encodes the correct expected behavior for
  `REQ-1b1071c8d317`; this WP makes the real pipeline actually reach it, not the test itself).
- New unit test(s) for the Step D ordering fix: a synthetic dangling-clause quote with a recoverable
  `parent_header_text` must survive Step D (not appear in `*_normalization_failures.jsonl`); the
  existing dangling-clause-with-no-recoverable-header case must still reject exactly as before.
- Live verification: reprocess the real corpus through Step D again (same pre-step pattern as
  WP-40), confirm `REQ-1b1071c8d317`'s content now survives with a populated `parent_stem`, reindex,
  spot-check via Qdrant payload.
- Zero-truth calibration: real numbers from the real 45-query gold set, not synthetic/assumed data.
- Full `pytest` suite and `ruff check .` clean throughout.

**Gate:** Both gold-label corrections applied and documented; the Step D ordering fix implemented,
tested, and verified live against the reprocessed real corpus (`REQ-1b1071c8d317` confirmed
recovered); zero-truth calibration run against the real 45-query gold set with the full trade-off
reported and an evidenced decision applied (a new default, or an explicit "no clean threshold exists,
here's what to try next" if that's what the data shows); full test suite and `ruff check .` clean.

**Findings:**

**Gold-label fix.** `Q-N03` and `Q-C05` corrected in `eval/gold_retrieval_queries.jsonl` — both now
reference the surviving child records that carry the removed governing clause's exact text as
`parent_stem`, with the correction documented in each query's `notes`. No pipeline change involved;
`_is_unrepairable_fragment()` is untouched and continues to correctly reject these two governing
clauses as non-obligation content.

**Step D / reconstruction ordering fix.** `pipeline/parse_and_normalize.py`'s `_is_dangling_clause()`
rejection branch now checks the chunk's `parent_header_text` (already loaded into `hierarchy` earlier
in the same loop, no new I/O) before rejecting — skips rejection only when a real header exists,
otherwise unchanged. **A nonempty header only means recovery is *possible*, not that it *happened*
(Codex review, PR #188, verified real):** the original fix relied entirely on a later, separate call
to `apply_parent_stem_reconstruction()` — `run_pipeline.py`'s own call is wrapped in a non-fatal
try/except, and `parse_and_normalize.py`'s own standalone CLI (`main()`) never called reconstruction
at all, so a bypassed dangling clause could survive Step D with no subject and no `parent_stem` under
either path. Fixed by calling `apply_parent_stem_reconstruction()` on Step D's own output from inside
`run()` itself (local import — `enrich_requirements.py` imports back from this module, so a top-level
import would be circular), guaranteeing every caller gets a fully-reconstructed record, not just the
in-process pipeline. `run_pipeline.py`'s own existing call remains as harmless, idempotent redundancy
(same pattern `enrich_requirements.run()` already uses for its own standalone-invocation safety).
Verified 4 ways: (1) new unit test confirms a dangling clause with a recoverable header survives Step
D while the existing no-header case still rejects exactly as before; (2) end-to-end test proves
`parse_and_normalize.run()` *alone* — no separate reconstruction call — already returns a record with
`parent_stem` populated, directly proving the standalone-CLI gap is closed; (3) the same test confirms
a redundant explicit `apply_parent_stem_reconstruction()` call afterward is a harmless no-op, not a
double-reconstruction bug; (4) live verification against the real corpus — reprocessed all 13
documents through Step D again (this time via `run()` alone doing double-duty), confirmed **3 real
records survive** with `dangling_clause_quote` previously rejecting them (`REQ-1b1071c8d317` afi17-203,
plus 2 more found live: `REQ-d26480316089` DODI 5200.48, `REQ-4ca0a0bc01d3` afi17-203), **all 3 with
`parent_stem` correctly populated** — spot-checked directly in the live Qdrant payload after reindex,
and confirmed identical (1,859 total, 204 with `parent_stem`) to the pre-Codex-fix state, proving the
fix closes a real gap with zero side effects on already-verified data. `unrepairable_fragment_quote`
(31), `orphaned_list_item_quote` (4), and `heading_echo_quote` (28) rejection counts are unaffected,
confirming the fix is precisely scoped to
the one rule it targets.

**Zero-truth/confidence-floor calibration — conclusive negative result: a flat `min_score` threshold
cannot fix this.** Swept 11 candidate thresholds (0.02 through 0.5, 25x the current default) against
a single retrieve() draw per query (`eval/calibrate_confidence_floor.py`, full results:
`eval/spike_results/wp_41_confidence_calibration/sweep_report.md`) — **0 of 8 zero-truth queries
correctly return empty results at ANY tested threshold**, including 0.5. Checked why directly: raw
top-5 scores for the 8 zero-truth queries range from 0.5 to **1.07** (`Q-Z03`, "federal tax
withholding requirements" — completely unrelated to this corpus) — routinely *higher* than genuine,
correctly-relevant weak matches this project has already measured (`Q-B05`'s real relevant results
scored as low as 0.033–0.09 in WP-40). The score distributions don't just overlap, they're inverted in
places: RRF fusion's rank-based score has no calibrated relationship to actual relevance for
off-topic queries. Raising the threshold past ~0.3 does measurably cost real recall (narrow recall@5
0.9545→0.8485, broad recall@5 0.379→0.295 at threshold=0.5) for zero benefit (still 0/8 zero-truth
correct) — there is no point on this curve worth taking. **Decision: no `min_score` default change.**
Forcing a threshold that costs real recall while fixing nothing would be worse than the status quo.
The real fix needs a calibrated absolute-relevance signal (e.g. a cross-encoder reranker's own
confidence score), not a threshold on an already-fused ranking score — this strengthens, not
replaces, WP-40's reranker recommendation (Phase 40's §8 Backlog updated to reflect this).

---

## 5. Success Gate

- [x] `Q-N03`/`Q-C05` gold-query labels corrected to reference current, parent_stem-carrying ids,
      with the correction documented.
- [x] Step D's `_is_dangling_clause()` rejection no longer discards a record when its chunk has a
      recoverable `parent_header_text` — verified via a new unit test and a live corpus reprocess
      confirming `REQ-1b1071c8d317` (plus 2 more found live) now survives with a populated
      `parent_stem`.
- [x] `test_regression_all_18_known_examples` still passes unmodified.
- [x] Zero-truth/confidence-floor calibration run against the real 45-query gold set; the full
      recall-vs-zero-truth trade-off reported; **evidenced decision: no `min_score` default change**
      (0/8 zero-truth correct at every threshold from 0.02-0.5, with real recall cost above ~0.3 and
      zero benefit anywhere on the curve) — documented as a conclusive negative result with the real
      next step (a calibrated relevance signal, not a threshold) fed back into Phase 40's Backlog.
- [x] No change to `_is_orphaned_list_item()`, `_is_unrepairable_fragment()`, or any other
      extraction-precision rule beyond the one specific ordering fix above.
- [x] Full `pytest` suite and `ruff check .` clean throughout.

---

## 6. Guardrails

- The Step D ordering fix only changes behavior for the specific, evidenced case (a dangling clause
  with a recoverable `parent_header_text`) — not a general loosening of any WP-38/WP-38.2 rejection
  rule.
- The zero-truth calibration is evidence-driven — report the real trade-off curve from the real gold
  set before picking a number, the same discipline WP-38's rule calibration and WP-40's whole
  methodology already established. If the data doesn't support a clean fix, say so rather than
  forcing one.
- Every gold-label change is documented with the reason, not a silent edit.
