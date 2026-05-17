# Phase 7: The Deployable Experience

> Goal: Transform the CLI tool into an interactive Metasploit-style shell while
> preserving full CLI automation compatibility.
>
> Status tracking: Update each task checkbox as work completes.

---

## Vision

```
$ python3 grcai.py

  ██████╗ ██████╗  ██████╗     █████╗ ██╗
 ██╔════╝ ██╔══██╗██╔════╝    ██╔══██╗██║
 ██║  ███╗██████╔╝██║         ███████║██║
 ██║   ██║██╔══██╗██║         ██╔══██║██║
 ╚██████╔╝██║  ██║╚██████╗    ██║  ██║██║
  ╚═════╝ ╚═╝  ╚═╝ ╚═════╝   ╚═╝  ╚═╝╚═╝
  Compliance Requirements Intelligence Engine

grcai > status
grcai > set top_k 10
grcai > ask What are the password complexity requirements?
grcai > ingest DODI_8500.01.pdf --index
grcai > exit
```

Single-command mode still works (no regression):
```
$ python3 grcai.py ask "What are the audit log requirements?" --synthesize
```

---

## Pre-Phase 7: Schema Versioning [x]

**Goal:** Add metadata fields to normalized JSONL so future pipeline changes don't silently break old records.

**Deliverables:**
- [x] Add to every `*_requirements_normalized.jsonl` record in Step D (`parse_and_normalize.py`):
  - `schema_version`: `"1.0"` (hardcoded constant, bump manually on breaking changes)
  - `pipeline_version`: `"1.0"` (same — bump when extraction logic changes significantly)
  - `extraction_model`: the Ollama model name used for Step C
  - `run_timestamp`: ISO 8601 UTC timestamp of when Step D ran
- [x] Old JSONL files without these fields still load cleanly (fields are informational, not required for indexing)
- [x] `SCHEMA_VERSION = "1.0"` defined as a constant at the top of `parse_and_normalize.py`

**Why before Phase 7:** These fields are free to add now and cost nothing. Skipping them means we can never tell which records came from which model or pipeline version once the corpus grows.

---

## Phase 7.1 — Config Engine [x]

**Goal:** Move hardcoded URLs out of grcai.py and into `~/.grcai/config.json`.

**Deliverables:**
- [x] Create `config.py` — standalone module, no circular imports
- [x] Config file location: `~/.grcai/config.json`
- [x] Keys: `ollama_url`, `qdrant_url`, `default_model`, `synthesis_model`, `top_k`, `processed_dir`
- [x] Load order: hardcoded defaults → config file → environment variables
- [x] Update `grcai.py` to import from `config.py` instead of using hardcoded constants

**Config file schema:**
```json
{
  "ollama_url": "http://192.168.90.100:11434",
  "qdrant_url": "http://192.168.30.153:6333",
  "default_model": "llama3.1:8b-instruct-q4_K_M",
  "synthesis_model": "qwen2.5:14b",
  "top_k": 20,
  "processed_dir": "~/documents/processed"
}
```

**Fallbacks (if no config file):** Current hardcoded values — no behavior change.

---

## Phase 7.2 — Setup Wizard (grcai init) [x]

**Goal:** Interactive first-run setup that writes `~/.grcai/config.json`.

**Deliverables:**
- [x] Add `init` subcommand to `grcai.py`
- [x] Prompt for each config value with current/default shown in brackets
- [x] Test each connection (Ollama ping, Qdrant ping) before saving; retry loop with "keep anyway?" prompt on failure
- [x] Print clear success/failure for each check
- [x] Write validated config to `~/.grcai/config.json`
- [x] Print path to saved config on success

**UX example:**
```
$ python3 grcai.py init

GRC AI Setup
============
Ollama URL [http://192.168.90.100:11434]:
  Testing connection... OK (4 models found)
Qdrant URL [http://192.168.30.153:6333]:
  Testing connection... OK (2 collections)
Default extraction model [llama3.1:8b-instruct-q4_K_M]:
Synthesis model [qwen2.5:14b]:
Default top-k [20]:

Config saved to /home/coder/.grcai/config.json
Run 'python3 grcai.py' to launch the interactive shell.
```

---

## Phase 7.3 — Interactive Shell (console.py) [x]

**Goal:** Standalone `cmd`-based interactive shell. Parallel to grcai.py — doesn't touch pipeline.

