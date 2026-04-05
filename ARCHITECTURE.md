# ReqBot Architecture

*Living document — update when adding modules, changing data flows, or modifying external dependencies.*

---

## What the System Does

ReqBot extracts cybersecurity compliance requirements from regulatory PDFs, indexes them into a
hybrid vector database, and provides a search/analysis interface for cross-framework compliance
research. It is designed to run entirely on local infrastructure (Ollama + Qdrant), with optional
remote synthesis via Anthropic or OpenAI APIs.

---

## Top-Level Module Map

```
reqbot.py          ← CLI entry point + all command implementations
console.py         ← Interactive shell (cmd.Cmd); wraps reqbot.py commands
config.py          ← Configuration loader (stdlib only; no internal imports)
run_pipeline.py    ← Pipeline orchestrator (Steps A–E + D.5); called by reqbot.py
synthesis.py       ← LLM synthesis abstraction (local Ollama or remote API)
CLAUDE.md          ← Agent onboarding (read first; current phase, file map, gotchas)

--- Pipeline Steps (standalone, no cross-imports) ---
extract_pdf_to_text.py       Step A  (legacy):  PDF → pages JSONL  [pymupdf / pdfplumber]
section_parser.py            Step A  (docling):  PDF → *_ancestry.json + in-memory AncestryResult
                                                 Docling DocumentConverter + iterate_items() traversal
                                                 section_ref_path (numbered only) / section_title_path (all)
                                                 parent_context = first ~600 chars after immediate parent heading
chunk_text.py                Step B  (legacy):  pages JSONL → chunks JSONL  (fixed-size sliding window)
                             Step B  (docling):  AncestryResult → chunks JSONL  (HybridChunker + breadcrumb injection)
                                                 Output fields: raw_text, text (breadcrumb+raw_text), breadcrumb,
                                                 section_ref_path, section_title_path, parent_header_text, parent_context
llm_extract_requirements.py  Step C:  chunks JSONL → extracted requirements JSONL  [Ollama: extraction_model]
                                      Pass 1 (default): source_quote + source_ref only
                                      Full mode (--full-extraction): adds description/tags/type
parse_and_normalize.py       Step D:  normalize, validate, deduplicate → normalized JSONL (schema v2.0)
                                      Derives hierarchy fields from chunks.jsonl:
                                      section_ref_path, section_title_path, parent_section_ref,
                                      parent_context, child_section_refs
enrich_requirements.py       Step D.5: normalized JSONL → enriched JSONL  [Ollama: enrichment_model]
                                        Adds description, domain_tags, requirement_type via batched LLM calls
                                        Resumable by requirement_id; skipped with --skip-enrichment
aggregate_and_export.py      Step E:  stats aggregation → final_output.json + stats.json
                                      stats.json includes hierarchy coverage (with_section_path, with_parent_context)

--- Indexing ---
embed_and_index.py        Step F:  normalized/enriched JSONL → Qdrant grc_requirements
embed_context_index.py    Step F2: chunks JSONL              → Qdrant grc_context
ask.py                    Standalone query module (also callable from reqbot.py)
```

### Internal Import Graph

```
console.py
  └── config
  └── reqbot

reqbot.py
  └── config
  └── run_pipeline       (lazy, ingest/batch commands)
  └── embed_and_index    (lazy, ingest/index/batch/reindex commands)
  └── embed_context_index (lazy, ingest/batch/index-context commands)
  └── ask                (lazy, ask command)
  └── synthesis          (lazy, when --synthesize is used)

run_pipeline.py
  └── extract_pdf_to_text  (in-process; legacy path only)
  └── section_parser       (in-process; docling Step A — lazy import)
  └── chunk_text           (in-process; both legacy and docling Step B)
  └── llm_extract_requirements (in-process)
  └── parse_and_normalize  (in-process)
  └── enrich_requirements  (in-process; Step D.5 — skipped with --skip-enrichment)
  └── aggregate_and_export (in-process)

config.py          → (no internal imports)
synthesis.py       → (no internal imports; all third-party imports are lazy)
ask.py             → (no internal imports)
section_parser.py  → (no internal imports)
enrich_requirements.py → (no internal imports)
Steps A–E          → (no cross-imports between steps)
```

**Key constraint:** Pipeline steps (A–E) are intentionally isolated — they do not import each
other. `run_pipeline.py` is the only orchestrator. Do not add cross-imports between step scripts.

---

## External Dependencies

### Services (runtime)

| Service | Default URL | Used By | Purpose |
|---------|-------------|---------|---------|
| Ollama | `http://192.168.90.100:11434` | Steps C, F, F2; ask; reqbot (compare, evidence, trace) | LLM inference + dense embeddings |
| Qdrant | `http://192.168.30.153:6333` | Steps F, F2; ask; reqbot | Vector storage and hybrid search |
| Anthropic API | `https://api.anthropic.com` | synthesis.py (optional) | Remote synthesis fallback |
| OpenAI API | `https://api.openai.com` | synthesis.py (optional) | Remote synthesis fallback |

