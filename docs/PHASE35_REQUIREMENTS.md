# ReqBot Phase 35 — Production Description-Grounding Entailment Gate

**Status:** Locked (drafted 2026-07-30; source: WP-34.4's spike findings,
`docs/PHASE34_REQUIREMENTS.md`, PR #164)
**Date:** 2026-07-30
**Preceded by:** Phase 34 (Docling-Only Migration & Actionability Structural Fixes) — closed
2026-07-30, all four WPs complete or spike-concluded.
**Followed by:** None currently planned.

---

## Status

This table is the live source of truth for Phase 35 WP status — update it here when a WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-35.1 — Build a Labeled Calibration Dataset for Description Faithfulness | Complete |
| WP-35.2 — Threshold Calibration Sweep | Complete |
| WP-35.3 — Obligation/Modality-Fabrication Secondary Check | Complete |
| WP-35.4 — Production Step D.5/D.6 Entailment Gate | Complete |
| WP-35.5 — Integration Gate | Complete |

---

## 1. Phase Framing

WP-34.4's spike (`docs/PHASE34_REQUIREMENTS.md` §4) established that a lightweight NLI entailment
model (MiniCheck, `flan-t5-large`) can catch Step D.5's fabricated-description symptom — a
`description` that invents content absent from its `source_quote` — with a clear, wide-margin
signal on real data: 5/6 known-fabricated examples caught, 0/9 false positives. That's the answer to
"is this technique viable," not "is this ready to ship." This phase is the "make it real" work the
spike deliberately didn't do (Non-Goals: investigation only, no production Step D.5 change).

**Two gaps found during the spike, both load-bearing for this phase's WP breakdown, not just
color:**

1. **No calibration data exists.** WP-32.1's Step D grounding-check threshold (quote-vs-chunk fuzzy
   matching) was picked by sweeping against `eval/gold_eval_chunks_curated.jsonl`'s 2,452
   hand-verified real quotes. That file has no equivalent for descriptions — its `gold_requirements`
   entries carry only `source_quote`/`source_ref`, no `description` field at all (confirmed by
   inspection while scoping this phase). WP-34.4's own 15-pair test set was deliberately hand-picked
   to include hard cases and demonstrate the technique works; it was never meant to calibrate a
   production threshold, and using it as one would be circular (the threshold would be tuned to the
   exact examples used to prove the concept). **This is why WP-35.1 exists as its own WP before
   WP-35.2 can start** — mirrors this phase's own version of Phase 34's hard sequencing dependency
   (WP-34.1 before WP-34.2/34.3).
2. **A named, distinct failure mode the entailment score alone doesn't catch.** Codex's review on
   PR #164 found that WP-34.4's test set had one real fabrication mislabeled as faithful: a glossary
   definition (`"Cybersecurity - Prevention of damage to..."`) reframed by Step D.5 as an imperative
   obligation (`"Implement cybersecurity measures to..."`). Every named fact carried over faithfully
   — only the "you must do this" framing was invented. MiniCheck scored it 0.9197 (confidently
   supported) because its factual content genuinely is grounded; the entailment check as used in the
   spike has no signal for obligation/modality that wasn't in the premise. **WP-35.3 exists
   specifically because this is a distinct, nameable pattern, not spike noise to shrug off.**

## 2. Goals

- Replace the spike's ad-hoc 15-pair test set with a real, honestly-sized labeled dataset for
  description faithfulness, built and hand-verified the same way WP-33.3's original hand-labeling
  was done (random sample, checked against source document context, not just eyeballed in
  isolation).
- Pick and document a production threshold via an actual sweep against that dataset, mirroring
  WP-32.1's methodology and level of rigor (a table of threshold vs. false-positive/catch-rate, not
  a single number asserted without evidence).
- Close the specific modality/obligation-fabrication gap WP-34.4's spike (via Codex's review) found,
  with its own targeted check — not by trying to make the entailment score alone handle everything.
- Wire the calibrated check into the real pipeline as a Step D.5 (or new Step D.6) rejection gate,
  matching the existing pattern (`quote_not_grounded_in_chunk`, `heading_echo_quote`,
  `unrepairable_fragment_quote`): a durable failure reason recorded in
  `*_normalization_failures.jsonl`, reject-only, no salvage/reconstruction.
- Make the new dependency a real, documented one (`pyproject.toml`), not an ad-hoc
  `pip install --break-system-packages` left as a README footnote.

## 3. Non-Goals

- No change to Step C's prompt or extraction behavior — this phase is entirely about Step D.5/D.6
  and what happens after extraction, same boundary WP-34.2/34.3/34.4 already respected.
- No attempt to make the entailment check itself understand modality/obligation semantics (e.g. by
  fine-tuning or prompting the NLI model differently) — WP-35.3's secondary check is a separate,
  deliberately simple mechanism, not an attempt to solve this inside the entailment model.
- No re-scoring or retroactive correction of already-indexed corpus data — this phase changes what
  future Step D.5 output does, not how past output is displayed or stored, matching Phase 34's
  identical stance on `services/docs_service.py`.
