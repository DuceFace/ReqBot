# Qdrant Integration Plan (Revised)

> Reconstructed from prior session. Reviewed by ChatGPT, then code-level
> review by Claude against actual codebase. Fixes applied.
>
> **Status: ALL PHASES COMPLETE** (original Qdrant integration + Phase 2 improvements)

## Context

The extraction pipeline (Steps A-E) is working. We need to add vector search
so users can query requirements with natural language. JSONL stays as system
of record; Qdrant is a rebuildable search index.

## Prerequisites

- `ollama pull nomic-embed-text` (768-dim embedding model)
- Qdrant running on port 6333 (docker-compose.yml in repo)
- Verify `ollama` Python package API (`embed()` vs `embeddings()`) at impl time
- Verify exact 70b model tag with `ollama list`

## Key Design Decisions

1. **System of record**: JSONL (canonical requirements). Qdrant is a rebuildable index, not source of truth.
2. **Embedding model**: `nomic-embed-text` (768-dim, via Ollama)
3. **Synthesis model**: `qwen2.5:14b` for ask.py (verify exact tag), overridable with `--model`
4. **Stable IDs**: Based on source_quote (document text), NOT description (LLM-generated, unstable across reruns)
5. **Document identity**: Store all three — `document_id` (short hash), `document_hash_full` (SHA-256), `source_pdf` (filename)
6. **Qdrant-only (Option B)**: No SQLite for now. JSONL + Qdrant. Migrate to Option A later if corpus grows.
7. **ask.py defaults to retrieve-only**: Get retrieval quality right before trusting synthesis. Use `--synthesize` flag explicitly.
8. **Single CLI interface**: `grcai` with subcommands. Subprocess dispatch for now, refactor to shared package later.
9. **Packaging goal**: Eventually Docker Compose (qdrant + app container), then optional web UI. Keep it simple now.
10. **Keep confidence**: Already a deterministic heuristic in Step D. Useful for filtering. ChatGPT said drop it but the existing impl is exactly the type of heuristic they said was acceptable.

---

## Phase 1: Modify Step D (`scripts/parse_and_normalize.py`) ✅ DONE

**Arg change:**
- Add `--source-pdf-path <path>` (full path to original PDF, NOT just filename)
  - Read PDF bytes → SHA-256
  - `document_id`: first 16 hex chars (short ID for filtering/display)
  - `document_hash_full`: full SHA-256 hex (audit/debug)
  - `source_pdf`: `Path(path).name` (user-facing filename)
- Note: Step E already has `--source-pdf` as a filename string. Using
  `--source-pdf-path` for Step D avoids naming collision.

**Schema changes to normalized output:**
- Add `document_id`, `document_hash_full`, `source_pdf`
- Replace `page_refs: [47, 48]` with `page_start: 47, page_end: 48`
  - Data already available at line 218; stop expanding to `range()`
- Preserve `chunk_id` in output (currently read but not written)
- Keep `confidence` (already deterministic, used by Step E)

**Stable IDs (replace sequential REQ-0001):**
- Order: validate/filter → deduplicate → assign stable IDs (dedupe first!)
- Normalize source_quote before hashing: lowercase, collapse whitespace, strip
- Primary: `SHA-256(document_id + source_ref + norm_quote)[:12]` → `REQ-a1b2c3d4e5f6`
- Fallback: `SHA-256(document_id + norm_quote)[:12]` if no source_ref
- Last resort: `SHA-256(document_id + str(chunk_id) + req_type + norm_desc)[:12]`
- Prefix all with `REQ-` for readability

**Updated normalized output schema:**
```json
{
  "requirement_id": "REQ-a1b2c3d4e5f6",
  "description": "...",
  "source_ref": "AC-2(1)",
  "domain_tags": ["access-control"],
  "requirement_type": "technical-control",
  "source_quote": "...",
  "chunk_id": 50,
  "page_start": 47,
  "page_end": 48,
  "confidence": 0.9,
  "document_id": "3f4a7b2c1e9d8a6f",
  "document_hash_full": "3f4a7b2c1e9d8a6f...(64 hex chars)",
  "source_pdf": "NIST.SP.800-53r5.pdf"
}
```

