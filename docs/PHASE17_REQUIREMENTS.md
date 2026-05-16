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
the service layer, or the API. All changes are confined to `cli/reqbot.py` (`cmd_setup`)
and `core/synthesis.py` (lazy model pull).

---

## 2. Relationship to Prior Phases

- **Phase 16** delivered the service layer and read-only API. Phase 17 builds on the
  existing `reqbot init` wizard (`cmd_init`) — `--advanced` mode will be a thin alias
  for it rather than a rewrite.
- **Phase 18** (GUI) depends on Phase 17 being able to stand up a working backend
  environment on a fresh machine before the frontend is layered on.

---

## 3. Decisions Locked for Phase 17

These decisions are fixed. They are not re-opened during implementation.

| Decision | Choice |
|----------|--------|
| Target platform | Linux x86_64 only |
| Docker | Required prerequisite — never auto-installed |
| Qdrant runtime | Docker container (`reqbot-qdrant`) |
| Qdrant data path | `~/.local/share/reqbot/qdrant/` — XDG, outside installer tree |
| Ollama | Only thing auto-installed; official installer only |
| Ollama service management | Verify reachability only; never invoke `ollama serve` directly |
| Synthesis model | Lazy-pulled on first `--synthesize` use; not pulled during setup |
| `reqbot init` | Kept unchanged; `reqbot setup --advanced` delegates to it verbatim |
| Air-gapped path | Future extension — not built in Phase 17; no `--offline` flag shipped |

---

## 4. Work Package Summary

| WP | Title | Scope |
|----|-------|-------|
| WP-17.1 | `reqbot setup` automated flow | New subcommand; Docker check, Qdrant container, Ollama check/install, core model pull, config write, status confirm |
| WP-17.2 | Lazy synthesis model pull | Detect missing synthesis model on first `--synthesize` use; pull transparently with progress message |
| WP-17.3 | `reqbot setup --advanced` | Flag that drops into the existing `reqbot init` interactive flow; `init` command kept unchanged |

---

## 5. WP-17.1 — `reqbot setup` Automated Flow

### 5.1 Goal

A user with Docker installed can run `reqbot setup` on a fresh Linux machine and arrive
at a working `reqbot ask` without any other manual steps.

### 5.2 Command

```
reqbot setup [--advanced]
```

Default (no flags): automated flow described in §5.3.
`--advanced`: drops into the existing interactive `reqbot init` wizard (§7).

### 5.3 User-Facing Flow

The command executes five steps in order. Each step prints a `[N/5]` status line before
starting. Any hard failure prints an actionable error message and exits non-zero — the
remaining steps do not run.

#### Step 1 — Docker check

```
[1/5] Checking for Docker...
      OK — Docker 26.1.4
```

Run `docker info` to verify Docker is installed and the daemon is reachable. Print the
detected version on success.

On failure:

```
[-] Docker is not running or not installed.
    Install Docker:  https://docs.docker.com/engine/install/
    Start the daemon and re-run: reqbot setup
```

Exit 1. Docker is never auto-installed.

#### Step 2 — Qdrant container

```
[2/5] Starting Qdrant...
      Container reqbot-qdrant started.
      Waiting for Qdrant to accept connections...
      OK — Qdrant ready (http://localhost:6333)
```

State machine (check in order):

1. `docker ps` — container `reqbot-qdrant` already running → print `Already running` and skip.
2. `docker ps -a` — container exists but stopped → `docker start reqbot-qdrant`.
3. Container does not exist → `docker run`:

```bash
docker run -d \
  --name reqbot-qdrant \
  --restart unless-stopped \
  -p 6333:6333 \
  -v "$HOME/.local/share/reqbot/qdrant:/qdrant/storage" \
  qdrant/qdrant
```

**Data path:** `~/.local/share/reqbot/qdrant/` — XDG Base Directory, outside the
installer-managed `~/.reqbot/` tree. Installer upgrades wipe `~/.reqbot/`; they do not
touch `~/.local/share/`. This path is safe across all upgrade paths without any special
installer exclusion logic.

After the container starts, poll `http://localhost:6333/collections` (up to 10 attempts,
1-second sleep between) to confirm Qdrant is accepting connections before proceeding.

