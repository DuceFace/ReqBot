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

## Current Phase: 14 — Structure-Aware Chunking

**Plan:** `docs/PHASE14_REQUIREMENTS.md`
**Previous phase plan:** `docs/PHASE13_REQUIREMENTS.md`

### Phase 11 — Core Quality Overhaul (COMPLETE 2026-03-21)

| Subphase | Status | Description |
|----------|--------|-------------|
| 11.1 — Project Hygiene | DONE 2026-03-19 | CLAUDE.md created, docs/ dir, ARCHITECTURE/CONTRIBUTING updated |
| 11.2 — Retrieval Fixes | DONE 2026-03-19 | Auto-tag hard filter removed; min_score=0.02 threshold (config/CLI/shell); full input validation across all shell commands |
| 11.3a — Embed source_quote | DONE 2026-03-19 | source_quote-first embedding; whitespace/empty guards; batch_size validation; reindex complete |
| 11.3b — Extraction Prompt | DONE 2026-03-21 | Prompt rewrite with GOOD/BAD examples; requirement_type fallback "" not "guidance"; typed_count fix; IP filter in source_ref hints; chunked file hashing; full corpus re-ingestion complete |

### Phase 12 — Verbatim-First Pipeline Overhaul (COMPLETE 2026-03-22)

| Subphase | Status | Description |
|----------|--------|-------------|
| 12.1 — Validation Gate | DONE 2026-03-21 | source_quote required at Step C/D/embed; description optional; display falls back to source_quote |
| 12.4 — Bug Fixes (pulled forward) | DONE 2026-03-22 | Strategy 3 rfind fix; IP filter in scan_source_refs; dedup scoring to confidence*1000-len(quote); grc_context document_id mismatch (PR #5, PR #6) |
| 12.2 — Two-Pass Extraction | DONE 2026-03-22 | Pass 1 prompt (source_quote+source_ref only); enrich_requirements.py (Pass 2); --skip-enrichment flag; tested on DODI/NIST/AFI; merged PR #7 |
| 12.3 — Query-Time Descriptions | DEFERRED | Superseded by Phase 13 WP-1; display deliverable done in 12.1; revisit after WP-3 eval baseline |

### Phase 13 — Extraction Model Optimization (COMPLETE 2026-03-22, WP-3 paused)

| Work Package | Status | Description |
|---|---|---|
| WP-1: Structured Output Decoding | DONE 2026-03-22 | `format: "json"` to Step C; 3 few-shot examples in Pass 1 prompt; Strategy 2 fallback logged |
| WP-2: Model Configuration Split | DONE 2026-03-22 | `extraction_model` / `enrichment_model` in config/pipeline/CLI; cache scoped by model |
| WP-3: Gold Evaluation Set | PAUSED | Tooling done (eval/ CSV export/import scripts); seeded 402-chunk gold set committed; curation paused — WP-3.3 review revealed upstream chunking defects. Resumes after Phase 14 artifacts regenerated. |
| WP-4: Training Data Curation | BLOCKED | Blocked on WP-3, which is blocked on Phase 14 |
| WP-5: Fine-Tuning + Integration | BLOCKED | Blocked on WP-4 |

**WP-3 gold set state:** 402 chunks selected and seeded. CSV review workflow in place (`eval/export_gold_review_csv.py` → Excel → `eval/import_gold_review_csv.py`). Curation paused because seeded artifacts reflect the broken fixed-size chunker; curating them now grades chunk damage, not extraction quality. Resume after Phase 14 re-ingest.

### Phase 14 — Structure-Aware Chunking (In Progress)

**Docling spike: COMPLETE 2026-04-04 — Outcome B (hybrid) confirmed by Codex review.**
See `eval/spike_results/report.md` and `docs/PHASE14_DOCLING_SPIKE_ADDENDUM.md`.

Key spike findings:
- Docling provides structural improvement on all 3 doc classes (NIST SP, DODI, AFI)
- `chunk.meta.headings` gives only the immediate heading per chunk — full ancestry requires `doc.body` traversal (bridge complexity)
- Canonical section IDs: numbered headings (e.g. "1.1") extract cleanly; prose titles (NIST/AFI) return empty refs — deterministic post-processing required
- ToC noise: 10–36% of chunks per doc are ToC garbage; must be filtered
- Decisions A and B from section 5 of the plan are moot — Docling replaces the layout/boundary decisions

| Work Package | Status | Description |
|---|---|---|
| WP-14.1: Section Header Parser | DONE 2026-04-04 | `section_parser.py`: Docling DocumentConverter + `iterate_items()` ancestry traversal; `section_ref_path` (numbered only) / `section_title_path` (all); ToC heading filter; `parent_context` via recommended Decision C default; PR #19 merged |
| WP-14.2: Structure-Aware Chunker | DONE 2026-04-04 | `chunk_text.py` `run_structure_aware()`: Docling HybridChunker backend; ToC chunk filter (>40% dotted-leader lines); breadcrumb injection from WP-14.1 ancestry map; `raw_text` / `text` / `breadcrumb` / `section_ref_path` / `section_title_path` / `parent_header_text` / `parent_context` fields; `--layout-mode docling` in `run_pipeline.py` |
| WP-14.3: Schema + Normalization | DONE 2026-04-04 | `parse_and_normalize.py` schema v2.0; 5 hierarchy fields in normalized records; `aggregate_and_export.py` hierarchy stats; `embed_and_index.py` payload updated; PR open |
| WP-14.4: Full Re-ingest | NOT STARTED | 45-doc re-ingest; record baseline dir names in `docs/phase14_baseline_dirs.txt` before running |

**Decision C (parent context scope):** accepted as-is. WP-14.2 inherits the WP-14.1 default — `parent_context` = first ~600 chars of body text after the immediate parent heading, fallback to header text. No further action required; WP-14.3 passes it through unchanged.

**Known deferred constraint (WP-14.2 scope):** prose heading depth collapse — all non-numbered headings resolve to depth=1 in the stack. This is correct for documents where "Chapter 1" and "ROLES AND RESPONSIBILITIES" are parallel labels for the same section. Full Docling structural level integration is deferred; documented in `section_parser.py` `_estimate_heading_depth`.

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
  extract_pdf_to_text.py   Step A:   PDF → pages JSONL
  chunk_text.py            Step B:   pages → chunks JSONL
  llm_extract_requirements.py  Step C:   chunks → extracted requirements (LLM)
                                         Pass 1 mode (default): source_quote + source_ref only
                                         Full mode (--full-extraction): adds description/tags/type
  parse_and_normalize.py   Step D:   normalize, validate, deduplicate
  enrich_requirements.py   Step D.5: normalized → enriched (description/tags/type via LLM)
                                         Optional; run_pipeline calls it by default (--skip-enrichment to skip)
  aggregate_and_export.py  Step E:   stats aggregation

Indexing:
  embed_and_index.py       Step F:  normalized JSONL → Qdrant grc_requirements
  embed_context_index.py   Step F2: chunks JSONL    → Qdrant grc_context
  ask.py                   Query module (hybrid search + synthesis)

Docs (read these, don't read source to answer these questions):
  README.md                User-facing CLI reference
  ARCHITECTURE.md          Module map, data flows, import graph, "what breaks if I change X"
  CONTRIBUTING.md          Naming rules, how to add commands/steps, logging, config, error handling
  INDEXED_DOCUMENTS.md     Live corpus inventory (45 docs, ~32k requirements)
  docs/PHASE11_REQUIREMENTS.md  Phase 11 plan (complete)
  docs/PHASE12_REQUIREMENTS.md  Phase 12 plan (complete)
  docs/PHASE13_REQUIREMENTS.md  Phase 13 plan (complete; WP-3 paused)
  docs/PHASE14_REQUIREMENTS.md  Current phase plan: structure-aware chunking
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

## Teammates & Code Review Workflow

Tyler has Gemini Pro and ChatGPT Pro access as code review teammates.
**Codex** has a local clone of the repo (`ReqBot-review` workspace) and can do PR-based reviews.

### Git Workflow (use this for all Phase 12+ work)

1. **Plan** — align on scope in chat before touching code
2. **Branch** — `git checkout -b <descriptive-name>` before any changes
3. **Code + test** — commit to the branch in small logical units; test against live Qdrant/Ollama
4. **Push** — `git push origin <branch-name>`
5. **Open PR** — Tyler clicks "Compare & pull request" on GitHub
6. **Codex review** — Tyler tells Codex `review PR #<number>`; Codex reads the diff directly
7. **Address feedback** — fix on the same branch, push again; re-review if needed
8. **Merge** — Tyler merges; do NOT merge yourself unless explicitly told to

**Core policy: if it changes the GitHub repo → branch + PR. If it's outside the repo → update directly.**

This means:
- All code changes → branch + PR, no exceptions
- CLAUDE.md and repo docs changed alongside code → include in the same PR
- CLAUDE.md standalone status updates (phase completions etc.) → still branch + PR
- memory.md (lives outside repo at ~/.claude/) → update directly, no PR needed

### Commit Message Style
- Bad: "updated files", "fixed bug"
- Good: "fix Step D typed_count metric to exclude empty-string requirement_type"
- Good: "add source_quote validation gate — reject requirements without verbatim text"

### Version Control Rules
- JSONL pipeline output never goes in the repo (lives in ~/documents/processed/)
- raw_pdfs/, Backups/, build/linux-x86_64/, dist/ are gitignored
- build/*.sh scripts ARE tracked (they're source, not artifacts)
- No new pip dependencies without discussion (targets air-gapped environments)

---

## What to Read Next

- **For the current task (Phase 14):** `docs/PHASE14_REQUIREMENTS.md`
- **For Phase 13 history:** `docs/PHASE13_REQUIREMENTS.md`
- **To understand a command:** `README.md` CLI reference section
- **To understand how modules connect:** `ARCHITECTURE.md`
- **To add a command or pipeline step:** `CONTRIBUTING.md`
- **To see what's indexed:** `INDEXED_DOCUMENTS.md` or `reqbot docs`
