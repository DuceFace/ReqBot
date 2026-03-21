# ReqBot

Compliance Requirements Intelligence Engine — extracts, indexes, and queries cybersecurity requirements from regulatory PDFs using a local LLM (Ollama) and Qdrant hybrid vector search.

**Current corpus:** 45 documents, ~32,000 requirements indexed.
See [INDEXED_DOCUMENTS.md](INDEXED_DOCUMENTS.md) for the full document inventory.

## Prerequisites

- Python 3.12+ (system Python — no venv required)
- Ollama running with the following models pulled:
  - `llama3.1:8b-instruct-q4_K_M` — extraction + query rewriting
  - `nomic-embed-text` — dense embeddings
  - `qwen2.5:14b` — synthesis answers
- Qdrant instance (local or remote)
- Install deps: `pip3 install --break-system-packages -r requirements.txt`

## Setup

```bash
# First-time configuration
reqbot init
```

This prompts for your Ollama and Qdrant URLs and writes `~/.config/reqbot/config.json`.

## Quick Start

```bash
# Launch the interactive shell
reqbot

# Single-command mode
reqbot ask "What are the access control requirements?"
reqbot ask "encryption at rest" --synthesize --context
reqbot docs
reqbot status
```

## CLI Reference

### `ask` — Query indexed requirements

```bash
reqbot ask "question" [options]

  --synthesize          Generate an LLM answer (default: retrieve-only)
  --context             Enrich results with surrounding raw chunk text (grc_context)
  --top-k N             Number of results (default: 20)
  --min-score F         Minimum relevance score threshold (default: 0.02)
  --model M             LLM for synthesis (default: qwen2.5:14b)
  --domain-tag T        Filter by domain tag (repeatable)
  --requirement-type T  Filter by requirement type (repeatable)
  --document-id D       Filter by document (repeatable)
  --json                Output as JSON
```

### `ingest` — Extract and optionally index a PDF

```bash
reqbot ingest <pdf> [options]

  --index               Also embed and index into Qdrant after extraction
  --layout-mode         PDF backend: pymupdf (default) or pdfplumber (table-aware)
  --output-dir          Output directory (default: documents/processed/<stem>_<timestamp>/)
  --model               Ollama extraction model (default: llama3.1:8b-instruct-q4_K_M)
  --max-chunks N        Limit to first N chunks (for testing)
```

### `batch` — Process an entire directory of PDFs

```bash
reqbot batch <pdf_dir> [--model M] [--layout-mode MODE]
```

Runs Steps A–E for every PDF in the directory. Run `reqbot reindex` after to embed and index.

### `reindex` — Rebuild Qdrant from all existing JSONL (no re-extraction)

```bash
reqbot reindex
```

Rebuilds from the most recent run per document. Uses atomic alias swap — live collection is untouched until all files succeed.

### `index` — Index an existing normalized JSONL

```bash
reqbot index <requirements_normalized.jsonl> [--recreate] [--batch-size N]
```

### `index-context` — Index raw chunks into grc_context collection

```bash
reqbot index-context <chunks.jsonl> [--document-id ID] [--source-pdf NAME] [--recreate]
```

### `compare` — Compare requirements across two documents

```bash
reqbot compare <doc_id_1> <doc_id_2> "topic"
```

### `evidence` — Evidence mapping for a control or topic

```bash
reqbot evidence "topic or control" [--domain-tag T] [--requirement-type T]
```

### `docs` — List indexed documents

```bash
reqbot docs
```

Shows every indexed document with requirement count, extraction mode, and run date.

### `status` — System health check

```bash
reqbot status
```

---

## Pipeline Steps

| Step | Script | Input | Output | LLM? |
|------|--------|-------|--------|------|
| A | `extract_pdf_to_text.py` | PDF | `*_pages.jsonl` | No |
| B | `chunk_text.py` | pages.jsonl | `*_chunks.jsonl` | No |
| C | `llm_extract_requirements.py` | chunks.jsonl | `*_extracted_requirements.jsonl` | Yes |
| D | `parse_and_normalize.py` | extracted_requirements.jsonl | `*_requirements_normalized.jsonl` | No |
| E | `aggregate_and_export.py` | requirements_normalized.jsonl | `*_final_output.json`, `*_stats.json` | No |
| F | `embed_and_index.py` | requirements_normalized.jsonl | Qdrant `grc_requirements` | No |
| F2 | `embed_context_index.py` | chunks.jsonl | Qdrant `grc_context` | No |

Steps F and F2 run automatically when `--index` is passed to `ingest`.

## Layout-Aware Extraction (pdfplumber mode)

For documents with structured tables (e.g. DODIs, DoDMs), use `--layout-mode pdfplumber`:

- Tables are detected, extracted as pipe-delimited rows, and wrapped in sentinel markers
- Chunker avoids splitting mid-table
- Falls back to PyMuPDF per-page if pdfplumber fails

```bash
reqbot ingest "DODI 5200.01_vol2.pdf" --index --layout-mode pdfplumber
```

## Qdrant Collections

| Collection | Contents | Used By |
|---|---|---|
| `grc_requirements` | Extracted, normalized requirement statements | `ask` retrieval |
| `grc_context` | Raw surrounding chunk text (Step B output) | `ask --context` enrichment |

Both use hybrid dense (768-dim cosine, nomic-embed-text) + sparse (BM25) vectors with RRF fusion.
JSONL is the system of record — Qdrant is a rebuildable index.

## Configuration

Config is stored at `~/.config/reqbot/config.json` (written by `reqbot init`).
Environment variables override config: `REQBOT_OLLAMA_URL`, `REQBOT_QDRANT_URL`, `REQBOT_TOP_K`, `REQBOT_MIN_SCORE`.

## Output Artifacts

```
*_pages.jsonl                    # Raw page text (Step A)
*_chunks.jsonl                   # Text chunks with page refs (Step B)
*_raw_responses.jsonl            # Raw LLM responses (Step C)
*_extracted_requirements.jsonl   # Parsed requirements (Step C)
*_parse_failures.jsonl           # LLM responses that couldn't be parsed (Step C)
*_requirements_normalized.jsonl  # Validated + deduplicated (Step D)
*_normalization_failures.jsonl   # Requirements that failed validation (Step D)
*_final_output.json              # Complete output with metadata (Step E)
*_stats.json                     # Pipeline metrics (Step E)
```