## Phase 2: New `scripts/embed_and_index.py` ✅ DONE

- Load `requirements_normalized.jsonl`
- **Embedding text format** (deterministic):
  ```
  {description}\n\nEvidence: {source_quote}
  ```
  Plus `\nRef: {source_ref}` only if source_ref is non-empty.
- Embed via Ollama with `nomic-embed-text`, batch size 32
  - Verify API: try `ollama.embed()`, fall back to `ollama.embeddings()`, or use raw `requests` for consistency with Step C
- Upsert into Qdrant collection `grc_requirements` (cosine, 768-dim)
- **Point IDs**: Check if qdrant-client supports string IDs. If yes, use `requirement_id` directly. If no, use uuid5 with fixed namespace constant.
- **Payload** (includes confidence, excludes embedding text):
  - `requirement_id`, `document_id`, `source_pdf`
  - `source_ref`, `domain_tags`, `requirement_type`
  - `source_quote`, `description`
  - `page_start`, `page_end`, `confidence`, `chunk_id`
- CLI: `embed_and_index.py <jsonl> [--recreate] [--batch-size N]`
  - Note: removed `--source-pdf` from this script. All document metadata is already in the JSONL from Step D.
  - `--recreate` = drop and recreate collection. Only for full reindex, NOT normal multi-doc workflow.

## Phase 3: New `scripts/ask.py` ✅ DONE

- Embed question with `nomic-embed-text`
- Query Qdrant top-K (default 20) with optional filters:
  - `--domain-tag`, `--requirement-type`, `--document-id`
  - **Normalize filter inputs** to canonical forms (lowercase, hyphens) at query time
- Format retrieved requirements as numbered evidence table
- **Grounding safeguards** in synthesis prompt:
  - "If evidence does not directly support a claim, say 'not supported by retrieved sources'"
  - Consistent citation format: `[N] (source_pdf, source_ref, pages X-Y)`
- **Default to retrieve-only**; synthesis requires explicit `--synthesize` flag
- `--synthesize` sends evidence to LLM (default: qwen2.5:14b, override with `--model`)
- CLI: `ask.py "question" [--top-k N] [--synthesize] [--model M] [--domain-tag T] [--requirement-type T] [--document-id D]`

## Phase 4: New `scripts/grcai.py` (CLI wrapper) ✅ DONE

- Argparse subcommands dispatching to existing scripts via subprocess
- **Proper returncode checking** on every subprocess (match run_pipeline.py pattern)
- Subcommands:
  - `grcai ingest <pdf> [--index]` → run_pipeline.py, optionally chain embed_and_index.py
  - `grcai index <jsonl>` → embed_and_index.py
  - `grcai ask "question"` → ask.py (passes through all ask.py flags)
  - `grcai status` → show Qdrant collections, Ollama models, processed docs
- Note: subprocess dispatch for now; refactor to shared package when packaging

## Phase 5: Update `scripts/run_pipeline.py` ✅ DONE

- Pass `--source-pdf-path <pdf_path>` to Step D (full path, not just name)
- Add `--index` flag to optionally chain embed_and_index.py after Step E

---

## Files Changed

| File | Action |
|------|--------|
| `scripts/parse_and_normalize.py` | Modify: document identity, stable IDs, schema changes |
| `scripts/run_pipeline.py` | Modify: pass --source-pdf-path to Step D, add --index flag |
| `scripts/embed_and_index.py` | New: embed requirements + upsert to Qdrant |
| `scripts/ask.py` | New: query Qdrant + optional LLM synthesis |
| `scripts/grcai.py` | New: CLI wrapper with subcommands |

## Verification

1. Run modified Step D on v2.1_test_controls data → confirm new fields, stable IDs, IDs identical across two runs
2. `ollama pull nomic-embed-text`, run embed_and_index.py on test requirements → confirm Qdrant collection with 51 points
3. `ask.py "What access control requirements exist?"` → confirm retrieval (retrieve-only default)
4. `ask.py "What are audit log retention requirements?" --synthesize` → confirm cited answer from 70b
5. Test `grcai.py` subcommands end-to-end
6. Run Step D twice with same input → confirm requirement_ids are identical (stable ID proof)

---

## Review Notes

