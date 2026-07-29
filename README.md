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
- A running [Qdrant](https://qdrant.tech/) instance, reachable by URL
- A running [Ollama](https://ollama.ai/) instance, reachable by URL

## Install / Deployment

ReqBot supports three paths depending on how you want to run it. All three run the same code —
Docker just wraps the pip package (WP-25.2) so you never need Node/npm/Python installed on the
host machine to get it running.

### 1. Docker (recommended for most deployments)

```bash
git clone <this-repo>
cd grc-ai-system
cp docker-compose.example.yml docker-compose.yml   # adjust Ollama URL / Qdrant version if needed
docker compose up -d
```

This builds the image from `Dockerfile` (multi-stage: a pinned `node:20` stage builds the
frontend, so the *build host* never needs Node either) and starts `reqbot` alongside a `qdrant`
container. Point it at an existing Ollama instance via `REQBOT_OLLAMA_URL` in the compose file —
Ollama itself isn't containerized by default since GPU/host setups vary too much for one example
to fit everyone (see the commented-out `ollama` service in `docker-compose.example.yml` if you
want it in Compose too).

The published port defaults to `127.0.0.1:8000:8000` — host-machine-only, matching `reqbot
serve`'s own loopback default. There is no authentication in the API layer yet (planned for
Phase 26+), so widening this to a real network interface is a deliberate operator choice; you're
responsible for your own reverse proxy/TLS/firewall if you do.

Configure service URLs and model preferences via `REQBOT_*` environment variables in
`docker-compose.yml` (see `ARCHITECTURE.md`'s Configuration table for the full list) — the
natural fit for a container, since it's set once at deploy time with no interactive session
required. The guided `reqbot init` wizard still works too if you prefer it: `docker compose exec
reqbot reqbot init`.

### 2. Source / dev install

```bash
pip install .
reqbot --help
```

Docling (structure-aware PDF extraction) is a base dependency as of WP-34.1 — it's the only
ingestion path, so `pip install .` alone is enough to ingest documents.

Optional extras:

```bash
pip install ".[remote]"    # remote synthesis via Anthropic/OpenAI
pip install ".[dev]"       # test/lint tooling
```

`pip install .` is the only supported install path — the older `requirements.txt`
(`pip install -r requirements.txt`, predating WP-25.2's packaging) was retired in WP-34.1.

### 3. Air-gapped Docker image transfer

For environments with no internet access at the target machine, build and export the image where
you *do* have connectivity, then transfer the archive over:

```bash
# On a connected machine:
docker build -t reqbot:latest .
docker save reqbot:latest | gzip > reqbot-image.tar.gz

# Also pull the Qdrant image referenced in docker-compose.example.yml, if it needs to travel too:
docker pull qdrant/qdrant:v1.17.1
docker save qdrant/qdrant:v1.17.1 | gzip > qdrant-image.tar.gz

# Transfer both .tar.gz files to the air-gapped machine by whatever means your environment
# permits (USB, approved file transfer, etc.), then on that machine:
gunzip -c reqbot-image.tar.gz | docker load
gunzip -c qdrant-image.tar.gz | docker load
docker compose up -d   # docker-compose.yml as copied in path 1 above
```

`docker-compose.example.yml`'s `reqbot` service tags its build output as `image: reqbot:latest`
(matching the tag used above) alongside `build: .` — Compose only builds an image that isn't
already present locally, so once `docker load` has populated that exact tag, `docker compose up
-d` runs the loaded image directly rather than trying to rebuild from source on a machine that
has neither a checkout nor build tools.

Ollama models themselves aren't part of this image transfer — pull/copy them to the air-gapped
Ollama instance separately (`ollama pull <model>` on a connected machine, then whatever your
environment's approved model-transfer process is; Ollama supports importing from a local model
file). This mirrors the same "ReqBot never installs Qdrant/Ollama or their models for you"
boundary that applies to every deployment path.

## Setup

Run once on a fresh machine:

```bash
reqbot init
```

This configures service URLs and model/synthesis preferences. ReqBot does not install, start, or
manage Qdrant or Ollama itself — both must already be running somewhere reachable by URL before
you run `init`:

- **Qdrant URL** — where your vector database is reachable.
- **Ollama URL** — where your Ollama instance is reachable. Ollama fills ReqBot's embedding,
  extraction, enrichment, and query-rewrite/HyDE model roles — needed for local pipeline work
  regardless of where answer synthesis happens. Recommended defaults, validated on consumer-grade
  hardware, not a hard requirement: `nomic-embed-text` (~274 MB) for embedding and
  `llama3.1:8b-instruct-q4_K_M` (~4.7 GB) for extraction/enrichment/rewrite; pull them yourself
  with `ollama pull <model>` if they aren't already on your instance, or configure different
  models that fit these roles (see `ARCHITECTURE.md`'s model table for what's actually
  configurable per role today). Changing the embedding model is the one role-change that needs
  a follow-up step: it defines the vector shape already stored in Qdrant, so run `reqbot reindex`
  afterward — until you do, `ask`/`compare`/`evidence` still work but surface a warning on any
  result indexed with a different embedding model than what's currently configured.
- **Synthesis** — Local Ollama, Remote (Claude/GPT-4o), or None (retrieval-only; `--synthesize`
  returns no generated answer). If you choose local, ReqBot does not pull the recommended
  synthesis model (`qwen2.5:14b`, ~9 GB) for you — pull it yourself (`ollama pull qwen2.5:14b`)
  or configure a different model you already have. A missing model fails clearly at synthesis
  time rather than triggering a silent download.

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

Supports the same model and enrichment flags as `ingest`.

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

Guided first-run setup — configures Qdrant/Ollama service URLs and models/synthesis (local,
remote, or none). Does not install or manage either service; both must already be running.

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
- **Evidence** — topic → requirements grouped by control/citation reference (`source_ref`), with
  optional LLM synthesis
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
| A | `section_parser.py` | PDF | `*_ancestry.json` (in-memory `AncestryResult`) | No |
| B | `chunk_text.py` | ancestry map | `*_chunks.jsonl` | No |
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

ReqBot ingests exclusively through Docling (structure-aware PDF parsing) as of WP-34.1 — the
earlier `pymupdf`/`pdfplumber` fallback backends and `--layout-mode` flag were removed, along with
the silent per-document fallback between them. A missing or broken Docling install now fails
loudly with an actionable error (`pip install .`) instead of silently downgrading.

```bash
reqbot ingest "NIST.SP.800-53r5.pdf"
```

- parses document structure with Docling's `DocumentConverter`
- injects breadcrumbs (`section_title_path`, `section_ref_path`) into each chunk
- attaches `parent_context` (first ~600 chars of the parent section body) to each requirement
- filters table-of-contents noise automatically
- produces schema v2.0 records with full hierarchy fields
- profile `skip_sections` filtering (e.g. dropping `REFERENCES`/`GLOSSARY` sections) takes effect
  on every ingest — this used to be a no-op under the now-removed legacy backends, since they had
  no section hierarchy to filter on

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
*_ancestry.json                  # Step A — section ancestry map
*_chunks.jsonl                   # Step B — includes breadcrumb/hierarchy fields
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
- `--extraction-model M`
- `--enrichment-model M`
- `--model M` - set both

## Project Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) - module map and data flows
- [CONTRIBUTING.md](CONTRIBUTING.md) - repo conventions and development rules
- [docs/OPERATIONS.md](docs/OPERATIONS.md) - operational runbook for rebuild/reindex steps, ingest
  recipes, and common gotchas
- [docs/PROFILES.md](docs/PROFILES.md) - `profiles/*.json` schema, validation rules, and what each
  field actually does at runtime
- [docs/PRODUCT_PRD.md](docs/PRODUCT_PRD.md) - product requirements document
- [docs/PHASE34_REQUIREMENTS.md](docs/PHASE34_REQUIREMENTS.md) - Phase 34 plan (docling-only
  migration, actionability structural fixes)
- [docs/TODO_future_improvements.txt](docs/TODO_future_improvements.txt) - live backlog the next
  phase gets drafted from once Phase 34 closes
- [archive/](archive/) - completed phase plans (Phases 7–32)
