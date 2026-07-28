# ReqBot Architecture

*Living document — update when adding modules, changing data flows, or modifying external dependencies.*

---

## What the System Does

ReqBot extracts cybersecurity compliance requirements from regulatory PDFs, indexes them into a
hybrid vector database, and provides a search/analysis interface for cross-framework compliance
research. It is designed to run entirely on local infrastructure (Ollama + Qdrant), with optional
remote synthesis via Anthropic or OpenAI APIs.

---

## Package Structure (Phase 16A+)

```
cli/
  reqbot.py      ← CLI entry point; argparse + cmd_* shims; display/formatting
  console.py     ← Interactive shell (cmd.Cmd); wraps reqbot.py commands

core/
  config.py      ← Configuration loader (stdlib only; no internal imports)
  constants.py   ← Shared constants (CONTEXT_UUID_NS namespace UUID)
  synthesis.py   ← LLM synthesis abstraction (local Ollama or remote API)
  ask.py         ← Standalone query module: hybrid search + RRF + query rewrite + HyDE
  profiles.py    ← list_profiles() → sorted list of profile names from profiles/*.json (Phase 22)

services/
  status_service.py     ← Ollama + Qdrant health checks; processed-doc listing
  docs_service.py       ← JSONL directory scan; document listing with counts/mode/date;
                           reads domain_profile from first JSONL record per doc
  trace_service.py      ← Requirement lookup by ID; cross-framework matches; context window
  compare_service.py    ← Exact control-ID match + hybrid semantic search; grouped results
  evidence_service.py   ← Hybrid search + grouping + context retrieval + LLM synthesis
  ask_service.py        ← Thin orchestration over core/ask.retrieve(); returns canonical API shape
  checklist_service.py  ← generate(processed_dir, doc_key, profile_name) → ChecklistEnvelope dict;
                           source resolution: prefers *_requirements_enriched.jsonl (Step D.5) within
                           latest run dir; CONFIDENCE_REVIEW_THRESHOLD = 0.8; deterministic
                           checklist_item_id derived from requirement_id (Phase 21)

api/
  app.py         ← FastAPI application; registers routers; CORS for localhost GUI origins
                   _SPA_PREFIXES = ("checklists/", "corpus/", "trace/") — prefix check before
                   Path.suffix guard in spa_fallback so dotted doc_keys (e.g. NIST.SP.800-53r5)
                   don't 404 on direct load/refresh
  routes/
    ask.py       ← POST /api/ask              → ask_service.ask(); validates AskRequest; RuntimeError → 503
    compare.py   ← POST /api/compare          → compare_service.compare(); RuntimeError → 503
    evidence.py  ← POST /api/evidence         → evidence_service.evidence(); RuntimeError → 503
    docs.py      ← GET /api/docs              → docs_service.list_docs(); exceptions → 503
    status.py    ← GET /api/status            → status_service.check(); exceptions → 503
    trace.py     ← GET /api/trace/{req_id}    → trace_service.trace(); ValueError → 404, RuntimeError → 503
    checklist.py ← GET /api/profiles          → core.profiles.list_profiles(); exceptions → 503
                   POST /api/checklist        → checklist_service.generate(); FileNotFoundError → 400/503, ValueError → 404
                   POST /api/checklist/export → checklist_export.to_{format}(); format: csv/json/markdown;
                                                Content-Disposition: attachment
  (Swagger UI at /api-docs; /docs reserved for the document-listing endpoint)

pipeline/
  run_pipeline.py              ← Pipeline orchestrator (Steps A–E + D.5)
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
                                        Pass 1 (only mode): source_quote + source_ref only —
                                        description/domain_tags/requirement_type come from
                                        Step D.5 enrichment, not Step C
  parse_and_normalize.py       Step D:  normalize, validate, deduplicate → normalized JSONL (schema v2.0)
                                        Derives hierarchy fields from chunks.jsonl:
                                        section_ref_path, section_title_path, parent_section_ref,
                                        parent_context, child_section_refs
  enrich_requirements.py       Step D.5: normalized JSONL → enriched JSONL  [Ollama: enrichment_model]
                                          Adds description, domain_tags, requirement_type via batched LLM calls
                                          Resumable by requirement_id; skipped with --skip-enrichment
  aggregate_and_export.py      Step E:  stats aggregation → final_output.json + stats.json
                                        stats.json includes hierarchy coverage (with_section_path, with_parent_context)
  embed_and_index.py           Step F:  normalized/enriched JSONL → Qdrant grc_requirements
  embed_context_index.py       Step F2: chunks JSONL              → Qdrant grc_context
  checklist_export.py          (Phase 21): to_csv() / to_json() / to_markdown() from ChecklistItem list;
                                           formula injection prevention via _csv_safe() (prefixes =,+,-,@);
                                           CSV column order: locate → ask → record → verify → trace

models/            ← Shared data schemas (populated in Phase 16C+)

frontend/          ← React + TypeScript + Tailwind web GUI (Phase 18+)
  package.json     ← dependencies: react, react-router-dom, tailwindcss
  vite.config.ts   ← Vite bundler; dev proxy /api → :8000; no custom base
  src/
    App.tsx        ← BrowserRouter + Routes:
                      /                     → redirect to /search
                      /search               → SearchView
                      /compare              → CompareView
                      /evidence             → EvidenceView
                      /corpus               → CorpusView
                      /corpus/:docId        → CorpusDetailView
                      /system               → SystemView
                      /checklists           → ChecklistsView
                      /checklists/:docId    → ChecklistPreviewView  (?profile= query param)
                      /docs                 → redirect to /corpus   (legacy bookmark compat)
                      /trace/:reqId         → TraceView
                      *                     → NotFoundView
    api/
      client.ts    ← typed fetch wrappers: ask, trace, docs, status, compare, evidence,
                      profiles(), checklist(), checklistExport() (Phase 22)
      types.ts     ← TypeScript types mirroring API contract; Phase 22 additions:
                      ChecklistRequest, ChecklistItem, ChecklistEnvelope,
                      ProfilesResponse, ChecklistExportRequest, DocsEntry.profile
    views/
      SearchView.tsx        ← query + doc filter + results; URL-driven state (?q=&doc=)
      TraceView.tsx         ← full requirement detail + cross-matches + context expand;
                               back-link derives label from route state (not hardcoded)
      CompareView.tsx       ← two-doc topic comparison; three result sections; URL-driven (?doc1=&doc2=&topic=)
      EvidenceView.tsx      ← topic → requirements grouped by control/citation reference
                               (source_ref); synthesis; URL-driven
      CorpusView.tsx        ← corpus browse; name filter + sort; rows link to /corpus/:docId
                               (renamed from DocsView.tsx in Phase 22; /docs redirects here)
      CorpusDetailView.tsx  ← single-doc detail; Search/Compare quick actions;
                               "Generate checklist" link → /checklists?doc=<docId> (Phase 22)
      SystemView.tsx        ← renders /api/status as Ollama/Qdrant readiness rows (Phase 22)
      ChecklistsView.tsx    ← /checklists generate screen; DocPicker + ProfilePicker;
                               ProfilePicker populated from GET /api/profiles (never hardcoded);
                               profilesLoaded bool gates canSubmit; navigate-only on submit (Phase 22)
      ChecklistPreviewView.tsx ← /checklists/:docId preview screen; fetches POST /api/checklist
                                  on mount from URL params (refresh-safe); flaggedOnly toggle
                                  resets on docId/profile change; separate empty states (Phase 22)
      NotFoundView.tsx      ← catch-all 404 view
    components/
      AppShell.tsx          ← flex layout wrapper: sticky SidebarNav + flex-1 content area (Phase 22)
      SidebarNav.tsx        ← w-52 sticky sidebar; active: Search/Compare/Evidence/Checklists/Corpus/System
                               (replaces NavBar.tsx which was deleted in Phase 22)
      ChecklistTable.tsx    ← 13-column table; 5 group headers (Locate/Ask/Record/Verify/Trace);
                               overflow-x: auto; flagged rows bg-amber-50; source_quote missing →
                               amber [MISSING SOURCE QUOTE] warning; scope attrs for accessibility (Phase 22)
      ExportButtonGroup.tsx ← "Export ▾" dropdown (CSV/JSON/Markdown/XLSX); fetch+Blob+anchor click;
                               filename from Content-Disposition; per-format loading state (Phase 22/23)
      ReviewFlagBadge.tsx   ← amber "Review needed" badge + reasons list (Phase 22)
      SystemHealthPanel.tsx ← renders Ollama/Qdrant status rows from /api/status (Phase 22)
      ResultCard.tsx        ← result row; passes router state for back-link preservation
      StatusDot.tsx         ← polls /api/status every 30s; links to /system page
      ErrorBanner.tsx       ← shared inline error display
      SynthesisBox.tsx      ← shared LLM synthesis output block (elapsed timer, loading state)
      LoadingSpinner.tsx
    hooks/
      useSynthesis.ts  ← generation-counter race protection; run(fetcher) / reset(); elapsed timer
    utils/
      ui.ts        ← docValue(doc): canonical doc identifier (prefers source_pdf, falls back to doc_key);
                      pageRange(); other shared helpers
  dist/            ← Vite production build output (gitignored; served by reqbot serve)
```

