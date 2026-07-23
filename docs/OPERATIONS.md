# ReqBot — Operations Runbook

Day-to-day procedures for running, developing, and maintaining ReqBot on the Proxmox dev environment.

---

## Environment Quick Facts

| Thing | Detail |
|---|---|
| Dev server | `192.168.30.152` (Proxmox blade, Coder workspace in Docker container) |
| Ollama | `http://192.168.90.100:11434` (Tyler's local machine) |
| Qdrant | `http://192.168.30.153:6333` (LXC on Proxmox blade) |
| Processed JSONL | `~/documents/processed/` |
| Config file | `~/.config/reqbot/config.json` |
| Project root | `~/grc-ai-system/` |

---

## First-Run Setup

New machine or fresh config: `python3 cli/reqbot.py init` — see README.md's "Setup" section
for the full Qdrant/Ollama URL and synthesis (local/remote/none) walkthrough. Qdrant and Ollama
must already be running before you run `init` — it configures URLs only, it does not install
or manage either service. `reqbot setup` still works as a deprecated alias.

---

## Starting the UI

The compiled `reqbot` binary is stale — always use the Python source directly:

```bash
cd ~/grc-ai-system
python3 cli/reqbot.py serve --host 0.0.0.0
```

The UI is then available via Coder port forwarding:
1. In VS Code: `Ctrl+Shift+P` → **Forward a Port** → `8000`
2. If the port was previously forwarded and is now hanging: `Ctrl+Shift+P` → **Stop Forwarding a Port** → `8000`, then re-add it
3. Open `http://localhost:8000` in your browser

> **Why not `http://192.168.30.152:8000` directly?** The Coder workspace runs inside a Docker container (`172.17.0.2`). Port 8000 is not exposed to the host network — only the Coder agent tunnel exposes it. Port 3000 (Coder itself) works because the Coder server runs on the host.

---

## Using the CLI

The compiled `reqbot` binary predates the current codebase. Use `python3 cli/reqbot.py` for everything:

```bash
cd ~/grc-ai-system

# Interactive shell (Metasploit-style, tab-complete)
python3 cli/reqbot.py

# Single commands
python3 cli/reqbot.py status
python3 cli/reqbot.py docs
python3 cli/reqbot.py ask "access control requirements"
python3 cli/reqbot.py checklist --doc NIST.SP.800-61r3 --format xlsx --output /tmp/out.xlsx
python3 cli/reqbot.py compare "AC-2"
python3 cli/reqbot.py compare "encryption at rest" --markdown
python3 cli/reqbot.py trace <requirement_id>
python3 cli/reqbot.py evidence "incident response"
```

> When running `run_pipeline.py` directly (not via the CLI), always pass `--ollama-url http://192.168.90.100:11434`. The default `localhost:11434` resolves to the dev server container, not Tyler's machine where Ollama runs.

---

## Rebuilding the Frontend

Requires Node.js 20 LTS or newer and npm on the PATH. Install Node 20+ using nvm, NodeSource, or
an OS package source that actually provides Node 20+. On Ubuntu, the default `apt install nodejs
npm` package may install Node 18, which is too old for ReqBot.

```bash
bash build/build-frontend.sh
```

The script checks for npm and a Node major version ≥20 up front and fails with a clear message
if either is missing or too old — it does not search for or fall back to any other Node
install. A successful build prints `[+] Frontend built → frontend/dist/`. The `dist/` folder is
gitignored — it is a build artifact, not tracked in the repo.

After rebuilding, **reload the browser tab** — the running server picks up new dist files immediately (no server restart needed).

---

## Ingesting a New Document

```bash
cd ~/grc-ai-system

# Standard ingest (most NIST/AFI/DAF docs) — indexes into Qdrant by default
python3 cli/reqbot.py ingest ~/path/to/doc.pdf \
  --ollama-url http://192.168.90.100:11434

# Table-heavy docs (DODIs) — pdfplumber handles tables better
python3 cli/reqbot.py ingest ~/path/to/dodi.pdf \
  --layout-mode pdfplumber \
  --ollama-url http://192.168.90.100:11434

# Structure-aware — required for profile skip_sections filtering to apply; slower
# on CPU (layout/table/OCR model inference) but exercises the full current pipeline
python3 cli/reqbot.py ingest ~/path/to/doc.pdf \
  --layout-mode docling \
  --ollama-url http://192.168.90.100:11434
```

Output goes to `~/documents/processed/<doc_stem>_<timestamp>/`. Indexing (both
`grc_requirements` and `grc_context`) runs automatically after extraction; add `--no-index`
for artifact-only/debug runs.

**Verifying GPU usage during ingestion:** Step C/D.5 extraction and enrichment run through
Ollama. Confirm inference is actually using the GPU, not silently falling back to CPU:

```bash
curl http://192.168.90.100:11434/api/ps
```

For each loaded model, compare `size_vram` to `size`: `size_vram == size` means the model is
fully resident in VRAM; `size_vram > 0` but less than `size` means only partial GPU offload.

To resume a killed Step C job (do NOT start a new run — you lose the prompt hash cache):
```bash
python3 pipeline/run_pipeline.py \
  ~/path/to/doc.pdf \
  --output-dir ~/documents/processed/<existing_run_dir> \
  --skip-to C \
  --ollama-url http://192.168.90.100:11434
```

---

## Rebuilding Qdrant from Existing JSONL

`reindex` rebuilds **both** `grc_requirements` and `grc_context` from existing artifacts in
`~/documents/processed/` without re-running extraction, using an atomic temp-collection +
alias swap for each collection — the live index is never touched until indexing succeeds.
Prefers `*_requirements_enriched.jsonl` over `*_requirements_normalized.jsonl` per document
when both exist.

```bash
python3 cli/reqbot.py reindex
```

For a faster requirements-only rebuild (skips the slower, CPU-bound context rebuild — useful
when only requirement JSONL changed):

```bash
python3 cli/reqbot.py reindex --requirements-only
```

Run after adding a new field to normalized/enriched JSONL, after a corpus refresh, or after
restoring from backup.

**Repair/debug:** to rebuild a single document's context chunks without a full reindex, use
the low-level `index-context` command directly:

```bash
python3 cli/reqbot.py index-context ~/documents/processed/<run_dir>/<doc_stem>_chunks.jsonl
```

---

## Nuking and Rebuilding the Qdrant Collections

Two different situations both start with "wipe the collections," but the recovery step differs:

- **Disaster recovery** (schema change, corruption, bad state) — rebuild from whatever JSONL
  already exists in `~/documents/processed/` via `reqbot reindex`. No re-extraction; picks up
  the latest run per document automatically.
- **Genuine corpus refresh** (re-ingesting documents through an updated pipeline) — re-ingest
  the documents you want refreshed via `reqbot ingest`/`reqbot batch` first. Indexing happens
  as part of that ingest itself; no separate `reindex` step is needed for freshly ingested docs.
  Only run `reindex` afterward if you also need to pick up *other* documents' existing JSONL
  that weren't part of the refresh.

To nuke, first inspect what actually exists — `grc_requirements` may be a plain collection or
an alias pointing at a hash-suffixed backing collection (WP-24.2's alias-swap rebuild pattern),
and the exact backing name changes every time the embedding config or a fresh reindex creates
a new one, so don't hardcode a literal name:

```bash
# 1. Check current state first
python3 cli/reqbot.py status
# or, for the raw collection/alias list:
python3 -c "
from qdrant_client import QdrantClient
c = QdrantClient(url='http://192.168.30.153:6333')
print('collections:', [col.name for col in c.get_collections().collections])
print('aliases:', [(a.alias_name, a.collection_name) for a in c.get_aliases().aliases])
"

# 2. Delete whatever collection name(s) that showed — for grc_requirements, delete the
#    backing collection (not just the alias) if one exists; delete grc_context directly.
curl -X DELETE http://192.168.30.153:6333/collections/<backing_or_plain_name>
curl -X DELETE http://192.168.30.153:6333/collections/grc_context

# 3. Rebuild — reindex from existing JSONL, or re-ingest for a genuine refresh (see above)
python3 cli/reqbot.py reindex
```

> The first `reindex` after upgrading to WP-24.2 migrates `grc_context` from a plain collection
> to an alias-backed one (a brief delete-then-alias-create window, same one-time cost
> `grc_requirements` already pays if it's ever nuked back to a real collection). Every
> `reindex` after that is a zero-downtime alias swap for both collections.

---

## Running Tests

```bash
cd ~/grc-ai-system
python3 -m pytest tests/unit/ -q
```

Lint:
```bash
python3 -m ruff check .
```

---

## Common Gotchas

- **`reqbot` binary is stale** — always use `python3 cli/reqbot.py`. The binary predates Phase 18 and does not have checklist, compare (updated), or any Phase 21+ commands.
- **Ollama URL** — pipeline scripts default to `localhost:11434` which resolves to the container, not Tyler's machine. Always pass `--ollama-url http://192.168.90.100:11434` when running pipeline scripts directly.
- **Step C resume** — re-running pipeline on the same PDF without `--output-dir` creates a new timestamped directory and loses the prompt hash cache. Use `--output-dir <old_dir> --skip-to C` to resume.
- **Frontend not updating** — the browser caches aggressively. After a frontend rebuild, do a hard reload (`Ctrl+Shift+R`) if a normal reload doesn't show changes.
- **Port forwarding stale** — if `http://localhost:8000` hangs, the VS Code port forward tunnel is stale. Stop and re-add port 8000 via `Ctrl+Shift+P`.
