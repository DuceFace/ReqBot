# ReqBot Phase 37 — Retrieval Quality: Eval Harness & Contextual Chunk Embeddings

**Status:** Locked (drafted 2026-07-31; source: direct conversation with Tyler after Phase 36
closed — see Phase Framing below)
**Date:** 2026-07-31
**Preceded by:** Phase 36 (Entailment-Gate Calibration Fix: Exact-Match Short-Circuit) — WP-36.1
complete, WP-36.2 deliberately deferred as backlog (`docs/PHASE36_REQUIREMENTS.md`).
**Followed by:** Phase 38 (Extraction Precision: Failure Audit & Targeted Fixes) —
`docs/PHASE38_REQUIREMENTS.md`, drafted 2026-07-31. Different pipeline stage (extraction precision
vs. retrieval quality) and a different origin (a separate conversation's diagnosis, not this phase's
own findings) — not a continuation of this phase's own work.

---

## Status

This table is the live source of truth for Phase 37 WP status — update it here when a WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-37.1 — Retrieval-Quality Eval Harness (Baseline) | Complete |
| WP-37.2 — Contextual Chunk Embeddings | Complete — negative result, reverted (not deployed) |

---

## 1. Phase Framing

Every phase so far (32 through 36) worked on requirement **extraction** quality — does Step C/D
correctly pull real, non-fabricated requirements out of a chunk. That work is real and has paid off
(Phase 34's docling migration, WP-34.2/34.3's fragment/echo rejection, Phase 35's description-
grounding gate, Phase 36's calibration fix). But it's a different pipeline stage from **retrieval**
quality — does `reqbot ask`/`search` actually surface the right requirements, ranked well, for a
real question. Tyler flagged this directly after Phase 36 closed: extraction correctness doesn't
matter if search can't find the right requirement in the first place, and search/ask is the core of
what makes ReqBot useful for compliance research (as opposed to just a checklist generator). This
phase is scoped to retrieval quality specifically — extraction correctness is Phases 32-35's job,
not re-litigated here.

**The concrete gap, checked directly before writing this doc, not assumed:**

- `pipeline/embed_and_index.py`'s `build_embedding_text()` embeds **only the bare `source_quote`**
  (plus an optional one-line `source_ref` citation string) for both the dense (`nomic-embed-text`)
  and sparse (BM25) vectors. Something like `"(b) Ensure passwords are changed every 60 days."` gets
  embedded with no indication of which system, document, or section it's from. ReqBot already
  captures `section_title_path`, `parent_context`, and `source_pdf` per requirement (stored in the
  Qdrant payload) — none of it is used at embedding time, only for display/filtering after a match is
  already found.
- This is precisely the failure mode Anthropic's published Contextual Retrieval research targets:
  short, decontextualized chunks embed and match poorly on their own. Their fix — prepending a short
  situating description to each chunk before embedding it, for both the dense and sparse (BM25)
  representations — reduced retrieval failure rate by ~35% in their published benchmark (~49% when
  combined with reranking). ReqBot has never adopted any version of this.
- Current retrieval architecture (`core/ask.py`), confirmed by reading `retrieve()`: hybrid dense +
  sparse BM25 + an optional third HyDE-generated-hypothesis dense leg, fused via Qdrant-native RRF,
  with an LLM query-rewrite step ahead of it (expands acronyms, extracts control IDs/domain tags) and
  a `min_score=0.02` floor after fusion. No reranking stage exists (`RETRIEVAL EXPERIMENTS` section of
  `docs/TODO_future_improvements.txt` lists a reranker spike as an unstarted backlog item — not
  duplicated by this phase, see Non-Goals).
- **No retrieval-quality eval harness exists at all.** `eval/eval_harness.py` measures Step C
  extraction precision/recall only (does the LLM find the right requirements in a chunk) — nothing
  measures whether a search query returns the right requirements, ranked well. This means none of the
  backlog's retrieval experiments (reranker, multi-vector, HyPE, corrective retrieval) have ever been
  measured before/after either. Any retrieval-quality fix — this phase's or a future one's — is
  currently unverifiable.
- **The live index is already stale relative to the processed corpus, checked directly via `reqbot
  status`/`docs` while scoping this phase:** Qdrant's `grc_requirements` collection has **173
  points**, but the processed JSONL corpus (`reqbot docs`, latest-run-wins) has **1,876 requirements
  across 13 documents**. This is the exact drift pattern documented as a known gotcha
  (`docs/OPERATIONS.md`'s reindex procedure, and prior-session memory) — most of the corpus was
  ingested with `--no-index` during Phase 35's dataset-harvesting expansion and never reindexed. A
  retrieval-quality baseline measured against 173 stale points would not be representative of the
  real corpus; this needs fixing before any query set is built against it.

## 2. Goals

- Sync the live Qdrant index to the full processed corpus (`reqbot reindex`) before measuring
  anything — a baseline against 9% of the real corpus is not a baseline worth trusting.
- Build a small, hand-labeled retrieval eval harness: real natural-language queries against the real
  corpus, each with a hand-verified set of relevant `requirement_id`s, measuring recall@k (k
  matching the CLI's actual `top_k` defaults) and MRR — the retrieval-quality equivalent of what
  `eval/eval_harness.py` already does for extraction.
- Run that harness against **current, unmodified** `reqbot ask`/`retrieve()` behavior first, to get
  a real baseline number before changing anything — same "verify before applying" discipline as every
  prior phase.
- Implement contextual chunk embeddings: prepend a short situating description (document title +
  section path, at minimum) to the text used for both dense and sparse embedding, using metadata
  ReqBot already captures.
- Re-run the same harness against the same queries post-change to get a real, honest before/after
  delta — not an assumption that this helps just because Anthropic's paper says a similar technique
  did, for a different corpus and a different embedding model.

## 3. Non-Goals

- **Not requirement extraction quality.** Phases 32-35 already own that pipeline stage
  (`pipeline/llm_extract_requirements.py`, Step C/D). This phase doesn't touch extraction logic,
  prompts, or the description-grounding gate — only what happens after a requirement record already
  exists, at embedding/search time.
- **Not a reranker.** Already a separate, unstarted backlog item (`docs/TODO_future_improvements.txt`
  RETRIEVAL EXPERIMENTS section, item 1). Worth its own phase, evaluated against this same harness
  once it exists — not bundled into this one to keep each change independently measurable.
- **Not multi-vector retrieval, HyPE, or a corrective retrieval gate.** Same reasoning — separate,
  already-tracked backlog items, each deserving its own isolated before/after measurement rather than
  several simultaneous changes making it impossible to tell which one moved the number.
- **Not LLM-generated per-chunk contextual summaries (Anthropic's full published technique).** Their
  benchmark used an LLM call per chunk (with prompt caching to control cost) to generate a bespoke
  situating sentence, not raw metadata concatenation. This phase starts with the free version — the
  metadata ReqBot already has (document title, section path, parent context) — and measures it
  honestly. If WP-37.2's harness results don't close enough of the gap, the LLM-generated version is
  a natural, separately-scoped follow-up with its own cost/latency tradeoff to evaluate — not
  pre-committed to here.
- **Not a change to the query-rewrite or HyDE prompts.** Both already exist and are already default-on
  (Phase 15/24 decisions); re-tuning them is a different, separate investigation from whether the
  indexed chunks themselves are well-formed.
- **Not fixing the Qdrant/JSONL drift as a recurring problem** (e.g., auto-reindex-on-ingest). Just
  syncing it once, here, as a prerequisite to a trustworthy baseline. Whether ingest should always
  reindex automatically is a separate, unasked question this phase doesn't take a position on.

---

## 4. Work Packages

### WP-37.1 — Retrieval-Quality Eval Harness (Baseline)

**Source:** Direct conversation with Tyler, 2026-07-31 — retrieval/search quality named as the core
concern, and the core of what makes ReqBot valuable beyond checklist generation.

**Problem:** No infrastructure exists to measure whether `reqbot ask`/`search` returns the right
requirements for a real query, ranked well. Every retrieval-quality claim — this phase's or any
future one's — is currently just a plausible-sounding guess.

**Scope:**
- Run `reqbot reindex` against the current processed corpus (13 documents, 1,876 requirements) so the
  live Qdrant index actually reflects it before building anything against it — verify via `reqbot
  status` that `grc_requirements`'s point count matches `reqbot docs`'s total afterward, not just that
  the command exited 0.
- Build a labeled query set: realistic natural-language compliance-research questions (matching how
  `reqbot ask` is actually used — not keyword lists), each hand-labeled with the `requirement_id`s
  that are genuinely relevant, checked against the real corpus text directly (same hand-verification
  discipline as WP-35.1's fabrication dataset — an LLM-generated label is not ground truth here,
  every label must be a human judgment call against real source text).
  - Cover a range of query shapes: specific/narrow (a single control-ID-adjacent question with one or
    two clearly-correct answers), broad/thematic (a topic spanning many requirements across possibly
    multiple documents), and at least a few queries that should legitimately return **zero** or very
    few results (a topic genuinely not covered by the current 13-document corpus) — a harness that
    only tests "find the right needle" misses "correctly report there's no needle."
  - Sample size: learn from WP-35.1's own documented data-scarcity lesson — don't assume an
    arbitrary round number (20, 50) is enough without checking; report the real count achieved and
    whether it's enough to draw a confident conclusion, the same honest caveat WP-35.2's threshold
    sweep already carries for its own small fabricated-example set.
- Implement the harness itself: for each labeled query, run it through the real, unmodified
  `core.ask.retrieve()` (current production defaults — hybrid + HyDE + RRF + query rewrite, nothing
  disabled to make the harness easier to build), compute recall@k for the CLI's actual `top_k`
  defaults and MRR, aggregate and report per-query and overall.
- Document the baseline numbers plainly, including where the current system already does well (don't
  bias the writeup toward finding problems) and where it doesn't.

**Non-goals:**
- No retrieval code changes in this WP — measurement only. WP-37.2 is where anything actually changes.
- Not a claim that this query set is exhaustive or a permanent fixture — it's a first, real, honest
  baseline instrument, expected to grow over time the same way `eval/gold_description_grounding.jsonl`
  did across WP-35.1's two expansion rounds.

**Tests/verification:**
- The harness script itself gets a small unit test against a synthetic mini-index (mocked Qdrant
  results), proving the recall@k/MRR math is correct independent of any real retrieval behavior.
- The real deliverable is the baseline report itself, run against the live corpus post-reindex — this
  is fundamentally a measurement WP, not a unit-testable-in-isolation one, same as WP-35.1/35.2's own
  verification shape.
- `ruff check .` clean.

**Gate:** A committed, hand-verified labeled query set exists; the harness runs against real,
unmodified `reqbot ask` behavior and produces real recall@k/MRR numbers; the Qdrant/JSONL drift found
above is fixed and confirmed fixed, not just attempted.

**Findings (2026-07-31):**

- **Index drift fixed and confirmed, not just attempted.** `reqbot reindex` run against the live
  Qdrant instance; `grc_requirements` now has exactly 1,876 points, matching `reqbot docs`'s total
  (13 documents) — checked via a direct `QdrantClient.scroll()` inspection, not just a successful
  exit code.
- **Labeled query set: 16 queries, 82 hand-verified relevant-`requirement_id` references, committed
  at `eval/gold_retrieval_queries.jsonl`.** 7 narrow (14 relevant IDs total, every one individually
  read against real source text), 5 broad/thematic (68 relevant IDs, each candidate pool built from
  a `domain_tags` + keyword filter then hand-read in full — not sampled — with real exclusions made
  where a hit matched the filter but wasn't actually a good answer: an acceptable-use-acknowledgment
  record that matched "personnel security" keywords but isn't about clearance requirements, and three
  incoherent docling table-extraction fragments that matched "incident report" keywords but aren't
  answers a real user would want), 4 zero-truth (genuinely off-topic questions — food safety
  inspections, workers' compensation, tax withholding, vehicle fuel efficiency — sanity-checked for
  zero literal keyword overlap with the corpus before labeling). Honest caveat, same shape as
  WP-35.1/35.2's own: 16 queries is a real, hand-verified baseline, not a large or statistically
  confident one — expected to grow over time.
- **The harness ran against the real, unmodified `reqbot ask` retrieval path** (production defaults:
  HyDE on, query rewrite on, `top_k=20`, `min_score=0.02`) — full results in
  `eval/spike_results/wp_37_1/results.json`/`report.md`.
- **Narrow queries: strong.** Mean recall@5 across the 7 narrow queries is 0.9643 (6/7 exact at 1.0;
  the 7th, the fragmented trusted-supplier procurement clause, reaches recall@10=1.0). Mean MRR is
  1.0 across all 7 — every narrow query's best answer came back at rank 1.
- **Broad queries: substantially weaker.** Mean recall@5 across the 5 broad queries is 0.2626,
  recall@10 is 0.3735, recall@20 is 0.5509, mean MRR is 0.6667 — even at the CLI's full `top_k=20`,
  the system finds barely half of the genuinely relevant requirements for a broad/thematic question
  on average (per-query recall@20 range: 0.38–0.88). This is a real, now-quantified version of
  exactly the concern that started this phase.
- **Zero-truth queries: the system never reports "no relevant results."** All 4 deliberately
  off-topic queries (food safety, workers' comp, tax withholding, vehicle fuel efficiency) returned
  the full 20 results, with top scores of 0.55–0.64 for the food-safety query specifically — not
  obviously distinguishable from a real match by score alone (the broad queries' own scores at their
  correct answers' ranks are in a comparable range). Checked directly what came back for the
  food-safety query: generic
  "security education and training program" / "self-inspection reports" records, related only by
  loose word overlap ("inspection," "program") that the query-rewrite step's LLM expansion actively
  helped bridge. Confirms, with real numbers, the previously-only-suspected RRF-score-floor gap
  documented in prior-session notes: nothing in the current pipeline can distinguish "a good match"
  from "the least-bad thing available."
- Overall aggregate across all non-zero queries: mean recall@5=0.6719, recall@10=0.739,
  recall@20=0.8129, MRR=0.8611 — a healthy-looking blended number that **hides** the narrow/broad
  split above. Reporting only the aggregate would have been misleading; both this project's own
  "verify before applying" discipline and the raw per-query table in `report.md` are why the split
  got caught and reported instead.

---

### WP-37.2 — Contextual Chunk Embeddings

**Source:** Anthropic's published Contextual Retrieval technique; the concrete gap found in
`pipeline/embed_and_index.py` while scoping this phase (Phase Framing above). Depends on WP-37.1.

**Problem:** `build_embedding_text()` embeds only the bare `source_quote` — no document, section, or
surrounding context — for both the dense and sparse vectors, despite that context already being
captured and stored per requirement. Short, decontextualized regulatory clauses are exactly the shape
Anthropic's research found this hurts most.

**Scope:**
- Add a situating-context prefix to the text passed into both `embed_batch()` (dense) and
  `embed_sparse_batch()` (sparse) — built from metadata already on the requirement record: document
  title (`source_pdf`), `section_title_path`, and `parent_context` where present. Exact format to be
  worked out against real examples (short and dense, not a restatement of the whole quote) rather than
  guessed up front.
- Keep `source_quote` itself (and the Qdrant payload generally) completely unchanged — this only
  changes what text gets *embedded*, not what's stored, displayed, or cited. `build_embedding_text()`
  already exists as the single seam for this; extend it, don't bypass it.
- Full reindex required (embedding text changes for every existing point) — use the existing
  `reqbot reindex` path (embedding-only, no re-extraction, atomic alias-swap per
  `docs/OPERATIONS.md`), not a new mechanism.
- Re-run WP-37.1's exact harness (same queries, same labels) against the new index and report the
  real delta — recall@k and MRR, before vs. after, per-query where it moved and where it didn't, not
  just the aggregate.
- If the result is a regression on some query shapes and an improvement on others, report that
  honestly rather than only the net number — matches this project's own "verify before applying"
  discipline extended to a phase's own conclusion, not just its inputs.
- **Control for HyDE sampling noise before trusting the delta (Codex review, PR #177, verified real):**
  `core.ask.generate_hyde_hypothesis()` samples at `temperature=0.3` with no seed, so HyDE's third RRF
  leg differs slightly between any two runs of the same query against the same index — a single-run
  before/after delta could partly reflect this instead of the embedding change under test. Either run
  the comparison with `--no-hyde` (isolates the change being measured, at the cost of not reflecting
  real `hyde=True` production behavior) or run N≥3 repeats per side and compare distributions, not
  single point estimates. Not fixed by caching/seeding HyDE in `core/ask.py` itself — that's a change
  to production retrieval logic, out of both WP-37.1's and WP-37.2's own Non-Goals.

**Non-goals:**
- No LLM-generated per-chunk context (see Phase Non-Goals) — deterministic, metadata-based context
  only, for this WP.
- No change to `source_quote`, the requirement schema, or anything downstream of retrieval (checklist
  generation, evidence display, synthesis prompts) — this is scoped to the embedding-text seam only.

**Tests/verification:**
- Unit tests for the new context-prefix builder: correct output for a record with full
  `section_title_path`/`parent_context`, correct (graceful, not crashing) output for a record missing
  some or all of that metadata (older pre-WP-14.2/14.3 artifacts, if any remain reachable).
- Full `pytest` suite passes; `ruff check .` clean.
- Live re-verification: WP-37.1's harness re-run against the reindexed corpus, real before/after
  numbers reported, not assumed.

**Gate:** The harness shows a real, measured recall@k/MRR delta (whatever direction it actually is)
against the exact same labeled query set WP-37.1 established; no regression in extraction-side tests;
`reqbot ask` manually exercised against a few real questions post-reindex to confirm results still
look sane, not just that the numbers moved.

**Findings (2026-07-31) — negative result, reverted, not deployed:**

- **Implemented and unit-tested** `build_context_prefix()`/extended `build_embedding_text()` in
  `pipeline/embed_and_index.py` exactly per Scope: document title + `section_title_path` as a header
  line, plus a word-boundary-truncated (100-char cap) `parent_context` excerpt — deterministic,
  metadata-only, no LLM call. Naive sentence-boundary splitting (on `". "`) was tried first and
  rejected before writing any code: this corpus's DoD/AF documents are full of numbered outline
  markers (`"1.4.1. Establish... 1.4.2. Provide..."`) that a period-based split mis-splits on, so
  truncation is word-boundary-only.
- **Controlled before/after comparison, following this WP's own Scope guardrail against HyDE noise
  (Codex review, PR #177):** ran WP-37.1's exact harness with `--no-hyde` against both the old
  (bare-`source_quote`) index and the new (contextual-prefix) index — same queries, same labels, only
  the embedded text differs. Real numbers, `eval/spike_results/wp_37_2/{before,after}_no_hyde/`:

  | Metric | Before | After | Δ |
  |---|---|---|---|
  | Mean recall@5 | 0.6683 | 0.5800 | **−0.0883** |
  | Mean recall@10 | 0.7118 | 0.6503 | **−0.0615** |
  | Mean recall@20 | 0.7523 | 0.7220 | **−0.0303** |
  | Mean MRR | 0.8542 | 0.7217 | **−0.1325** |

  Every aggregate metric regressed. Also ran production defaults (`hyde=True`) on both sides for a
  realistic-behavior cross-check: WP-37.1's original baseline (recall@5=0.6719, MRR=0.8611) vs. this
  WP's after-state (recall@5=0.58, MRR=0.8264) — same direction, same rough magnitude. The regression
  is consistent whether or not HyDE noise is controlled for, so it isn't an artifact of that risk.
- **Per-query breakdown (`--no-hyde`, the controlled comparison): 11 of 12 non-zero queries got worse
  or stayed flat (5 regressed, 6 held flat), 1 was genuinely mixed, 0 improved outright** (corrected
  after Codex + Gemini review, PR #178 — the original draft of this Finding wrongly lumped Q-B04 in
  with the pure regressions, and then a follow-up fix mis-summed the regressed+flat total as 10
  instead of 11; both caught by review, not self-caught, recounted directly against the saved
  `results.json` files to confirm). All 7 narrow queries held roughly steady (6 exactly flat, one dip:
  Q-N01's recall@5 1.0→0.5, recovering to 1.0 by recall@20). 4 of 5 broad queries regressed outright,
  two severely (Q-B02: MRR 0.25→0.0769; Q-B05: MRR 1.0→0.3333). **Q-B04 is mixed, not a regression**:
  recall@10 actually rose (0.3333→0.4) while recall@20 fell (0.4667→0.4) and recall@5/MRR stayed flat
  (0.2/1.0 both runs) — reported honestly as mixed rather than folded into "regressed," per this WP's
  own Scope commitment to report per-query movement accurately.
- **A verified, evidenced example consistent with the regression hypothesis — not an unretrieved
  record, and not claimed as a proven causal mechanism (corrected after Codex review, PR #178: the
  original draft cited `REQ-0b553500baf4`, which checking the actual `retrieved_ids` arrays directly
  shows never appeared in either run's top-20 at all — a real error, caught and fixed, not silently
  dropped).** Q-B02's ("firewalls and boundary protection devices") relevant record
  `REQ-e41d286c83f4` (afi17-203) is confirmed present in the *before* run at rank 4
  (`eval/spike_results/wp_37_2/before_no_hyde/results.json`) and confirmed *absent* from the *after*
  run's full top-20 (direct set-membership check against both saved `retrieved_ids` arrays). Its
  quote is genuinely on-topic ("modifying network access controls (e.g., firewall)..."); its new
  prefix is `"afi17-203 — Actions > 3.7.2. Methodology."` plus a `parent_context` excerpt about
  *"containment actions to regain control of or isolate the system..."* — describing incident-response
  *methodology*, not the firewall/boundary-protection *topic* the quote itself is about. This is
  consistent with the hypothesis that section-heading/parent_context metadata in this corpus often
  describes procedural framing rather than topical content (DoD/AF documents are organized around
  structure like `"SECTION 2: RESPONSIBILITIES"`, `"3.7.2. Methodology"`, `"1.2. POLICY"` rather than
  topic) — but this single example, like any single example in a hybrid RRF system with many
  simultaneously-changed candidates, cannot fully isolate causation on its own (Codex's point,
  accepted as valid). Treat the mechanism as a well-evidenced hypothesis explaining the measured
  aggregate regression, not a proven root cause.
- **Reverted, not merged into production.** `pipeline/embed_and_index.py` restored to its pre-WP-37.2
  form (`git checkout main -- pipeline/embed_and_index.py`); its own unit tests removed with it (dead
  code otherwise); the live Qdrant index reindexed back to the bare-`source_quote` embeddings and
  confirmed at 1,876/1,876 points. `reqbot ask` manually re-exercised post-revert against a real
  question ("What are the encryption requirements for protecting data?") — five on-topic, sensibly
  ranked results, sane behavior confirmed. This phase's Gate only requires a real, honestly-reported
  delta "whatever direction it actually is" — it does not require shipping a change that measurably
  makes retrieval worse.
- **This is still a real, useful result, not a wasted WP.** It rules out the cheap, free version of
  contextual embeddings for this specific corpus and gives a concrete, evidenced reason why (procedural
  vs. topical document structure) rather than a vague "didn't help." That reason specifically argues
  *against* naively scaling straight to Anthropic's full LLM-generated-context technique next, since an
  LLM given the same section-heading/parent_context inputs could make the same mistake — a future
  attempt needs the LLM prompt to explicitly recognize and skip procedural/administrative framing, not
  just summarize whatever surrounding text exists. See `docs/TODO_future_improvements.txt` for the
  backlog item.

---

## 5. Success Gate

- [x] Qdrant's live index matches the full processed corpus (confirmed via `reqbot status` vs.
      `reqbot docs`), not the 173/1,876-point drift found while scoping this phase.
- [x] A committed, hand-verified retrieval-quality labeled query set exists, with a documented
      baseline (recall@k, MRR) against current production `reqbot ask` behavior.
- [x] Contextual chunk embeddings were implemented, unit-tested, and the corpus was reindexed with
      them for real measurement — **not** left deployed: the measured result was a real regression, so
      the code was reverted and the live index restored to bare-`source_quote` embeddings (WP-37.2
      Findings). This gate is about honest measurement, not about a change surviving contact with data.
- [x] A real, honestly-reported before/after delta exists on the exact same query set, controlled for
      HyDE sampling noise — the delta pointed negative, reported as such, not reframed as a partial win.
- [x] Full `pytest` suite and `ruff check .` clean; `reqbot ask` manually exercised both post-change
      (mid-experiment) and post-revert (final state) to confirm sane behavior throughout.

## 6. Guardrails

- No claim about retrieval quality — this phase's or a future one's — ships without being checked
  against the real harness first. This phase exists because that harness didn't exist at all; don't
  let it ship without one either.
- Don't conflate this with extraction-quality work. If something looks like an extraction problem
  while working on this phase, note it in `docs/TODO_future_improvements.txt` and move on — it
  belongs in a Phase 32-35-style extraction fix, not here.
- The labeled query set's ground truth must be hand-verified against real corpus text, the same
  discipline as `eval/gold_description_grounding.jsonl` — an LLM-generated label is a candidate to
  check, never an accepted answer on its own.
- One change at a time, one measurement at a time (WP-37.2's context prefix, evaluated alone against
  WP-37.1's fixed baseline) — don't bundle in a reranker or other backlog experiment just because it's
  adjacent; each gets its own isolated before/after or the numbers stop meaning anything.