**Build:** `bash build/build-frontend.sh` (npm ci + npm run build → frontend/dist/).
`reqbot serve` detects dist/index.html and serves the GUI; falls back to API-only mode if absent.
The Docker image (Phase 25, WP-25.3) builds this in its own `node:20` stage and copies
the result in as package data — see `Dockerfile`.

Each package contains an `__init__.py`. Entry points defensively insert the repo root onto
`sys.path` at startup, so imports resolve the same way whether running from a source
checkout or an installed `reqbot` package (`pip install .`, Phase 25 WP-25.2).

### Internal Import Graph

```
cli/console.py
  └── core.config
  └── cli.reqbot

cli/reqbot.py
  └── core.config
  └── services.status_service      (lazy, status + setup commands)
  └── services.docs_service        (lazy, docs command)
  └── services.trace_service       (lazy, trace command)
  └── services.compare_service     (lazy, compare command)
  └── services.evidence_service    (lazy, evidence command)
  └── services.checklist_service   (lazy, checklist command)
  └── pipeline.checklist_export    (lazy, checklist command — to_csv/to_json/to_markdown/to_xlsx)
  └── pipeline.run_pipeline        (lazy, ingest/batch commands)
  └── pipeline.embed_and_index     (lazy, ingest/index/batch/reindex commands)
  └── pipeline.embed_context_index (lazy, ingest/batch/index-context commands)
  └── core.ask                     (lazy, ask command)
  └── core.synthesis               (lazy, when --synthesize is used)
  └── api.app + uvicorn            (lazy, serve command — ImportError-guarded)

services/*.py
  └── (no cross-service imports)
  └── core.synthesis   (evidence_service only — LLM auditor summary)
  └── core.ask         (ask_service only — calls core.ask.retrieve())
  └── core.constants   (trace_service, evidence_service — CONTEXT_UUID_NS)

api/app.py
  └── api.routes.ask
  └── api.routes.docs
  └── api.routes.status
  └── api.routes.trace
  └── api.routes.checklist

api/routes/ask.py          → core.config, services.ask_service
api/routes/compare.py      → core.config, services.compare_service
api/routes/evidence.py     → core.config, services.evidence_service
api/routes/docs.py         → core.config, services.docs_service
api/routes/status.py       → services.status_service
api/routes/trace.py        → core.config, services.trace_service
api/routes/checklist.py    → core.config, services.checklist_service,
                             pipeline.checklist_export, core.profiles

pipeline/run_pipeline.py
  └── pipeline.extract_pdf_to_text  (in-process; legacy path only)
  └── pipeline.section_parser       (in-process; docling Step A — lazy import)
  └── pipeline.chunk_text           (in-process; both legacy and docling Step B)
  └── pipeline.llm_extract_requirements (in-process)
  └── pipeline.parse_and_normalize  (in-process)
  └── pipeline.enrich_requirements  (in-process; Step D.5 — skipped with --skip-enrichment)
  └── pipeline.aggregate_and_export (in-process)

pipeline/chunk_text.py
  └── pipeline.section_parser  (lazy; docling path only)

core/config.py     → (no internal imports)
core/constants.py  → (no internal imports; stdlib uuid only)
core/synthesis.py  → (no internal imports; all third-party imports are lazy)
core/ask.py        → core.synthesis   (lazy, --synthesize only)
               → core.constants   (CONTEXT_UUID_NS for grc_context lookup)
pipeline/section_parser.py  → (no internal imports)
pipeline/enrich_requirements.py → (no internal imports)
Steps A–E          → (no cross-imports between steps; run_pipeline.py is the sole orchestrator)
```

