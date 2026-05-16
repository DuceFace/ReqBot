# ReqBot Phase 15 Extension — Retrieval Hardening

**Status:** DEFERRED — see docs/TODO_future_improvements.txt for backlog entries
**Date:** April 2026
**Predecessor:** Phase 15 HyDE spike (passed gate)

> **Decision (2026-05-16):** Retrieval stack is sufficient to proceed to Phase 16. These work packages
> are valuable but non-blocking. Deferred to post-Phase 18 or when a specific retrieval failure mode
> justifies revisiting. Do not begin implementation until Phase 18 GUI is complete and stable.

---

## 1. Executive Summary

Phase 15 validated HyDE as a meaningful retrieval improvement. That result is useful, but it does not mean retrieval work is finished.

ReqBot's retrieval stack is already stronger than a typical RAG system: structure-aware chunking, document hierarchy preservation, hybrid dense + sparse retrieval, RRF fusion, metadata filtering, raw context lookup, and now HyDE augmentation. The next gains should come from precision and coverage improvements that fit ReqBot's actual corpus and failure modes, not from adding generic RAG complexity.

This proposal recommends four retrieval-hardening work packages as a gated extension to Phase 15, with a strict time box to prevent scope creep before Phase 16 API work begins.

### What changed from the original proposal

This revision incorporates several decisions made during architectural review:

- **Index bloat is not a meaningful constraint at ReqBot's scale.** The corpus is ~32,000 requirements. Tripling index size to ~96K points has negligible impact on query latency (vector search is sublinear) and negligible impact on memory at 32GB RAM. Indexing cost is borne at ingest time, which is a tiny fraction of the workflow. All work packages should optimize for retrieval confidence, not index speed.
- **Multi-query retrieval and HyDE are converging strategies.** Rather than treating multi-query as a separate spike, it is folded into a single configurable "retrieval depth" concept alongside HyPE.
- **HyPE is not competing with HyDE — they are complementary.** HyPE provides pre-embedded question variants at index time (fast baseline). HyDE provides a query-specific hypothesis at runtime (catches what HyPE missed). Running both with RRF fusion and a reranker is the strongest retrieval stack available.
- **Corrective retrieval is built on reranker confidence scores**, not standalone heuristics. The reranker must ship first.
- **A time box prevents this extension from blocking Phase 16.**

---

## 2. Relationship to Forward Plan

- Phase 15 completed its original HyDE gate and established that retrieval quality is worth further investment before interface work dominates attention.
- Phase 16 depends on the retrieval path being worth wrapping in services and exposing through an API.
- This proposal does not reopen the HyDE decision. It builds on it.
- This proposal does not expand into agentic RAG, web search, or interface work.

If accepted, these work packages act as Phase 15 extension work, not Phase 16 scope.

---

## 3. Time Box

**Weeks 1–2:** WP-15.5 (reranker) and WP-15.8 (multi-vector). These are the highest-value, lowest-risk spikes and do not depend on each other.

**Week 3:** Evaluate results. If retrieval is strong enough, freeze Phase 15 and move to Phase 16. If gaps remain, run WP-15.6 (retrieval depth / HyPE) in parallel with early Phase 16 API scaffolding — they don't conflict architecturally.

**WP-15.9 (corrective gate):** Runs after the reranker ships, since it depends on reranker scores as its confidence signal. Can run in parallel with Phase 16.

If any spike runs past its allocated time without clear results, kill it and move on. The retrieval stack is already good. These extensions make it better, but none of them are blocking.

---

## 4. Work Package Summary

| WP | Title | Priority | Depends On |
|----|-------|----------|------------|
| WP-15.5 | Reranker | Do first | Nothing |
| WP-15.8 | Multi-Vector Retrieval | Do first (parallel with 15.5) | Nothing |
| WP-15.6 | Retrieval Depth + HyPE | Do if gaps remain | WP-15.5 results |
| WP-15.9 | Corrective Retrieval Gate | Do after reranker ships | WP-15.5 |

---

## 5. Design Philosophy

### 5.1 The Pipeline Is Still the Product

These work packages must improve retrieval quality, not increase architectural novelty.

### 5.2 Retrieval First, Framework Second

ReqBot should borrow retrieval ideas from the literature, not import LangChain-style abstractions or agent frameworks. Direct Python control over each retrieval stage is non-negotiable.

