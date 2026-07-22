# ReqBot

ReqBot is a local-first compliance requirements intelligence engine. It extracts cybersecurity requirements from regulatory PDFs, stores the pipeline artifacts as JSONL, indexes the results into Qdrant, and provides a CLI, interactive shell, and web GUI for search and trace.

Everything is designed to run on local infrastructure with Ollama + Qdrant. JSONL is the system of record; Qdrant is a rebuildable index.

Run `reqbot serve` to start the web interface. Run `reqbot docs` to see your indexed documents and requirement counts.

## What It Does

- Extracts requirement statements from PDFs with a two-pass pipeline.
- Preserves document hierarchy (section breadcrumbs, parent context, section ref paths) through the full pipeline.
- Separates extraction and enrichment models so each stage can be tuned independently.
- Supports hybrid retrieval over requirements plus optional raw chunk context lookup.
- Rebuilds Qdrant from existing JSONL without re-running extraction.
- Generates compliance checklists from indexed documents — via CLI or browser.
- Serves a web GUI (`reqbot serve`) — search, trace, compare, generate checklists, and export in a browser.

## Requirements

- Python 3.12+
- Docker (only needed if you have `reqbot init` bootstrap Qdrant locally)
- [Ollama](https://ollama.ai/) (only needed if you have `reqbot init` bootstrap it locally)
- Python dependencies:

```bash
pip3 install --break-system-packages -r requirements.txt
```

## Setup

Run once on a fresh machine:

```bash
reqbot init
```

This asks, per service, whether to use an existing instance or set one up locally:

- **Qdrant** — point at an existing URL, or have `reqbot init` start a local Docker container.
- **Ollama** — point at an existing URL, or have `reqbot init` install it locally and pull the
  two core models (`nomic-embed-text` ~274 MB for embeddings; `llama3.1:8b-instruct-q4_K_M`
  ~4.7 GB for extraction/query rewriting/HyDE). These are needed for local pipeline work
  regardless of where answer synthesis happens.
- **Synthesis** — Local Ollama, Remote (Claude/GPT-4o), or None (retrieval-only; `--synthesize`
  returns no generated answer). The synthesis model (`qwen2.5:14b`, ~9 GB) is **not** pulled
  during setup if you choose local — it downloads automatically the first time you run
  `--synthesize`.

The two service choices are independent — e.g. an existing managed Qdrant plus a locally
bootstrapped Ollama, or vice versa, both work.

`reqbot setup` still works as a deprecated alias for `reqbot init` (existing scripts/docs
referencing it won't break), but `reqbot init` is the one documented first-run path.

## Quick Start

```bash
# Web interface (search + trace in a browser)
reqbot serve          # then open http://localhost:8000

# Interactive shell
reqbot

# Query indexed requirements
reqbot ask "What are the access control requirements?"
reqbot ask "encryption at rest" --synthesize --context

# Inspect corpus / system state
reqbot docs
reqbot status

# Ingest a PDF (indexes into Qdrant by default)
reqbot ingest path/to/doc.pdf
```

## Core Commands

### `ask`

Search indexed requirements and optionally synthesize an answer.

```bash
reqbot ask "question" [options]
```

Common options:

- `--synthesize` - generate an LLM answer instead of retrieval-only output
- `--context` - include surrounding raw chunk text from `grc_context` (retrieval-time only; does not affect indexing)
- `--top-k N` - number of results
- `--min-score F` - minimum RRF score threshold
- `--model M` - synthesis model
- `--domain-tag T` - filter by domain tag, repeatable
- `--requirement-type T` - filter by requirement type, repeatable
- `--document-id D` - filter by document, repeatable
- `--json` - emit JSON
- `--no-rewrite` - disable query rewriting
- `--rewrite-model M` - model for query rewriting
- `--no-hyde` - disable HyDE (Hypothetical Document Embedding) retrieval augmentation; falls
  back to baseline dense + BM25 RRF only. HyDE is on by default — it generates a hypothetical
  requirement statement and adds its embedding as a third RRF leg, and passed its Phase 15
  evaluation gate (≥3 queries improved, none degraded, no hallucinated IDs). `--no-rewrite` and
  `--no-hyde` are independent controls; the fastest pre-Phase-24 retrieval behavior is both
  flags together.

### `ingest`

Run the extraction pipeline on a single PDF. Indexes into Qdrant (both
`grc_requirements` and `grc_context`) by default.

```bash
reqbot ingest <pdf> [options]
```

Important options:

- `--no-index` - skip indexing, write pipeline artifacts only (debug/inspection)
- `--layout-mode {pymupdf,pdfplumber,docling}` - PDF extraction backend
- `--output-dir DIR` - write artifacts to a specific directory
- `--extraction-model M` - Step C model
- `--enrichment-model M` - Step D.5 model
- `--model M` - convenience alias that sets both extraction and enrichment models
- `--skip-enrichment` - skip Pass 2 enrichment and index Pass 1 output directly
- `--max-chunks N` - limit Step C processing for testing

### `batch`

Run the pipeline on every PDF in a directory.

```bash
reqbot batch <pdf_dir> [options]
```

Supports the same `--layout-mode`, model, and enrichment flags as `ingest`.

### `reindex`

Rebuild `grc_requirements` and `grc_context` from the most recent processed artifacts for
each document.

```bash
reqbot reindex                    # rebuilds both collections
reqbot reindex --requirements-only  # fast path — requirements only, skips context
```

This does not re-run extraction. It rebuilds from existing JSONL/chunk artifacts using an
atomic temp-collection + alias swap for both collections, so the live index is never touched
until indexing succeeds. Prefers `*_requirements_enriched.jsonl` over
`*_requirements_normalized.jsonl` per document when both exist. `--requirements-only` skips
the slower, CPU-bound `grc_context` rebuild — useful when only requirement JSONL changed.

### `index`

Embed and index an existing normalized JSONL file.

```bash
reqbot index <requirements_normalized.jsonl> [--recreate] [--batch-size N]
```

### `index-context`

Embed and index Step B chunk text into the `grc_context` collection.

```bash
reqbot index-context <chunks.jsonl> [--document-id ID] [--source-pdf NAME] [--recreate]
```

### `compare`

Compare requirements across two indexed documents.

```bash
reqbot compare <doc_id_1> <doc_id_2> "topic"
```

### `evidence`

Generate evidence mappings for a topic or control.

```bash
reqbot evidence "topic or control" [--domain-tag T] [--requirement-type T]
```

### `checklist`

Generate a compliance checklist for an indexed document.

```bash
reqbot checklist --doc <doc_key> --profile <profile> [--format {csv,json,md,xlsx}] [--output FILE]
```

Options:

- `--doc` - document key (from `reqbot docs`)
- `--profile` - profile name (e.g. `cybersecurity`)
- `--format` - output format; default `csv`
- `--output` - write to file instead of stdout

The same checklist is available from the browser via the Checklists screen.

### `init`

Guided first-run setup — asks, per service, whether to use an existing Qdrant/Ollama instance
or bootstrap one locally, then configures models and synthesis (local, remote, or none).

```bash
reqbot init
```

Writes `~/.config/reqbot/config.json`.

### `setup`

Deprecated alias for `init` — runs the same guided flow. `--advanced` is accepted but is a
no-op (kept for backward compatibility with older scripts/docs).

```bash
reqbot setup            # same as: reqbot init
reqbot setup --advanced # same as: reqbot init
```

### `docs`

List indexed documents and requirement counts.

```bash
reqbot docs
```

### `serve`

Start the API server and web GUI.

```bash
reqbot serve [--host H] [--port P]
```

Defaults to `127.0.0.1:8000`. Opens a browser-accessible interface at `http://localhost:8000`:

- **Search** — query the corpus, filter by document, click through to trace
- **Trace** — full requirement detail: description, source quote, provenance, cross-framework matches, optional source context expansion
- **Compare** — side-by-side topic comparison across two documents (exact + semantic matches)
- **Evidence** — topic → requirements grouped by document, with optional LLM synthesis
- **Corpus** — browse the indexed corpus; filter and sort; drill into a single document; launch checklist generation from a document detail page
- **Checklists** — pick a document and profile, generate a checklist, preview all items in a grouped table (Locate / Ask / Record / Verify / Trace), and export as CSV, JSON, Markdown, or XLSX
- **System** — Ollama and Qdrant health status

The API is always available at `/api/` regardless of whether the frontend build is present. Swagger UI at `/api-docs`.

### `status`

Run a system health check.

```bash
reqbot status
```

## Pipeline Overview

ReqBot uses a two-pass extraction pipeline by default.

| Step | Script | Input | Output | LLM? |
|---|---|---|---|---|
| A | `extract_pdf_to_text.py` | PDF | `*_pages.jsonl` | No |
| B | `chunk_text.py` | pages JSONL (legacy) or ancestry map (docling) | `*_chunks.jsonl` | No |
| C | `llm_extract_requirements.py` | chunks JSONL | `*_extracted_requirements.jsonl` | Yes |
| D | `parse_and_normalize.py` | extracted requirements JSONL | `*_requirements_normalized.jsonl` | No |
| D.5 | `enrich_requirements.py` | normalized JSONL | `*_requirements_enriched.jsonl` | Yes |
| E | `aggregate_and_export.py` | normalized or enriched JSONL | `*_final_output.json`, `*_stats.json` | No |
| F | `embed_and_index.py` | normalized or enriched JSONL | Qdrant `grc_requirements` | No |
| F2 | `embed_context_index.py` | chunks JSONL | Qdrant `grc_context` | No |

Default behavior:

- Step C runs in Pass 1 mode and extracts `source_quote` + `source_ref`.
- Step D validates and deduplicates.
- Step D.5 enriches with `description`, `domain_tags`, and `requirement_type`.
- `reqbot ingest` indexes both requirements and chunk context after the pipeline completes;
  `--no-index` skips indexing for artifact-only/debug runs.

Advanced behavior:

- `--skip-enrichment` keeps the pipeline in Pass 1 only.

## Layout-Aware Extraction

ReqBot supports three PDF extraction backends via `--layout-mode`.

**`pymupdf` (default)** — fast text extraction for prose-heavy documents (NIST SPs, AFIs, DAF manuals).

**`pdfplumber`** — table-aware extraction for documents with structured tables (DODIs, DoDMs):

```bash
reqbot ingest "DODI 5200.01_vol2.pdf" --layout-mode pdfplumber
```

- extracts tables as structured rows
- preserves table boundaries during chunking
- falls back per page if table extraction fails

**`docling`** — structure-aware chunking that preserves section hierarchy:

```bash
reqbot ingest "NIST.SP.800-53r5.pdf" --layout-mode docling
```

- parses document structure with Docling's `DocumentConverter`
- injects breadcrumbs (`section_title_path`, `section_ref_path`) into each chunk
- attaches `parent_context` (first ~600 chars of the parent section body) to each requirement
- filters table-of-contents noise automatically
- produces schema v2.0 records with full hierarchy fields
- **required** for profile `skip_sections` filtering to take effect — legacy `pymupdf`/
  `pdfplumber` chunking has no section hierarchy to filter on, so `skip_sections` is a no-op
  under those two modes

## Qdrant Collections

| Collection | Contents | Used By |
|---|---|---|
| `grc_requirements` | extracted requirements | `ask`, `compare`, `evidence` |
| `grc_context` | raw chunk text from Step B | `ask --context` |

Both collections use hybrid dense + sparse retrieval with reciprocal rank fusion.

## Configuration

Config lives at:

```text
~/.config/reqbot/config.json
```

Important fields:

- `ollama_url`
- `qdrant_url`
- `default_model`
- `extraction_model`
- `enrichment_model`
- `synthesis_model`
- `top_k`
- `min_score`

Supported environment overrides:

- `REQBOT_OLLAMA_URL`
- `REQBOT_QDRANT_URL`
- `REQBOT_DEFAULT_MODEL`
- `REQBOT_EXTRACTION_MODEL`
- `REQBOT_ENRICHMENT_MODEL`
- `REQBOT_SYNTHESIS_MODEL`
- `REQBOT_TOP_K`
- `REQBOT_MIN_SCORE`

## Output Artifacts

Typical processed output includes:

```text
*_pages.jsonl                    # Step A
*_chunks.jsonl                   # Step B (includes breadcrumb/hierarchy fields in docling mode)
*_ancestry.json                  # Step A (docling mode only — section ancestry map)
*_raw_responses.jsonl            # Raw Step C model responses
*_extracted_requirements.jsonl   # Parsed Step C output
*_parse_failures.jsonl           # Step C parse failures
*_requirements_normalized.jsonl  # Step D validated + deduplicated records (schema v2.0)
*_normalization_failures.jsonl   # Step D validation failures
*_requirements_enriched.jsonl    # Step D.5 enriched records
*_final_output.json              # Step E aggregate export
*_stats.json                     # Step E metrics (includes hierarchy coverage stats in v2.0)
```

These artifacts are the durable source of record. If Qdrant needs to be rebuilt, use `reqbot reindex`.

## Standalone Pipeline Usage

For debugging or reruns, you can call the orchestrator directly:

```bash
python3 run_pipeline.py <pdf_path> [options]
```

Useful flags:

- `--skip-to {A,B,C,D,E}` - resume from an existing output directory
- `--skip-enrichment` - stop after Step D
- `--layout-mode {pymupdf,pdfplumber,docling}` - PDF extraction backend
- `--extraction-model M`
- `--enrichment-model M`
- `--model M` - set both

## Project Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) - module map and data flows
- [CONTRIBUTING.md](CONTRIBUTING.md) - repo conventions and development rules
- [docs/PHASE22_REQUIREMENTS.md](docs/PHASE22_REQUIREMENTS.md) - Phase 22 plan (Browser Checklist Workflow)
- [docs/PHASE23_REQUIREMENTS.md](docs/PHASE23_REQUIREMENTS.md) - Phase 23 plan (Checklist Assessor Workflow)
- [docs/PRODUCT_PRD.md](docs/PRODUCT_PRD.md) - product requirements document
- [archive/](archive/) - completed phase plans (Phases 14–21)
