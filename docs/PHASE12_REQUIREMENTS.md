# Phase 12: Pipeline Architecture Overhaul

> **Goal:** Shift the ingestion pipeline from LLM-heavy interpretation toward verbatim-first
> extraction + query-time intelligence. Deliver stronger, more evolvable data with less
> ingestion-time model bias.
>
> **Prerequisite:** Phase 11 complete (11.3b full corpus re-ingestion done and verified).
>
> **Rule:** One subphase at a time. Complete, then get Gemini review before proceeding.

---

## Context: Why This Phase Exists

Phase 11 established the direction: embed source_quote (verbatim), not description (paraphrase).
Phase 12 takes that philosophy to its logical conclusion across the entire pipeline.

**Core insight from Phase 11 design review:**

> Ingestion = capture ground truth.
> Query / evidence = interpret, summarize, synthesize.

The current single-pass Step C asks an 8B model to simultaneously:
1. Identify whether a statement is an actionable requirement
2. Extract the verbatim source text
3. Paraphrase it into a description
4. Classify it (domain_tags, requirement_type)

Steps 3 and 4 introduce model bias, inconsistency, and irreversibility at ingest time.
Step 2 is the only truly essential operation. Steps 3 and 4 can be deferred and improved
independently without re-ingestion.

---

## Phase 12.1 — Flip Step C Validation Gate

**Current behavior:** Step C requires a non-empty `description` to accept a requirement.
If `source_quote` is empty, the LLM generates a description from nothing — a fabricated
paraphrase with no ground truth anchor. That requirement should not exist.

**Fix:** Flip the validation gate in `llm_extract_requirements.py:validate_requirement()`:
- Require `source_quote` (non-empty after strip)
- Make `description` optional (empty string is acceptable)
- A requirement with no source_quote is dropped, regardless of description

**Also:** Update `embed_and_index.py` — remove the `source_quote or description` fallback.
If source_quote is required at ingest, the fallback is vestigial and masks bugs.

**Impact:**
- Requirements without verbatim evidence are no longer indexed
- Descriptions may be absent for some requirements — display layer must handle this
- `ask.py` / `reqbot.py` result display: show source_quote as primary, description as optional annotation

### Deliverables

- [x] Read `llm_extract_requirements.py:validate_requirement()` and `embed_and_index.py:build_embedding_text()` fully
- [x] Flip validation gate: require source_quote, make description optional
- [x] Remove `source_quote or description` fallback from `build_embedding_text()`
- [x] Update PROMPT_TEMPLATE: source_quote is now required; description is still requested but not required
- [x] Update result display in `ask.py` / `reqbot.py`: show source_quote as primary text when description is absent
- [ ] Test on 2-3 documents before full re-run

---

## Phase 12.2 — Two-Pass Extraction

**Current:** Single LLM pass per chunk produces source_quote + source_ref + description + domain_tags + requirement_type.

**Proposed:**
- **Pass 1 (ingestion):** Extract source_quote + source_ref only. Fast, high-recall, low-interpretation.
  The 8B model does one job: find verbatim requirement text and its document locator.
- **Pass 2 (optional, deferrable):** Generate description, domain_tags, requirement_type.
  Can be run later with any model. Can be re-run with better models without re-ingestion.
  Produces a separate enrichment JSONL that is merged into the normalized record.

**Benefits:**
- Pass 1 is dramatically faster (~60-70% less LLM work per chunk)
- domain_tags and requirement_type can be improved without re-ingesting the corpus
- Data model is model-agnostic — ground truth is never overwritten
- Cross-framework scalability: enrichment can be tuned per document family (NIST vs DoD vs AFI)

**Prerequisites:** Phase 12.1 complete (source_quote is already the required field).

### Design Notes

Pass 1 output schema (minimal):
```json
{"source_quote": "...", "source_ref": "AC-3", "chunk_id": 42}
```

Pass 2 enrichment schema:
```json
{"source_quote": "...", "description": "...", "domain_tags": [...], "requirement_type": "..."}
```

Pass 2 can be run as a separate step (`enrich_requirements.py`) that reads the Pass 1
normalized JSONL and writes an enriched version. Step F (embed_and_index) reads enriched JSONL.
If enrichment has not run, Step F embeds source_quote directly (already the primary field).

### Deliverables

- [ ] Design Pass 1 and Pass 2 schemas and data flow
- [ ] Implement `enrich_requirements.py` (Pass 2 enrichment step)
- [ ] Update `run_pipeline.py` to support `--skip-enrichment` flag
- [ ] Update `reqbot.py` ingest/batch commands to reflect two-pass option
- [ ] Test on 3 documents (one NIST, one DODI, one AFI) before full re-run

---

## Phase 12.3 — Query-Time Description Generation

**Current:** Descriptions are generated at ingest time by the 8B extraction model.

