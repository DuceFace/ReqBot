# ReqBot Phase 17 — Setup and Environment Standardization

**Requirements Document — May 2026**

---

## 1. Executive Summary

Phase 17 makes ReqBot runnable on a fresh Linux system with a single command. Today,
getting ReqBot working requires manual steps: install Docker, pull Qdrant, install Ollama,
pull models, write a config file. A first-time user who reads the README and runs
`reqbot setup` should have a working `reqbot ask` in one session, without editing a
config file or issuing a separate `ollama pull`.

Phase 17 is infrastructure work. It does not change the pipeline, the retrieval engine,
the service layer, or the API. All changes are confined to `cli/reqbot.py` (`cmd_setup`),
`core/synthesis.py` (lazy model pull), and minor supporting changes to `core/config.py`
if needed.

---

## 2. Relationship to Prior Phases

- **Phase 16** delivered the service layer and read-only API. Phase 17 builds on the
  existing `reqbot init` wizard (`cmd_init`) — `--advanced` mode will be a thin alias
  for it rather than a rewrite.
- **Phase 18** (GUI) depends on Phase 17 being able to stand up a working backend
  environment on a fresh machine before the frontend is layered on.

---

## 3. Work Package Summary

| WP | Title | Scope |
|----|-------|-------|
| WP-17.1 | `reqbot setup` automated flow | New subcommand; Docker check, Qdrant container, Ollama check/install, core model pull, config write, status confirm |
| WP-17.2 | Lazy synthesis model pull | Detect missing synthesis model on first `--synthesize` use; pull transparently with progress message |
| WP-17.3 | `reqbot setup --advanced` | Flag that drops into the existing `reqbot init` interactive flow; `init` command kept as alias |

---

## 4. WP-17.1 — `reqbot setup` Automated Flow

### 4.1 Goal

A user with Docker installed can run `reqbot setup` on a fresh Linux machine and arrive
at a working `reqbot ask` without any other manual steps.

### 4.2 Command

```
reqbot setup [--advanced]
```

Default (no flags): automated flow described in §4.3.
`--advanced`: drops into the existing interactive `reqbot init` wizard (§6).

### 4.3 Setup Flow (default path)

The command executes these steps in order. Each step prints a clear status line. Any
hard failure prints an actionable error message and exits non-zero.

#### Step 1 — Docker check

```
[1/5] Checking for Docker...
```

- Run `docker info` (or `docker version`) to verify Docker is installed and the daemon
  is reachable.
- **If Docker is missing or daemon is not running:** print a clear message with
  installation instructions and exit 1. Do not auto-install Docker — it requires
  distro-specific handling and often `sudo`, making silent install unsafe and fragile.

```
[-] Docker is not running or not installed.
    Install Docker: https://docs.docker.com/engine/install/
    Then start the daemon and re-run: reqbot setup
```

#### Step 2 — Qdrant container

```
[2/5] Starting Qdrant...
```

Check and start state in order:

1. `docker ps` — if a container named `reqbot-qdrant` is already running, print
   `Already running` and skip.
2. `docker ps -a` — if `reqbot-qdrant` exists but is stopped, run `docker start reqbot-qdrant`.
3. Otherwise, run:

```bash
docker run -d \
  --name reqbot-qdrant \
  --restart unless-stopped \
  -p 6333:6333 \
  -v "$HOME/.reqbot/qdrant:/qdrant/storage" \
  qdrant/qdrant
```

- Data directory: `~/.reqbot/qdrant/` — persists across upgrades (install dir
  `~/.reqbot/` is wiped on upgrade, but the qdrant subdirectory is excluded; verify
  this is true in the installer or document the caveat).
- Port: 6333 (default Qdrant REST port).
- After starting, poll `http://localhost:6333/collections` up to 10 times (1s sleep
  between attempts) to confirm Qdrant is accepting connections before proceeding.

#### Step 3 — Ollama check and install

```
[3/5] Checking for Ollama...
```

- Run `ollama --version` (or `which ollama`) to check if Ollama is installed.
- **If installed:** print `Found Ollama <version>` and skip installation.
- **If missing:** print the intent and run the official installer:

```
    Not found. Installing Ollama via official installer...
```

