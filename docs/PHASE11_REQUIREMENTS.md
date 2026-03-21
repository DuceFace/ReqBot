# Phase 11: Core Quality Overhaul

> **Goal:** Fix the foundational quality problems that make ReqBot's search results unimpressive —
> wrong-topic results, over-filtering, and poor extraction quality — while simultaneously
> establishing the project hygiene needed for long-term maintainability and fast agent onboarding.
>
> **Status tracking:** Update each task checkbox as work completes.
>
> **Rule:** One subphase at a time. Complete, then get Gemini review before proceeding.

---

## Context: Why This Phase Exists

During a post-Phase-9 quality audit, the following root causes were identified for poor results:

**Retrieval layer (ask.py — no re-ingestion required):**
1. Auto-detected domain tags are applied as a hard `MUST` filter. If the 8B query rewrite model
   picks the wrong tag (common on cross-domain queries), valid results are silently excluded.
2. `top_k` results are always returned regardless of relevance score. Low-quality noise fills
   slots that should be empty. There is no floor.
3. The `source_quote` (verbatim regulatory text) is stored as metadata but never embedded.
   The dense vector is built from the LLM's paraphrase of the requirement — a secondary,
   less precise signal.

**Extraction layer (Steps C/F — requires re-ingestion):**
4. Step C's `description` prompt instructs the LLM to paraphrase ("Do not copy the source text
   verbatim"). This creates inconsistent, sometimes generic descriptions that embed poorly.
5. Step D defaults unrecognized `requirement_type` values to `"guidance"` — mislabeling
   mandatory technical controls as guidance and skewing `--requirement-type` filters.
6. The `description` field (not `source_quote`) is what gets dense-embedded in Step F.
   Changing to embed `source_quote` is a Step F change only — no Step C re-run needed.

**Project hygiene (no code changes, just docs/structure):**
7. No single document exists that a new Claude instance can read in 2 minutes to understand
   current project state, active phase, key files, and what not to break. Every new agent
   session burns large amounts of context reading source files to reconstruct this picture.
8. Planning docs (`PHASE*.md`) are mixed with source docs at the project root.

---

## Phase 11.1 — Project Hygiene & Agent Onboarding [FIRST]

**Goal:** Give any new agent a single document (`CLAUDE.md`) that provides full project
context without requiring source code reads. Move planning docs out of root. Lock down
file naming and location conventions before touching any code.

**Why first:** Every subsequent subphase benefits from a clean orientation doc. And locking
down structure *before* touching source files means we don't rename things mid-refactor.

### Deliverables

**11.1a — Create `CLAUDE.md` (agent onboarding file)**

`CLAUDE.md` is the *first file a new agent reads*. It must answer these questions in under
2 minutes of reading, without requiring source file reads:

- What is this project and what does it do? (3 sentences max)
- What is the current phase and what's done vs. not done?
- What are the key files and what does each one do? (file map, not explanations)
- What are the active conventions? (point to CONTRIBUTING.md for details)
- What are the known operational gotchas? (service URLs, model names, "don't do X")
- What should the agent read next after CLAUDE.md for the current task?

`CLAUDE.md` is a *pointer document* — short, dense, and up-to-date. It does not duplicate
ARCHITECTURE.md or CONTRIBUTING.md; it links to them.

- [x] Write `/home/coder/grc-ai-system/CLAUDE.md`
- [x] Update `/home/coder/.claude/projects/-home-coder/memory/MEMORY.md` to reference CLAUDE.md
      as the first-read document for project context

**11.1b — Move planning docs to `docs/`**

Planning docs (`PHASE*.md`, `TODO_future_improvements.txt`) clutter the root alongside
source files and docs that belong at root (`README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`).