Both service URLs are configurable via `~/.config/reqbot/config.json` or environment variables
(`REQBOT_OLLAMA_URL`, `REQBOT_QDRANT_URL`). See [Configuration](#configuration) below.

### Python Packages

| Package | pip name | Used By | Notes |
|---------|----------|---------|-------|
| `fitz` | `pymupdf` | extract_pdf_to_text | Default PDF backend |
| `pdfplumber` | `pdfplumber` | extract_pdf_to_text | Optional; lazy import; table-aware backend |
| `docling` | `docling` | section_parser, chunk_text | Optional; lazy import; structure-aware backend (Phase 14) |
| `requests` | `requests` | llm_extract_requirements, reqbot | HTTP calls to Ollama REST API |
| `ollama` | `ollama` | ask, embed_and_index, embed_context_index, synthesis, reqbot | Ollama Python client |
| `fastembed` | `fastembed` | ask, embed_and_index, embed_context_index, reqbot | BM25 sparse embeddings (CPU-only) |
| `qdrant_client` | `qdrant-client` | ask, embed_and_index, embed_context_index, reqbot | Qdrant client |
| `anthropic` | `anthropic` | synthesis (optional) | Remote synthesis; lazy import |
| `openai` | `openai` | synthesis (optional) | Remote synthesis; lazy import |

**Install (dev/system Python):**
```bash
pip3 install --break-system-packages pymupdf pdfplumber fastembed qdrant-client ollama requests
# Optional for remote synthesis:
pip3 install --break-system-packages anthropic openai
```

### Models (Ollama)

| Model | Role | Pulled Via |
|-------|------|-----------|
| `llama3.1:8b-instruct-q4_K_M` | Step C extraction + query rewriting | `ollama pull llama3.1:8b-instruct-q4_K_M` |
| `nomic-embed-text` | Dense embeddings (768-dim) | `ollama pull nomic-embed-text` |
| `qwen2.5:14b` | Synthesis answers | `ollama pull qwen2.5:14b` |

---

## Data Flow

### Ingest Pipeline (PDF → Qdrant)

**Legacy path (`--layout-mode pymupdf` or `pdfplumber`):**

```
PDF file
  │
  ▼ Step A: extract_pdf_to_text.py
*_pages.jsonl          (one record per page: {page_num, text, source_pdf})
  │
  ▼ Step B: chunk_text.py  (sliding window, 3000 chars / 200 overlap; table-aware if pdfplumber)
*_chunks.jsonl
  │
  (continues to Step C below)
```

**Docling path (`--layout-mode docling`):**

```
PDF file
  │
  ▼ Step A: section_parser.py  (Docling DocumentConverter + iterate_items() traversal)
*_ancestry.json        (section ancestry map — section_ref_path, section_title_path, parent_context)
  + AncestryResult     (in-memory DoclingDocument, passed directly to Step B)
  │
  ▼ Step B: chunk_text.py  run_structure_aware()  (Docling HybridChunker + breadcrumb injection)
*_chunks.jsonl         (fields: raw_text, text, breadcrumb, section_ref_path,
                        section_title_path, parent_header_text, parent_context)
  │
  (continues to Step C below)
```

**Steps C–F (both paths):**

```
*_chunks.jsonl
  │
  ▼ Step C: llm_extract_requirements.py   [Ollama: extraction_model]
*_raw_responses.jsonl
*_extracted_requirements.jsonl   (Pass 1: source_quote + source_ref; prompt-hash-cached per model)
*_parse_failures.jsonl
  │
  ▼ Step D: parse_and_normalize.py
*_requirements_normalized.jsonl  (schema v2.0; validated, deduped, stable REQ-<12hex> IDs;
                                   hierarchy fields derived from chunks.jsonl:
                                   section_ref_path, section_title_path, parent_section_ref,
                                   parent_context, child_section_refs)
*_normalization_failures.jsonl
  │
  ▼ Step D.5: enrich_requirements.py  [Ollama: enrichment_model]  (skippable)
*_requirements_enriched.jsonl    (adds description, domain_tags, requirement_type)
  │
  ▼ Step E: aggregate_and_export.py
*_final_output.json
*_stats.json           (includes hierarchy coverage: with_section_path, with_parent_context)
  │
  ├─▶ Step F: embed_and_index.py          [Ollama: nomic-embed-text + fastembed BM25]
  │       └──▶ Qdrant: grc_requirements   (hybrid dense+sparse; payload includes all 5 hierarchy fields)
  │
  └─▶ Step F2: embed_context_index.py     [Ollama: nomic-embed-text + fastembed BM25]
          └──▶ Qdrant: grc_context        (hybrid dense+sparse, raw chunk text)
```

**Source of record:** JSONL files on disk. Qdrant is a rebuildable index — always rebuild from
JSONL via `reqbot reindex`, never treat Qdrant as authoritative.

### Query Flow (ask / compare / evidence)

```
User query string
  │
  ▼ Query rewriting   [Ollama: llama3.1:8b — expands query, extracts control IDs, detects domain tags]
Rewritten query + control ID hints
  │
  ▼ Hybrid search     [nomic-embed-text dense + fastembed BM25 sparse → RRF fusion]
Top-K results from Qdrant grc_requirements
  │
  ├─▶ (if --context) Fetch surrounding chunks from Qdrant grc_context
  │
  ▼ (if --synthesize) synthesis.py
    ├─▶ Local: Ollama qwen2.5:14b
    └─▶ Remote: Anthropic claude-sonnet-4-6 or OpenAI gpt-4o
  │
  ▼ Formatted output to stdout (or --output file for evidence)
```

---

## Qdrant Collections

| Collection | Contents | Vector Schema | Used By |
|------------|----------|---------------|---------|
| `grc_requirements` | Normalized requirement statements | 768-dim cosine (dense) + BM25 sparse, RRF fusion | ask, trace, compare, evidence |
| `grc_context` | Raw chunk text (Step B output) | Same hybrid schema | ask/trace/evidence --context |

Both collections use an atomic alias swap on reindex — the live collection is not touched until
all documents succeed. On failure, the temp collection is deleted.

---

## Configuration

Three-layer load order (later layers win):

```
1. Hardcoded defaults (config.py _DEFAULTS)
2. ~/.config/reqbot/config.json       ← written by reqbot init
3. Environment variables (REQBOT_*)
```

| Config Key | Env Var | Default |
|------------|---------|---------|
| `ollama_url` | `REQBOT_OLLAMA_URL` | `http://192.168.90.100:11434` |
| `qdrant_url` | `REQBOT_QDRANT_URL` | `http://192.168.30.153:6333` |
| `default_model` | `REQBOT_DEFAULT_MODEL` | `llama3.1:8b-instruct-q4_K_M` |
| `extraction_model` | `REQBOT_EXTRACTION_MODEL` | falls back to `default_model` |
| `enrichment_model` | `REQBOT_ENRICHMENT_MODEL` | falls back to `default_model` |
| `synthesis_model` | `REQBOT_SYNTHESIS_MODEL` | `qwen2.5:14b` |
| `top_k` | `REQBOT_TOP_K` | `20` |
| `min_score` | `REQBOT_MIN_SCORE` | `0.02` |
| `processed_dir` | `REQBOT_PROCESSED_DIR` | `~/documents/processed` |
| `synthesis_backend` | `REQBOT_SYNTHESIS_BACKEND` | `local` |

Optional files loaded at startup:
- `~/.config/reqbot/authority.json` — document authority weights (1–5 scale)

**Install directory** (`~/.reqbot/`) is wiped on upgrade. Config directory
(`~/.config/reqbot/`) is never touched by install/upgrade/uninstall.

---

## Entry Points

| Entry | How | Notes |
|-------|-----|-------|
| `reqbot` | Installed launcher → `reqbot.py` | CLI mode (subcommand) or shell mode (no args) |
| `python3 reqbot.py <cmd>` | Dev/source mode | Same behavior, no installer needed |
| `python3 run_pipeline.py <pdf>` | Direct pipeline run | Bypass reqbot for Step C resume with `--output-dir` |
| `python3 <step>.py` | Individual step | Each step is standalone with `--help` |

---

## What Breaks If You Change X

| Module | Dependents | Risk |
|--------|-----------|------|
| `config.py` | `reqbot.py`, `console.py` | Config schema changes break both entry points |
| `parse_and_normalize.py` (JSONL schema) | `embed_and_index.py`, `embed_context_index.py`, `reqbot.py` (trace/compare/evidence), `ask.py` | Schema version bump required; reindex needed |
| `embed_and_index.py` (vector schema) | `ask.py`, `reqbot.py` (all query commands) | Collection recreation required; full reindex needed |
| `ask.py` (search result format) | `reqbot.py` (ask, compare, evidence commands) | Result parsing in reqbot.py must match |
| `synthesis.py` API signature | `reqbot.py` (evidence, ask --synthesize) | Signature is: `synthesize(snippets, query, backend, model, ollama_url, provider, api_key)` |
| `run_pipeline.py` return value | `reqbot.py` (ingest, batch commands) | Returns path to normalized/enriched JSONL; change breaks auto-index |
| `section_parser.py` output fields | `chunk_text.py` `run_structure_aware()` | AncestryResult fields (item_ancestry, doc) must stay stable; chunk_text reads both |
| `chunk_text.py` chunk fields (docling) | `parse_and_normalize.py` `build_chunk_hierarchy_map()` | Hierarchy field names (section_ref_path etc.) must match what Step D reads from chunks.jsonl |