```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

This is the only auto-install step. It is transparent (user sees the installer output),
uses the official channel, and is widely documented. After install, verify `ollama serve`
is running (check the API at `http://localhost:11434`); start it if not.

#### Step 4 — Pull core models

```
[4/5] Pulling core models...
```

Pull exactly two models — enough to make `reqbot ask` and `reqbot ingest` work:

| Model | Size (approx.) | Purpose |
|-------|----------------|---------|
| `nomic-embed-text` | ~274 MB | Dense embeddings (required for search) |
| `llama3.1:8b-instruct-q4_K_M` | ~4.7 GB | Step C extraction + query rewriting |

For each model:
- Check if already present: `ollama list` and look for the model name.
- If present: print `Already pulled` and skip.
- If missing: run `ollama pull <model>` — the Ollama CLI shows progress natively.

Do **not** pull `qwen2.5:14b` (synthesis model, ~9 GB) here. It is lazy-loaded in WP-17.2.

Total first-run download (if both missing): ~5 GB.

#### Step 5 — Write config and confirm

```
[5/5] Writing config and running status check...
```

- Write `~/.config/reqbot/config.json` with localhost defaults:
  - `qdrant_url`: `http://localhost:6333`
  - `ollama_url`: `http://localhost:11434`
  - All model names at their standard defaults (same as `core/config.py _DEFAULTS`)
- **If a config file already exists:** print a warning and ask before overwriting:

```
    Config already exists at ~/.config/reqbot/config.json.
    Overwrite with localhost defaults? (y/N):
```

  If user says no: skip the write (existing config stands).

- Run `reqbot status` inline and print its output. If status shows all green, print the
  success banner:

```
=== ReqBot is ready ===

  reqbot ask "what are the password requirements?"
  reqbot docs
  reqbot serve   # starts the read-only API on http://127.0.0.1:8000

Note: The synthesis model (qwen2.5:14b, ~9 GB) will download automatically
on your first use of --synthesize.
```

### 4.4 Implementation Notes

- `cmd_setup` lives in `cli/reqbot.py` alongside `cmd_init` and the other `cmd_*`
  functions.
- All subprocess calls (`docker`, `ollama`) use `subprocess.run()` with explicit
  `check=False` — capture returncode and stderr, handle failures explicitly rather than
  letting exceptions propagate unchecked.
- HTTP polling (Qdrant readiness) uses `requests.get()` with a short timeout, same
  pattern as `cmd_init`'s `_test_qdrant()`.
- The setup command must be importable without Docker, Ollama, or any third-party package
  installed — all subprocess and HTTP calls happen inside the function body, not at
  module import time.

### 4.5 Success Criteria

- Fresh Linux machine with Docker installed → `reqbot setup` completes without errors
- `reqbot ask "test"` succeeds after setup without any additional manual steps
- `reqbot status` shows all green after setup
- No manual config editing required
- Clear, actionable error message for every failure path (Docker missing, Qdrant
  fails to start, Ollama install fails, model pull fails)
- Re-running `reqbot setup` on an already-configured machine is safe and idempotent
  (each step skips if already satisfied)

---

## 5. WP-17.2 — Lazy Synthesis Model Pull

### 5.1 Goal

Users who only need search and trace should not wait for a 9 GB download during setup.
The synthesis model (`qwen2.5:14b`) is pulled automatically and transparently on the
first command that requires it.

### 5.2 Trigger Points

Any path that calls `core/synthesis.py`'s `synthesize_answer()` or
`core/ask.retrieve()` with `synthesize=True` can trigger the lazy pull. The cleanest
hook is inside `synthesize_answer()` itself — it already handles the Ollama client
and knows which model is requested.

### 5.3 Behavior

When `synthesize_answer()` is called with a local Ollama backend:

1. Before issuing the generation request, check whether the model is available:
   `GET http://<ollama_url>/api/tags` and scan the name list.
2. If the model is **not** present, print to stderr (one-time message):

```
[*] Synthesis model qwen2.5:14b not found locally. Downloading (~9 GB)...
    This is a one-time download. Run `ollama pull qwen2.5:14b` manually to
    control timing.
```

3. Run `ollama pull <synthesis_model>` via subprocess, streaming output to stderr so
   the user sees progress.
