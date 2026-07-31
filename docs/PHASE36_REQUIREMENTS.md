# ReqBot Phase 36 — Entailment-Gate Calibration Fix: Exact-Match Short-Circuit

**Status:** Locked (drafted 2026-07-31; source: WP-35.5's integration findings,
`docs/PHASE35_REQUIREMENTS.md`, PR #170; `docs/TODO_future_improvements.txt` item 33)
**Date:** 2026-07-31
**Preceded by:** Phase 35 (Production Description-Grounding Entailment Gate) — closed 2026-07-31,
all five WPs complete, Success Gate met (`docs/PHASE35_REQUIREMENTS.md`).
**Followed by:** Phase 37 (Retrieval Quality: Eval Harness & Contextual Chunk Embeddings) —
`docs/PHASE37_REQUIREMENTS.md`, drafted 2026-07-31. WP-36.2 stays deferred rather than folded into
Phase 37 — different pipeline stage (entailment-check calibration vs. search/retrieval), different
concern.

---

## Status

This table is the live source of truth for Phase 36 WP status — update it here when a WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-36.1 — Exact-Match Short-Circuit for the Entailment Check | Complete |
| WP-36.2 — Re-sweep the Entailment Threshold Post-Fix | Deferred (2026-07-31) — see `docs/TODO_future_improvements.txt` item 33 |

---

## 1. Phase Framing

WP-35.5's integration gate (Phase 35) ran a full, real pipeline ingest of `afpd_17-1.pdf` and found
that Step D.6's MiniCheck entailment check (WP-35.2/35.4) rejected 5 of 64 descriptions — **every one
of which was a byte-identical copy of its own `source_quote`**, with `support_prob` scores of
0.6782–0.8442 against the 0.85 threshold. A verbatim copy cannot be "fabricated" in any meaningful
sense (there is zero new content), so this is a real MiniCheck calibration weakness for very short,
identical premise/hypothesis pairs, not a genuine fabrication catch.

Checking this against the existing calibration data (rather than treating it as a one-off) showed the
problem is not rare and not new:

- **78 of the 92 `wp_35_1_harvest` faithful records in `eval/gold_description_grounding.jsonl` (85%)
  are exact matches after the same `normalize_text()` normalization the short-circuit itself uses**
  (77 by byte-identical `description == source_quote`, plus one — `REQ-22336c31702a` — that differs
  only in leading capitalization; caught by Codex review on WP-36.1's PR #173, after the count below
  had already been used to scope this WP with the wrong number). The faithful holdout is a random
  sample of everything neither WP-35.1 harvester heuristic flagged as a candidate fabrication — it is
  not gated by those heuristics, so an exact match trivially lands in it.
- **4 of the 5 false positives WP-35.2's original threshold sweep reported at 0.85 are this exact
  pattern** (`REQ-938435202cf9` 0.8473, `REQ-8105d9acb410` 0.2766, `REQ-fd23f59eb131` 0.2507,
  `REQ-69fe659699bb` 0.3312 — checked directly against `eval/spike_results/wp_35_2/results.json`).
  Only one original false positive (`REQ-7b7cbb7ef5b7`) is a genuine near-paraphrase.
- WP-35.5's live full-pipeline run reproduced this at a comparable rate (5/64 ≈ 7.8%, consistent with
  — not worse than — the originally-measured 5.4%), confirming it is a stable, real characteristic of
  the deployed check, not sampling noise from one run.

Given 85% of the calibration set's faithful examples are exact matches, this pattern very plausibly
affects a meaningful share of real production traffic too — Step D.5's own enrichment prompt already
permits (and, per these numbers, sometimes produces) a description that is just the source text
verbatim when the source is already precise. Every time that happens today, Step D.6 has roughly an
80%-of-false-positives'-worth chance of needlessly blanking a perfectly correct description.

