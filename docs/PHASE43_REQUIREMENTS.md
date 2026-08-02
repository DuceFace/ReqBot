# ReqBot Phase 43 — Reranker Spike

**Status:** Complete — measured, **No-Go** on shipping FlashRank as configured. Tested both the
default `ms-marco-TinyBERT-L-2-v2` and the larger `ms-marco-MiniLM-L-12-v2`; neither clears the
gate. No default changed; see §11 Findings.
**Date:** 2026-08-02
**Preceded by:** Phase 42 (Table-Structure-Aware Serialization) — `docs/PHASE42_REQUIREMENTS.md`,
complete. This phase picks up the reranker recommendation carried forward from Phase 40's §8
Backlog and reaffirmed in Phase 41 and Phase 42's own backlog notes — see §1 below.
**Followed by:** Not decided. §11's Backlog names one remaining concrete next step (escalate to a
full cross-encoder — a new dependency, its own stop-and-ask conversation) plus the pre-existing
Evidence/Compare and WP-15.9 items from §3/§7 — none started, no decision made on which (if any)
to pick up next.

---

## Status

| WP | Status |
|---|---|
| WP-43 — Reranker Spike | Complete — measured No-Go, no default changed |

---

## 1. Phase Framing

Phase 40's failure-mode audit of the 45-query gold set found `over_grab` (42 occurrences — the
single largest finding of any kind, spread across 19 queries) and `ranking_miss` (17, or 8
excluding one heavy query, `Q-B05`) as the two largest categories: cases where the correct
requirement is retrievable but not well-ranked, or a wrong one displaces it in the final top-k.
WP-40's own conclusion: "a reranker is the best-evidenced single lever" — deferred to backlog
rather than built, pending its own scoping conversation.

Phase 41 swept 11 `min_score` thresholds (0.02–0.5) against the same gold set specifically to see
whether a threshold could fix zero-truth (deliberately off-topic) queries confidently returning
irrelevant results. Finding: **0 of 8 zero-truth queries correctly returned empty at any threshold
tested, including 0.5.** Off-topic queries' top scores ranged 0.5–1.07 (e.g. `Q-Z03`, "federal tax
withholding") — routinely *higher* than genuine weak matches (`Q-B05`'s relevant results scored
0.033–0.09). The score distributions are inverted, not merely overlapping, so no threshold on the
RRF-fused score can separate them. Phase 41's conclusion: "the real fix needs a calibrated
absolute-relevance signal (e.g. a cross-encoder reranker's own confidence score), not a threshold
on an already-fused ranking score" — strengthening rather than replacing WP-40's recommendation.

Phase 42 then produced a concrete, current example of `ranking_miss` in the live corpus: after
WP-42's table-serialization fix made `Q-T02`'s correct records extractable for the first time, the
query still scores 0 recall@20 in production. Checked directly with `core.ask.retrieve(top_k=100,
min_score=0)`, the correct records are present, correctly grounded, and verbatim — ranked
33rd/51st/69th/87th of 100, entirely outside production's `top_k=20`. Phase 42 explicitly flagged
this as "WP-40's own dominant, already-deferred-to-the-reranker finding," out of scope for that WP.

This is the third phase in a row to surface or reaffirm the same recommendation without acting on
it. This phase is that scoping conversation, turned into an implementation plan.

Prior planning already exists and this phase follows it rather than redesigning from scratch:
`docs/TODO_future_improvements.txt`'s "Retrieval Experiments" §1, and the fuller architecture
writeup in `archive/PHASE15_EXTENSION_RETRIEVAL_HARDENING.md` (WP-15.5), which specified the
candidate-pool-then-rerank architecture, the FlashRank-first library choice, and explicit
reject-if criteria.

**Scope discipline:** this is a measurement-gated spike, not a change that ships default-on.
`rerank` defaults to `False` everywhere it's added in this phase; production retrieval behavior is
unchanged unless and until a future decision, informed by this phase's measured results, turns it
on.

## 2. Goals

1. Resolve, explicitly and up front, whether this phase touches only the Ask/Search retrieval path
   (`core.ask.retrieve()`) or first centralizes the duplicated retrieval logic in Evidence/Compare —
   see §4.
2. Build a local reranker as a reusable, retrieval-agnostic component and wire it into
   `core.ask.retrieve()` behind an opt-in flag.
3. Measure it against the 45-query gold set (`eval/gold_retrieval_queries.jsonl`): Precision@5,
   Recall@5/10/20, MRR, zero-truth score behavior, and latency — baseline vs. reranked.
4. Produce a go/no-go recommendation from that data. Do not flip any default in this phase
   regardless of outcome.

## 3. Non-Goals

- **Evidence/Compare reranking.** Both `services/evidence_service.py:build()` and
  `services/compare_service.py:compare()`'s semantic path independently reimplement dense+sparse
  embed and RRF `query_points()` rather than calling `core.ask.retrieve()` — confirmed by direct
  code inspection (see §4). Neither currently has fusion headroom past `top_k` for a reranker to
  reorder within (`query_points(..., limit=top_k)` directly, no separate pool size). Extending
  reranking to them is a named follow-up WP, not silently assumed here — see §7.
- **WP-15.9's corrective retrieval gate** (replacing `min_score` with the reranker's own score as
  the zero-truth confidence signal). Explicitly depends on this phase's output; this phase reports
  the evidence (does `rerank_score` separate zero-truth from real matches better than RRF score
  did?) but does not implement the gate itself.
