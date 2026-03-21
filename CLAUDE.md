# ReqBot — Agent Onboarding

*Read this first. It should take under 2 minutes. Do not read source files until you know what you need.*

---

## What This Is

**ReqBot** is a local-AI compliance research tool. It extracts cybersecurity requirements from
regulatory PDFs (NIST, DODI, AFI, CNSSI, etc.), indexes them into a hybrid vector database
(Qdrant), and provides a search/analysis shell for cross-framework compliance research.
Everything runs on local infrastructure (Ollama + Qdrant). Remote synthesis via Claude or
GPT-4o is optional and off by default.

---

## Current Phase: 11 — Core Quality Overhaul

**Plan:** `docs/PHASE11_REQUIREMENTS.md`

| Subphase | Status | Description |
|----------|--------|-------------|
| 11.1 — Project Hygiene | DONE 2026-03-19 | CLAUDE.md created, docs/ dir, ARCHITECTURE/CONTRIBUTING updated |
| 11.2 — Retrieval Fixes | DONE 2026-03-19 | Auto-tag hard filter removed; min_score=0.02 threshold (config/CLI/shell); full input validation across all shell commands |
| 11.3a — Embed source_quote | DONE 2026-03-19 | source_quote-first embedding; whitespace/empty guards; batch_size validation; reindex complete |
| 11.3b — Extraction Prompt | **NEXT** | Rewrite Step C prompt + examples; fix requirement_type fallback; full corpus re-ingestion |

**Rule:** One subphase at a time. Complete → Gemini review → proceed.

---

## Infrastructure

| Service | URL | What It Does |
|---------|-----|-------------|
| Ollama | `http://192.168.90.100:11434` | LLM inference + dense embeddings (Tyler's local machine) |
| Qdrant | `http://192.168.30.153:6333` | Vector database (LXC on Proxmox blade) |

**Models on Ollama:**
- `llama3.1:8b-instruct-q4_K_M` — Step C extraction + query rewriting
- `nomic-embed-text` — dense embeddings (768-dim)
- `qwen2.5:14b` — synthesis answers

**Config:** `~/.config/reqbot/config.json` (written by `reqbot init`)
**Processed JSONL:** `~/documents/processed/` (source of record — Qdrant is rebuildable)

---

## Key File Map

```
reqbot.py          ← CLI entry point + all cmd_* command implementations
console.py         ← Interactive shell (cmd.Cmd); wraps reqbot.py commands
config.py          ← Config loader: defaults → ~/.config/reqbot/config.json → env vars
synthesis.py       ← LLM synthesis: local Ollama or remote Anthropic/OpenAI
run_pipeline.py    ← Pipeline orchestrator, calls Steps A–E in sequence

Pipeline steps (standalone scripts, no cross-imports):
  extract_pdf_to_text.py   Step A: PDF → pages JSONL
  chunk_text.py            Step B: pages → chunks JSONL
  llm_extract_requirements.py  Step C: chunks → extracted requirements (LLM)
  parse_and_normalize.py   Step D: normalize, validate, deduplicate
  aggregate_and_export.py  Step E: stats aggregation

Indexing:
  embed_and_index.py       Step F:  normalized JSONL → Qdrant grc_requirements
  embed_context_index.py   Step F2: chunks JSONL    → Qdrant grc_context
  ask.py                   Query module (hybrid search + synthesis)

Docs (read these, don't read source to answer these questions):
  README.md                User-facing CLI reference
  ARCHITECTURE.md          Module map, data flows, import graph, "what breaks if I change X"
  CONTRIBUTING.md          Naming rules, how to add commands/steps, logging, config, error handling
  INDEXED_DOCUMENTS.md     Live corpus inventory (45 docs, ~32k requirements)
  docs/PHASE11_REQUIREMENTS.md  Current phase plan with checkboxes
  docs/PHASE12_REQUIREMENTS.md  Next phase plan: verbatim-first pipeline overhaul
```

---

## Corpus State

- **45 documents indexed**, ~32,000 requirements in Qdrant
- **Collections:** `grc_requirements` (normalized reqs) + `grc_context` (raw chunks)
- **Both use:** hybrid dense (nomic-embed-text 768-dim) + sparse (BM25) with RRF fusion
- **DODIs:** extracted with `--layout-mode pdfplumber` (table-aware)
- **NIST/AFI/DAF:** extracted with `--layout-mode pymupdf` (default)
- **Full doc list:** `INDEXED_DOCUMENTS.md` or run `reqbot docs`

---

## Operational Rules (do not violate)

1. **Use `python3`** — `python` command is not found on this system
2. **No venv** — system Python; install with `pip3 install --break-system-packages <pkg>`
3. **JSONL is source of record** — Qdrant can always be rebuilt with `reqbot reindex`
4. **Resuming a killed Step C job** — use `python3 run_pipeline.py <pdf> --output-dir <old_dir> --skip-to C`, not a fresh ingest (the prompt hash cache lives in the old output dir)
5. **reindex deduplication** — keeps most recently modified JSONL per document; directory names must follow `{stem}_{YYYYMMDD}_{HHMMSS}` convention
6. **Context window math** — `--synthesize --context --top-k 20` sends ~4k tokens to the LLM; llama3.1:8b has 8k context. Don't increase top-k carelessly.
7. **Build artifacts** — `build/linux-x86_64/` and `dist/` are generated; never edit files there directly. Edit source at root, then rebuild.

---

## How to Run

```bash
# Interactive shell
reqbot

# Single command
reqbot ask "What are the access control requirements?"
reqbot ask "encryption at rest" --synthesize
reqbot docs
reqbot status

# Ingest a new PDF
reqbot ingest path/to/doc.pdf --index
reqbot ingest path/to/dodi.pdf --index --layout-mode pdfplumber

# Rebuild Qdrant from all existing JSONL (no re-extraction)
reqbot reindex
```

---

## Teammates

Tyler has Gemini Pro and ChatGPT Pro access as code review teammates.
- Get Gemini review after completing each subphase before proceeding
- They've caught real bugs in past phases — use them

---

## What to Read Next

- **For the current task (Phase 11):** `docs/PHASE11_REQUIREMENTS.md`
- **To understand a command:** `README.md` CLI reference section
- **To understand how modules connect:** `ARCHITECTURE.md`
- **To add a command or pipeline step:** `CONTRIBUTING.md`
- **To see what's indexed:** `INDEXED_DOCUMENTS.md` or `reqbot docs`
