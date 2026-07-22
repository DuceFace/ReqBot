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

`npm` is not on the PATH in the Coder workspace. Use the Node binary bundled with VS Code Server:

```bash
cd ~/grc-ai-system/frontend

# One-liner (copy-paste ready)
NODE=/tmp/code-server/lib/code-server-4.129.0/lib/node && \
  $NODE node_modules/.bin/tsc --noEmit && \
  $NODE node_modules/.bin/vite build
```

A successful build prints `✓ built in X.XXs` and updates `frontend/dist/`. The `dist/` folder is gitignored — it is a build artifact, not tracked in the repo.

After rebuilding, **reload the browser tab** — the running server picks up new dist files immediately (no server restart needed).

> If the VS Code version changes and the path above breaks, find the new node binary with:
> `find /home/coder/.vscode-server -name "node" -type f`

---

## Ingesting a New Document

```bash
cd ~/grc-ai-system

# Standard ingest (most NIST/AFI/DAF docs)
python3 pipeline/run_pipeline.py \
  --pdf ~/path/to/doc.pdf \
  --ollama-url http://192.168.90.100:11434

# Table-heavy docs (DODIs)
python3 pipeline/run_pipeline.py \
  --pdf ~/path/to/dodi.pdf \
  --layout-mode pdfplumber \
  --ollama-url http://192.168.90.100:11434

# Then index into Qdrant
python3 cli/reqbot.py index --dir ~/documents/processed/<doc_run_dir>
```

Output goes to `~/documents/processed/<doc_stem>_<timestamp>/`.

To resume a killed Step C job (do NOT start a new run — you lose the prompt hash cache):
```bash
python3 pipeline/run_pipeline.py \
  --pdf ~/path/to/doc.pdf \
  --output-dir ~/documents/processed/<existing_run_dir> \
  --skip-to C \
  --ollama-url http://192.168.90.100:11434
```

---

## Rebuilding Qdrant from Existing JSONL

Re-indexes all documents in `~/documents/processed/` without re-running extraction:

```bash
python3 cli/reqbot.py reindex
```

Useful after: adding a new field to normalized JSONL, or after restoring from backup.

---

## Nuking and Rebuilding the Qdrant Collections

To start fresh (e.g., after a corpus refresh with newly ingested docs):

```bash
# 1. Delete the collections via Qdrant API
curl -X DELETE http://192.168.30.153:6333/collections/grc_requirements_1775409441
curl -X DELETE http://192.168.30.153:6333/collections/grc_context

# 2. Reindex from scratch
python3 cli/reqbot.py reindex

# 3. Re-index context chunks
python3 pipeline/embed_context_index.py --processed-dir ~/documents/processed/
```

> The collection name suffix (`_1775409441`) is a hash of the embedding config. It will be the same after a fresh reindex as long as the model and dimensions haven't changed. Verify with `reqbot status`.

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