**Proposed:** Remove description from ingestion entirely. Generate concise summaries
at query/evidence time using the synthesis model (qwen2.5:14b or claude-sonnet-4-6)
from the source_quote directly.

**Benefits:**
- Better summary quality (larger synthesis model vs 8B extraction model)
- Descriptions are always fresh — no stale paraphrases in the index
- Source of truth is always the verbatim text

**Prerequisites:** Phase 12.2 complete.

### Deliverables

- [ ] Remove description generation from Pass 2 enrichment (or make it opt-in)
- [ ] Add per-result description generation in `ask.py` result formatting (when --synthesize or --describe flag)
- [ ] Update result display to show source_quote as the primary result text

---

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Validation gate | source_quote required, description optional | Description with no source_quote is fabricated — not ground truth |
| source_ref | Locator metadata only | Document-specific addressing, not universal semantic signal |
| Two-pass | Pass 1 = quote capture, Pass 2 = enrichment | Separates ground truth from interpretation; enables independent improvement |
| Description timing | Query-time (eventually) | Larger models produce better summaries; avoids stale ingest-time paraphrases |
| Data model | source_quote is source of truth | Embedding, display, and deduplication all anchor to verbatim text |

---

## Deferred Issues (from Phase 11.3b Gemini/ChatGPT review — evaluate before Phase 12 work begins)

### JSON Recovery Strategy 3 — rfind correctness risk (`llm_extract_requirements.py`)
Strategy 3 in `extract_json_array()` uses `rfind("}")` to find the boundary of the last complete object in a truncated LLM response. This has no awareness of JSON string contents — a `}` inside a string value (e.g., in a description or source_quote) could be mistaken for an object boundary, silently truncating a valid requirement or producing a corrupt partial record. Strategy 2 already uses proper bracket-stack counting with string-literal awareness and handles the non-truncated case. Strategy 3 only fires when Strategy 2 fails AND the array was truncated by the LLM hitting its token limit. Real-world frequency is low but non-zero. Fix requires either a streaming JSON parser (`ijson`) or extending the Strategy 2 bracket-stack approach to handle the truncated-array case.

### IP/version string pollution in `scan_source_refs` (`llm_extract_requirements.py`)
The dragnet regex `\b\d+\.\d+(?:\.\d+)+\b` captures IP addresses and semantic version strings. The hint slot cap is `_MAX_HINT_REFS = 20`. A chunk with many IP addresses (e.g., a network security policy with example addresses) can fill all 20 slots with noise, pushing actual section refs out and silently degrading source_ref extraction accuracy on that chunk. Fix: filter candidates before appending — skip strings where all dot-separated segments are ≤ 255 (likely IP) or where the pattern matches common version formats (e.g., three segments all < 100).

### Deduplication scoring (`parse_and_normalize.py`)
Winner selection in `deduplicate_requirements()` uses `len(domain_tags) * 10 + len(source_quote)`. More tags does not imply better quality — the extraction model can hallucinate tags, and a longer source_quote is not necessarily more precise. The confidence score is computed immediately before deduplication but is not used in the scoring. Fix: weight confidence score heavily in the winner selection formula; favor shorter, more precise source_quotes over longer ones for equal confidence.

---

---

## Phase 12.4 — Deferred Bug Fixes (from Phase 11.3b review)

These are correctness/quality bugs identified during Phase 11 review. They do not
block Phase 12.1-12.3 and can be addressed as a standalone cleanup subphase.

### JSON Recovery Strategy 3 — rfind correctness risk (`llm_extract_requirements.py`)
Strategy 3 in `extract_json_array()` uses `rfind("}")` to find the boundary of the
last complete object in a truncated LLM response. A `}` inside a string value could
be mistaken for an object boundary. Fix: extend Strategy 2's bracket-stack approach
to handle the truncated-array case, or use `ijson` for streaming parse.

### IP/version string pollution in `scan_source_refs` (`llm_extract_requirements.py`)
The dragnet regex `\b\d+\.\d+(?:\.\d+)+\b` captures IP addresses and version strings,
consuming hint slots from the 20-slot cap. Fix: filter candidates before appending —
skip strings where all dot-separated segments are ≤ 255 (likely IP) or match common
version patterns.

### Deduplication scoring (`parse_and_normalize.py`)
Winner selection uses `len(domain_tags) * 10 + len(source_quote)`. More tags ≠ better
quality. Fix: weight confidence score heavily in winner selection; favor shorter,
more precise source_quotes for equal confidence.

### Deliverables

- [ ] Fix Strategy 3 rfind truncation bug in `extract_json_array()`
- [ ] Filter IP/version strings from `scan_source_refs()` hint candidates
- [ ] Improve deduplication scoring to weight confidence and source_quote precision

---

## Execution Order

```
12.1 (flip gate) → test → Gemini review
12.2 (two-pass) → test → Gemini review
12.3 (query-time descriptions) → test → Gemini review
12.4 (deferred bug fixes) → test → Gemini review
```