#### Step 3 — Ollama check and install

```
[3/5] Checking for Ollama...
      Found Ollama 0.6.1 — reachable at http://localhost:11434
```

**Check (binary):** run `ollama --version`. If found, verify the API is reachable:
`GET http://localhost:11434` with a 5-second timeout.

- API reachable → print version and continue.
- Binary found but API not reachable → print instructions and exit 1:

```
[-] Ollama is installed but not reachable at http://localhost:11434.
    Ensure the Ollama service is running and re-run: reqbot setup
```

Do not attempt to start the Ollama service. The official installer manages the service
via systemd or an equivalent init system. Invoking `ollama serve` directly from setup
would conflict with that and could result in duplicate processes or non-persistent
behavior. Verifying reachability is sufficient.

**Install (binary missing):** print intent and run the official installer:

```
      Not found. Installing Ollama via official installer...
```

```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

Stream the installer's stdout/stderr directly to the terminal. After the installer exits,
verify API reachability at `http://localhost:11434` (same poll pattern as Qdrant — up to
10 attempts, 1-second sleep). If the API is still not reachable after polling:

```
[-] Ollama was installed but the service is not yet reachable at http://localhost:11434.
    Try: systemctl start ollama   (or your init system's equivalent)
    Then re-run: reqbot setup
```

Exit 1.

#### Step 4 — Pull core models

```
[4/5] Pulling core models...
      nomic-embed-text      Already pulled
      llama3.1:8b-instruct-q4_K_M  Pulling... (4.7 GB)
```

Pull exactly two models. For each: check `ollama list`; skip if present; otherwise run
`ollama pull <model>` with stdout/stderr streamed directly to the terminal.

| Model | Size (approx.) | Purpose |
|-------|----------------|---------|
| `nomic-embed-text` | ~274 MB | Dense embeddings (required for search) |
| `llama3.1:8b-instruct-q4_K_M` | ~4.7 GB | Step C extraction + query rewriting |

Do **not** pull `qwen2.5:14b` (synthesis, ~9 GB) — lazy-loaded in WP-17.2.

Total first-run download (both missing): ~5 GB.

#### Step 5 — Write config and confirm

```
[5/5] Writing config and running status check...
      Config written to ~/.config/reqbot/config.json
```

Write `~/.config/reqbot/config.json` with localhost defaults:
- `qdrant_url`: `http://localhost:6333`
- `ollama_url`: `http://localhost:11434`
- All model names at their standard defaults (same as `core/config.py _DEFAULTS`)

If a config file already exists, ask before overwriting:

```
    Config already exists at ~/.config/reqbot/config.json.
    Overwrite with localhost defaults? (y/N):
```

If user says no, skip the write (existing config stands).

Run `reqbot status` inline and print its output. If status shows all green, print:

```
=== ReqBot is ready ===

  reqbot ask "what are the password requirements?"
  reqbot docs
  reqbot serve   # starts the read-only API on http://127.0.0.1:8000

Note: The synthesis model (qwen2.5:14b, ~9 GB) will download automatically
on your first use of --synthesize.
```

---

### 5.4 Behavior on Re-Run

`reqbot setup` is idempotent. Running it on an already-configured machine is always safe.

| Component | State | Behavior |
|-----------|-------|----------|
| Docker | Running | Proceed |
| Docker | Not running / not installed | Exit 1 with instructions |
| `reqbot-qdrant` container | Running | Skip — print `Already running` |
| `reqbot-qdrant` container | Stopped | `docker start reqbot-qdrant` |
| `reqbot-qdrant` container | Does not exist | `docker run` with volume mount |
| Ollama binary | Present and API reachable | Skip install — print version |
| Ollama binary | Present but API not reachable | Exit 1 with instructions |
| Ollama binary | Missing | Run official installer; poll for reachability |
| `nomic-embed-text` | Already pulled | Skip — print `Already pulled` |
| `nomic-embed-text` | Missing | `ollama pull` |
| `llama3.1:8b-instruct-q4_K_M` | Already pulled | Skip — print `Already pulled` |
| `llama3.1:8b-instruct-q4_K_M` | Missing | `ollama pull` |
| Config file | Exists | Prompt before overwrite |
| Config file | Does not exist | Write with localhost defaults |