**Key constraint:** Pipeline steps (A–E) are intentionally isolated — they do not import each
other. `run_pipeline.py` is the only orchestrator. Do not add cross-imports between step scripts.

**Docling exception (in-memory pass-through):** In the docling path, `run_pipeline.py` passes
an in-memory `AncestryResult` object from `section_parser.py` (Step A) directly to
`chunk_text.py` (Step B). This avoids a redundant second PDF parse but is a deliberate
exception to the JSONL-only inter-step communication pattern. The `_ancestry.json` file is
still written to disk as a durable artifact; the in-memory object is an optimization, not a
replacement for it. All other step boundaries remain JSONL-only.

---

## External Dependencies

### Services (runtime)

| Service | Default URL | Used By | Purpose |
|---------|-------------|---------|---------|
| Ollama | `http://localhost:11434` | Steps C, F, F2; ask; reqbot (compare, evidence, trace) | LLM inference + dense embeddings |
| Qdrant | `http://localhost:6333` | Steps F, F2; ask; reqbot | Vector storage and hybrid search |
| Anthropic API | `https://api.anthropic.com` | synthesis.py (optional) | Remote synthesis fallback |
| OpenAI API | `https://api.openai.com` | synthesis.py (optional) | Remote synthesis fallback |

Both service URLs are configurable via `~/.config/reqbot/config.json` or environment variables
(`REQBOT_OLLAMA_URL`, `REQBOT_QDRANT_URL`). See [Configuration](#configuration) below.

### Python Packages

| Package | pip name | Used By | Notes |
|---------|----------|---------|-------|
| `fitz` | `pymupdf` | extract_pdf_to_text | `--layout-mode` fallback backend -- always installed; used when `auto` can't find docling, or when passed explicitly |
| `pdfplumber` | `pdfplumber` | extract_pdf_to_text | Optional; lazy import; table-aware backend |
| `docling` | `docling` | section_parser, chunk_text | Optional; lazy import; structure-aware backend (Phase 14); `--layout-mode` default (`auto`) uses this when installed (WP, PR #147) |
| `requests` | `requests` | llm_extract_requirements, reqbot | HTTP calls to Ollama REST API |
| `ollama` | `ollama` | core/ask, embed_and_index, embed_context_index, synthesis, services/compare_service, services/evidence_service | Ollama Python client |
| `fastembed` | `fastembed` | core/ask, embed_and_index, embed_context_index, services/compare_service, services/evidence_service | BM25 sparse embeddings (CPU-only) |
| `qdrant_client` | `qdrant-client` | core/ask, embed_and_index, embed_context_index, services/trace_service, services/compare_service, services/evidence_service | Qdrant client |
| `anthropic` | `anthropic` | core/synthesis (optional) | Remote synthesis; lazy import |
| `openai` | `openai` | core/synthesis (optional) | Remote synthesis; lazy import |
| `fastapi` | `fastapi` | api/ | REST API framework (Phase 16C+) |
| `uvicorn` | `uvicorn` | cli/reqbot.py serve | ASGI server; lazy import; only needed for `reqbot serve` |
| `aiofiles` | `aiofiles` | Starlette dep tree | Explicit pin; pulled in by Starlette; Phase 18+ |

**Install (dev/system Python):**
```bash
pip3 install --break-system-packages -r requirements.txt
# Optional for remote synthesis:
pip3 install --break-system-packages anthropic openai
```

**Frontend build deps (dev machine only — end users receive pre-built dist/):**

| Tool | Version | Purpose |
|------|---------|---------|
| Node.js | 20 LTS | JavaScript runtime for Vite build |
| npm | 10+ | Package manager (lockfile committed) |
| Vite | 5 | Bundler + dev server |
| TypeScript | 5 | Type checking |
| Tailwind CSS | 3 | Utility-first CSS (purged at build time) |

### Models (Ollama)

ReqBot needs several model **roles** configured against your Ollama endpoint: embedding,
extraction, enrichment, query-rewrite/HyDE, and optional synthesis. None of them are pulled
automatically by `reqbot init`/`setup` (WP-25.1b) — Ollama and its models are expected to already
exist before you run `init`; pull manually with `ollama pull <model>`.

The defaults below are what's validated on Tyler's own consumer-grade hardware — a recommended
starting point, not a universal requirement. Nothing about ReqBot's design assumes these specific
models; any Ollama-compatible model that fits a role works, subject to the configurability caveats
below.

| Role | Recommended default | Configurable? |
|------|---------------------|---------------|
| Embedding | `nomic-embed-text` | Yes (WP-25.6c) — `embedding_model` in `reqbot init` or config, independent of `default_model` (it defines the vector shape already stored in Qdrant, so it never silently inherits a `default_model` change the way extraction/enrichment/rewrite do). Changing it is still the highest-risk config edit in the system: it takes effect on the *next* index/reindex, not retroactively — a full `reqbot reindex` is required afterward to bring existing points onto the new model. Every indexed point carries `embedding_model` + `embedding_dim` in its Qdrant payload as provenance; query time (`ask`/`compare`/`evidence`) compares each result's provenance against the currently configured model and surfaces a non-blocking `warnings` entry on mismatch rather than silently returning wrong-but-confident results. Qdrant's own vector-dimension check still applies on top of this — switching to a model with a different dimension than the collection's current one fails loudly and immediately. |
| Extraction | `llama3.1:8b-instruct-q4_K_M` | Yes — `extraction_model` in `reqbot init` or config. Advanced users may point this at a different model. |
| Enrichment | `llama3.1:8b-instruct-q4_K_M` | Yes — `enrichment_model` in `reqbot init` or config. Advanced users may point this at a different model. |
| Query rewrite / HyDE | `llama3.1:8b-instruct-q4_K_M` | Yes (WP-25.6b) — `rewrite_model` in `reqbot init` or config, same `REQBOT_REWRITE_MODEL` env-var pattern and default-model fallback as extraction/enrichment. `--rewrite-model` in `cli/reqbot.py` overrides it per-call; unset, it defers to config instead of a second hardcoded literal. |
| Local synthesis (optional) | `qwen2.5:14b` | Yes — `synthesis_model` in `reqbot init` or config. Only relevant when the synthesis backend is `local`. Not pulled by `init` or automatically at any point (~9 GB) — if it's missing on the configured Ollama server, synthesis fails clearly at call time naming the model and the `ollama pull` command to fix it, rather than silently downloading it. |

**Qdrant data path (Docker-managed):** `~/.local/share/reqbot/qdrant/` — XDG Base Directory, outside the
installer-managed `~/.reqbot/` tree so it survives installer upgrades without exclusion logic.

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

### Query Flow (ask / compare / evidence / GUI)

```
Browser (SearchView)            CLI (reqbot ask)
  │  POST /api/ask                │  cmd_ask()
  │                               │
  └──────────────┬────────────────┘
                 ▼
        ask_service.ask()
                 │
                 ▼
        core/ask.retrieve()
                 │
  ▼ Query rewriting   [Ollama: llama3.1:8b — expands query, extracts control IDs, detects domain tags]
Rewritten query + control ID hints
  │
  ▼ Hybrid search     [nomic-embed-text dense + fastembed BM25 sparse → RRF fusion]
Top-K results from Qdrant grc_requirements
  │
  ├─▶ (if context=true / --context) Fetch surrounding chunks from Qdrant grc_context
  │
  ▼ (if --synthesize CLI, or "Generate Answer" GUI button) synthesis.py
    ├─▶ Local: Ollama qwen2.5:14b
    └─▶ Remote: Anthropic claude-sonnet-4-6 or OpenAI gpt-4o
  │
  ├─▶ CLI: Formatted output to stdout (or --output file for evidence)
  └─▶ GUI: JSON → SearchView results list → TraceView on click
```

**GUI-specific flows (Phase 18–19):**
- `GET /api/trace/{req_id}` → `trace_service.trace()` → TraceView (full detail + cross-matches)
- `GET /api/trace/{req_id}?context=true` → same service, triggers context window fetch from grc_context
- `POST /api/compare` → `compare_service.compare()` → CompareView (exact + semantic matches, three sections)
- `POST /api/evidence` → `evidence_service.evidence()` → EvidenceView (grouped requirements + synthesis)
- `GET /api/docs` → `docs_service.list_docs()` → CorpusView (corpus browse) + SearchView doc filter dropdown
- `GET /api/status` → `status_service.check()` → StatusDot (polls every 30s) + SystemView health panel

**GUI-specific flows (Phase 22 — checklist workflow):**
- `GET /api/profiles` → `core.profiles.list_profiles()` → ChecklistsView ProfilePicker
- `POST /api/checklist` → `checklist_service.generate()` → ChecklistPreviewView table render
- `POST /api/checklist/export` → `checklist_export.to_{format}()` → file download via fetch+Blob+anchor click
  (format: csv / json / markdown; filename from Content-Disposition header; never window.location.href)

---

## Qdrant Collections

| Collection | Contents | Vector Schema | Used By |
|------------|----------|---------------|---------|
| `grc_requirements` | Normalized requirement statements | cosine dense + BM25 sparse, RRF fusion | ask, trace, compare, evidence |
| `grc_context` | Raw chunk text (Step B output) | Same hybrid schema | ask/trace/evidence --context |

Dense vector dimension is derived from the configured `embedding_model`'s actual output at
collection-creation time (WP-25.6c), not a hardcoded constant — `nomic-embed-text` (the default)
happens to be 768-dim, but collection creation is deferred until the first successful embedding
comes back so a differently-sized model still produces a correctly-shaped collection.

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
| `ollama_url` | `REQBOT_OLLAMA_URL` | `http://localhost:11434` |
| `qdrant_url` | `REQBOT_QDRANT_URL` | `http://localhost:6333` |
| `default_model` | `REQBOT_DEFAULT_MODEL` | `llama3.1:8b-instruct-q4_K_M` |
| `extraction_model` | `REQBOT_EXTRACTION_MODEL` | falls back to `default_model` |
| `enrichment_model` | `REQBOT_ENRICHMENT_MODEL` | falls back to `default_model` |
| `rewrite_model` | `REQBOT_REWRITE_MODEL` | falls back to `default_model` |
| `synthesis_model` | `REQBOT_SYNTHESIS_MODEL` | `qwen2.5:14b` |
| `embedding_model` | `REQBOT_EMBEDDING_MODEL` | `nomic-embed-text` (independent of `default_model`) |
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
| `reqbot` | Installed launcher → `cli/reqbot.py` | CLI mode (subcommand) or shell mode (no args) |
| `python3 cli/reqbot.py <cmd>` | Dev/source mode | Same behavior, no installer needed |
| `reqbot init` | Config wizard | One-shot first-run setup: configures Qdrant/Ollama URLs and model/synthesis preferences, writes config. Does not install or manage either service. Operational bootstrap — not part of pipeline or retrieval. |
| `reqbot setup [--advanced]` | Deprecated alias | Delegates to `reqbot init` verbatim; `--advanced` is a no-op. |
| `reqbot serve [--host H] [--port P]` | API server | Starts uvicorn on 127.0.0.1:8000; Swagger at /api-docs |
| `python3 pipeline/run_pipeline.py <pdf>` | Direct pipeline run | Bypass reqbot for Step C resume with `--output-dir` |
| `python3 pipeline/<step>.py` | Individual step | Each step is standalone with `--help` |

---

## What Breaks If You Change X

| Module | Dependents | Risk |
|--------|-----------|------|
| `core/config.py` | `cli/reqbot.py`, `cli/console.py`, all services | Config schema changes break all entry points and services |
| `pipeline/parse_and_normalize.py` (JSONL schema) | `pipeline/embed_and_index.py`, `pipeline/embed_context_index.py`, `services/trace_service.py`, `services/compare_service.py`, `services/evidence_service.py`, `core/ask.py` | Schema version bump required; reindex needed |
| `pipeline/embed_and_index.py` (vector schema) | `core/ask.py`, all services that query Qdrant | Collection recreation required; full reindex needed |
| `core/ask.py` (search result format) | `cli/reqbot.py` cmd_ask | Result format from `ask.run()` drives CLI display |
| `core/ask.retrieve()` return dict keys | `services/ask_service.py` | ask_service reads `results`, `synthesis_text`, `total`, `retrieval_ms` — adding keys is safe, removing/renaming is breaking |
| `services/ask_service.py` response shape | `api/routes/ask.py` | API contract: `query`, `filters`, `results`, `metadata.{top_k,result_count,retrieval_ms,synthesis}` — treat as versioned from Phase 16C |
| `api/routes/*.py` response shapes | future GUI / frontend consumers | API responses are versioned from day one per Phase 16 design principles |
| `core/synthesis.py` API signature | `services/evidence_service.py`, `core/ask.py` (--synthesize) | Signature: `synthesize(question, evidence, backend, model, ollama_url, provider, api_key, raw_prompt)` |
| `pipeline/run_pipeline.py` return value | `cli/reqbot.py` cmd_ingest, cmd_batch | Returns path to normalized/enriched JSONL; change breaks auto-index |
| `pipeline/section_parser.py` output fields | `pipeline/chunk_text.py` `run_structure_aware()` | AncestryResult fields (item_ancestry, doc) must stay stable; chunk_text reads both |
| `pipeline/chunk_text.py` chunk fields (docling) | `pipeline/parse_and_normalize.py` `build_chunk_hierarchy_map()` | Hierarchy field names (section_ref_path etc.) must match what Step D reads from chunks.jsonl |
| `pipeline/checklist_export.py` column order / field names | `api/routes/checklist.py`, `cli/reqbot.py` cmd_checklist | CSV column order and JSON field names are part of the export contract; changing them breaks existing assessor tooling |
| `services/checklist_service.py` return shape (ChecklistEnvelope) | `api/routes/checklist.py`, `cli/reqbot.py` cmd_checklist | `items`, `summary`, `doc_key`, `profile` keys are consumed by both route and CLI; `checklist_item_id` must remain deterministic from `requirement_id` |
| `core/profiles.py` `list_profiles()` | `api/routes/checklist.py` GET /api/profiles | ProfilePicker in ChecklistsView is populated entirely from this response; an empty list blocks checklist generation in the browser |
| Service return schemas | `cli/reqbot.py` cmd_* display logic | Services return structured dicts; CLI display code unpacks specific keys — adding/renaming keys is safe, removing is breaking |
