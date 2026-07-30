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
| WP-35.2 — Threshold Calibration Sweep | Not started |
| WP-35.3 — Obligation/Modality-Fabrication Secondary Check | Not started |
| WP-35.4 — Production Step D.5/D.6 Entailment Gate | Not started |
| WP-35.5 — Integration Gate | Not started |

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

- Harvested from `~/documents/processed/*/` across 11 pipeline runs / 8 distinct source documents
  (1,204 unique `(source_pdf, chunk_id, source_quote, description)` triples after dedup): the
  original 2 corpus documents (`afpd_17-1.pdf`, `CJCSI 6510.02G.pdf`, 5 runs) plus 6 freshly-ingested
  documents (`DODI 5200.01.pdf`, `afi17-203.pdf`, `NIST.SP.800-125.pdf`, `DODI 5200.44.pdf`,
  `DODI 8410.03.pdf`, `afi10-2402.pdf`, all ingested today with `--no-index`). The fresh ingests were
  necessary, not just nice-to-have for diversity: all 5 pre-existing runs predate today's
  WP-34.1/34.2/34.3 merges, so none of the local corpus reflected the current, fixed pipeline before
  this WP ran.
- `eval/harvest_description_grounding_candidates.py` flagged candidates with two structural
  heuristics — the same shape that surfaced WP-34.4's own 15 examples in the first place, scaled up:
  a short/colon-terminated quote paired with a much-longer, low-similarity description
  (citation/fragment-shaped), and a `profiles/cybersecurity.json` `obligation_verbs` term present in
  `description` but literally absent from `source_quote` (modality-shaped) — plus a random sample of
  everything neither heuristic flagged, restricted to post-fix runs, as the faithful holdout.
- **Real hit rate is low: 17 distinct flagged candidates out of 1,204 scanned (~1.4%).** All 17 were
  hand-verified against their own `section_title_path`/`parent_context`, per this WP's scope. 14 were
  confirmed genuine fabrications; the other 3 were exactly the heuristic's own predicted
  false-positive shape (a real modal-verb or near-synonym paraphrase, e.g. `will`→`must`) and are
  kept as `faithful`-labeled WP-35.3 fixtures specifically because they were flagged, not despite it.
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
- Given the honest hit rate above, the faithful holdout was deliberately oversized (90 records
  against 14 fabricated + 3 reclassified, 8 of those 17 marked `wp_34_4_spike`) to reach this WP's
  Gate at a defensible total scale — 107 records combined (99 genuinely new to this WP), order-of-
  magnitude 100+ as scoped, with the shortfall on the fabricated side documented rather than papered
  over with synthetic or padded examples.
- **Output:** `eval/gold_description_grounding.jsonl` — 107 records: 5 `fabricated_citation`, 3
  `fabricated_fragment`, 3 `fabricated_modality`, 3 `fabricated_other`, 93 `faithful` (99 `source:
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

**Non-goals:**
- No production code change — this WP picks and documents a number for WP-35.4 to use.

**Tests/verification:**
- The sweep itself, committed as a report (mirroring `eval/entailment_spike.py`'s own
  `eval/spike_results/` pattern).

**Gate:** A specific threshold is chosen and documented with real false-positive/catch-rate evidence
at WP-35.1's dataset scale, not asserted from WP-34.4's 15-pair result alone.

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

---

## 5. Success Gate

Phase 35 is complete when:

1. WP-35.1's labeled dataset is committed and documented.
2. WP-35.2's threshold is chosen with real sweep evidence against that dataset.
3. WP-35.3's secondary check catches the known modality-fabrication pattern WP-34.4 found.
4. WP-35.4's gate runs in the real pipeline with durable, distinguishable failure reasons.
5. WP-35.5's integration gate confirms end-to-end behavior against a real document.
6. Full unit suite passes (`pytest`); `ruff check .` passes.
7. `docs/TODO_future_improvements.txt` item 31 is marked resolved, pointing at this phase.

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