### 5.3 Optimize for Retrieval Confidence, Not Index Speed

Indexing is a one-time cost per document, borne at ingest time. The user never sees it. Query-time confidence is what matters. Index size is not a constraint at ReqBot's corpus scale (~32K requirements, 32GB RAM). Work packages should not compromise retrieval quality to minimize index footprint.

### 5.4 Add Stages Only When Failure Modes Justify Them

Each work package must correspond to a real retrieval failure mode:

- Reranking addresses low precision inside a good recall set
- Multi-vector addresses single-surface embedding blind spots
- Retrieval depth addresses narrow query framing and HyDE runtime cost
- Corrective retry addresses weak evidence sets that produce false confidence

If a work package does not clearly target one of those failure modes, it should not ship.

---

## 6. WP-15.5 — Reranker Spike

### 6.1 Goal

Determine whether a local reranker improves top-result precision after existing hybrid retrieval.

### 6.2 Rationale

ReqBot has a strong recall path: dense retrieval, BM25 sparse retrieval, optional HyDE augmentation, RRF fusion. What it does not yet have is a precision stage that reads the retrieved candidates more carefully and reorders them. The reranker is also the foundation for WP-15.9 — its scores become the confidence signal for corrective retrieval.

### 6.3 Architecture

```
query
  └─► existing hybrid retrieval (dense + sparse + optional HyDE)
          └─► top-N candidate set (N > final k, e.g. 40-50)
                  └─► reranker scores each candidate against query
                          └─► top-k final results (reordered by reranker score)
```

### 6.4 Scope

- Re-rank only the top candidate set from current retrieval
- Keep baseline retrieval intact underneath
- Evaluate a local reranker first — start with FlashRank for speed, escalate to a cross-encoder only if FlashRank precision is insufficient
- Do not replace RRF — the reranker sits after fusion, not instead of it
- Do not add this to GUI or API scope yet

### 6.5 Success Criteria