This was explicitly **not** fixed during Phase 35 — WP-35.5 is an integration gate, not a new
failure-mode investigation (its own Non-Goals), and the false-positive rate itself was already a
known, accepted, documented cost of the WP-35.2 threshold decision (never claimed to be zero). This
phase is the deliberate, scoped follow-up: TODO item 33's own suggested direction, treated with the
same rigor (real data, real re-validation, no code merged without evidence) as every prior WP-32/33/
34/35 fix in this project.

## 2. Goals

- Add a deterministic, cheap short-circuit ahead of the MiniCheck call in
  `pipeline/entailment_gate.py`: an exact match (after the same `normalize_text()` normalization
  every other check in this file already uses) between `description` and `source_quote` is always
  treated as grounded, skipping the model call for that record entirely — not just accepting
  whatever score the model would have returned.
- Re-validate against the **existing** `eval/gold_description_grounding.jsonl` dataset — no new
  harvest needed, it already contains 78 exact-match faithful examples and 8 independent fabricated
  examples (none of which are exact matches, since a fabrication by definition introduces content
  absent from the quote — worth confirming directly, not just asserting, per this project's own
  "verify before applying" discipline).
- Re-sweep the entailment threshold (WP-36.2) now that exact matches no longer pass through the
  model at all — the population the threshold is chosen against has fundamentally changed (removing
  85% of what was previously the faithful side's mass), so the original 0.85 number's own
  justification needs to be re-derived, not silently carried forward.
- Live-verify the fix against the same two real documents WP-35.5 already touched
  (`afpd_17-1.pdf`, `NIST.SP.800-125.pdf`): confirm the 5 previously-wrongly-rejected descriptions
  now pass, and the known modality-fabrication catch (`REQ-757d551b3e59`) is still caught.

## 3. Non-Goals

- **Not "near-exact" fuzzy matching** (trivial whitespace, punctuation, or casing differences beyond
  what `normalize_text()` already handles). TODO item 33 mentions this as a possible future direction,
  but it is a distinct, unvalidated shape — near-misses could behave very differently from true exact
  matches, and extending the short-circuit there without its own empirical check would repeat exactly
  the mistake this phase exists to fix (assuming a pattern generalizes without checking). Explicitly
  deferred, not pre-decided here.
- **Not a new calibration-dataset harvest.** WP-35.1's existing 108-record dataset already contains
  enough exact-match examples (78) to validate this fix; building new harvesting infrastructure would
  be disproportionate to a narrow, well-understood problem.
- **Not a change to WP-35.3's modality check.** It has zero known false positives against the current
  dataset and the two real WP-35.5 documents; out of scope, untouched.
- **Not a change to Step D.5's enrichment prompt.** WP-35.5's Findings noted that
  `ENRICH_SINGLE_PROMPT_TEMPLATE`'s own "return `\"\"` if source text is self-explanatory" instruction
  isn't always followed, which is part of why verbatim-copy descriptions exist at all — a real,
  separate, pre-existing question about Step D.5's prompt-following behavior, not this phase's job.
- **Not a change to WP-35.4's "clear description, keep requirement" reject semantics.** Unaffected by
  this fix — this phase changes *when* a rejection fires, not what happens once it does.

---

## 4. Work Packages

### WP-36.1 — Exact-Match Short-Circuit for the Entailment Check

**Source:** `docs/TODO_future_improvements.txt` item 33; WP-35.5's Findings
(`docs/PHASE35_REQUIREMENTS.md`).

**Problem:** MiniCheck scores a `description` that is byte-identical to its own `source_quote`
inconsistently — sometimes below the 0.85 threshold — despite there being no possible fabrication in
an exact copy. This accounts for 4 of WP-35.2's original 5 measured false positives and reproduced
live in WP-35.5's integration run.

**Scope:**
- Add an exact-match check (e.g. `_is_exact_match(source_quote, description)`) to
  `pipeline/entailment_gate.py`, using `normalize_text()` (already imported from
  `pipeline/parse_and_normalize.py`) on both sides — the same normalization every existing check in
  this file already relies on (whitespace collapse + lowercasing), not a new/different comparison
  rule.
- Wire it into `run()`'s scoring loop: a record whose normalized `description` equals its normalized
  `source_quote` is excluded from the batch sent to MiniCheck entirely (real compute saved, not just
  a discarded score — matching the existing pattern where empty-description records are already
  excluded from `pairs`) and never receives a `description_not_grounded` error.
- Confirm directly (not assume) that `is_fabricated_obligation()` already returns `False` for two
  identical strings on its own — if so, no change needed there; the modality check doesn't need its
  own short-circuit, it's already correct by construction for this shape.
- Decide and document the exact boundary: is this literal equality after `normalize_text()` only, or
  does it need its own dedicated helper distinct from that function (e.g. if `normalize_text()`'s
  whitespace/casing normalization is too permissive or not permissive enough for this specific
  purpose)? Check against real near-miss examples from the dataset (a description differing by one
  trailing period, one whitespace run, etc.) before finalizing, not by assumption.

**Non-goals:**
- No fuzzy/similarity-based matching (see Phase Non-Goals above) — literal equality after
  normalization only.
- No change to `MODAL_MARKERS`/`ACTION_VERB_FORMS`/the modality check's own logic.

**Tests/verification:**
- Unit tests: exact match after trivial whitespace/casing differences is short-circuited; a
  near-miss (single word different) is *not* short-circuited and still goes through MiniCheck; the
  short-circuit correctly excludes the record from the batch sent to the scorer (assert on the fake
  scorer's received `pairs`, mirroring `tests/unit/test_entailment_gate.py`'s existing
  `test_score_entailment_skips_scorer_call_for_empty_pairs` pattern).
- Re-run validation against `eval/gold_description_grounding.jsonl`: confirm all 4 known exact-match
  false positives (`REQ-938435202cf9`, `REQ-8105d9acb410`, `REQ-fd23f59eb131`, `REQ-69fe659699bb`) no
  longer reject, and the 8 independent fabricated examples' catch rate is unaffected (none should be
  exact matches — confirm this is actually true against the committed data, don't assume it).
- Full `pytest` suite passes; `ruff check .` clean.

**Gate:** The 4 known exact-match false positives from WP-35.2's original sweep are eliminated
without any change to the fabricated-example catch rate; the short-circuit is proven not to fire on a
real near-miss case, not just on literal duplicates.

**Findings (2026-07-31):**

- `is_fabricated_obligation()` confirmed directly (not assumed) to already return `False` for
  identical strings — no change needed there; only `run()`'s MiniCheck batching needed the
  short-circuit.
- Checked the boundary question against real data before implementing: `eval/gold_description_
  grounding.jsonl` has 10 near-miss pairs (ratio > 0.9 after `normalize_text()`, not exact) — a
  dropped leading list marker (`(5)`, `e.`), a trailing period, a `will`→`must` modal swap, and the
  known modality-fabrication catch `REQ-757d551b3e59` itself. None of these are caught by plain
  literal equality after `normalize_text()`, confirming that boundary (no separate/fuzzier helper)
  is correct — permissive enough to catch the real exact-copy shape, not so permissive it swallows a
  case that should still be checked.
- Confirmed directly against `eval/gold_description_grounding.jsonl`'s `wp_35_1_harvest` partition
  (8 fabricated, 92 faithful) that none of the 8 fabricated examples are exact matches — the
  short-circuit provably cannot affect their scoring path.
- Live-ran the real `pipeline/entailment_gate.run()` (real installed MiniCheck, not mocked) against
  that same 100-record partition:
  - All 4 known exact-match false positives (`REQ-938435202cf9`, `REQ-8105d9acb410`,
    `REQ-fd23f59eb131`, `REQ-69fe659699bb`) now pass.
  - Fabricated catch rate: 8/8 (up from WP-35.2's entailment-only 7/8 — expected, not a WP-36.1
    effect: production `run()` combines entailment OR modality, and none of the 8 changed their
    entailment-scoring path at all).
  - Faithful false-positive rate dropped from 5/92 (5.4%) to 1/92 (1.1%). The one remaining rejection
    (`REQ-7b7cbb7ef5b7`) is the already-documented genuine near-paraphrase from WP-35.2's original
    sweep, correctly *not* short-circuited (Non-Goal: no fuzzy matching) — this WP was never meant to
    fix that one.
- Full `pytest` (751 passed) and `ruff check .` clean.

---

### WP-36.2 — Re-sweep the Entailment Threshold Post-Fix

**Deferred (2026-07-31), not abandoned.** WP-36.1 alone already measures well on the live composite
gate (entailment OR modality, threshold still 0.85): 8/8 fabrications caught, 1/92 faithful false
positives (`docs/PHASE36_REQUIREMENTS.md`'s WP-36.1 Findings above). That's *better* on the FP axis
than this WP's own hand-check estimate for a raised threshold (0.95 gave 8/92 FP) — but that estimate
was entailment-alone, from `eval/spike_results/wp_35_2/results.json`, and doesn't account for the
modality check's independent contribution to the 8/8 catch rate at 0.85. **Whoever picks this WP back
up should re-derive the hand-check against the deployed composite behavior first, not reuse the
entailment-alone numbers above** — it's plausible the honest conclusion is "0.85 already wins, no
threshold change warranted," not that 0.95 is better. Tracked as a fine-tuning backlog item in
`docs/TODO_future_improvements.txt` item 33; production quality is good enough now that this isn't
blocking anything.

**Source:** WP-36.1's short-circuit changes which records the MiniCheck threshold is actually
exercised against — WP-35.2's original sweep numbers no longer describe the deployed check's real
population once exact matches stop reaching the model. Depends on WP-36.1.

**Problem:** WP-35.2's threshold (0.85) was chosen against a faithful population that was 85% exact
matches. Removing that entire slice changes what "5.4% FP rate" or any other sweep number actually
means — the original table's numbers describe a check that no longer exists in the same form.

**Scope:**
- **Re-sweep against the full composite gate's behavior, not just MiniCheck's conditional behavior on
  the records it still sees — this distinction matters and was verified with real numbers, not
  assumed (Codex review, PR #171).** The `FP_RATE_CAP` denominator must stay the full 92-record
  `wp_35_1_harvest` faithful population, with every exact-match record counted as an automatic accept
  regardless of which threshold is being swept (the short-circuit guarantees they pass; excluding
  them from the denominator entirely would misrepresent what fraction of *real* faithful traffic the
  deployed gate actually rejects). Only the 14 non-exact-match faithful records' pass/fail varies with
  the swept threshold (78 records are exact matches under `_is_exact_match()`'s `normalize_text()`
  comparison, not 77 — corrected after Codex review on WP-36.1's PR #173 found a
  capitalization-only match, `REQ-22336c31702a`, that the doc's original literal-`==` count missed;
  its own support_prob, 0.9655, was already above every threshold considered below, so this
  correction changes the population counts here but not the FP counts or conclusion). Checked
  directly against the committed `eval/spike_results/wp_35_2/results.json` scores: excluding the 78
  short-circuited records from the denominator entirely (the wrong methodology, in this WP's own
  first-drafted version of this Scope) makes threshold 0.95 look disqualified (8/14 ≈ 57% FP against
  the reduced denominator) and the sweep would still land back on
  0.85, silently defeating this WP's entire purpose. Under the correct composite denominator, 0.95
  has an 8/92 ≈ 8.7% FP rate — within the 10% cap — while catching **100% of the 8 known fabricated
  examples** (up from 7/8 at 0.85). This is real, verified evidence that a better threshold is likely
  available once the short-circuit is in place — confirm it holds with the actual resweep script
  (not just this hand-check) before treating 0.95 as the new answer.
- Re-run `eval/threshold_sweep.py` (or a filtered variant implementing the composite-denominator
  methodology above) against `eval/gold_description_grounding.jsonl`, using the same `FP_RATE_CAP`
  diminishing-returns selection rule as WP-35.2's original sweep — not a different rule invented for
  this WP, just applied to the corrected population.
- Document whether the chosen threshold actually changes from 0.85, and why or why not — a real,
  evidence-backed answer either way, not an assumption. Given the independent fabricated partition is
  still only 8 examples (WP-35.2's own documented "provisional, not confident" limitation), carry that
  same caveat forward here rather than treating a new number as more confident than the data supports
  — even though the hand-check above is promising, 8 examples is still 8 examples.
- Update `DESCRIPTION_ENTAILMENT_THRESHOLD` in `pipeline/entailment_gate.py` if the resweep concludes
  a different number is warranted; update its surrounding comment (currently cites WP-35.2's sweep
  numbers directly) to reflect the new evidence.
- **Live re-verification against the same two real documents WP-35.5 exercised** — not new
  documents, the same ones, so the before/after comparison is exact and traceable:
  - `afpd_17-1.pdf`: confirm all 5 previously-wrongly-rejected descriptions
    (`"Participate in cyberspace governance forums."` ×3, `"Serve as lead command..."`,
    `"Provide investment performance information..."`) now pass.
  - `NIST.SP.800-125.pdf`: confirm `REQ-757d551b3e59` (the known modality-fabrication case, which
    MiniCheck alone scores 0.9367 — confidently supported — and only the modality check catches) is
    still caught, and requirement count is still preserved end to end.

**Non-goals:**
- No change to how the modality check combines with the entailment check (still OR, per WP-35.4's
  decision) — this WP only revisits the entailment threshold's specific number.
- No production pipeline re-architecture — same Step D.6 shape, just a corrected threshold and the
  WP-36.1 short-circuit ahead of it.

**Tests/verification:**
- The resweep itself, committed as a report mirroring `eval/spike_results/wp_35_2/`'s existing
  format (full sweep table, per-subtype breakdown, explicit confidence statement).
- Full `pytest` suite passes; `ruff check .` clean.
- Manual: the two real-document re-verifications above, with before/after `support_prob` values
  recorded for the specific records checked (not just a pass/fail summary).

**Gate:** A threshold is chosen with real sweep evidence against the corrected composite-denominator
population (exact matches counted as automatic accepts, not excluded); the two real documents'
previously-documented false positive and true positive are re-confirmed live, not just against the
static dataset.

---

## 5. Success Gate

Phase 36 is complete when:

1. WP-36.1's exact-match short-circuit eliminates the 4 known false positives from WP-35.2's original
   sweep without affecting fabrication catch rate.
2. WP-36.2's threshold re-sweep is documented with real evidence, whether or not the number changes.
3. Live re-verification against `afpd_17-1.pdf` and `NIST.SP.800-125.pdf` confirms the fix in
   practice — the previously-observed false positives now pass, the previously-observed true positive
   is still caught.
4. Full unit suite passes (`pytest`); `ruff check .` passes.
5. `docs/TODO_future_improvements.txt` item 33 is marked resolved, pointing at this phase.

---

## 6. Guardrails

1. One WP at a time — WP-36.1 must land before WP-36.2 can be meaningfully validated (WP-36.2's
   resweep population depends on WP-36.1's short-circuit actually existing).
2. Resist scope creep into near-exact fuzzy matching just because this phase is already touching the
   same code — that shape needs its own empirical validation before any code change, matching the
   discipline that found this phase's own problem in the first place (checking a claim against real
   data before shipping it).
3. Don't silently carry forward "provisional, not confident" language without re-checking it's still
   accurate — if WP-36.2's resweep happens to land on a materially larger independent fabricated
   partition somehow, say so plainly; if it's still just the same 8 examples, say that plainly too.
4. No claim in either WP's Findings ships without being checked against the real committed data first
   — this phase exists because a plausible-sounding claim ("structurally invisible to calibration")
   turned out to be false when actually checked. Hold this phase's own write-ups to that same
   standard.