- **WP-15.8 multi-vector retrieval** — unrelated backlog item, not touched here.
- **Any CLI/API/GUI-facing exposure of `rerank`.** Internal/eval-only for this phase, matching
  WP-15.5's original scope note ("do not add this to GUI or API scope yet").
- **Flipping any default to `True`.** Regardless of measured results, that is a distinct future
  decision made after Tyler reviews this phase's report — not assumed by this plan.

## 4. Architecture Decision (resolved up front, per Tyler's explicit request)

`core.ask.retrieve()` is **not** a shared retrieval choke point today. Direct inspection of all
three retrieval call sites found:

| Logic | Ask (`core/ask.py`) | Evidence (`services/evidence_service.py`) | Compare (`services/compare_service.py`) |
|---|---|---|---|
| Dense embed | `:628-629` | `:246-252` (own copy) | `:150-156` (own copy) |
| Sparse (BM25) embed | `:656-661` | `:255-263` (own copy) | `:158-166` (own copy) |
| Filter build | `:101-144` (`build_query_filter`) | `:266-279` (inline, different fields) | `:168-178` (inline) |
| RRF `query_points()` | `:704-710` | `:284-299` (own copy) | `:181-198` (own copy) |
| `min_score` threshold | `:714-720` | absent | absent |
| Candidate pool past `top_k` | `fusion_limit` widened when `min_score>0` | `limit=top_k` directly — no headroom | `limit=top_k` directly — no headroom |
| HyDE / query rewrite | `:610-652` | none | none |

Evidence and Compare each independently reimplement the same hybrid-search shape rather than
calling `retrieve()`, and neither has the candidate-pool headroom a reranker needs to reorder
within.

**Decision (confirmed with Tyler): build the reranker as a standalone, retrieval-agnostic module
and wire it into `core.ask.retrieve()` only for this phase.** Evidence and Compare are explicitly,
deliberately left unreranked — named as a scoped follow-up (§7), not silently deferred the way this
same recommendation has already been deferred three times (Phase 40 → 41 → 42).

Rationale: the reranker module (`rerank(query, candidates, top_k) -> candidates`) never assumes
who fetched its candidates, so wiring it into Evidence/Compare later is a plumbing change, not a
rewrite. This avoids taking on the larger regression surface of refactoring two live production
call sites (Evidence and Compare are used today, in the GUI and via MCP) inside the same phase as
the actual measurement work, and matches WP-15.5's own original scope note: "Do not add this to
GUI or API scope yet."

The alternative considered — centralizing the duplicated hybrid-search core across all three paths
first, then adding reranking uniformly — was rejected for this phase specifically because of scope
and risk, not because it's wrong: it does resolve a real, pre-existing violation of this project's
"business logic gets written once" architecture principle, and remains a reasonable direction for a
future WP once reranking itself has cleared its measurement gate.

## 5. New Dependency (stop-and-ask)

Per the project's private agent-docs guide, a new dependency is a conversation, not a unilateral
call — flagging explicitly: this phase proposes **FlashRank** (lightweight, ONNX-based, no `torch`
requirement — the same shape as `fastembed`'s existing BM25 model, downloading a small model to a
local cache on first use). This matches existing project guidance in both
`docs/TODO_future_improvements.txt` and the archived WP-15.5 writeup: "start with FlashRank for
speed, escalate to a cross-encoder only if FlashRank precision is insufficient." Proposed as a new
optional extra in `pyproject.toml` (mirroring `remote`/`mcp`/`grounding-check`) —
`rerank = ["flashrank>=0.2.0"]` — kept out of the base install while this remains an opt-in spike.
If it later graduates to default-on, moving it into base dependencies is a separate follow-up call.