- Improves Precision@5 on the Phase 15 evaluation query set
- Produces no regressions on known-good baseline queries
- Adds acceptable latency for CLI use (measure, don't gate on a hard number)

### 6.6 Reject If

- Precision gains are marginal or inconsistent
- Latency cost makes normal `ask` usage feel sluggish
- The reranker promotes superficially similar but non-authoritative text over exact regulatory language

---

## 7. WP-15.8 — Multi-Vector Retrieval Spike

### 7.1 Goal

Improve retrieval coverage by indexing multiple semantic surfaces per requirement, all mapping back to the same `requirement_id`.

### 7.2 Rationale

A requirement in ReqBot is not a single piece of text. It may be meaningfully represented by:

- `description` (the normalized requirement statement)
- `source_quote` (verbatim text from the source document)
- `section_title_path` / `parent_context` (structural breadcrumb)

Queries may align with any of those surfaces. A user asking about "annual account reviews" might match the description, while a user quoting "AC-2(j)" matches the source quote. Currently, only one surface is embedded per requirement.

### 7.3 Architecture

At index time:

1. Embed `description` (current behavior)
2. Embed `source_quote` as an additional retrieval surface
3. Both vectors map back to the same `requirement_id`

At query time:

1. Retrieve as normal — both surfaces are candidates
2. **Collapse to unique `requirement_id` before reranking** — this is critical
3. Reranker scores unique logical requirements, not duplicate surfaces

Without the dedup-before-rerank rule, multiple surfaces from the same requirement crowd out other unique relevant requirements and distort top-k quality.

### 7.4 Scope

- Start with 2 surfaces only: `description` + `source_quote`
- Add `section_title_path` only if the first two leave visible gaps
- Keep mapping back to a single canonical requirement payload
- Evaluate on queries that currently fail due to surface mismatch

### 7.5 Success Criteria

- Surfaces relevant requirements that single-surface retrieval misses
- Does not flood results with duplicate entries for the same requirement
- Keeps output format stable by deduping at the requirement level
- Index size growth is proportional and manageable (~64K points for 2 surfaces)

### 7.6 Reject If

- Duplicate management becomes messy or brittle
- Surface-specific embeddings mostly return the same results as the current single-surface path (no incremental value)
- The dedup logic introduces edge cases that make retrieval behavior harder to reason about

---

## 8. WP-15.6 — Retrieval Depth + HyPE

### 8.1 Goal

Provide a configurable retrieval depth that controls how much query expansion the system performs, and optionally front-load part of that expansion into index time via HyPE.

### 8.2 Rationale

HyDE, multi-query, and HyPE are all query expansion strategies. Rather than treating them as separate systems, they should be unified into a single concept: **retrieval depth** — how hard the system works to find relevant results for a given query.

- **HyDE** generates a hypothetical answer at runtime (already implemented)
- **Multi-query** generates multiple query variants at runtime
- **HyPE** generates hypothetical questions at index time, eliminating runtime cost for pre-anticipated queries

These are complementary. HyPE provides a fast baseline of pre-embedded question variants. HyDE provides a query-specific hypothesis for cases HyPE didn't anticipate. Multi-query adds additional runtime angles when the user wants maximum recall.

### 8.3 User-Facing Concept: Retrieval Depth

Expose retrieval depth as a simple user-facing knob:

| Level | Label | Behavior | Runtime LLM calls |
|-------|-------|----------|-------------------|
| 1 | Fast | Raw query only, no expansion | 0 |
| 2 | Normal | HyDE (1 hypothesis) | 1 |
| 3 | Deep | HyDE + 2-3 additional query variants from distinct retrieval perspectives | 3-4 |

If HyPE is enabled on the corpus, pre-embedded question vectors are always included in retrieval regardless of depth level — they're free at query time.

This maps to a CLI flag: `reqbot ask "query" --depth fast|normal|deep` with `normal` as the default (current HyDE behavior).

### 8.4 HyPE: Offline Question Generation

At ingest time (optional, enabled per corpus):

1. Generate 2-3 plausible user questions per requirement
2. Embed those hypothetical questions
3. Store them as additional retrieval surfaces linked back to the original requirement

At query time:

1. Embed only the user query
2. Retrieve against all surfaces including pre-embedded HyPE questions
3. Map results back to the original requirement
4. Collapse to unique `requirement_id` before reranking (same rule as WP-15.8)

### 8.5 HyPE Anti-Hallucination Constraint

The same constraint from Phase 15 HyDE applies: generated questions must not contain fabricated control IDs, section numbers, or numeric thresholds. Log all generated questions to a review file during the spike. Inspect in batch.

### 8.6 Scope

- Implement retrieval depth as a configurable parameter
- Implement HyPE as an optional flag on `ingest` (`--generate-hype-questions`)
- HyPE is a corpus-owner decision at ingest time, not a query-time decision
- Evaluate HyPE quality vs. runtime HyDE on the Phase 15 query set
- Do not adopt HyPE as default unless it proves clearly useful

### 8.7 Multi-Query Design Constraint

When depth is set to deep, the additional query variants must be semantically distinct, not surface-level paraphrases. To force actual diversity, generate variants from distinct retrieval perspectives:

- Auditor / assessor language
- Implementer / operator language
- Policy / legal / governance language

If generated variants collapse into paraphrases of the same retrieval intent, the spike should be treated as failed even if recall appears to rise slightly.

### 8.8 Success Criteria

- Deep retrieval surfaces relevant requirements that normal (HyDE-only) misses on ≥2 test queries
- HyPE achieves comparable recall to runtime HyDE with lower query latency
- Retrieval depth is configurable without code changes (CLI flag or config)
- No obvious semantic drift from low-quality generated questions

### 8.9 Reject If

- Multi-query variants collapse into paraphrases
- HyPE questions are noisy, repetitive, or generic
- Deep retrieval adds significant latency with minimal recall improvement over normal
- The retrieval depth parameter creates confusing behavior differences for the end user

---

## 9. WP-15.9 — Corrective Retrieval Gate

### 9.1 Goal

Add a confidence-aware recovery path when first-pass retrieval is weak: retry once with a targeted rewrite, or return an explicit low-confidence warning.

### 9.2 Rationale

ReqBot should not quietly trust a weak retrieval set just because something was returned. For compliance work, a controlled low-confidence signal is better than a false-confidence answer.

The specific failure mode: 20 results come back, 18 are garbage, synthesis builds on 2 weak results. The system looks confident but the answer is fragile.

### 9.3 Architecture

```
query
  └─► normal retrieval + reranking
          └─► confidence check (reranker scores)
                  ├─► strong → return normal results
                  ├─► weak but recoverable → LLM rewrites query targeting a different angle
                  │       └─► one retry through retrieval + reranking
                  │               └─► merge both result sets, re-rerank
                  └─► still weak after retry → return results with confidence warning
```

### 9.4 Confidence Signals (from reranker)

The reranker provides natural confidence signals:

- Top-5 reranked scores all below a threshold → weak evidence
- Large score gap between top-1 and the rest → thin evidence (one good hit, nothing supporting)
- Low score variance across all candidates → the reranker can't differentiate (everything looks equally mediocre)

These are more reliable than RRF fusion scores or model self-confidence.

### 9.5 Scope

- Depends on WP-15.5 (reranker must ship first)
- One retry maximum — no loops, no escalation chains
- The rewrite query is generated by the LLM targeting a different retrieval angle, not a paraphrase
- If retry doesn't improve the result set, return results with a confidence flag, not an empty response
- The confidence warning is visible to the user: `[!] Low confidence — retrieved evidence may not fully address this query`
- Abstain is preferred over speculative recovery when evidence quality is genuinely weak
- No web search, no agentic loops, no open-ended retry

### 9.6 Success Criteria

- Improves handling of weak or ambiguous queries (retry surfaces better results on ≥2 test cases)
- Reduces false-confidence outputs on poor evidence
- Confidence flag fires on genuinely weak retrievals, not on normal queries
- Does not create unstable multi-step retrieval behavior
- The retry path is deterministic and debuggable

### 9.7 Reject If

- The retry logic is hard to reason about or produces inconsistent behavior
- The confidence threshold fires too aggressively (flags good retrievals as weak)
- The system starts masking poor retrieval with unnecessary LLM work
- The outcome is mostly complexity without measurable quality lift

---

## 10. Explicit Non-Goals

This extension does **not** recommend adding:

- Full agentic RAG or autonomous retrieval agents
- Adaptive web-search routing
- Answer-from-model-memory paths
- LangGraph orchestration or framework-heavy abstractions
- Time-weighted retrieval
- Any interface, API, or GUI changes

These are either the wrong fit for a compliance-first local tool or premature relative to ReqBot's current priorities.

---

## 11. Evaluation Plan

### 11.1 Shared Principle

Each work package must be evaluated against the same question: **Does this improve retrieval quality enough to justify the added complexity?**

### 11.2 Execution Order

| Week | Work | Gate |
|------|------|------|
| 1–2 | WP-15.5 (reranker) + WP-15.8 (multi-vector) in parallel | Precision@5 improvement, no regressions |
| 2 (end) | Evaluate: is retrieval strong enough for Phase 16? | If yes → freeze Phase 15, move to Phase 16 |
| 3 | If gaps remain: WP-15.6 (retrieval depth + HyPE) | Can run in parallel with early Phase 16 API scaffolding |
| Ongoing | WP-15.9 (corrective gate) after reranker is stable | Depends on reranker confidence scores being calibrated |

### 11.3 Metrics (all spikes)

- Precision@5
- New relevant hits surfaced vs. current baseline (post-HyDE)
- Ranking changes at the top of the list
- Latency delta
- Operational complexity added

### 11.4 Evaluation Rule

No work package becomes default behavior unless it demonstrates a clear quality win and no meaningful regression on baseline queries. Log all intermediate artifacts (hypotheses, reranker scores, generated queries) for batch review.

---

## 12. Architecture Safety Test

Before any work package ships, all of the following must remain true:

- Baseline retrieval can still run without the experimental stage
- Experimental features are removable without refactoring the rest of the pipeline
- Output remains requirement-centric, not surface-centric
- CLI behavior stays understandable and debuggable
- The reranker, multi-vector, and HyPE stages are independently toggleable

If a work package violates those constraints, the design is wrong.

---

## 13. Decision Gate

| Decision | Meaning |
|----------|---------|
| **Full adopt** | Run all four work packages per the time-boxed schedule |
| **Partial adopt** | Run WP-15.5 + WP-15.8 only, evaluate before committing further |
| **Reject** | Freeze retrieval after HyDE and proceed directly to Phase 16 |

**Recommendation: Partial adopt.** Run the reranker and multi-vector spikes first. They have the best risk/reward ratio and build directly on ReqBot's existing strengths. Decide on WP-15.6 and WP-15.9 based on observed results, not speculation.

---

*This document is a proposal for review by Gemini, GPT, and Claude Code. No implementation should begin until the decision gate is resolved and the time box is agreed.*