- No commitment yet to exactly how MiniCheck's own transitive dependency footprint gets handled
  (see WP-35.4's Scope) — worth flagging now, not deciding blind: installing MiniCheck from its
  GitHub source pulled in `openai`, `datasets`, `aiohttp`, and `pyarrow` as transitive dependencies
  (confirmed during WP-34.4's spike setup) — likely used by MiniCheck's own LLM-judge/dataset-eval
  code paths that this phase doesn't need, not by the `flan-t5-large` scoring path actually used.
  Whether to accept that footprint, vendor just the scoring logic, or find a lighter integration
  path is a real WP-35.4 decision, not pre-decided here.

---

## 4. Work Packages

### WP-35.1 — Build a Labeled Calibration Dataset for Description Faithfulness

**Source:** Gap 1 in §1 above.

**Problem:** No dataset exists anywhere in this repo that pairs real `(source_quote, description)`
records with a hand-verified faithful/fabricated label at meaningful scale. WP-34.4's 15 pairs are
real but small and deliberately curated to include hard cases — using them to calibrate a threshold
would mean tuning to the examples used to prove the concept, not an independent validation set.

**Scope:**
- Generate a candidate pool of real `(source_quote, description)` pairs from this repo's own
  Step D.5 enrichment output — either the already-enriched JSONL under `~/documents/processed/*/`
  (the same source WP-34.4 drew its 15 pairs from) or, if broader corpus coverage is needed, fresh
  enrichment runs (Step D.5 needs Ollama; `--skip-to` isn't available for D.5 alone the way it is
  for Step D — check `pipeline/run_pipeline.py`'s actual `skip_to` handling before assuming this is
  free).
- **Not pure random sampling — stratified/targeted harvesting, with a documented reason.** Found
  during a manual local Codex review of this doc (2026-07-30, not posted to GitHub): a random sample
  of *fresh* Step D.5 output risks containing too few real fabrications to calibrate against, because
  several of WP-34.4's own known-bad patterns are now prevented before they'd ever reach Step D.5 on
  a current ingest. Checked directly — this is worse than it first sounds: 4 of WP-34.4's 6
  known-bad examples are now structurally prevented at the source, not just 1 or 2. The citation-list
  fabrications (`JP 3-12`, `DoDI 8500.01`) were already covered by the pre-existing `REFERENCES`
  skip_sections entry once docling+skip_sections is properly applied — confirmed in
  `docs/PHASE34_BRAINSTORM.md` §3 ("Category 1... likely already solved... zero occurrences across
  both documents"). The heading-echo fragment (`"All HAF Functionals..."`) is now caught by WP-34.2.
  The glossary-definition case (`"Cybersecurity - Prevention of..."`) is now caught by WP-34.3's
  `TERMS` filter. Only the two subtler cases (`cjcsi_po_service_principal_fragment`,
  `cjcsi_distribution_fabricated_attribution`) aren't yet structurally prevented. Given that, random
  sampling of fresh output would mostly find clean, already-faithful descriptions — real evidence the
  earlier fixes work, but useless for calibrating a *catch rate*. Instead: harvest deliberately,
  with a minimum count per fabrication subtype (citation/fragment-completion-shaped, and
  modality-fabrication-shaped) — reusing the same structural heuristics that surfaced WP-34.4's own
  candidates (short/colon-terminated quotes paired with a much longer, low-similarity description)
  scaled up, plus a separately-labeled faithful holdout sampled randomly from clean output (that part
  can stay random, since faithful examples aren't the scarce resource). Target order-of-magnitude
  100+ records total across both categories combined — more than WP-34.4's 15, deliberately not
  claiming WP-32.1's 2,452-scale rigor since that was checked mechanically via substring matching;
  this requires real human judgment per record, same constraint WP-33.3's 40-record hand-labeling
  had. Each record's `section_title_path` and `parent_context` must be checked, not just the bare
  quote/description pair in isolation — WP-34.4's own Codex-caught miss was only found by checking
  the full record, not the quote/description text alone.
- Output: a new fixture file (e.g. `eval/gold_description_grounding.jsonl`) with
  `(source_quote, description, label, notes, section_title_path, parent_context, source_pdf,
  chunk_id)` — not just the bare quote/description pair. The preceding bullet requires checking
  `section_title_path`/`parent_context` to determine a label in the first place (this is exactly how
  WP-34.4's own Codex-caught miss was found); a fixture that discards that context after labeling
  can't be audited or reproduced later without re-locating the original record under
  `~/documents/processed/`, which may not still exist by the time WP-35.2/35.3 consume this file
  (found during PR #165 review, Codex). `label` at minimum distinguishes faithful vs. fabricated,
  and should separately flag the WP-35.3 modality-fabrication subtype found in WP-34.4, not lump it
  in with citation/fragment-completion fabrications as one undifferentiated category.
- Explicitly account for `gold_eval_chunks_curated.jsonl`'s own known noise (~20% per prior
  operational findings) if any part of this dataset is built by pairing that file's quotes with
  freshly-generated descriptions — don't inherit its noise silently into a new "gold" file without
  saying so.

**Non-goals:**
- Not a full-corpus dataset — a representative, honestly-labeled sample, matching WP-33.3's own
  precedent rather than attempting exhaustive coverage.
- No production code change — this WP produces a fixture file and documents how it was built.

**Tests/verification:**
- The fixture file itself is the deliverable; document the sampling method, hand-labeling process,
  and inter-example checking discipline in this phase doc once complete (which documents/chunks it
  came from, how many were reviewed, how many were excluded and why).

**Gate:** A committed, documented labeled dataset exists with enough real fabricated and real
faithful examples (both citation/fragment-completion style and modality-fabrication style) to make
WP-35.2's sweep meaningful — not just WP-34.4's original 15 relabeled.

**Findings (2026-07-30/31):**

- Harvested from `~/documents/processed/*/` across 16 pipeline runs / 13 distinct source documents
  (2,064 unique `(source_pdf, chunk_id, source_quote, description)` triples after dedup): the
  original 2 corpus documents (`afpd_17-1.pdf`, `CJCSI 6510.02G.pdf`, 5 runs) plus 11 freshly-ingested
  documents across two expansion rounds (`DODI 5200.01.pdf`, `afi17-203.pdf`, `NIST.SP.800-125.pdf`,
  `DODI 5200.44.pdf`, `DODI 8410.03.pdf`, `afi10-2402.pdf`, then `DODI 5200.48.pdf`,
  `DODI 8551.01.pdf`, `afi13-550.pdf`, `afman17-2101.pdf`, `dafman17-1305.pdf`, all ingested today
  with `--no-index`). The first round's fresh ingests were necessary, not just nice-to-have for
  diversity: all 5 pre-existing runs predate today's WP-34.1/34.2/34.3 merges, so none of the local
  corpus reflected the current, fixed pipeline before this WP ran. The second round was a direct
  response to a Codex review finding on this WP's own PR (see below).
- `eval/harvest_description_grounding_candidates.py` flagged candidates with two structural
  heuristics — the same shape that surfaced WP-34.4's own 15 examples in the first place, scaled up:
  a short/colon-terminated quote paired with a much-longer, low-similarity description
  (citation/fragment-shaped), and a `profiles/cybersecurity.json` `obligation_verbs` term present in
  `description` but literally absent from `source_quote` (modality-shaped) — plus a random sample of
  everything neither heuristic flagged, restricted to post-fix runs, as the faithful holdout.
- **Real hit rate is low and stayed low after doubling the corpus: 18 distinct flagged candidates out
  of 2,064 scanned (~0.9%).** All 18 were hand-verified against their own
  `section_title_path`/`parent_context`, per this WP's scope. 14 were confirmed genuine fabrications;
  the other 4 were exactly the heuristic's own predicted false-positive shape (a real modal-verb or
  near-synonym paraphrase, e.g. `will`→`must`) and are kept as `faithful`-labeled WP-35.3 fixtures
  specifically because they were flagged, not despite it.
  - Every citation/fragment-shaped fabrication found (5 of 5) came from `pre_fix` runs, and every one
    traces to a document/pattern WP-34.4's own spike already knew about — no *new* citation/fragment
    fabrication turned up anywhere in the 6 freshly-ingested, post-fix documents. Real, positive
    confirmation (not just the a-priori expectation carried over from WP-34.4's findings) that
    WP-34.2/34.3 structurally prevent this shape going forward.
  - Modality/attribution-shaped fabrication is **not** similarly prevented: 4 of the 6 real
    modality/other fabrications came from freshly-ingested, post-fix documents never seen during
    WP-34.4's spike (`REQ-757d551b3e59`/`NIST.SP.800-125.pdf`, `REQ-c6d23854cd0b`/`DODI 8410.03.pdf`,
    `REQ-f7a98a6a365d`/`afi10-2402.pdf`, `REQ-cbc6374a655f`/`afi10-2402.pdf`) — direct, current
    evidence motivating WP-35.3, not just the one historical Codex-caught example carried over from
    Phase 34.
  - `REQ-c6d23854cd0b` surfaced a real gap in `parse_and_normalize.py`'s `_is_unrepairable_fragment`:
    it only fires on colon-terminated quotes, but this record — a bare enumerated list-item topic
    phrase with no trailing colon — has the identical fabrication shape. Logged as item 32 in
    `docs/TODO_future_improvements.txt`; out of scope to fix in this WP.
- **Self-caught data-completeness bug:** the first commit on this WP's PR was built from a harvest run
  where `afi10-2402.pdf`'s ingest (started in the background, ~135 chunks, much larger/slower than
  the other 5 fresh documents) hadn't actually finished — its completion notification arrived only
  *after* the dataset was already committed and the PR opened. `eval/harvest_description_grounding_
  candidates.py` counts `runs_scanned` from directory existence, not from whether each run's
  `*_requirements_enriched.jsonl` had finished writing, so the miss wasn't visible in its own output
  totals. Re-running the harvester once the ingest genuinely completed surfaced 2 more real
  fabrication candidates from `afi10-2402.pdf` alone (both included above) and changed the faithful
  holdout's composition. Fixed by re-harvesting, re-verifying, and rebuilding before this section was
  finalized — not left as a known gap for WP-35.2 to discover. The underlying metric bug (counting
  `runs_scanned` from directory existence rather than from whether each run's own enriched file had
  finished writing) was independently caught by Gemini review on this WP's PR, in code this session
  had already fixed the *data* for but not yet the *metric* itself — `runs_scanned` now only counts
  directories that actually contributed records; `run_dirs_found` reports the raw directory count
  separately, so a future in-progress-ingest run shows up as a visible gap between the two instead of
  silently inflating `runs_scanned`.
- **Circular-evidence bug, found by Codex review on this WP's own PR:** 8 of the first 17
  hand-verified records — 6 `fabricated_*` and 2 `faithful` — turned out (exact `source_quote` match)
  to already be `eval/entailment_spike.py`'s own `KNOWN_BAD`/`KNOWN_GOOD` fixtures, re-discovered
  independently by this WP's heuristics without being recognized as duplicates. Counting them as new
  calibration evidence would be exactly the circularity this WP exists to avoid (Phase Framing, Gap
  1: "using [the spike's 15 pairs] as [a calibration threshold] would be circular"). Fixed, not just
  noted: every record now carries a `source` field (`wp_34_4_spike` for the 8 duplicates,
  `wp_35_1_harvest` for everything genuinely new) — see `eval/build_gold_description_grounding.py`'s
  `SPIKE_OVERLAP_IDS`. The 8 stay in the file as a regression check (does WP-35.2's chosen threshold
  still classify the original spike cases correctly), but WP-35.2 must filter to
  `source == "wp_35_1_harvest"` for its actual catch-rate/false-positive statistics.
- **Independent fabricated partition is thin, and a second corpus expansion confirmed this is a real
  finding, not just insufficient search — found by Codex review on this WP's own PR.** After
  excluding the 8 `wp_34_4_spike` records, the `wp_35_1_harvest` partition has only 8 fabricated
  examples against 92 faithful (3 `fabricated_citation`, 1 `fabricated_fragment`, 2
  `fabricated_modality`, 2 `fabricated_other`) — thin enough that a single record flipping catch/miss
  moves the apparent catch rate by 12.5 points, and citation/fragment subtype evidence is especially
  sparse. Response: ingested 5 more documents (`DODI 5200.48.pdf`, `DODI 8551.01.pdf`,
  `afi13-550.pdf`, `afman17-2101.pdf`, `dafman17-1305.pdf`), nearly doubling `records_scanned` (1,204
  → 2,064). Result: **zero new fabricated candidates of either subtype** — the only new flagged
  candidate was one more real `will`→`must` faithful paraphrase. This is itself informative, not a
  null result to shrug off: it's now been confirmed twice (once at ~1,200 records, again at ~2,000)
  that citation/fragment/modality-shaped fabrication is genuinely rare in fresh, post-fix pipeline
  output, not an artifact of an insufficiently broad first search. Growing the independent fabricated
  count meaningfully further would likely need an order-of-magnitude larger harvest (dozens more
  documents), disproportionate to this WP's scope — so rather than keep chasing a number, this
  limitation is carried forward explicitly into WP-35.2's Scope below (filter, minimum-count
  awareness, and a documented exploratory/provisional stance) instead of being masked by further
  padding.
- Given the honest hit rate above, the faithful holdout was deliberately oversized (90 records
  against 14 fabricated + 4 reclassified, 8 of those 18 marked `wp_34_4_spike`) to reach this WP's
  Gate at a defensible total scale — 108 records combined (100 genuinely new to this WP), order-of-
  magnitude 100+ as scoped, with the shortfall on the fabricated side documented rather than papered
  over with synthetic or padded examples.
- **Output:** `eval/gold_description_grounding.jsonl` — 108 records: 5 `fabricated_citation`, 3
  `fabricated_fragment`, 3 `fabricated_modality`, 3 `fabricated_other`, 94 `faithful` (100 `source:
  wp_35_1_harvest`, 8 `source: wp_34_4_spike`). Built by `eval/build_gold_description_grounding.py`
  from `eval/harvest_description_grounding_candidates.py`'s output plus this WP's hand-verification
  labels (both scripts committed for reproducibility, along with the harvester's intermediate output,
  `eval/spike_results/wp_35_1/harvest_candidates.json`, matching the existing
  `eval/spike_results/wp_33_3/`, `eval/spike_results/wp_34_4/` precedent).

---

### WP-35.2 — Threshold Calibration Sweep

**Source:** Gap 1 in §1 above. Depends on WP-35.1.

**Problem:** WP-34.4 showed the technique separates known cases with a wide margin (0.133 max
known-bad vs. 0.852 min known-good) but never swept a range of thresholds against real,
independently-built data the way WP-32.1 did before picking `QUOTE_GROUNDING_THRESHOLD = 60`.

**Scope:**
- Sweep `support_prob` threshold candidates against WP-35.1's labeled dataset, reporting a table of
  false-positive rate (faithful descriptions wrongly rejected) vs. catch rate (fabricated
  descriptions correctly rejected) per threshold — same shape as `QUOTE_GROUNDING_THRESHOLD`'s own
  documented sweep in `pipeline/parse_and_normalize.py`.
- **Filter to `source == "wp_35_1_harvest"` for these statistics.** WP-35.1's dataset also carries 8
  records tagged `source == "wp_34_4_spike"` — exact duplicates of `eval/entailment_spike.py`'s own
  proof-of-concept fixtures, kept in the file for a regression check but excluded from the primary
  sweep specifically to avoid the circularity WP-35.1's own Findings section found and fixed (Codex
  review, PR #166): counting the spike's own examples toward this WP's "independent" catch-rate would
  inflate it artificially. After picking a threshold from the `wp_35_1_harvest` partition, separately
  confirm it still classifies all 8 `wp_34_4_spike` records correctly — a real, if smaller, check that
  nothing regressed, just not part of the primary statistics.
- Pick a threshold with the same kind of explicit reasoning already established in this codebase
  (diminishing-returns framing, not just "the number that gave 100% on our small set").
- If the sweep reveals the technique doesn't hold up as well against a larger, less-curated dataset
  as WP-34.4's small set suggested, that's a valid, documented outcome — not a reason to force a
  threshold that doesn't actually separate the two classes well.
- **Treat this sweep as exploratory/provisional, not a confident calibration — found by Codex review
  on WP-35.1's own PR (#166), confirmed by a second corpus-expansion attempt that found zero new
  fabricated examples (see WP-35.1's Findings).** The `wp_35_1_harvest` partition has only 8
  independent fabricated examples (3 citation, 1 fragment, 2 modality, 2 other) against 92 faithful —
  thin enough that a single record flipping catch/miss moves the apparent catch rate by 12.5 points,
  and per-subtype evidence (especially `fabricated_fragment`, at 1 example) is too sparse to calibrate
  a subtype-specific threshold with any confidence. Report per-subtype breakdowns alongside the
  aggregate sweep, not just an aggregate number that hides this. If the chosen threshold's
  classification of any individual fabricated example is sensitive to minor `support_prob` shifts (not
  a wide, comfortable margin the way WP-34.4's original 15-pair spike showed), that must be reported
  as an underpowered/inconclusive result — a real option is to pick a conservative threshold band
  rather than a single precise cutoff, or to explicitly recommend a further targeted harvest (not
  necessarily more random documents, since that already proved to have a very low yield — WP-33.3/
  WP-34.4's spike-example provenance suggests hand-constructed or targeted-search candidates may be
  more productive) before WP-35.4 treats any number here as production-ready.

**Non-goals:**
- No production code change — this WP picks and documents a number for WP-35.4 to use.

**Tests/verification:**
- The sweep itself, committed as a report (mirroring `eval/entailment_spike.py`'s own
  `eval/spike_results/` pattern), including the per-subtype breakdown and an explicit statement of
  whether the result should be treated as confident or provisional given the data-scale caveat above.

**Gate:** A specific threshold is chosen and documented with real false-positive/catch-rate evidence
at WP-35.1's dataset scale, not asserted from WP-34.4's 15-pair result alone — and the sweep report
honestly states whether that evidence is strong enough to be confident, or whether it's provisional
given the thin independent fabricated partition.

**Findings (2026-07-30/31):**

- `eval/threshold_sweep.py` scores all 108 `eval/gold_description_grounding.jsonl` records with
  MiniCheck (`flan-t5-large`, same checkpoint as WP-34.4's spike) and sweeps `support_prob`
  thresholds from 0.05 to 0.95 in 0.05 steps, filtered to `source == "wp_35_1_harvest"` (8
  fabricated, 92 faithful) for the primary statistics, with the 8 `wp_34_4_spike` records checked
  separately as a regression test — matching the Scope above exactly.
- **The naive "maximize catch rate" selection would have picked a bad threshold, and the sweep
  caught it.** The first version of this script picked whichever threshold first reached 100% catch
  rate on the independent partition — 0.95 — without weighing the cost. That threshold does catch
  all 8 fabricated examples, but at a 58.7% false-positive rate (54 of 92 faithful descriptions
  wrongly rejected), a number that would make the check unusable in production. Fixed before this
  section was written up: selection now picks the highest catch rate among thresholds with a
  false-positive rate ≤ 10% (a documented judgment call, not derived from the data), mirroring
  `QUOTE_GROUNDING_THRESHOLD`'s own diminishing-returns reasoning.
- **Chosen threshold: `support_prob < 0.85` → reject.** 87.5% catch rate (7/8), 5.4% false-positive
  rate (5/92). One step up (`0.9`) gives the *same* catch rate (7/8) at more than double the
  false-positive rate (13.0%) — a clean, real diminishing-returns cliff, not an arbitrary cutoff.
- **The one miss at 0.85 is the exact case WP-35.3 exists to catch.** Per-subtype catch rate:
  `fabricated_citation` 3/3, `fabricated_fragment` 1/1, `fabricated_other` 2/2,
  `fabricated_modality` **1/2**. The missed modality example scores high because its factual content
  genuinely is grounded — only the invented obligation isn't — precisely the entailment-score
  blind spot Gap 2 (§1) and WP-35.3 describe. This is real, current evidence (not just the one
  historical Codex-caught spike example) that the two-layer design (entailment threshold + separate
  modality check) is necessary, not redundant.
- **Regression check against the 8 `wp_34_4_spike` records: 7/8 correct at 0.85.** The one incorrect
  classification is `REQ-a485fe91aa5f` (`afpd_definition_reframed_as_imperative`,
  `support_prob=0.9197`) — the same known miss WP-34.4's own spike and Codex's PR #164 review
  already found and named. Its continued miss here isn't a new problem; it's confirmation that
  WP-35.3's secondary check is catching a gap the entailment score was never going to close on its
  own, at any threshold (0.9197 is close enough to the faithful-side cluster that no reasonable
  false-positive-rate cap would push the threshold that high).
- **Sensitive, not just thin — found by Codex review on this WP's own PR (#167).** The first
  committed version of this report gave the aggregate catch rate (7/8) without checking how close
  any individual catch sat to the cutoff. `REQ-c6d23854cd0b` (`fabricated_fragment`,
  `DODI 8410.03.pdf`) is caught at `support_prob=0.8421` against a `0.85` threshold — a margin of
  only `0.0079`. A sub-one-point shift in that single score, well within plausible model/prompt
  noise, would drop catch rate from 7/8 to 6/8. Fixed, not just acknowledged: `eval/
  threshold_sweep.py` now has a `margin_analysis()` function that reports the narrowest catch/accept
  on every run, and the report explicitly names the record and margin rather than leaving the
  aggregate rate to imply more confidence than the evidence supports.
- **Confidence call: provisional, not a confident production calibration** — carried forward
  explicitly per the Scope above, given both the 8-example independent fabricated partition
  (documented in WP-35.1's own Findings as a real, twice-confirmed data-scarcity result, not
  insufficient search) and the narrow-margin finding above. WP-35.4 must not treat `0.85` as
  beyond-question final without acknowledging both caveats.
- Output: `eval/spike_results/wp_35_2/report.md` and `results.json` (full sweep table, per-subtype
  breakdown, regression check, all 108 scored records). `eval/threshold_sweep.py` and
  `tests/unit/test_threshold_sweep.py` (pure-logic tests for `sweep()`/`regression_check()`, added
  proactively given how much scrutiny WP-35.1's harvester/builder scripts got for missing test
  coverage) committed alongside.

---

### WP-35.3 — Obligation/Modality-Fabrication Secondary Check

**Source:** Gap 2 in §1 above — the Codex-caught miss on PR #164.

**Problem:** A description can be fully grounded in factual content named by its source_quote while
still fabricating an obligation the quote never states (definitional prose reframed as an
imperative command). The entailment score alone doesn't reliably catch this — confirmed by the one
real miss WP-34.4 found (`support_prob=0.9197` on a case that should have been rejected).

**Scope:**
- A cheap, deterministic secondary check (no LLM call, matching this project's established
  preference for Step D checks that are fast and don't add extraction-time cost), reusing the
  cybersecurity profile's own `obligation_verbs` list from `profiles/cybersecurity.json` rather than
  inventing a separate vocabulary. **Not simple set-membership/presence checking** — verified during
  PR #165 review (Codex) against this repo's own existing fixtures (`eval/entailment_spike.py`) that
  naive vocabulary presence gets both directions wrong:
  - **Under-catches** the actual known-bad case if checked as "quote already contains some
    obligation word, so any obligation word in description is fine": the definition-fabrication
    example's quote already contains "ensure" (`"...to ensure its availability..."`), but that's a
    purpose clause ("in order to ensure X"), not an obligation modal attached to an actor — the
    fabricated word is "Implement," a distinct verb absent from the quote entirely. A correct check
    needs to compare specific words/senses present in `description` against `source_quote`, not
    "does *an* obligation word exist on each side."
  - **Over-catches** on a real faithful case if checked as strict per-word set difference (does each
    specific obligation word in `description` appear literally in `source_quote`): the
    `dodi_nsa_approved_crypto` fixture is a legitimate, faithful "will" → "must" modal-verb
    substitution — a real paraphrase already confirmed faithful in WP-34.4. Obligation verbs are
    routinely paraphrased between near-synonyms in this domain ("will"/"must"/"shall"/"is required
    to" function interchangeably in DoD/NIST regulatory writing); a literal per-word match would
    false-positive on exactly this kind of correct paraphrase.
  - **What this means for implementation, left open here on purpose:** the check needs at least (a)
    a modal-equivalence grouping so `obligation_verbs` entries that function as synonyms don't count
    as mismatches, and (b) some way to distinguish a word's grammatical role (an actual imperative
    modal attached to a subject/actor, vs. the same surface word used in a purpose clause, an
    example, a definition, or a quoted title) rather than bare string containment. Whether that's a
    small synonym-grouping table plus a lightweight dependency/POS check, or some other mechanism,
    is WP-35.3's own design decision — not pre-solved in this phase doc, but the naive
    "vocabulary presence" framing this section originally described is confirmed insufficient
    against this project's own real fixtures and must not be implemented as literally first written.
- Validate against WP-35.1's dataset specifically for this subtype — the modality-fabrication label
  from WP-35.1's fixture file is what this WP's own fixtures should be drawn from, not invented
  fresh. At minimum, both counterexamples found during this phase's own scoping review (the
  "ensure"-as-purpose-clause case and the "will"/"must" paraphrase) must be included as fixtures,
  not just the original miss.
- Decide how this combines with WP-35.2's entailment threshold in WP-35.4 (either check independently
  rejects, or both feed one combined decision) — a real design decision for WP-35.4, not pre-decided
  here.

**Non-goals:**
- Not a general grammar/mood classifier — a narrow, targeted check for the specific pattern found,
  matching this project's preference for minimal, explainable Step D checks over a broader
  ML-based solution to a narrow problem.
- No change to `profiles/cybersecurity.json`'s `obligation_verbs` list itself unless the WP-35.1
  dataset reveals it's missing genuine obligation words relevant to this specific check — reusing
  it, not necessarily expanding it.

**Tests/verification:**
- Positive/negative fixtures drawn from WP-35.1's dataset, following the same pattern established in
  `tests/unit/test_normalize.py` and `tests/unit/test_skip_section.py`.

**Gate:** The known WP-34.4 miss (glossary definition reframed as imperative) is caught by this
check even where the entailment score alone would pass it; the "will" → "must" and other real modal
paraphrases already confirmed faithful in WP-34.4's own fixtures are not falsely rejected; the
"ensure"-as-purpose-clause case specifically does not cause a false negative on the original miss.

**Findings (2026-07-31):**

- Confirmed against this repo's own fixtures (Codex's PR #165 review) that neither naive framing
  works: "any obligation word anywhere in the quote makes any obligation word in description fine"
  under-catches the known miss (the quote's "ensure" is a purpose clause, not the actor being
  commanded to do anything), while "every obligation word in description must appear literally in
  the quote" over-catches real modal-verb paraphrases like `dodi_nsa_approved_crypto` (will → must).
- **Design: split `obligation_verbs` into two functionally different classes, not one flat list.**
  `MODAL_MARKERS` (`shall`, `must`, `will`, `are to`, `is responsible for`, `required`/`required to`)
  express obligation without naming an action — substituting among these restates existing modality.
  `ACTION_VERBS` (`implement`, `establish`, `maintain`, `enforce`, `ensure`) each name a specific
  act — introducing one with no counterpart anywhere in the quote invents a *new* action, not just a
  modality restatement. This split falls directly out of the fixture set: every real fabrication
  found (`afpd_definition_reframed_as_imperative`, and WP-35.1's `REQ-757d551b3e59`/
  `REQ-cbc6374a655f`) introduces a brand-new `ACTION_VERB` (always "Implement" in the observed cases)
  into a quote that names no action of its own at all; every real paraphrase found (`will`→`must`,
  `required`(adj.)→`must`, `support`→`maintain` alongside an already-present `must`) only ever
  substitutes within/around an already-obligatory sentence.
- **`ensure` is genuinely ambiguous and needed its own rule.** It's the one word that appears in both
  the `ACTION_VERBS` list and, idiomatically, in purpose clauses ("...to ensure availability...").
  Resolved with a bare-infinitive check (`_is_infinitive_purpose_clause`): an `ACTION_VERBS` match
  immediately preceded by "to " is treated as non-governing (explains *why*, doesn't command *who*).
  Applied to all `ACTION_VERBS` uniformly, not just `ensure` — the same non-finite grammatical shape
  applies regardless of which verb follows "to ", and no fixture required narrowing it further.
- **The actual rule:** a description fabricates an obligation only if (a) it introduces a governing
  `ACTION_VERBS` word absent from the quote, AND (b) the quote itself asserts no obligation at all —
  no `MODAL_MARKERS` word and no governing `ACTION_VERBS` word of its own. If the quote already
  asserts *some* obligation (by either mechanism), a new/substituted action verb is treated as a
  paraphrase of an already-obligatory sentence, not a fabricated new command. This is a deliberately
  narrow rule (per this WP's own Non-Goals — not a grammar/mood classifier) and is exactly why
  `REQ-35dfe9353e60` (quote already has "must"; description swaps "support"→"maintain") correctly
  passes while structurally near-identical `REQ-cbc6374a655f` (quote has no obligation marker at
  all; description adds "Implement") correctly fails.
- **Validated against WP-35.1's full dataset, not just the two originating fixtures:** all 3
  `fabricated_modality` records caught (3/3), zero false positives across all 94 `faithful` records
  (including the 4 specifically WP-35.1-flagged near-synonym paraphrase fixtures —
  `REQ-679a055fb375`, `REQ-efc38d9d853d`, `REQ-35dfe9353e60`, `REQ-668a74c21bd2`). The 11 other
  fabricated-subtype records (citation/fragment/other — not this check's job) also weren't
  incidentally flagged, for whatever that's worth as an informational data point; not a claim this
  check should ever be relied on for those subtypes.
- **Gemini-found (PR #168): `ACTION_VERBS` exact-match regex missed inflected surface forms.**
  `_governing_action_verbs_in` originally matched only the bare base form (`\bmaintain\b`, etc.),
  which does not match "maintains"/"enforces"/"established"/"implementing" — the ordinary way
  regulatory source_quote text states a governing action in third-person-singular present tense or
  past/gerund form (e.g. `"The ISSO maintains access logs."`). Verified by reproduction before
  fixing: `is_fabricated_obligation("The ISSO maintains access logs.", "Maintain access logs.")`
  incorrectly returned `True` — a faithful tense/person normalization would have been rejected as
  fabricated in production. Fixed by matching each base verb against its small, closed set of
  attested inflections (`ACTION_VERB_FORMS`) and keying results by base form regardless of which
  surface inflection matched, so a quote's "maintains" and a description's "Maintain" compare equal.
  Re-validated after the fix: still 3/3 `fabricated_modality` caught, 0/94 false positives — the fix
  closes a real gap without needing new dataset examples to prove it (none of WP-35.1's 108 records
  happened to contain an inflected action verb, which is exactly why this shipped uncaught by the
  dataset validation and needed a reviewer to find it structurally instead).
- **Codex-found (PR #168, two P2s) + Gemini-found (PR #168, one High): the purpose-clause exclusion
  and the action-verb-only fabrication check were each too narrow, in ways only surfaced by reasoning
  about the code's own logic against new sentence shapes, not by the dataset (none of WP-35.1's 108
  records happened to exercise these shapes either).** All three verified by reproduction before
  fixing:
  - *Codex:* a description reframing a purely factual quote via a brand-new **modal marker** with no
    action-verb change at all (`"Encryption transforms data."` → `"Encryption must transform data."`)
    was missed entirely — `is_fabricated_obligation` only ever checked for a newly introduced
    `ACTION_VERB`, never for a newly introduced `MODAL_MARKER`. Fixed by making the check symmetric:
    it now fires whenever `source_quote` asserts no obligation at all (neither mechanism) but
    `description` asserts one (either mechanism) — simpler than the original action-verb-only
    formulation, not just more correct.
  - *Codex:* `"Personnel have a responsibility to maintain records."` → `"Maintain records."` was
    wrongly flagged as fabricated — the purpose-clause exclusion discarded the quote's own "maintain"
    because it's a bare "to VERB", but "a responsibility **to** maintain" is the obligation itself
    (an infinitive complement of an obligation-bearing noun), not a purpose/goal clause.
  - *Gemini:* `"Agencies are required to implement X."` / `"...are to establish X."` had the identical
    root problem from the opposite direction — `"required to"`/`"are to"` are themselves
    `MODAL_MARKERS` phrases that end in a literal "to", so the verb they govern was being discarded
    as a purpose clause by the same over-broad rule, missing real fabrications where this
    construction appears in a description against a non-obligatory quote.
  - **Fixed with one unified change, not two separate patches**, since both findings share the same
    root cause: `_is_infinitive_purpose_clause` now checks what precedes the "to" — a `MODAL_MARKERS`
    phrase ending in "to", or one of a short `OBLIGATION_COMPLEMENT_NOUNS` list
    (`responsibility`/`duty`/`obligation`/`requirement`) — and only treats the infinitive as a
    non-governing purpose clause when neither applies. The original miss this WP exists to catch
    (`"...to ensure its availability..."`, preceded by neither) is unaffected and still caught.
  - Re-validated after all three fixes: still 3/3 `fabricated_modality` caught, 0/94 false positives
    against WP-35.1's dataset — none of these fixes were data-driven corrections of a wrong dataset
    read; they were structural gaps a reviewer found by testing the code's logic against sentence
    shapes the dataset simply didn't happen to contain.
- **Gemini-found (PR #168, Medium): `None` `source_quote`/`description` crashed with `AttributeError`
  inside `normalize_text()`** rather than passing through — reproduced before fixing
  (`is_fabricated_obligation(None, "Implement X.")` crashed on `.strip()`). Not a live bug against
  today's only caller (WP-35.1's gold dataset never has a null field), but a real risk for WP-35.4's
  eventual production caller, where a missing field is a real possibility. Fixed with an early guard;
  a missing field asserts nothing and fabricates nothing, so it passes through as not-fabricated.
- **Gemini's next review round (PR #168) had two findings — one real, one checked and rejected.**
  - *Claimed (rejected):* case-sensitive matching causes capitalized modal markers/action verbs
    ("SHALL", "Implement") to be missed. Checked before acting: `normalize_text()` (imported from
    `pipeline/parse_and_normalize.py`) already lowercases (`text.strip().lower()`) — confirmed by
    direct reproduction with a capitalized quote, which classified correctly. This finding's premise
    was factually wrong; no code change made. Recorded here rather than silently dropped, per this
    project's "verify before applying" discipline applying in both directions — a reviewer being
    wrong is itself worth a one-line note, not just a quiet no-op.
  - *Real:* `MODAL_MARKERS` had plural `"are to"` but not singular `"is to"` — a real DoD/NIST
    phrasing for a singular actor (`"The ISSO is to maintain access logs."`). Reproduced before
    fixing: this faithful sentence's own quote wasn't recognized as asserting any obligation, so a
    faithful `"Maintain access logs."` description was wrongly flagged as fabricated. Fixed by adding
    `"is to"` to `MODAL_MARKERS`; picked up automatically by the existing modal-marker-ending-in-"to"
    purpose-clause exemption with no other code change needed.
- Output: `eval/modality_fabrication_check.py` (the check itself — `is_fabricated_obligation()` plus
  a validation `main()`), `tests/unit/test_modality_fabrication_check.py` (32 tests: the known
  WP-34.4/Codex miss, the 4 real paraphrase fixtures, the inflected-verb-form fix, the two purpose-
  clause fixes, the new-modal-marker fix, the `None`-field guard, the singular "is to" fix, plus unit
  coverage of the helper functions), and `eval/spike_results/wp_35_3/report.md`/`results.json` (full
  validation output, mirroring the `eval/spike_results/wp_34_4/`, `eval/spike_results/wp_35_2/`
  precedent).
- Per this WP's own Scope, deliberately not wired into `pipeline/parse_and_normalize.py` yet — how
  this combines with WP-35.2's entailment threshold (independent rejects vs. one combined decision)
  is an explicit WP-35.4 design decision, not pre-decided here.

---

### WP-35.4 — Production Step D.5/D.6 Entailment Gate

**Source:** WP-34.4's spike conclusion. Depends on WP-35.2 and WP-35.3.

**Problem:** The validated technique and calibrated threshold need to actually run against every
Step D.5 enrichment output, not just exist as an eval script.

**Scope:**
- Add MiniCheck as a real dependency in `pyproject.toml` (base install or a new optional extra —
  decide based on the transitive-footprint question raised in §3's Non-Goals; if the footprint is
  heavy and the check is meant to run inline during every ingest, base install matches WP-34.1's
  own docling precedent; if it's expensive enough to want opt-in, a new extra is more appropriate —
  make and document the call here, don't default silently).
- **Explicitly decide what "reject" means here — this is a real open question, not
  pre-answered by copying WP-34.2's pattern.** Found during a manual local Codex review of this doc
  (2026-07-30, not posted to GitHub): every existing Step D check this phase's WPs have referenced as
  precedent (`empty_source_quote`, `quote_not_grounded_in_chunk`, `heading_echo_quote`,
  `unrepairable_fragment_quote`) rejects because `source_quote` itself — the core artifact — is
  unreliable; there's nothing valid underneath to keep. This gate is different in kind:
  `source_quote` already passed those checks and is confirmed grounded by the time Step D.5 runs;
  only the *derived* `description` field can be bad. If this check reject-drops the whole requirement
  the same way the quote-level checks do, a real, valid requirement gets silently destroyed just
  because one non-deterministic Step D.5 LLM call produced a bad summary — confirmed this isn't
  hypothetical: `pipeline/run_pipeline.py` already has an established, different precedent for this
  exact situation (Step D.5 enrichment failing outright doesn't discard the requirement — "the
  pipeline continues with the normalized JSONL for indexing"). This WP must explicitly decide and
  document one of: (a) `description_not_grounded`/`description_fabricated_obligation` clear or blank
  the `description` field (and whatever Step D.5 fields depend on it) but keep the underlying
  requirement, consistent with the existing enrichment-failure precedent, or (b) the whole
  requirement is dropped only when `source_quote` itself is independently invalid, never solely for
  a bad `description`. Record whichever is chosen with the same rigor as every other durable failure
  reason in `*_normalization_failures.jsonl` — but don't default to blanket reject-the-requirement
  just because that's what the unrelated quote-level checks do.
- Decide and document whether this runs as part of Step D.5 itself or a new Step D.6 immediately
  after it — Step D.5 already isn't fully deterministic and involves an LLM call; this check does
  not need one, so it may be cleaner as its own deterministic pass over Step D.5's output rather
  than folded into the same function.
- One combined LLM call vs. two separate passes isn't the concern here (this check makes no LLM
  call at all) — the actual design question is pipeline sequencing (D.5 → D.6) and whether a
  Step D.5 failure should even reach this check (if Step D.5 itself failed/fell back, is there a
  `description` to check at all — confirm current fallback behavior before assuming there always is).

**Non-goals:**
- No re-architecting of Step D.5's own enrichment prompt or logic — this WP adds a check after it,
  doesn't change what it does.
- No retroactive re-check of already-indexed requirements — applies to future ingests only, same
  stance as every other Phase 34/35 WP.

**Tests/verification:**
- Unit tests for the new check function(s), mirroring `test_normalize.py`'s existing
  `_is_heading_echo`/`_is_unrepairable_fragment` test style.
- Full `pytest` suite passes; `ruff check .` clean.
- Manual: re-run enrichment against real corpus documents, confirm the known WP-34.4/Codex-found
  fabrication patterns are now rejected end-to-end, not just in the standalone eval script.

**Gate:** The calibrated gate runs as part of the real pipeline, with durable, distinguishable
failure reasons; known fabrication patterns from WP-34.4 are caught in a live pipeline run, not just
the eval script; the requirement-vs-description-field question above is explicitly decided and
documented, not left implicit — and whichever way it's decided, a requirement with a genuinely valid
`source_quote` is never silently lost solely because `description` failed this check.

**Findings (2026-07-31):**

- **All three open design questions from Scope, decided and documented, not defaulted:**
  - *Dependency footprint:* new `grounding-check` optional extra in `pyproject.toml`, not base
    install. MiniCheck's GitHub install pulls torch/transformers/datasets/openai/pyarrow — a heavy
    footprint basic ingestion doesn't need, unlike docling (WP-34.1), which had no choice but to go
    base since it's the only ingestion path left. Pinned to the exact commit this repo's WP-35.2
    threshold was calibrated against
    (`git+https://github.com/Liyan06/MiniCheck.git@b58b9fa69acbd1015ec970fa65dd752413a053d2`), with
    the PyPI name-collision warning from `docs/PHASE34_REQUIREMENTS.md` carried into the dependency
    comment itself so a future contributor doesn't rediscover it the hard way.
  - *Reject semantics:* **(a)** — clear the `description` field (set to `""`) on rejection, never
    drop the requirement. `source_quote`, `domain_tags`, `requirement_type`, and every other field
    pass through unchanged even when `description` is cleared. Matches Step D.5's own existing
    enrichment-failure precedent exactly, per the Scope's reasoning.
  - *Sequencing:* a new Step D.6 (`pipeline/entailment_gate.py`), not folded into Step D.5. Runs on
    whatever `index_path` currently is (enriched if D.5 succeeded, normalized otherwise) whenever
    Step D ran — so a description carried over from Step C (D.5 skipped or failed outright) still
    gets checked, not just freshly-enriched ones. Confirmed via reading `enrich_requirements.py`
    directly: a failed per-record enrichment call leaves that record's `description` exactly as Step
    C/D produced it, not blanked — so there's real content worth checking either way.
  - *How the two checks combine (WP-35.3's own open question):* **OR, not AND** — either check
    rejecting is enough. They catch different fabrication shapes by design (Gap 2, §1): requiring
    both to agree would silently reopen the exact blind spot WP-35.3 exists to close, since
    MiniCheck's own per-subtype numbers (WP-35.2's report) show `fabricated_modality` is precisely
    the subtype it's weakest at (1/2 caught at the chosen threshold).
- **Architectural consequence found by reading `core/artifact_resolver.py` before assuming a new
  output file would "just work": every downstream consumer of a document's requirements — GUI,
  checklist, evidence, `reqbot reindex` — goes through `resolve_latest_requirement_files()`/
  `resolve_requirement_file()`, not through `run_pipeline.py`'s own `index_path` variable.** Adding
  `*_requirements_gated.jsonl` without teaching this shared resolver about it would have made the
  gate a no-op for every consumer except a single fresh pipeline run — silently bypassed everywhere
  else. Fixed: `_GATED_SUFFIX` added, preference order now gated > enriched > normalized (both in
  `doc_key_from_requirements_path()` and `resolve_latest_requirement_files()`), with "latest run
  wins" still taking priority over file-type preference, matching the existing enriched-over-
  normalized precedent exactly. `services/checklist_service.py` and `cli/reqbot.py`'s docstrings
  updated to match; the one-off, already-historical `record_baseline_dirs.py` (a WP-14.4 pre-step
  script) deliberately left untouched — checked, not a live consumer of "the best available file"
  for any current feature.
- **Moved WP-35.3's check into `pipeline/entailment_gate.py` as real production logic, rather than
  importing production code from `eval/`.** `eval/modality_fabrication_check.py` now only imports
  `is_fabricated_obligation` and validation-reports against it — mirroring the existing, opposite-
  direction precedent (`eval/harvest_description_grounding_candidates.py` already imports
  `normalize_text` from `pipeline/parse_and_normalize.py`): `pipeline/` holds canonical production
  logic, `eval/` scripts reuse it for reporting, never the other way around. Zero behavior change —
  confirmed by re-running the WP-35.3 validation script post-move: still 3/3 `fabricated_modality`
  caught, 0/94 false positives, identical to pre-move.
- **Manual verification, against real corpus documents, not just the standalone eval script (Tests/
  verification requirement):** ran `pipeline/entailment_gate.py` directly against two real, already-
  enriched local documents.
  - `NIST.SP.800-125.pdf` (151 requirements): 13 rejected (12 `description_not_grounded`, 1
    `description_fabricated_obligation`). The known WP-35.1 fabrication `REQ-757d551b3e59`
    ("Implement better control of OSs...") was caught live — and its `support_prob` was `0.9367`,
    confidently *above* the entailment threshold, confirming live, in production code (not just the
    eval script) that MiniCheck alone would have missed this exact case and the modality check is
    what actually caught it. Requirement count in: 151, out: 151 — nothing dropped.
  - `afi10-2402.pdf` (290 requirements): 9 rejected. The known WP-35.1 fabrication
    `REQ-cbc6374a655f` ("Implement Insider Threat Program...") was caught by **both** checks at once
    (`support_prob=0.4524`, well below threshold, and the modality check both fired) — confirming
    the failures record correctly captures co-occurring reasons rather than picking just one.
    Requirement count in: 290, out: 290.
- **CLI:** `--skip-description-gate` added to `reqbot ingest`, `reqbot batch`, and standalone
  `run_pipeline.py`, mirroring `--skip-enrichment`'s existing pattern exactly. `README.md` updated
  (pipeline stage list, flag references, Installation section) to document the new extra and flag.
- **Codex-found (PR #169, two P1s) + Gemini-found (PR #169, one High): three real gaps, all
  verified by reproduction before fixing.**
  - *Codex P1:* if MiniCheck is installed but `scorer.score()` itself raises (missing NLTK
    `punkt_tab` resource — an easy-to-forget separate manual step this WP's own README section
    documents; OOM; a transient model-load error), the exception escaped `run()` entirely.
    `run_pipeline.py`'s own caller then catches it and falls back to the **completely ungated**
    file — silently losing the dependency-free modality-fabrication check too, not just the
    entailment check that actually failed, contradicting this module's own documented guarantee.
    Reproduced with a scorer stub that raises on `.score()`: confirmed the whole gate crashed.
    Fixed by wrapping the scoring call itself in a `try`/`except` inside `run()`, degrading to
    "entailment skipped" exactly like the not-installed case — the modality check runs regardless.
  - *Codex P1:* `core/artifact_resolver.py`'s gated-preference change (this WP) assumed every file
    in a run directory represents one coherent, complete pipeline invocation. That's false for a
    reused output directory (`--skip-to D --skip-description-gate`, or a failed Step D.6) — Step
    D.5/D.6 are independently skippable, so a rerun can regenerate `enriched`/`normalized` while
    leaving an **older, now-inconsistent** `gated` file untouched, and the resolver would keep
    preferring it forever purely because "gated" outranks "enriched" as a tier — the same latent
    risk already existed for enriched-over-normalized, just never triggered until this WP made
    partial-step reruns common. Reproduced: wrote a gated file, then an enriched file 50ms later
    in the same run dir — resolver returned the stale gated file. Fixed with
    `_freshest_acceptable_tier()`: a higher tier is only preferred when it is not older than every
    lower tier present in the same run directory; otherwise falls through to the next tier down.
  - *Gemini (High):* a record missing `source_quote` entirely (not something the normal pipeline
    path can produce — Step D's own `empty_source_quote` check, confirmed by reading
    `parse_and_normalize.py` directly, guarantees anything reaching Step D.6 already has a
    non-empty string) raised a raw `KeyError` rather than being handled gracefully. Real risk
    specifically for `entailment_gate.py`'s own standalone CLI entry point, which can be pointed at
    an arbitrary, non-pipeline-validated file. Reproduced, then fixed with `.get("source_quote") or
    ""` at both call sites, matching this file's own existing `is_fabricated_obligation()` None-
    guard precedent.
  - Re-verified all fixes against the same two real documents used for this WP's original manual
    verification: identical results (13/151 and 9/290 rejected, same records) — the fixes close
    real gaps without changing any real-world outcome.
- Output: `pipeline/entailment_gate.py` (Step D.6 itself), `core/artifact_resolver.py` (gated-
  preference update + `_freshest_acceptable_tier()` staleness guard), `pipeline/run_pipeline.py`
  (Step D.6 wiring), `cli/reqbot.py` (flag passthrough), `pyproject.toml` (`grounding-check` extra),
  `eval/modality_fabrication_check.py` (thinned to import-and-report), `tests/unit/
  test_entailment_gate.py` (13 tests: MiniCheck-unavailable graceful skip, entailment rejection,
  modality rejection, both-reasons co-occurrence, empty-description pass-through, requirement-
  never-dropped invariant, gated-filename derivation from both enriched and normalized inputs,
  scoring-failure degradation, missing-`source_quote` guard), `tests/unit/test_artifact_resolver.py`
  (+6 tests for gated preference/fallback/latest-run-wins/staleness-within-a-run),
  `tests/unit/test_modality_fabrication_check.py` (import path updated only, all 32 tests unchanged
  and still passing).

---

### WP-35.5 — Integration Gate

**Source:** Standard phase-closing practice (matches Phase 20/23's own integration-gate WPs).

**Problem:** Each of WP-35.1–35.4 is independently testable, but the phase needs one pass confirming
they compose correctly against a real, full pipeline run.

**Scope:**
- Full ingest of at least one real document end-to-end with the new gate active, confirming: known
  fabrication patterns caught, known faithful descriptions pass, failure reasons recorded correctly,
  and — the actual yield check depends on what WP-35.4 decided — either no unexpected drop in
  requirement *count* (if bad descriptions clear the field but keep the requirement) or no unexpected
  drop in requirement count *beyond* records whose `source_quote` was independently invalid (if
  WP-35.4 decided full rejection is warranted). Confirm whichever WP-35.4 actually chose is what this
  gate observes — don't assume requirement count should stay flat if the decision was to reject.
- Update `docs/PHASE33_REQUIREMENTS.md`'s WP-33.3 Findings categories 1 and 3 (both cite the
  description-fabrication symptom) to reference this phase's actual fix, closing the loop WP-34.4's
  spike opened.

**Non-goals:**
- Not a new failure-mode investigation — confirms the already-scoped fix works end-to-end.

**Tests/verification:**
- Full `pytest` suite passes; `ruff check .` clean; manual full-pipeline run.

**Gate:** Phase 35's Success Gate below is met.

**Findings (2026-07-31):**

- **Full, fresh, real end-to-end pipeline run** — `reqbot ingest raw_pdfs/afpd_17-1.pdf --no-index`
  (the actual CLI entry point, not a standalone module call like WP-35.4's manual verification used)
  — confirming the whole orchestration, not just `entailment_gate.py` in isolation: Step D (73 raw →
  64 normalized) → Step D.5 (64 enriched) → **Step D.6 ran automatically, no flag needed** (loaded 64,
  wrote 64 gated + a 5-record failures file) → **Step E's own log line confirms it read from the
  gated file, not the enriched one** (`"Loading normalized requirements from:
  ...afpd_17-1_requirements_gated.jsonl"`) → final output: 64 requirements. Requirement count
  preserved end-to-end (73 raw → 64 after Step D's own unrelated checks → 64 through D.5/D.6/E) —
  confirms WP-35.4's chosen semantics (clear description, never drop the requirement) held in a real
  run, not just unit tests.
- **`core/artifact_resolver.py` confirmed against the real corpus, not just synthetic `tmp_path`
  tests:** `resolve_requirement_file()` correctly resolved to this fresh run's
  `afpd_17-1_requirements_gated.jsonl`, in preference to an *older* `afpd_17-1` run from 2026-07-29
  that only has non-gated files — both the gated-tier preference and the latest-run-wins logic
  confirmed together on real, pre-existing multi-run corpus state.
- **A real, honest limitation surfaced by testing against fresh data the calibration set never
  covered — not glossed over, logged as `docs/TODO_future_improvements.txt` item 33.** All 5
  rejected descriptions in this run are **byte-identical to their own `source_quote`** (e.g.
  `"Participate in cyberspace governance forums."` verbatim on both sides), scoring
  `support_prob` 0.6782–0.8442 — below the 0.85 threshold despite having zero new content to be
  "fabricated." WP-35.3's modality check correctly did not flag any of these (nothing obligatory was
  invented) — confirming the two checks' specificity is doing exactly what it's designed to do; this
  is purely an entailment-threshold weakness for very short, verbatim premise/hypothesis pairs.
  Checked directly: this exact shape (`description == source_quote`) could never have been surfaced
  by either of WP-35.1's harvester heuristics (`_is_citation_fragment_shaped` requires the
  description to be *longer*; `_is_modality_shaped` requires an obligation word present on one side
  and absent from the other — identical text trivially fails both), so it was structurally invisible
  to WP-35.2's calibration sweep, not a regression from a previously-measured number. This is exactly
  the kind of gap the "provisional, not confident" caveat (carried through WP-35.2/35.3/35.4's docs
  from the start) exists to warn about — real-world evidence of it, not a hypothetical. Not fixed in
  this WP, per its own Non-Goals (not a new failure-mode investigation); logged with a concrete
  suggested direction (a cheap exact-match short-circuit ahead of the MiniCheck call, or a targeted
  future harvest of short verbatim-pair examples) for whoever picks it up next.
- `docs/PHASE33_REQUIREMENTS.md`'s WP-33.3 Findings (categories 1 and 3, both cite the description-
  fabrication symptom this phase fixes, plus the Conclusion's forward-looking "claim/entailment
  problem... worth scoping as its own investigation" note) updated with closing pointers to this
  phase's actual implementation, closing the loop WP-34.4's spike opened back in Phase 34.
- `docs/TODO_future_improvements.txt` item 31 marked `[RESOLVED -- Phase 35, WP-35.1 through
  WP-35.4]`, replacing its now-stale "not yet implemented" scoping text with a concise pointer to
  this phase doc — matching item 25's existing resolved-item format.
- Full `pytest` suite (746 tests) passes; `ruff check .` clean.

---

## 5. Success Gate

Phase 35 is complete when:

1. ✅ WP-35.1's labeled dataset is committed and documented.
2. ✅ WP-35.2's threshold is chosen with real sweep evidence against that dataset.
3. ✅ WP-35.3's secondary check catches the known modality-fabrication pattern WP-34.4 found.
4. ✅ WP-35.4's gate runs in the real pipeline with durable, distinguishable failure reasons.
5. ✅ WP-35.5's integration gate confirms end-to-end behavior against a real document.
6. ✅ Full unit suite passes (`pytest`); `ruff check .` passes.
7. ✅ `docs/TODO_future_improvements.txt` item 31 is marked resolved, pointing at this phase.

**Phase 35 is complete.**

---

## 6. Guardrails

1. One WP at a time — each lands as its own PR, reviewed before proceeding to the next, same cadence
   as prior phases. WP-35.1 must land before WP-35.2 and WP-35.3 can be meaningfully validated (a
   hard dependency — both need real labeled data, not WP-34.4's small curated set).
2. WP-35.3's secondary check stays narrow and deterministic — resist the temptation to fold it into
   a second ML model or a broader classifier. The problem found is specific (obligation language
   fabricated on top of faithful facts); the fix should be equally specific.
3. WP-35.4's checks never salvage/reconstruct a rejected `description` from surrounding context —
   that part of WP-34.2's principle carries over unchanged. What does *not* automatically carry over:
   whether failing this check drops the whole requirement or just the `description` field. WP-34.2's
   checks reject the whole requirement because the thing they check (`source_quote`) has nothing
   valid to fall back to if it fails; WP-35.4's checks run on a field that's already downstream of an
   independently-valid `source_quote`, so that same reasoning doesn't automatically apply — it's an
   explicit WP-35.4 decision (see that WP's Scope), not assumed here.
4. The MiniCheck dependency-footprint decision (§3's Non-Goals) must actually be made and documented
   during WP-35.4, not defaulted to "whatever `pip install` happened to pull in" the way WP-34.4's
   spike setup left it.