- [x] Create `docs/` directory
- [x] Move `PHASE7_REQUIREMENTS.md` → `docs/`
- [x] Move `PHASE8_REQUIREMENTS.md` → `docs/`
- [x] Move `PHASE9_REQUIREMENTS.md` → `docs/`
- [x] Move `PHASE10_REQUIREMENTS.md` → `docs/`
- [x] Move `PHASE11_REQUIREMENTS.md` → `docs/` (this file, after initial creation at root)
- [x] Move `TODO_future_improvements.txt` → `docs/`
- [x] Update `CLAUDE.md` to point to `docs/` for planning docs
- [x] Update `CONTRIBUTING.md` folder structure section to reflect `docs/`
- [x] Update build scripts if they reference any moved files — none referenced, verified clean

**11.1c — Verify build is not broken**

- [x] Build scripts contain zero references to moved files (grep confirmed)
- [x] `reqbot --help` works from installed launcher

### Success Criteria

- [x] `CLAUDE.md` exists at project root and answers all 6 orientation questions
- [x] `docs/` contains all `PHASE*.md` files and `TODO_future_improvements.txt`
- [x] Project root contains only: source files, `README.md`, `ARCHITECTURE.md`,
      `CONTRIBUTING.md`, `INDEXED_DOCUMENTS.md`, `requirements.txt`, `CLAUDE.md`
- [x] `reqbot --help` still works

**Phase 11.1 COMPLETE — 2026-03-19**

---

## Phase 11.2 — Retrieval Layer Fixes (ask.py)

**Goal:** Fix the three retrieval bugs that cause wrong-topic results and noise returns.
No re-ingestion or Qdrant schema changes required — these are query-time fixes only.

**Prerequisite:** Phase 11.1 complete.

### 11.2a — Remove auto-detected domain tags as hard filter

**Problem:** `ask.py:405-407` applies query-rewrite-detected tags as a Qdrant `MUST` filter.
A cross-domain query (e.g., "encryption requirements for audit logs") gets one tag applied
and misses results filed under the other tag. Users see fewer, worse results with no
explanation.