See `scripts/qdrant_plan_review.md` for the full code-level analysis that
produced these revisions. Key fixes from original plan:
- `--source-pdf-path` instead of `--source-pdf` (Step D needs actual PDF path)
- `chunk_id` preserved in normalized output
- `confidence` kept (was already a valid deterministic heuristic)
- `page_refs` list replaced with `page_start`/`page_end` integers
- `--source-pdf` removed from embed_and_index.py (metadata already in JSONL)
- Point ID strategy: prefer string IDs if qdrant-client supports them
- Explicit dedupe-then-ID ordering
- Returncode checking in grcai.py subprocess calls

---

## Phase 2 Improvements ✅ ALL DONE

Post-integration improvements implemented on top of the base Qdrant pipeline.
Each was reviewed by Gemini Pro before being marked complete.

### P1 — Hybrid Search ✅
- `embed_and_index.py`: Added sparse BM25 vectors via `fastembed` (Qdrant/bm25 model)
- `grc_requirements` collection now uses dense (768-dim cosine) + sparse (BM25) vectors
- `ask.py`: RRF (Reciprocal Rank Fusion) merges dense and sparse results before reranking
- `grcai.py`: Added `reindex` subcommand with atomic alias swap (live index untouched on failure)

### P2 — Query Rewriting ✅
- `ask.py`: LLM pre-processes the user question before embedding
  - Expands the query into a retrieval-optimized form
  - Extracts explicit control IDs (e.g. `AC-3`, `IA-5(1)`) for exact-match boosting
  - Auto-detects domain tags from question text for optional pre-filtering
- Uses `llama3.1:8b-instruct-q4_K_M` for rewriting (same model as extraction, fast)
- Rewriting is transparent — original question still shown, rewritten form logged

### P3 — Pre-scan Source Refs ✅
- `llm_extract_requirements.py`: Scans each chunk with compiled regex patterns before LLM call
  - Patterns: NIST/STIG control IDs (`AC-3(4)`), Section refs, Para refs, numbered hierarchies
  - Key fix: uses `(?!\w)` not `\b` at end of control ID pattern (handles trailing parentheses)
  - Results injected as non-coercive hints in the extraction prompt
  - Capped at 20 candidates; early-exit once cap reached
- Improves `source_ref` accuracy without changing LLM model or prompt structure

### P4 — Dual Index ✅
- New `embed_context_index.py`: Indexes raw Step B chunks into `grc_context` collection
  - Same hybrid dense+sparse schema as `grc_requirements`
  - Point IDs: `uuid5(CONTEXT_UUID_NAMESPACE, "{document_id}:{chunk_id}")` — deterministic O(1) lookup
  - `CONTEXT_UUID_NAMESPACE` is fixed and must match between this file and `ask.py`
- `ask.py`: Added `--context` flag
  - Retrieves source chunk from `grc_context` by direct UUID lookup (no second vector search)
  - Extracts windowed context centered on `source_quote` (300 char window each side)
  - Falls back to top of chunk if quote not found; graceful degradation if collection missing
- `grcai.py`: `ingest --index` and `batch` both run F2 context indexing automatically
- `grcai.py`: Added `index-context` subcommand for manual per-file indexing

### P5 — pdfplumber Layout-Aware Chunking ✅
- `extract_pdf_to_text.py`: Added `--layout-mode {pymupdf,pdfplumber}` (default: `pymupdf`)
  - `pdfplumber` mode: vertical crop sweep preserves reading order (prose → table → prose)
  - Tables extracted as pipe-delimited rows, wrapped in `<<<TABLE_START>>>`/`<<<TABLE_END>>>` sentinels
  - Per-page fallback to PyMuPDF if pdfplumber fails
  - PyMuPDF remains default — zero impact on existing workflows
- `chunk_text.py`: Added `--table-aware` flag
  - `find_table_spans()`: scans concatenated text for sentinel regions
  - `chunk_text()`: pushes split points past table ends; snaps overlap cursor past table end
  - Prevents both mid-table splits and "table tail" overlap artifacts
- `run_pipeline.py`: `--layout-mode` passed to Step A; `--table-aware` auto-enabled for Step B when pdfplumber
- `grcai.py`: `--layout-mode` exposed on `ingest` and `batch` subparsers