---

### 5.5 Failure Handling Matrix

| Failure | User Message | Exit Code | Setup Continues? |
|---------|-------------|-----------|-----------------|
| Docker not installed | "Install Docker: ..." | 1 | No |
| Docker daemon not running | "Start the daemon and re-run..." | 1 | No |
| `docker run reqbot-qdrant` fails | "Failed to start Qdrant container: <stderr>" | 1 | No |
| Qdrant not reachable after 10s | "Qdrant did not become ready in time..." | 1 | No |
| Ollama API not reachable (binary present) | "Ensure the Ollama service is running..." | 1 | No |
| Ollama official installer exits non-zero | "Ollama install failed: <stderr>" | 1 | No |
| Ollama API not reachable after install | "Service not yet reachable — try: systemctl start ollama" | 1 | No |
| `ollama pull` exits non-zero | "Model pull failed: <model> — <stderr>" | 1 | No |
| Config write fails (permissions) | "Could not write config: <error>" | 1 | No |
| User declines config overwrite | Existing config used; setup continues | — | Yes |
| `reqbot status` reports unhealthy | Status output shown; no hard exit | 0 | — |

All failure messages end with a concrete next-step instruction. Generic `Something went
wrong` messages are not acceptable.

---

### 5.6 Internal Implementation Notes

- `cmd_setup` lives in `cli/reqbot.py` alongside the other `cmd_*` functions.
- All subprocess calls (`docker`, `ollama`) use `subprocess.run()` with `check=False`.
  Capture `returncode` and `stderr`; handle failures explicitly.
- For long-running commands (`docker run`, `ollama pull`, Ollama installer): pass
  `stdout=None, stderr=None` so the subprocess inherits the parent's terminal and the
  user sees live output. For brief probe commands (`docker info`, `ollama --version`,
  HTTP checks): capture output for parsing.
- HTTP polling uses `requests.get()` with a 5-second timeout, same pattern as
  `cmd_init`'s `_test_qdrant()`. Sleep 1 second between attempts; give up after 10.
- All subprocess and HTTP calls happen inside `cmd_setup()`. Importing `cli/reqbot.py`
  must not trigger any subprocess or network call — this is already the pattern for all
  other `cmd_*` functions.
- No new pip dependencies. `subprocess`, `requests`, `time`, and `os` are all already in
  use in `cli/reqbot.py`.

---

### 5.7 Success Criteria

- Fresh Linux machine with Docker installed → `reqbot setup` completes, `reqbot ask "test"` works
- `reqbot status` shows all green after setup completes
- No manual config editing required
- Re-running on an already-configured machine is safe and idempotent per §5.4
- Every failure path produces a message matching the matrix in §5.5

---

## 6. WP-17.2 — Lazy Synthesis Model Pull

### 6.1 Goal

Users who only need search and trace should not wait for a 9 GB download during setup.
The synthesis model (`qwen2.5:14b`) is pulled automatically and transparently on the
first command that requires it.

### 6.2 Hook Location

`core/synthesis.py` — inside `synthesize_answer()`, local Ollama path only. This
function already holds the model name and Ollama URL; it is the right place to check
presence before issuing a generation request.

### 6.3 User-Facing Behavior

When `synthesize_answer()` is called with a local Ollama backend and the model is not
present:

1. Print to stderr (one-time, before pull begins):

```
[*] Synthesis model qwen2.5:14b not found locally. Downloading (~9 GB)...
    This is a one-time download. Run `ollama pull qwen2.5:14b` manually to
    control timing.
```

2. Run `ollama pull <synthesis_model>` via subprocess with output streamed to the
   terminal.
3. After the pull completes, proceed with the synthesis call normally.

### 6.4 Internal Behavior

- Check: `GET http://<ollama_url>/api/tags`, scan `models[].name` for the synthesis
  model. If present, skip all of the above.
- The `/api/tags` check adds one lightweight HTTP call per synthesis invocation while
  the model is absent. Once pulled, the check is a fast list scan — no noticeable
  overhead.