## 6. Implementation Plan (not started — see §8 Process)

1. **`core/reranker.py`** (new): `rerank(query: str, candidates: list[dict], top_k: int) ->
   list[dict]`. Takes result dicts shaped like `retrieve()`'s existing `results` entries, scored
   against `description` + (`embedding_text` if present, else `source_quote`) — **not** bare
   `source_quote` unconditionally. Codex review (PR #190) caught that scoring only
   `description + source_quote` would discard the governing context WP-39.2's parent-stem
   reconstruction deliberately prefixes onto `embedding_text` for fragment-shaped quotes (e.g. a
   dangling `"(3) Restrain competition."` with no visible list-introducing clause). Without it, the
   8 `parent_child_context` gold-set queries could have their correct hits reach FlashRank as
   context-free fragments and get demoted, producing a false no-go result — `parent_stem`/
   `embedding_text` are already carried on `retrieve()`'s result dicts (`core/ask.py` already reads
   `hit.get("parent_stem")` for display, `pipeline/embed_and_index.py:build_embedding_text()`
   establishes the same `embedding_text`-over-`source_quote` precedence at index time; this mirrors
   it at rerank time for consistency). Returns the top_k reordered with a new `rerank_score` field
   attached. FlashRank imported lazily inside the function so importing this module doesn't
   hard-fail without the `rerank` extra installed; a clear error is raised only when `rerank=True`
   is actually requested without it.

