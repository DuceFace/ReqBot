# ReqBot

ReqBot is a local-first compliance requirements intelligence engine. It extracts cybersecurity requirements from regulatory PDFs, stores the pipeline artifacts as JSONL, indexes the results into Qdrant, and provides a CLI, interactive shell, and web GUI for search, comparison, and evidence mapping.

Everything is designed to run on local infrastructure with Ollama + Qdrant. JSONL is the system of record; Qdrant is a rebuildable index.

Run `reqbot serve` to start the web interface. Run `reqbot docs` to see your indexed documents and requirement counts.

## What It Does

- Extracts requirement statements from PDFs with a two-pass pipeline.
- Preserves document hierarchy (section breadcrumbs, parent context, section ref paths) through the full pipeline.
- Separates extraction and enrichment models so each stage can be tuned independently.
- Supports hybrid retrieval over requirements plus optional raw chunk context lookup.
- Rebuilds Qdrant from existing JSONL without re-running extraction.
- Serves a web GUI (`reqbot serve`) — search, filter, and drill into full requirement provenance in a browser.

## Requirements

- Python 3.12+
- Docker (required; runs Qdrant as a container)
- [Ollama](https://ollama.ai/) (auto-installed by `reqbot setup` if absent)
- Python dependencies:

```bash
pip3 install --break-system-packages -r requirements.txt
```

## Setup

Run once on a fresh Linux machine with Docker installed:

```bash
reqbot setup
```

This automates five steps: Docker check → Qdrant container → Ollama install (if absent) → core model pull → config write. When it completes, `reqbot ask` is ready.

The two core models pulled during setup:

| Model | Size | Purpose |
|-------|------|---------|
| `nomic-embed-text` | ~274 MB | Dense embeddings (required for all search) |
| `llama3.1:8b-instruct-q4_K_M` | ~4.7 GB | Step C extraction + query rewriting |

The synthesis model (`qwen2.5:14b`, ~9 GB) is **not** pulled during setup. It downloads automatically the first time you run `--synthesize`.

**Advanced / custom infrastructure:**

```bash
reqbot setup --advanced   # or: reqbot init
```

Opens an interactive wizard for configuring remote Ollama/Qdrant URLs, custom models, or remote synthesis backends (Anthropic, OpenAI).

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

# Ingest a PDF and index it
reqbot ingest path/to/doc.pdf --index
```

## Core Commands

### `ask`

Search indexed requirements and optionally synthesize an answer.

```bash
reqbot ask "question" [options]
```

Common options:

- `--synthesize` - generate an LLM answer instead of retrieval-only output
- `--context` - attach surrounding raw chunk text from `grc_context`
- `--top-k N` - number of results
- `--min-score F` - minimum RRF score threshold
- `--model M` - synthesis model
- `--domain-tag T` - filter by domain tag, repeatable
- `--requirement-type T` - filter by requirement type, repeatable
- `--document-id D` - filter by document, repeatable
- `--json` - emit JSON
- `--no-rewrite` - disable query rewriting
- `--rewrite-model M` - model for query rewriting

### `ingest`

Run the extraction pipeline on a single PDF.

```bash
reqbot ingest <pdf> [options]
```

Important options:

- `--index` - also embed and index into Qdrant after extraction
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

Rebuild Qdrant from the most recent processed JSONL for each document.

```bash
reqbot reindex
```

This does not re-run extraction. It rebuilds from existing artifacts and uses an atomic alias swap.

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

### `setup`

Automated first-run setup (Docker, Qdrant, Ollama, models, config).

```bash
reqbot setup            # automated flow
reqbot setup --advanced # interactive wizard (same as reqbot init)
```

### `init`

Interactive setup wizard — configure URLs, models, and optional remote synthesis.

```bash
reqbot init
```

Writes `~/.config/reqbot/config.json`. Use this for non-default infrastructure (remote Ollama/Qdrant, custom models).

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

- **Search view** — query the corpus, filter by document, click through to trace
- **Trace view** — full requirement detail: description, source quote, provenance, cross-framework matches, optional source context expansion

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
- `reqbot ingest --index` indexes both requirements and chunk context after the pipeline completes.

Advanced/legacy behavior:

- `--skip-enrichment` keeps the pipeline in Pass 1 only.
- standalone `run_pipeline.py --full-extraction` uses the older single-pass extraction path.

## Layout-Aware Extraction

ReqBot supports three PDF extraction backends via `--layout-mode`.

**`pymupdf` (default)** — fast text extraction for prose-heavy documents (NIST SPs, AFIs, DAF manuals).

**`pdfplumber`** — table-aware extraction for documents with structured tables (DODIs, DoDMs):

```bash
reqbot ingest "DODI 5200.01_vol2.pdf" --index --layout-mode pdfplumber
```

- extracts tables as structured rows
- preserves table boundaries during chunking
- falls back per page if table extraction fails

**`docling`** — structure-aware chunking that preserves section hierarchy:

```bash
reqbot ingest "NIST.SP.800-53r5.pdf" --index --layout-mode docling
```

- parses document structure with Docling's `DocumentConverter`
- injects breadcrumbs (`section_title_path`, `section_ref_path`) into each chunk
- attaches `parent_context` (first ~600 chars of the parent section body) to each requirement
- filters table-of-contents noise automatically
- produces schema v2.0 records with full hierarchy fields

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
- `--full-extraction` - use the legacy single-pass Step C prompt
- `--layout-mode {pymupdf,pdfplumber,docling}` - PDF extraction backend
- `--extraction-model M`
- `--enrichment-model M`
- `--model M` - set both

## Project Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) - module map and data flows
- [CONTRIBUTING.md](CONTRIBUTING.md) - repo conventions and development rules
- [docs/PHASE13_REQUIREMENTS.md](docs/PHASE13_REQUIREMENTS.md) - Phase 13 extraction optimization plan
- [docs/PHASE14_REQUIREMENTS.md](docs/PHASE14_REQUIREMENTS.md) - Phase 14 structure-aware chunking plan