**Deliverables:**
- [x] Create `console.py` using Python stdlib `cmd.Cmd`
- [x] Prompt: `grcai > `
- [x] Built-in shell commands:
  - [x] `help` / `?` — list commands and usage (cmd module handles this)
  - [x] `status` — ping Ollama and Qdrant, show collection counts (reuse grcai status logic)
  - [x] `docs` — list indexed documents (reuse grcai docs logic)
  - [x] `tags` — list all distinct domain_tag values in the corpus (query Qdrant for facets)
  - [x] `analyze` — corpus quality summary (req counts by doc/tag/type, extraction failure rates)
  - [x] `show` — display current session variables (like Metasploit `show options`)
  - [x] `set <key> <value>` — override a session variable (e.g., `set top_k 10`)
  - [x] `unset <key>` — clear a session filter variable
  - [x] `exit` / `quit` / `Ctrl+D` — clean exit
- [x] Session state: `set` changes apply only for the current session, not saved to config
- [x] Readline history (stdlib `readline` if available — graceful fallback if not)
- [x] Empty line does nothing (no repeat last command)
- [x] Unknown command prints helpful error, not a stack trace

**[GEMINI] argparse Death Trap — MUST implement:** ✓ DONE
- [x] All shell command handlers wrap argparse calls in `_parse_shell_args()` which catches `SystemExit`
- [x] Bad flags print an error via `err()` and return to `grcai >` prompt
- [x] `sys.exit()` never propagates to kill the shell
- [x] `ValueError` (unclosed quotes in shlex) also caught

**[GEMINI] Log Spam vs Shell UX — MUST implement:** ✓ DONE
- [x] Shell launch sets root logger level to `WARNING` (suppress INFO wall-of-text)
- [x] Clean Metasploit-style print statements for key events:
  - `[*]` informational (white/default)
  - `[+]` success (green ANSI if terminal supports it, plain text fallback)
  - `[-]` error (red ANSI if terminal supports it, plain text fallback)
  - `[!]` warning (yellow ANSI if terminal supports it, plain text fallback)
- [x] Single-command CLI mode (`grcai ask "..."`) keeps full logging unchanged
- [x] No new dependencies — ANSI codes only, with `sys.stdout.isatty()` guard

**Show output example:**
```
grcai > show

Session Variables
=================
ollama_url      http://192.168.90.100:11434
qdrant_url      http://192.168.30.153:6333
default_model   llama3.1:8b-instruct-q4_K_M
synthesis_model qwen2.5:14b
top_k           20
document_id     (not set)
domain_tag      (not set)
requirement_type (not set)
```

---

## Phase 7.4 — Wiring the Arsenal [x]

**Goal:** Port pipeline commands into the shell. Update grcai.py launch behavior.

**Deliverables:**

**Shell commands added to console.py:** ✓ ALL DONE
- [x] `ask <question>` — calls `cmd_ask()` directly with session vars; supports inline flags (`ask ... --synthesize`)
- [x] `ingest <pdf> [flags]` — calls `cmd_ingest()`; supports `--index`, `--layout-mode`
- [x] `index <jsonl>` — calls `cmd_index()` directly
- [x] `reindex` — calls `cmd_reindex()` directly
- [x] `batch <dir>` — calls `cmd_batch()`

**grcai.py launch behavior:** ✓ DONE
- [x] No arguments → launch interactive shell (`console.py`)
- [x] With arguments → execute single command and exit (current behavior, no regression)

**[CHATGPT] Internal API instead of subprocess — MUST implement:** ✓ DONE
- [x] Shell command handlers call `cmd_*` Python functions directly — NOT subprocess
- [x] `do_ask()` calls `_grcai.cmd_ask(ns)` directly; same for `index`, `reindex`, `status`, `docs`
- [x] `shlex.split()` + argparse used to parse shell input into args namespace
- [x] Subprocess used only for ingest/batch pipeline steps (acceptable — streaming output)
- [x] Session URL/model vars passed via `Namespace` to each `cmd_*` call

**[GEMINI] Target Paradigm — session filtering:** ✓ DONE
- [x] `set document_id NIST.SP.800-53r5` auto-injects `--document-id` into every `ask`
- [x] Same for `domain_tag` and `requirement_type` session vars
- [x] CLI flags override session (not merge) — explicit flags take priority
- [x] `show` highlights active filters in green; unset vars shown in dim grey
- [x] `unset document_id` clears just that filter; other filters unchanged
- [x] Metasploit "lock onto a target" pattern — set once, fire many times

**Target paradigm UX example:**
```
grcai > set document_id NIST.SP.800-53r5
[*] document_id => NIST.SP.800-53r5

grcai > ask "What are the password complexity requirements?"
[*] Filtering by document_id: NIST.SP.800-53r5
[*] Querying...

grcai > unset document_id
[*] document_id cleared
```