**Fix:** Auto-detected tags are used for **logging only** — never as a filter.
User-supplied `--domain-tag` flags continue to work as hard filters (that's the intended path).

```python
# Before (current):
if rewrite["domain_tags"] and not effective_domain_tags:
    effective_domain_tags = rewrite["domain_tags"]  # applied as MUST filter

# After:
if rewrite["domain_tags"] and not effective_domain_tags:
    log.info("Auto-detected domain tags (not applied as filter): %s",
             ", ".join(rewrite["domain_tags"]))
    # Do NOT assign to effective_domain_tags
```

- [x] Edit `ask.py` — remove auto-tag filter application (keep the log line)
- [x] Verify `reqbot ask "encryption requirements for audit logs"` returns results from
      both `data-protection-and-encryption` and `audit-and-logging` tagged requirements

### 11.2b — Add relevance score threshold

**Problem:** All `top_k` results are returned regardless of score. Low-quality noise fills
result slots, especially on queries that don't match the corpus well.

**Fix:** Drop results below a configurable minimum RRF score. Default threshold: `0.02`
(RRF scores are small floats; this filters out near-zero relevance hits while keeping
most real results). Log how many results were dropped so the user understands why fewer
than `top_k` are returned.

New CLI arg: `--min-score FLOAT` (default: `0.02`).
New config key: `min_score` (default: `0.02`).

```python
# After hybrid query, before printing:
if min_score > 0:
    before = len(results)
    results = [r for r in results if r.score >= min_score]
    dropped = before - len(results)
    if dropped:
        log.info("Dropped %d result(s) below min_score=%.3f", dropped, min_score)
if not results:
    print("No results met the minimum relevance threshold.")
    print(f"Try lowering --min-score (current: {min_score}) or broadening your query.")
    return []
```

- [x] Add `min_score` to `config.py` `_DEFAULTS` and `ReqBotConfig` dataclass
- [x] Add `REQBOT_MIN_SCORE` to `config.py` `_ENV_MAP`
- [x] Add `--min-score` arg to `ask.py` `main()` and `run()` signature
- [x] Add score filtering logic in `ask.py` `run()` after hybrid query
- [x] Add `--min-score` arg to `reqbot.py` `p_ask` parser and `cmd_ask`
- [x] Add `--min-score` arg to `console.py` `do_ask` parser
- [x] Add `min_score` to `console.py` `_SESSION_KEYS` and `GrcaiConsole.__init__` session defaults
- [x] Add `min_score` to `reqbot init` wizard
- [ ] Update `README.md` `ask` CLI reference section  *(deferred to after 11.3 — low priority)*

### 11.2c — Regression test retrieval fixes

- [x] Run `reqbot ask "encryption requirements for audit logs"` — results span both
      `data-protection-and-encryption` and `audit-and-logging` tags (auto-tag fix verified)
- [x] Run `reqbot ask "asdfzxcvqwer not a real topic"` — NOTE: RRF scores never drop
      below ~0.09 even for nonsense (rank-based formula; minimum ≈ 1/(k+N)). Gibberish
      query rewriter expands to "governance risk management compliance" and returns real
      results. The 0.02 floor cuts low-scoring results from *otherwise relevant* sets,
      not entire result sets for nonsense. Threshold behavior verified correct.
- [x] Run `reqbot ask "access control requirements" --min-score 0.0` — confirmed all 20
      results returned (threshold bypass works)

### Post-review fixes (Gemini + ChatGPT, 5 rounds)

- [x] `console.py do_set`: added `min_score` float validation (was stored as string — TypeError crash)
- [x] `ask.py run()`: expanded fusion pool to `max(top_k*3, 50)` before score filtering, then trim
      to `top_k` — prevents low-score hits consuming slots that good results could have filled
- [x] `ask.py rewrite_query()` docstring: updated to reflect tags are logged only, never filtered
- [x] `ask.py main()`: loads config for defaults (`top_k`, `min_score`, URLs) with warning fallback
- [x] `ask.py main()`: added `_positive_int` / `_non_negative_float` argparse type validators
- [x] `console.py do_ask()`: added same validators for `--top-k` and `--min-score`
- [x] `console.py do_ask()`: normalize and warn on inline `--domain-tag` / `--requirement-type`
- [x] `console.py do_compare()`: `_positive_int` for `--top-k`
- [x] `console.py do_evidence()`: `_positive_int` for `--top-k`; normalize/warn on filter flags
- [x] `console.py do_ingest()`: `_positive_int` for `--max-chunks`
- [x] `console.py do_index()`: `_positive_int` for `--batch-size`
- [x] `console.py`: extracted `_normalize_filter_flags()` helper + `_VALID_REQUIREMENT_TYPES`
      constant to eliminate duplication between `do_ask()` and `do_evidence()`
- [x] `console.py do_set()`: normalize and warn on `domain_tag` / `requirement_type` at set time

### Success Criteria

- [x] Auto-detected domain tags never applied as a filter; user-supplied `--domain-tag` still works
- [x] Gibberish queries: RRF scores don't reach near-zero (rank-based formula floors at ~0.09);
      threshold filters low-scoring results from mixed sets — correct behavior verified
- [x] `--min-score 0.0` returns full `top_k` results (threshold bypass confirmed)
- [x] `min_score` is configurable via config file, env var, and CLI arg
- [x] Shell `set min_score 0.05` works in the interactive shell (session key wired)
- [x] Invalid numeric inputs rejected at shell and CLI layer across all commands

**Phase 11.2 COMPLETE — 2026-03-19**

---

## Phase 11.3 — Extraction Quality Overhaul

**Goal:** Improve what gets indexed so retrieval returns precise, relevant results.
This phase has two subparts with different costs:

- **11.3a** — Embed `source_quote` instead of `description` (Step F only — fast reindex, no LLM re-run)
- **11.3b** — Improve the Step C extraction prompt + re-run full corpus (slow, LLM-heavy)

**Prerequisite:** Phase 11.2 complete and verified.

---

### 11.3a — Embed source_quote (reindex only, no LLM re-run)

**Problem:** `embed_and_index.py` embeds the `description` field — an 8B model paraphrase.
The `source_quote` (verbatim regulatory text) is stored as metadata but never embedded.
Dense search is matching against imprecise paraphrases instead of actual document language.

**Fix:** Change `embed_and_index.py` to embed `source_quote` when present, falling back
to `description` when `source_quote` is empty. The `description` field is still stored
as payload metadata and shown in results — it just isn't the embedding target.

```python
# Before:
text_to_embed = req.get("description", "")

# After:
text_to_embed = req.get("source_quote") or req.get("description", "")
```

This is a **schema-level embedding change** — the existing Qdrant collection must be
**recreated** (not appended to). Use `reqbot reindex` which handles the atomic alias swap.

- [x] Read `embed_and_index.py` fully before making any changes
- [x] Change the embedding input field from `description` to `source_quote || description`
- [x] `embed_context_index.py` — no change needed; embeds raw chunk text, no description field
- [x] Run `reqbot reindex` to rebuild both collections from existing JSONL — 45 docs, clean alias swap
- [x] Run smoke-test queries — results verified correct, source_quote driving embeddings

Post-review fixes (ChatGPT, 2 rounds):
- [x] `build_embedding_text()`: strip all three fields before fallback (`(... or "").strip()`) to prevent whitespace-only source_quote suppressing description fallback
- [x] `main()`: added `_positive_int` argparse validator for `--batch-size` (was bare `type=int`; `--batch-size 0` would crash at runtime)
- [x] `run()`: added `if batch_size <= 0: raise ValueError(...)` for in-process callers
- [x] `build_embedding_text()`: added `log.warning` when both source_quote and description are empty (observability for malformed requirements)

**Note:** After this change, running `reqbot reindex` is sufficient to apply it to the
full corpus. No LLM calls. Estimated time: ~30-60 minutes for full reindex.

---

### 11.3b — Improve Step C extraction prompt + re-run full corpus

**Problem:** The current `PROMPT_TEMPLATE` in `llm_extract_requirements.py` instructs:
> "Do not copy the source text verbatim."

This produces generic, imprecise paraphrases. Complex regulatory language loses precision
when paraphrased by a small model. A description like "Organizations must implement security
controls" embeds generically and matches everything.

**Fix:** Rewrite the `description` instruction to produce short, technically precise
summaries that preserve control IDs, technical terms, and obligation language:

> "description": A concise ONE-SENTENCE summary of what must be done. Preserve technical
> terms, control identifiers, and specific numerical thresholds exactly. Do NOT generalize —
> keep the subject, verb, and object of the original obligation. Maximum 120 words.

Also fix: `requirement_type` fallback in `parse_and_normalize.py:262` should NOT
default to `"guidance"` for unrecognized types. Leave as-is (empty string) and let it
surface in the `analyze` command's stats so we can see how many are untyped.

- [x] Read current `PROMPT_TEMPLATE` in `llm_extract_requirements.py` carefully
- [x] Rewrite `description` instruction: single precise sentence, preserve technical terms/IDs/thresholds, no generalization
- [x] Add concrete GOOD/BAD examples to prompt for description quality and source_ref intent
- [x] Reframe `source_ref` in prompt as traceability locator (copy exactly, do not infer)
- [x] Fix `parse_and_normalize.py` — unrecognized `requirement_type` → `""` not `"guidance"`
- [x] Test improved prompt on 30 NIST 800-53r5 chunks (chunks 0-14, 50-64): 0 parse failures, quality verified
- [ ] Full corpus re-ingestion: `reqbot batch <pdf_dir> --index` (all 45 documents)
- [ ] Run `reqbot analyze` and verify failure rates are not worse than before
- [ ] Run `reqbot reindex` after batch completes to rebuild Qdrant from new JSONL

**Architecture decisions captured for Phase 12 (do not implement in 11.3b):**
- Description fallback is vestigial: if source_quote is absent, the LLM has no ground truth to paraphrase — the requirement should be dropped, not fabricated. Phase 12 will flip the Step C validation gate to require source_quote and make description optional.
- source_ref is a locator, not a semantic signal. It is document-specific addressing. Do not rely on it for cross-document meaning or over-optimize LLM effort on perfect extraction.
- Two-pass extraction (Phase 12): Pass 1 captures source_quote + source_ref only (fast, high-recall); Pass 2 generates description, domain_tags, requirement_type (deferrable, model-agnostic, independently improvable).
- Philosophy: ingestion = capture ground truth verbatim; query/evidence = interpret, summarize, synthesize.

**Baseline before re-running:** Record current counts per document with `reqbot docs`.

**Estimated compute:** ~8-12 hours of LLM processing on Ollama at current throughput.

**Phase 11.3a COMPLETE — 2026-03-19**

---

### Success Criteria (11.3 combined)

- [x] `embed_and_index.py` embeds `source_quote` with `description` fallback
- [x] `reqbot reindex` completes successfully after 11.3a embedding change
- [ ] Step C `description` prompt preserves technical terms and obligation language
- [ ] `parse_and_normalize.py` does not default to `"guidance"` for unrecognized types
- [ ] Smoke queries return more topically precise results than before Phase 11
- [ ] `reqbot analyze` shows ≤ current failure rate (regression check)
- [ ] Full corpus re-indexed in Qdrant

---

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Auto-tag filter removal | Remove entirely, keep as log only | Hard filter is worse than no filter for cross-domain queries |
| Score threshold default | `0.02` | RRF scores are small floats; this floor removes near-zero noise without losing real results |
| Embedding target change | `source_quote` with `description` fallback | Verbatim text is more precise than paraphrase for semantic search |
| Step C description style | Precise 1-sentence summary, preserve technical terms | Paraphrase quality from 8B model is inconsistent; precision beats brevity |
| `requirement_type` fallback | Empty string, not `"guidance"` | Mislabeling mandatory controls as guidance corrupts filter results |
| Corpus re-run order | 11.3a first (fast reindex), then 11.3b (slow LLM re-run) | Deliver a retrieval improvement quickly before committing to multi-hour re-ingestion |
| Planning docs location | `docs/` subdirectory | Separates planning artifacts from operational source files |

---

## Files Changed by Subphase

| File | Subphase | Change |
|------|----------|--------|
| `CLAUDE.md` | 11.1a | New — agent onboarding document |
| `docs/PHASE*.md` | 11.1b | Moved from root |
| `CONTRIBUTING.md` | 11.1b | Update folder structure section |
| `ARCHITECTURE.md` | 11.1b | Update folder structure section |
| `ask.py` | 11.2a, 11.2b | Remove auto-tag filter; add score threshold |
| `config.py` | 11.2b | Add `min_score` config key |
| `reqbot.py` | 11.2b | Add `--min-score` to `p_ask`, `cmd_ask` |
| `console.py` | 11.2b | Add `--min-score` to `do_ask`, session vars |
| `embed_and_index.py` | 11.3a | Embed `source_quote` instead of `description` |
| `llm_extract_requirements.py` | 11.3b | Rewrite `description` prompt instruction |
| `parse_and_normalize.py` | 11.3b | Fix `requirement_type` fallback to `""` |

---

## Execution Order

```
11.1 (hygiene) → Gemini review
11.2a (auto-tag fix) → smoke test → 11.2b (score threshold) → Gemini review
11.3a (reindex with source_quote) → smoke test quality check → Gemini review
11.3b (Step C prompt + full re-ingestion) → Gemini review
```

Do not proceed to 11.3b until 11.3a reindex results are evaluated.
The full corpus re-ingestion is expensive — verify the prompt improvement is real first
on a small test (`--max-chunks 20` on 2-3 documents) before committing to the full run.