2. **`core/ask.py`'s `retrieve()`**: add `rerank: bool = False` and `rerank_pool_size: int = 100`.
   When `rerank=True`:
   - Widen `fusion_limit` unconditionally to `max(rerank_pool_size, top_k)`, decoupled from
     `min_score` entirely (today, `core/ask.py:676`'s `max(top_k * 3, 50) if min_score > 0 else
     top_k` only widens when `min_score` is set, which a reranker can't rely on). **Codex review
     (PR #190) caught that the original `max(top_k * 3, 50)` proposal — 60 at the harness's
     `top_k=20` default — is too shallow for this very doc's own motivating example**: Q-T02's
     known-relevant records sit at ranks 33/51/69/87 (§1); a pool of 60 would never let the
     reranker see two of the four. `rerank_pool_size` is a first-class, independently configurable
     spike parameter (not derived from `top_k`) defaulting to 100 — enough margin over Q-T02's
     worst known case — and the harness (§6.3) sweeps it rather than treating 100 as
     self-evidently correct. This supersedes the archived WP-15.5 writeup's "N > k, e.g. 40-50"
     guidance, which predates Q-T02's concrete evidence (Phase 42).
   - Skip the existing pre-rerank `min_score` filter (`core/ask.py:714-720`) — Phase 41 already
     showed the RRF score threshold isn't a reliable relevance signal; filtering on it before
     reranking would reintroduce the problem the reranker exists to fix. Call `rerank()` on the
     full fused pool, trim to `top_k` by `rerank_score` after.
   - `rerank_score` flows through into each result dict alongside the existing `score` field.

3. **`eval/retrieval_eval_harness.py`**:
   - Add `--rerank` CLI flag / `rerank: bool = False` param, plus `--rerank-pool-size` /
     `rerank_pool_size: int = 100` param on `run_harness()`, passed to `retrieve()`. The
     measurement run (§10) sweeps at least two pool sizes (e.g. 50 and 100) rather than trusting
     the default in isolation — Codex review (PR #190) flagged that a single untested pool size
     could silently produce a "no improvement" result that's actually just a too-shallow pool, not
     evidence against reranking itself.
   - Add **Precision@5** to `compute_metrics()` — not currently computed (only recall@k and MRR
     exist today), but the primary gate metric per both Tyler's ask and
     `docs/TODO_future_improvements.txt`'s existing gate criteria:
     `precision@5 = |relevant ∩ top_5| / 5`.
   - `rerank_score` reporting: record each returned result's `rerank_score` in `per_query` output
     for **every** query, not only the 8 `shape == "zero"` ones. Codex review (PR #190) caught that
     the original zero-truth-only reporting couldn't actually support the plan's own §9 claim of
     checking whether `rerank_score` "separates off-topic from genuine-weak-match" — separation is
     a two-sided comparison, and weak-match evidence (e.g. `Q-B05`'s real matches, RRF-scored
     0.033–0.09 per Phase 41) requires the same score capture on the positive side. The Findings
     write-up (item 5 below) compares zero-truth vs. weak-match vs. strong-match `rerank_score`
     distributions directly, not zero-truth in isolation.
   - Latency: record wall-clock ms per query (`retrieve()` already returns `retrieval_ms`), report
     mean/p95 for baseline vs. reranked runs.

4. **`pyproject.toml`**: add the `rerank` optional extra (§5).

5. **This document**: fill in a Findings section with the live measurement results, the go/no-go
   decision against §8's gate, and flip Status to Complete once merged.

### Tests

- `tests/unit/test_reranker.py` (new): `rerank()` reorders a synthetic candidate list by relevance,
  attaches `rerank_score`, respects `top_k`, and raises a clear error (not a bare import traceback)
  when FlashRank isn't installed. Includes a `parent_child_context` case (Codex review, PR #190):
  a candidate with a dangling-fragment `source_quote` and a governing-clause-prefixed
  `embedding_text` scores using `embedding_text`, not the bare fragment.
- `tests/unit/test_ask_reranker.py` (new, or folded into `test_ask_run.py`): `retrieve(rerank=True)`
  widens the pool regardless of `min_score`, skips pre-rerank `min_score` filtering, calls the
  reranker module (mocked — no FlashRank install needed to run these), and `rerank=False` (default)
  is byte-for-byte unchanged from current behavior.
- `tests/unit/test_retrieval_eval_harness.py` (extended): Precision@5 computation including the
  fewer-than-5-results edge case, `--rerank` flag plumbing, zero-truth score reporting.

## 7. Backlog (follow-up work, named so it doesn't evaporate again)

- **Evidence/Compare reranking.** Prerequisite: give both paths `fusion_limit` headroom past
  `top_k` (they currently call `query_points(..., limit=top_k)` directly). Once WP-43's reranker
  module clears its own gate, wiring it into Evidence/Compare is expected to be a plumbing change
  against the already-built, retrieval-agnostic `core/reranker.py`, not a rewrite.
- **WP-15.9 corrective retrieval gate** — depends on this phase's zero-truth score-behavior
  findings.
- Centralizing the duplicated hybrid-search core across Ask/Evidence/Compare (§4's rejected
  alternative) remains a reasonable direction independent of reranking, if the project wants to
  resolve the underlying "business logic written once" violation directly.

## 8. Process — plan reviewed before implementation

Unlike prior phases, this plan itself goes through the normal Codex/Gemini PR review cycle before
any implementation code is written:

1. Branch `wp-43-reranker-spike` off `main` (done).
2. This document, plan-only, as the first commit — no `core/`, `eval/`, or `pyproject.toml`
   changes yet.
3. Open a PR, let Codex and Gemini review the plan itself.
4. Address findings on the plan by revising this document; still no implementation code.
5. Stop and wait for Tyler's explicit approval of the reviewed plan — a clean automated review of
   the plan doc is not, by itself, approval to start building.
6. Only after that approval: add the implementation commits from §6 to the same branch/PR, which
   then goes through its own normal review pass. Run the live measurement, fill in results, flip
   Status to Complete once merged.

## 9. Success Gate / Decision Criteria

- Precision@5 improves on the 45-query gold set.
- No regression on Recall@5/10/20/MRR versus current baseline.
- Zero-truth queries: document whether `rerank_score` separates off-topic from genuine-weak-match
  better than the RRF score did (Phase 41's finding). Not required to fully solve zero-truth in
  this phase (that's WP-15.9, out of scope here) — just to report the evidence.
- Latency acceptable for interactive CLI/GUI use — measured and reported, not hard-gated to a
  specific number (matches WP-15.5's original criterion).
- Regardless of results, no default flips to `True` anywhere in this phase.

## 10. Verification

- `pytest` full suite green, `ruff check .` clean.
- Fully reversible by construction, more so than Phase 42: `rerank` defaults to `False` everywhere,
  and this phase makes no ingestion/indexing/Qdrant/JSONL changes at all — a pure query-time
  addition. There is nothing to revert beyond not passing `rerank=True`.
- Live measurement run against the real 45-query gold set and live Qdrant/Ollama: baseline
  (`--rerank` omitted) vs. reranked, comparing Precision@5, Recall@5/10/20, MRR, `rerank_score`
  behavior across zero-truth/weak-match/strong-match queries, and latency. This is the deliverable
  Tyler asked for — the go/no-go decision is made from this data, not assumed.
- **Both arms run with `--no-hyde`.** Codex review (PR #190) caught that the harness's own file
  header (`eval/retrieval_eval_harness.py:21-32`) already documents `generate_hyde_hypothesis()`
  sampling at `temperature=0.3` with no seed, so HyDE's third RRF leg differs between separate runs
  of the same query — a single-run baseline-vs-reranked delta could partly reflect HyDE sampling
  noise rather than the reranker's actual effect. `--no-hyde` for both arms isolates the variable
  under test (at the cost of not reflecting default `hyde=True` production behavior). If time
  allows, a secondary `hyde=True` run repeated N≥3 times per arm (comparing distributions, not
  single points) can corroborate the `--no-hyde` result, but isn't required to reach a decision.

## 11. Findings

Implemented per §6 exactly as planned (`core/reranker.py`, `retrieve(rerank=..., rerank_pool_size=...)`,
harness `--rerank`/`--rerank-pool-size`/Precision@5/latency/per-query `rerank_score`), all unit
tests green (`pytest`, `ruff check .` both clean), then measured live against the real 45-query
gold set and live Qdrant/Ollama (`grc_requirements` at 1848 points), `--no-hyde` on both arms per
§10, FlashRank's default `ms-marco-TinyBERT-L-2-v2` model, swept `rerank_pool_size` at 50 and 100.

### 11.1 Aggregate results

These artifacts were regenerated three times over the course of this PR's review (§6.3's
config-recording fix, then again after §6's `source_ref` fix), each time against the same,
unchanged corpus (confirmed via `reqbot status` — same collection names, same 1848/839 point
counts throughout). The committed files reflect the final (third) run, current as of the latest
code. All three runs are reported here because the spread between them turned out to be a finding
in its own right — see the variance discussion below the table.

| Run | Precision@5 | Recall@5 | Recall@10 | Recall@20 | MRR | Mean latency | p95 latency |
|---|---|---|---|---|---|---|---|
| Baseline (no rerank) | 0.2629 (stable across all 3 runs) | 0.5402 (stable) | 0.6208 (stable) | 0.6693 (stable) | 0.6124–0.6267 | ~1750–1800ms | ~2350–2400ms |
| Reranked, pool=50 | 0.2514 (stable) | 0.5171–0.5237 | 0.5985 (stable) | 0.6537–0.6926 | 0.6264–0.6407 | ~1860–1920ms | ~2440–2550ms |
| Reranked, pool=100 | 0.2514–**0.2629** | 0.5187–0.5314 | 0.5995–0.6090 | 0.6613–0.6683 | 0.6297–0.6358 | ~2010–2030ms | ~2600–2625ms |

(MiniLM-L-12 is a separate model/config — see §11.6, not folded into this table.)

**Precision@5 — the primary gate metric — never exceeds baseline in any of the 9 (3 runs × 3
non-baseline configs) measurements taken**, and regresses in all but one (pool=100's third run tied
baseline exactly at 0.2629). Recall@5 and Recall@10 regress in every single measurement, every run,
both pool sizes — the most consistent finding in this entire spike. Recall@20 is the most volatile:
it improved over baseline in the first measurement cycle, then regressed in the third, for both
pool sizes. Latency increased consistently by roughly 5-15% at pool=100 across all three runs — not
itself gating (WP-15.5's "measure, don't hard-gate" criterion) but a real, repeatable cost for zero
repeatable benefit on the gate's primary metric.

**Run-to-run variance is larger than initially characterized, and is itself a real finding.** The
first regeneration (for §6.3's config-recording fix) showed only MRR shifting meaningfully run to
run, with Precision@5/Recall@5/10/20 stable — the note originally here characterized the variance
as narrow (MRR-only, small magnitude). The **second** regeneration (for §6's `source_ref` fix,
which does change reranker input text and so isn't purely a noise-isolation control) showed a much
larger spread: Recall@20 flipped sign entirely (from improving over baseline to regressing over
baseline, at both pool sizes), and pool=100's Precision@5 moved a full regression-vs-tie range.
`--no-hyde` and `rewrite_query()`'s `temperature=0.0` still rule out the two previously-known noise
sources (HyDE sampling, per this file's own header caution; non-deterministic rewrite) — the
remaining source is most likely Qdrant's HNSW dense-vector search, which is approximate and can
break near-ties differently between runs, compounded here by the `source_ref` text change itself
having some real (if apparently small) effect on reranker scoring. The two are not cleanly
separable from three data points.

**This does not change the qualitative conclusion** — Precision@5 and Recall@5/10 regressed in
*every* measurement across all three cycles, with no exceptions on Recall@5/10 and only one
tie (not an improvement) on Precision@5 — but it does mean single-run point estimates on this
45-query set are not precise enough to support fine-grained comparisons (e.g. "pool=50 vs.
pool=100" or the zero-truth separation analysis in §11.2, which flipped between runs — see below).
A rigorous future comparison should run N≥3 repeats per configuration and compare distributions,
the same discipline WP-37.2's original HyDE caution already recommended for a different reason.
Documented as a second caution in `eval/retrieval_eval_harness.py`'s own module docstring.

### 11.2 Zero-truth score separation — genuinely inconclusive on a single run

Directly answering Phase 40/41's backlog note (evaluate the reranker's confidence output against
the 8 zero-truth queries specifically). This section changed twice during review, and the second
change is the more important one:

**Round 1** pooled all 20 returned results per zero-truth query against only the top-5 per real
query — an apples-to-oranges comparison at different depths, and not the statistic a corrective
gate would actually threshold. **Codex review (PR #191) caught this**; redone as **per-query
maximum `rerank_score`**, which on that run showed the two ranges not overlapping, by a margin of
0.0007 (zero-truth ceiling 0.0246 vs. the weakest real query's own ceiling, `Q-N10`, at 0.0253) —
explicitly flagged at the time as "razor-thin... would very plausibly flip on a different query."

**Round 2**: regenerating the artifacts again for the `source_ref` fix (§6) reran the identical
measurement, and it *did* flip. In the current, final artifact:

| Bucket | n queries | min of per-query max | max of per-query max | mean of per-query max |
|---|---|---|---|---|
| Zero-truth | 8 | 0.0004 | **0.0256** (`Q-Z07`) | 0.0091 |
| Non-zero-truth (n=37 — every non-`zero`-shape query gets a `rerank_score`, including `Q-T04`/`Q-T05`, real on-topic content with no `requirement_id` to score recall against) | 37 | **0.0129** (`Q-N10`) | 0.9998 | 0.9224 |

`Q-N10` — a genuinely correct query (`recall@5=1.0`, its answer at rank 2) — now scores *below* the
zero-truth ceiling (0.0129 vs. 0.0256). The exact same query that sat 0.0007 *above* the zero-truth
ceiling in round 1 sits 0.0127 *below* it in round 2. Two runs of the identical experiment produced
opposite answers to "do the ranges overlap." Given §11.1's run-to-run variance finding, this isn't
surprising in hindsight, but it directly falsifies round 1's own "razor-thin but real" framing —
razor-thin margins on a single 45-query run aren't real margins at all, they're noise.

What *is* stable across both rounds: the **mean** (0.9245 round 1 [after Codex's separate
arithmetic-error fix] vs. 0.9224 round 2 — consistent), and the general **bimodal shape** (most real
queries score near-maximum confidence — 32 of 37 at 0.94+ in round 1, comparably in round 2 — while
a handful of genuinely correct queries score surprisingly low: `Q-T03`, `Q-C04`, and now `Q-N10`
too). The mean-level gap between zero-truth (~0.01) and real queries (~0.92) is large and appears
robust; the *boundary* behavior — whether the single worst real query beats the single best
zero-truth query — is not, at this sample size and run count.

**Revised conclusion: genuinely inconclusive on the specific question of whether a fixed threshold
would work**, though the underlying signal (mean-level separation) is real and still supports Phase
41's hypothesis that a calibrated per-candidate score is a fundamentally different kind of signal
than RRF's fused score (which Phase 41 found gives off-topic queries *higher* scores than genuine
weak matches outright, 1.07 vs. 0.033-0.09 — a problem no threshold could ever fix; here at least
the *typical* case separates cleanly). A future WP-15.9 scoping conversation needs its own N≥3-repeat
measurement before treating either "a threshold exists" or "the boundary case is thin" as settled —
neither is, on the evidence collected here.

### 11.3 Flagship case (Q-T02) — still not fixed, and why

Phase 42's motivating example was checked directly rather than assumed. Live, fresh check today
(not relying on Phase 42's original numbers, since the corpus has re-indexed since):
`core.ask.retrieve(query, top_k=200, min_score=0, hyde=False)` with the same query rewrite the
harness itself applies (`"AF critical asset identification process task critical assets
nomination approval"`) places Q-T02's three gold-labelled records at:

- `REQ-2d5b8006ec40` — rank 40 (RRF score 0.0487)
- `REQ-7758064f03f2` — rank 116 (RRF score 0.0170)
- `REQ-8864b3fc4a01` — **not present in the top 200 at all**

At `rerank_pool_size=100`, only the first of the three ever enters the candidate pool — the other
two are unreachable at any pool size in the range this spike tested. Inspecting the pool=100 run's
actual output for Q-T02: the reachable one (`REQ-2d5b8006ec40`, "HAF, MAJCOM/DRUs, FOAs... review/
validate nominated TCAs" — squarely on-topic for the query's "approving" half) still didn't crack
the reranked top 20. FlashRank instead gave near-maximum confidence (0.99, 0.99, 0.99, 0.98, 0.98,
0.98) to six candidates describing the CARM Program's general purpose and asset-prioritization
role — topically adjacent, plausible-sounding, but not the specific process-step content the query
actually asks for. This is a precise, concrete instance of the aggregate Precision@5 regression:
the reranker is confidently promoting near-miss generalities over an on-topic specific.

**Conclusion: reranking with FlashRank's default model does not fix the case that motivated this
WP.** Two-thirds of the failure is a pool-depth problem no tested pool size reaches; the reachable
third is a precision problem the default model doesn't solve.

### 11.4 Go/No-Go decision

Against §9's gate:
- ❌ Precision@5 improves — **failed** (never exceeded baseline in 9 measurements across 3
  configs × 3 runs; one tie, everything else a regression — §11.1).
- ❌ No regression on Recall@5/10/20/MRR — **failed** (Recall@5 and Recall@10 regressed in every
  single measurement, all runs, both pool sizes — the most consistent finding in this WP).
- ✅ Zero-truth score-separation evidence reported — **met** (the gate only requires reporting the
  evidence, not a clean result): the evidence itself turned out **genuinely inconclusive** on
  whether a fixed threshold would separate zero-truth from real queries (§11.2 — a "razor-thin"
  non-overlap in one run flipped to actual overlap on a rerun), though the underlying mean-level
  signal is real and stable across runs.
- ✅ Latency measured and reported, not hard-gated — **met** (a real, repeatable ~5-15% increase at
  pool=100 across all three runs, moot given the precision/recall gate failure).

**Decision: No-Go.** FlashRank's default `ms-marco-TinyBERT-L-2-v2` model, over either candidate
pool size tested, does not clear the bar this WP set before implementation started. Per §9 and
Tyler's explicit framing throughout this WP, **no default changes** — `rerank` stays `False`
everywhere; production Ask/Search behavior is exactly what it was before this WP, byte-for-byte
(confirmed by `test_rerank_false_default_never_calls_reranker` and this run's own baseline column
above). **Still No-Go after also testing a stronger model — see §11.6.**

This is not a failed WP — it is exactly the answer a measurement-gated spike exists to produce.
The infrastructure built here (the standalone `core/reranker.py` module, decoupled candidate-pool
sizing, the harness's Precision@5/latency/rerank_score instrumentation) is real, reusable, and not
wasted: a future attempt with a stronger model can reuse all of it and would only need to swap
which model `core/reranker.py`'s `Ranker()` construction points at.

### 11.5 Backlog (concrete next steps, not decided)

- ~~Try a stronger bundled FlashRank model before concluding reranking itself is not viable.~~
  **Done — see §11.6.** Tested `ms-marco-MiniLM-L-12-v2`: moved Recall@5/MRR in the right direction
  but didn't clear the gate either, at a much higher and consistent latency cost, and with a wide,
  stable zero-truth overlap (worse than TinyBERT's own flip-prone boundary case). Not worth testing
  FlashRank's other remaining bundled models (`ms-marco-MultiBERT-L-12`, `rank-T5-flan`) on the
  strength of this trend without a specific reason to expect a different outcome from them.
- **Escalate to a full cross-encoder** (e.g. via `sentence-transformers`) per the original WP-15.5/
  `docs/TODO_future_improvements.txt` guidance's explicit fallback path — a new, heavier dependency,
  its own stop-and-ask conversation. Any such follow-up should budget for N≥3-repeat measurement
  runs from the start, given §11.1's variance finding, rather than trusting single-run numbers.
- **Evidence/Compare reranking** — unchanged from §3/§7: still blocked on giving those paths
  candidate-pool headroom past `top_k`, and now additionally motivated less urgently given this
  spike's own models didn't clear the gate on the one path they were tried against.
- **WP-15.9 corrective retrieval gate** — §11.2's zero-truth separation result is genuinely
  inconclusive on the specific boundary question (it flipped between two runs of the identical
  measurement), though the mean-level signal is real and stable. A future scoping conversation
  needs its own N≥3-repeat measurement across a larger query sample before treating either "a
  threshold exists" or "the boundary is thin" as settled — neither is, on the evidence here.

### 11.6 Stronger model check: ms-marco-MiniLM-L-12-v2

Per §11.5's backlog, tested FlashRank's larger `ms-marco-MiniLM-L-12-v2` model (21.6MB vs.
TinyBERT's 3.26MB) — zero new dependency, `core/reranker.py`'s `model_name` parameter (added for
exactly this) is all that changed. Same methodology otherwise: `rerank_pool_size=100`, `--no-hyde`,
same 45-query gold set, same live corpus.

| Run | Precision@5 | Recall@5 | Recall@10 | Recall@20 | MRR | Mean latency | p95 latency |
|---|---|---|---|---|---|---|---|
| Baseline | 0.2629 | 0.5402 | 0.6208 | 0.6693 | 0.6124–0.6267 | ~1750–1800ms | ~2350–2400ms |
| TinyBERT, pool=100 | 0.2514–0.2629 | 0.5187–0.5314 | 0.5995–0.6090 | 0.6613–0.6683 | 0.6297–0.6358 | ~2010–2030ms | ~2600–2625ms |
| MiniLM-L-12, pool=100 | 0.2514 | **0.5456** | 0.5988 | 0.6653 | **0.6778** | **~6550–6730ms** | **~7930–7980ms** |

(Ranges reflect the three measurement cycles described in §11.1; MiniLM was only run once per
change, at the final/current code, so it has single values, not ranges.) MiniLM-L-12 is the
best-performing configuration on Recall@5 and MRR — Recall@5 clears baseline (0.5456 vs. 0.5402,
still a modest margin given §11.1's variance) and MRR improves meaningfully. Precision@5 (0.2514)
sits at the low end of TinyBERT's own observed range rather than beating it, and Recall@10/20 both
regress versus baseline — so this still does not clear §9's gate as written (a regression on any
one of Recall@5/10/20/MRR disqualifies, not a net average).

**Latency is the more serious, and more consistent, problem**: mean retrieval time roughly
quadrupled versus baseline (~1780ms → ~6550-6730ms across runs), p95 similarly (~2380ms →
~7930-7980ms) — the larger model's ONNX inference cost dominates and this delta held steady across
every measurement, unlike the accuracy metrics. TinyBERT's much smaller latency increase was
arguably tolerable; this isn't, for interactive CLI/GUI use.

**Q-T02 is still unfixed** with MiniLM too, the same shape of failure as TinyBERT, stable across
every run: its top picks are the same plausible-but-generic CARM-program candidates seen under
TinyBERT (`REQ-9a1f01a2d295`, `REQ-f78038d96493`, `REQ-95cbb901f073`, `REQ-70f62fcdd0cf` — reordered
among themselves, but the same small set), and the one reachable target (`REQ-2d5b8006ec40`, rank 40
in the RRF pool) never cracks the reranked top 20 under either model, in any run. Confirms the
failure is about which candidates reach the reranker at all (pool depth) and this specific
query/corpus content, not about either model's precision ceiling — the one finding in this entire
document that showed zero variance across all measurement cycles.

**Zero-truth separation**: on the final run, MiniLM's zero-truth ceiling is `Q-Z06` ("parking and
traffic enforcement on a military installation" — deliberately off-topic, keyword-overlapping on
"military installation") at 0.2629 — higher than several genuinely on-topic queries' own per-query
maxima (`Q-T03`: 0.1134, `Q-C04`: 0.1523), a wide, consistent overlap across every run measured for
this model. §11.2's revised conclusion (genuinely inconclusive for TinyBERT, given its own boundary
case flipped between runs) still holds a real distinction here: MiniLM's overlap is large and stable
across runs, not razor-thin and flip-prone the way TinyBERT's was. If anything's true about
model-size effects on this specific dimension, it's that MiniLM is consistently worse, not that
either model is reliably "clean."

**Conclusion: still No-Go**, and this specific stronger model isn't the answer either. It moves MRR
and Recall@5 in the right direction but trades away both latency and zero-truth calibration to get
there, doesn't actually beat TinyBERT on Precision@5, and still doesn't fix the motivating case.
This backlog question now has a real, measured answer rather than remaining open speculation.