---

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Shell framework | Python stdlib `cmd.Cmd` | Zero deps, handles help/completion/history |
| Config location | `~/.grcai/config.json` | Standard user config convention |
| Shell dispatch | `shlex.split()` → call cmd_* functions directly | No subprocess, faster, cleaner error handling |
| Subprocess exception | ingest/batch only (streaming output) | Long-running pipeline steps need live output |
| Session state | In-memory dict on GrcaiConsole instance | Simple, clean, no persistence needed |
| Readline | stdlib `readline`, graceful fallback | Better UX, zero deps |
| No regression | `grcai.py <args>` still works unchanged | Preserves scripting/automation |
| argparse in shell | Wrap all calls in `try/except SystemExit` | Prevents bad flags from killing the shell |
| Logging in shell | Set root logger to WARNING on shell launch | Suppress INFO spam; use `[*]/[+]/[-]/[!]` prints |
| Color output | ANSI codes with `sys.stdout.isatty()` guard | No deps; graceful fallback in pipes/scripts |
| Target paradigm | Session vars auto-inject into ask filters | Metasploit "set target, fire many" UX |
| Cross-doc dedup | DECIDED AGAINST | Source attribution is the point — same control in NIST + DODI + CNSSI is valuable signal, not noise |

---

## Backlog (post-Phase 7)

**Reranking (high value, non-trivial):**
- After hybrid retrieval (top 50), pass results through a cross-encoder reranker before returning top-k
- Candidate models: `bge-reranker-large`, `jina-reranker` (via Ollama or direct HuggingFace)
- Flow: hybrid search (top 50) → rerank → return top 10
- Regulatory language benefits heavily from reranking — long dense text needs semantic re-scoring

**Ingest idempotency:**
- `document_id` is already SHA-256 of PDF — the hash exists
- Before starting Step A, check if `document_id` is already present in Qdrant payload
- If found: print `[!] Already indexed — use --force to re-extract` and skip
- Prevents accidental reprocessing of large documents

---

## Files Changed

| File | Action |
|------|--------|
| `parse_and_normalize.py` | Modify — add schema_version, pipeline_version, extraction_model, run_timestamp fields |
| `config.py` | New — config loader module |
| `console.py` | New — interactive shell |
| `grcai.py` | Modify — import config, add `init` subcommand, launch shell on no-args |

Pipeline scripts (A-F2) are **not touched** in Phase 7.

---

## Success Criteria — ALL MET ✓

- [x] Normalized JSONL records include schema_version, pipeline_version, extraction_model, run_timestamp
- [x] `python3 grcai.py` launches interactive shell with banner
- [x] `python3 grcai.py ask "..."` still works (single-command mode, full logging)
- [x] `python3 grcai.py init` writes a valid config file
- [x] `set top_k 5` then `ask "..."` in shell uses top_k=5
- [x] `set document_id NIST.SP.800-53r5` then `ask "..."` auto-filters to that doc
- [x] `set domain_tag incident-response` then `ask "..."` scopes to that tag across all docs
- [x] Both filters stack: `set document_id X` + `set domain_tag Y` both inject simultaneously
- [x] `unset document_id` clears just that filter, leaving others intact
- [x] `show` displays all session vars including active filters (active filters highlighted green)
- [x] `tags` lists domain_tag values with counts from the live corpus
- [x] `analyze` shows corpus quality summary (counts by doc/tag/type)
- [x] `status` works from inside the shell
- [x] Bad flag (e.g., `ask "q" --tpo-k 5`) prints error, returns to prompt (no shell exit)
- [x] Shell commands call cmd_* functions directly — no subprocess for query/index operations
- [x] Shell launch suppresses INFO logs; uses `[*]/[+]/[-]/[!]` prefix output
- [x] Ctrl+D exits cleanly
- [x] No pipeline scripts (A-F2) modified

## Gemini Code Reviews

- **Pre-Phase 7 + 7.1:** Approved. Flagged processed_dir patching for subprocess → fixed.
- **7.2:** Approved on re-review. Bugs fixed: URL trailing-slash poisoning, silent connection failure on init.
- **7.3:** Approved after fixes: doc_key clobbering (stem vs parent.name), Qdrant 180s hang-of-death (pre-loop connection check + mid-loop break), UTF-8 encoding on all file opens, readline history save on exit.
- **7.4 (first pass):** Hallucinated `no_rewrite`/`rewrite_model` fields — correctly rejected. Real fixes: synthesis model default wired from session, extraction model default correct.
- **Phase 7 final (complete codebase):** Two bugs fixed — subprocess pathing disconnect (cmd_ingest/cmd_batch now pre-compute full timestamped out_dir), sticky filter override (domain_tag/requirement_type correctly override session only when no CLI flags provided).

**Final verdict: APPROVED — Phase 7 complete.**