- Do not add a persistent "model is present" flag or cache file. The `/api/tags`
  endpoint is the authoritative source.

### 6.5 Scope Constraints

- Lazy pull applies to **local Ollama backend only**. Remote synthesis (Anthropic,
  OpenAI) has no model to pull; skip the check entirely on the remote path.
- No changes to `core/ask.py`, the service layer, or the API.

### 6.6 Success Criteria

- First `reqbot ask "..." --synthesize` after setup pulls the synthesis model
  transparently with visible progress
- Subsequent `--synthesize` calls proceed without a download or check message
- Remote synthesis backends (Anthropic, OpenAI) are unaffected

---

## 7. WP-17.3 — `reqbot setup --advanced`

### 7.1 Goal

Power users who want to configure remote Ollama/Qdrant URLs, custom models, or remote
synthesis backends should still have access to the full interactive wizard.

### 7.2 Behavior

`reqbot setup --advanced` dispatches to `cmd_init` verbatim:

```python
def cmd_setup(args: argparse.Namespace) -> int:
    if getattr(args, "advanced", False):
        return cmd_init(args)
    # ... automated flow ...
```

`reqbot init` remains a direct command. No deprecation in this phase.

### 7.3 Success Criteria

- `reqbot setup --advanced` is identical in behavior to `reqbot init`
- `reqbot init` works unchanged

---

## 8. Explicit Exclusions

| Exclusion | Rationale |
|-----------|-----------|
| Windows / macOS support | Linux x86_64 only in Phase 17 |
| Docker Compose full-stack | API + GUI + Qdrant as one `docker-compose up` — natural extension of Phase 18, not a Phase 17 deliverable |
| `reqbot uninstall` | Out of scope |
| Automated Qdrant upgrade | No auto-upgrade; users run `docker pull qdrant/qdrant` + container recreation manually |
| Air-gapped offline bundle | Future extension. The `--offline` flag is **not** shipped as a stub — CLI surface area should not be added before the feature exists. Document the planned flag in a future PHASE19+ requirements doc when ready. |

---

## 9. Anti-Patterns to Avoid

- **Silent installs.** Only Ollama is auto-installed, using the official installer with
  all output passed through to the terminal. Docker is never silently installed.
- **Managing the Ollama service lifecycle.** Never invoke `ollama serve` from setup.
  The official installer owns service management; verify reachability and fail cleanly
  if it is not reachable.
- **Swallowing subprocess failures.** Every `subprocess.run()` call inspects the return
  code. A failed `docker run`, `ollama pull`, or Ollama install stops setup with an
  actionable message matching the matrix in §5.5.
- **Setup logic at import time.** All subprocess and HTTP calls stay inside `cmd_setup()`.
  Importing `cli/reqbot.py` must not trigger network or subprocess calls.
- **Mutation of pipeline or retrieval behavior.** Phase 17 touches only `cli/reqbot.py`
  and `core/synthesis.py`. No changes to `core/ask.py`, the service layer, or the API.

---

## 10. Files Changed

| File | Change |
|------|--------|
| `cli/reqbot.py` | Add `cmd_setup()`; add `setup` subparser with `--advanced` flag; add `"setup": cmd_setup` to commands dict |
| `core/synthesis.py` | Add lazy model presence check + pull inside `synthesize_answer()` local Ollama path |
| `README.md` | Update quick-start section to lead with `reqbot setup` instead of manual first-run steps |
| `ARCHITECTURE.md` | Note that `reqbot setup` is operational bootstrap — not part of pipeline/runtime retrieval logic |

No new pip dependencies. `subprocess`, `requests`, `time`, and `os` are all already
imported in `cli/reqbot.py`.

---

## 11. Final Gate

Phase 17 is complete when:

- `reqbot setup` on a Docker-equipped fresh Linux machine produces a working
  `reqbot ask` in one session, no manual steps required
- Re-running `reqbot setup` on an already-configured machine is safe and produces
  no unintended side effects (idempotency per §5.4)
- First `--synthesize` call triggers a transparent synthesis model pull
- `reqbot setup --advanced` and `reqbot init` behave identically
- No regression in CLI, pipeline, service layer, or API behavior