4. After the pull completes, proceed with the synthesis call normally.

### 5.4 Scope Constraints

- Lazy pull applies to **local Ollama backend only**. Remote synthesis (Anthropic,
  OpenAI) has no model to pull.
- The check adds one HTTP call per synthesis invocation only when the model is missing.
  Once pulled, the check is a fast list lookup with no noticeable overhead.
- Do not add a persistent "model is pulled" flag or cache file — the `/api/tags`
  check is the authoritative source.

### 5.5 Success Criteria

- First `reqbot ask "..." --synthesize` after setup pulls the synthesis model
  transparently with visible progress
- Subsequent `--synthesize` calls do not repeat the download or the check message
- Pulling a remote synthesis backend (Anthropic, OpenAI) is unaffected

---

## 6. WP-17.3 — `reqbot setup --advanced`

### 6.1 Goal

Power users who want to configure remote Ollama/Qdrant URLs, custom models, or remote
synthesis backends should still have access to the full interactive wizard.

### 6.2 Behavior

`reqbot setup --advanced` runs the existing `cmd_init` logic verbatim. No rewrite of
`cmd_init` is required in this phase — `--advanced` is a dispatch alias:

```python
def cmd_setup(args: argparse.Namespace) -> int:
    if getattr(args, "advanced", False):
        return cmd_init(args)
    # ... automated flow ...
```

`reqbot init` remains available as a direct command (no deprecation in this phase).

### 6.3 Success Criteria

- `reqbot setup --advanced` produces identical behavior to `reqbot init`
- `reqbot init` still works unchanged

---

## 7. Explicit Exclusions

The following are out of scope for Phase 17:

- **Air-gapped bundle** — designing an offline bundle (`reqbot setup --offline
  /path/to/bundle`) that includes pre-pulled model files and a Qdrant Docker image.
  The setup command should accept `--offline <path>` as a flag from day one (to avoid
  a future breaking change) but the bundle itself is not built in this phase.
  Implementation: `--offline` flag is parsed but prints `Not yet implemented` and exits.
- **Windows / macOS support** — setup.sh targets Linux. Other platforms are deferred.
- **Docker Compose full-stack** — API + GUI + Qdrant in one `docker-compose up`.
  Natural extension of Phases 16–18 but not a Phase 17 deliverable.
- **`reqbot uninstall`** — out of scope.
- **Automated Qdrant upgrade** — if a newer Qdrant image is available, setup does not
  auto-upgrade. Document this as a manual `docker pull qdrant/qdrant` + container
  recreation step in README if needed.

---

## 8. Anti-Patterns to Avoid

- **Silent installs.** Only Ollama is auto-installed, and it is done visibly using the
  official installer with all output passed through to the terminal. Docker is never
  silently installed.
- **Swallowing subprocess failures.** Every `subprocess.run()` call checks the return
  code. A failed `docker run`, `ollama pull`, or `ollama install` stops the setup with
  an actionable message, never silently continues.
- **Mutation of pipeline or retrieval behavior.** Phase 17 is CLI-only. No changes to
  `core/ask.py`, the service layer, or the API.
- **Adding setup logic to module import time.** All Docker/Ollama checks happen inside
  `cmd_setup()`. Importing `cli/reqbot.py` must not trigger any subprocess or network
  call.

---

## 9. Files Changed

| File | Change |
|------|--------|
| `cli/reqbot.py` | Add `cmd_setup()`; add `setup` subparser with `--advanced` and `--offline` flags; add `"setup": cmd_setup` to commands dict |
| `core/synthesis.py` | Add lazy model pull check inside `synthesize_answer()` local path |
| `docs/PHASE17_REQUIREMENTS.md` | This document |

No new pip dependencies. `subprocess`, `requests`, and `time` are all already in use.

---

## 10. Final Gate

Phase 17 is complete when:

- `reqbot setup` on a Docker-equipped fresh Linux machine produces a working
  `reqbot ask` in one session, no manual steps required
- Re-running `reqbot setup` is idempotent and safe
- `--synthesize` triggers a transparent model pull on first use
- `reqbot setup --advanced` and `reqbot init` behave identically
- `--offline` flag is stubbed (parses without error, prints not-implemented message)
- No regression in CLI, pipeline, or API behavior
