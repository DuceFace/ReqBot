# ReqBot Phase 37 — Retrieval Quality: Eval Harness & Contextual Chunk Embeddings

**Status:** Locked (drafted 2026-07-31; source: direct conversation with Tyler after Phase 36
closed — see Phase Framing below)
**Date:** 2026-07-31
**Preceded by:** Phase 36 (Entailment-Gate Calibration Fix: Exact-Match Short-Circuit) — WP-36.1
complete, WP-36.2 deliberately deferred as backlog (`docs/PHASE36_REQUIREMENTS.md`).
**Followed by:** None currently planned.

---

## Status

This table is the live source of truth for Phase 37 WP status — update it here when a WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-37.1 — Retrieval-Quality Eval Harness (Baseline) | Not started |
| WP-37.2 — Contextual Chunk Embeddings | Not started |

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

---

## 5. Success Gate

- [ ] Qdrant's live index matches the full processed corpus (confirmed via `reqbot status` vs.
      `reqbot docs`), not the 173/1,876-point drift found while scoping this phase.
- [ ] A committed, hand-verified retrieval-quality labeled query set exists, with a documented
      baseline (recall@k, MRR) against current production `reqbot ask` behavior.
- [ ] Contextual chunk embeddings are implemented and the corpus is reindexed with them.
- [ ] A real, honestly-reported before/after delta exists on the exact same query set — whatever
      direction it actually points.
- [ ] Full `pytest` suite and `ruff check .` clean; `reqbot ask` manually exercised post-change.

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
