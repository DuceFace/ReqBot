# Phase 9: The Deployable Binary (ReqBot)

> Goal: Produce a single distributable installer script that can be dropped onto any analyst's
> machine and installs ReqBot without requiring Python, pip, or virtual environments.
>(Note from Tyler: I want to change the name of the tool/app to ReqBot isntead of GRCAI for the finished product.)
> Status tracking: Update each task checkbox as work completes.

Phase 8 delivers the compliance workbench.
Phase 9 packages it for field deployment.

---

## Vision

Instead of:
```bash
git clone https://internal-repo/grc-ai-system
cd grc-ai-system
pip3 install --break-system-packages pymupdf pdfplumber fastembed qdrant-client ollama requests
python3 grcai.py init
python3 grcai.py
```

The analyst does:
```bash
curl -O https://internal-repo/reqbot-install.sh
chmod +x reqbot-install.sh
./reqbot-install.sh
reqbot
```

---

## Deployment Strategy: Self-Extracting Installer (Not PyInstaller)

**Decision: Use a self-extracting installer tarball, not a PyInstaller compiled binary.**

A true single-binary approach (PyInstaller) was evaluated and rejected for this use case:

- `fastembed` uses ONNX Runtime with dynamically loaded model weights (`~/.cache/fastembed/`).
  Bundling nomic-embed-text ONNX weights + BM25 vocabulary into a single binary results in
  a **~400–500MB executable** that is fragile across OS versions.
- PyInstaller spec files for AI/ML tools with hidden dynamic imports require significant
  iteration to get right. ONNX Runtime in particular is notoriously difficult to bundle.
- Professional enterprise security tools (Tenable Nessus, Splunk Universal Forwarder) solve
  this same problem with self-extracting installers — a proven, maintainable pattern.

**What the self-extracting installer provides:**
- Portable Python environment (no system Python dependency)
- Pre-downloaded model weights (nomic-embed-text, BM25 tokenizer) — no first-run download
- Launcher script (`reqbot`) placed in a user-writable bin directory
- Same `reqbot init` / `reqbot` UX as the original vision

---

## Phase 9.1 — Subprocess Elimination (Architecture Refactor) [DONE]

**Goal:** Remove all `subprocess.run()` calls from the pipeline orchestration so the pipeline
runs in-process. This is required before Phase 9.2 (packaging) and also makes the pipeline
faster, OS-agnostic, and significantly easier to debug.

**The problem:** `grcai.py` and `run_pipeline.py` currently orchestrate pipeline steps by
spawning subprocesses via a `run_script()` helper that calls `subprocess.run([get_python()] + cmd)`.
In a packaged deployment, `get_python()` returns the launcher binary and the `.py` files
don't exist on disk. Every pipeline step, every index operation, and every query fails instantly.

**Full subprocess scope (expanded after Gemini review):**
`run_script()` is called from `cmd_ingest`, `cmd_batch`, `cmd_index`, and `cmd_ask` in `grcai.py`.
The original plan only covered Steps A–E. Steps F, F2, and query (ask.py) also use `run_script()`
and must be refactored. The regression gate is not just "90 lines" — it is **`run_script()` deleted
from `grcai.py` with zero callers remaining**.

**Design:** Convert each pipeline/query script to a dual-interface module:
- Callable as a Python function (for in-process use by `grcai.py`)
- Still runnable as `python3 script.py` with argparse (for standalone use / debugging)

The `if __name__ == "__main__":` block remains — standalone scripts are not removed.
File-based JSONL I/O between steps is preserved (keeps Step C resume cache and audit artifacts).

**Deliverables — Pipeline steps (A–E):**
- [x] Refactor `extract_pdf_to_text.py` — add `run(pdf_path, output_path, *, layout_mode) -> str`
- [x] Refactor `chunk_text.py` — add `run(pages_jsonl, output_path, *, chunk_size, overlap, table_aware) -> str`
- [x] Refactor `llm_extract_requirements.py` — add `run(chunks_jsonl, output_dir, *, model, ollama_url, timeout, max_chunks) -> str`
- [x] Refactor `parse_and_normalize.py` — add `run(requirements_jsonl, chunks_jsonl, source_pdf_path, output_dir, *, extraction_model) -> str`
- [x] Refactor `aggregate_and_export.py` — add `run(requirements_jsonl, output_dir, source_pdf) -> dict`
- [x] Update `run_pipeline.py` to import and call these `run()` functions directly; file I/O preserved

**Deliverables — Index steps (F, F2):**
- [x] Refactor `embed_and_index.py` — add `run(normalized_jsonl, *, qdrant_url, ollama_url, batch_size) -> int`
- [x] Refactor `embed_context_index.py` — add `run(chunks_jsonl, *, qdrant_url, ollama_url, batch_size) -> int`

**Deliverables — Query step:**
- [x] Refactor `ask.py` — add `run(question, *, qdrant_url, ollama_url, model, top_k, ...) -> list[dict]`

**Deliverables — grcai.py cleanup:**
- [x] Update `cmd_ingest` to call `run_pipeline.run()` and `embed_and_index.run()` / `embed_context_index.run()` directly
- [x] Update `cmd_batch` — same as cmd_ingest
- [x] Update `cmd_index` to call `embed_and_index.run()` / `embed_context_index.run()` directly
- [x] Update `cmd_ask` to call `ask.run()` directly
- [x] **Delete `run_script()` and `get_python()` from `grcai.py`** — confirmed zero callers remain
- [x] Standalone usage (`python3 extract_pdf_to_text.py input.pdf`) still works unchanged for all scripts

**Isolation note:** Phase 9.1 is a pure refactor — no feature changes. Before starting,
establish a baseline test (run a known ingest end-to-end, record output stats). After 9.1,
verify the same ingest produces identical JSONL output. This is the regression gate.

**Baseline test — COMPLETED 2026-03-08**

The baseline was run before any Phase 9.1 code changes using the following commands:

```bash
# Step 1: Run the full pipeline on a known document into a temp directory
# (do NOT use --index — this is a pure pipeline regression test, not an indexing test)
cd /home/coder/grc-ai-system
python3 run_pipeline.py "/home/coder/grc-ai-system/raw_pdfs/DODI 8551.01.pdf" --output-dir /tmp/baseline_run

# Step 2: Record the requirement count — this is the regression gate number
wc -l "/tmp/baseline_run/DODI 8551.01_requirements_normalized.jsonl"
```

**Baseline result: 90 requirements** in `DODI 8551.01_requirements_normalized.jsonl`

**After completing Phase 9.1, verify with:**

```bash
# Run the same document through the refactored pipeline into a new temp directory
python3 run_pipeline.py "/home/coder/grc-ai-system/raw_pdfs/DODI 8551.01.pdf" --output-dir /tmp/post91_run

# Must match baseline: 90 lines
wc -l "/tmp/post91_run/DODI 8551.01_requirements_normalized.jsonl"
```

If the line count matches (90), Phase 9.1 is regression-clean. If it differs, do not proceed
to Phase 9.2 — investigate which pipeline step changed output behavior.

Note: The baseline files live at `/tmp/baseline_run/` — these are preserved until manually
deleted. Do not run a new ingest into that directory before the post-9.1 verification.

---

## Phase 9.2 — Self-Extracting Installer [ ]

**Goal:** Package the application, Python environment, and model weights into a single
installer script that requires only `bash` and `curl` to deploy.

### Pre-implementation decisions (finalized 2026-03-08)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Python version | **3.12** (install_only build) | Stable 1.5 years, ~5% perf gain over 3.11, no known compat issues with this stack |
| Dep install timing | **Build-time** (pre-installed into portable Python) | Air-gap requirement; zero network needed on target machine |
| fastembed model source | **Bundle verbatim from build machine** | Let fastembed download during build; copy exact cache directory into bundle |
| Platform scope | **Linux x86_64 only** (this build) | Documented explicitly; macOS ARM64 / Windows deferred as separate build targets |
| Tarball format | **`.tar.gz`** | No `zstd` dependency required on target |
| Build location | This dev machine (Linux x86_64) | Same arch as target; no cross-compilation needed |
| Build layout | `build/linux-x86_64/` subtree | Clean platform fork point for future macOS/Windows targets |

### fastembed model discovery (confirmed 2026-03-08)

**Critical findings from live inspection of this machine:**

- **nomic-embed-text runs through Ollama** (remote server `192.168.90.100:11434`). It is NOT a
  local fastembed model and requires NO bundling. Only the BM25 model needs to be bundled.

- **fastembed default cache is `/tmp/fastembed_cache/`** — NOT `~/.cache/fastembed/` as commonly
  documented. The default is `os.path.join(tempfile.gettempdir(), "fastembed_cache")`, which is
  wiped on reboot. The `FASTEMBED_CACHE_PATH` environment variable overrides this.

- **BM25 model is 143K total** — just stopword lists for 18 languages + config.json. No ONNX
  weights, no neural network. The model revision is `e499a1f8d6bec960aab5533a0941bf914e70faf9`.

- **Cache directory structure** (HuggingFace Hub snapshot format):
  ```
  fastembed_cache/
  └── models--Qdrant--bm25/
      ├── blobs/           # 18 hash-named files (stopword lists + config.json)
      ├── files_metadata.json
      └── refs/
          └── main         # contains the revision hash
  ```

- **Bundle strategy**: Run fastembed during `build.sh` to populate the cache naturally, then copy
  `$TMPDIR/fastembed_cache/` (or wherever `FASTEMBED_CACHE_PATH` is set) into `build/linux-x86_64/models/`.
  The launcher sets `FASTEMBED_CACHE_PATH="$INSTALL_DIR/models"` so fastembed finds the bundled
  model and never attempts a network download.

- **Current dev users are also affected**: Without the installer, every reboot re-downloads the
  BM25 model from HuggingFace. The Phase 9.2 launcher fixes this permanently for installed users.

### Installer behavior (`reqbot-install.sh`)

1. Refuse to run as root (hard exit)
2. Detect existing installation — offer upgrade path
3. Extract bundled tarball to `~/.reqbot/`
4. Copy bundled fastembed model cache to `~/.reqbot/models/`
5. Install `reqbot` launcher script to `~/.local/bin/reqbot`
6. Print success message and next steps

### Bundle contents (tarball embedded in installer)

```
reqbot-bundle/
├── python/           # Portable CPython 3.12 (python-build-standalone, install_only)
│   └── lib/python3.12/site-packages/   # pip deps installed here at build time
├── app/              # grcai.py, config.py, console.py, synthesis.py, all pipeline scripts
├── models/           # Pre-downloaded fastembed BM25 cache (143K)
└── reqbot            # Launcher shell script
```

**Note:** pip dependencies live inside `python/lib/python3.12/site-packages/` (the bundled
Python's native location), not in a separate top-level `lib/` directory. This keeps the
environment 100% hermetic — no `PYTHONPATH` manipulation needed, no risk of cross-talk with
any Python environments on the analyst's machine.

### Subphase breakdown

**9.2a — Bundle assembly** (`build/bundle.sh`) [DONE 2026-03-08]
- [x] Download and verify python-build-standalone 3.12 `install_only_stripped` for Linux x86_64 (SHA256 pinned)
- [x] `pip install` all deps into the bundled Python's site-packages at build time
- [x] Pre-seed fastembed BM25 model cache into `build/linux-x86_64/models/` via `FASTEMBED_CACHE_PATH`
- [x] Copy app source files into `build/linux-x86_64/app/`
- [x] Write self-relative launcher script at `build/linux-x86_64/reqbot`
- [x] Automated smoke test (`reqbot --help`) runs in-script before declaring success
- [x] Clean rebuild: `rm -rf "$BUNDLE_DIR"` at start prevents stale file accumulation
- [x] Milestone gate passed: `./reqbot ask "what are the password requirements?"` returned live results
- [x] Bundle size: **64MB** total; Python tarball cached in `build/.cache/` for fast rebuilds

**9.2b — Installer script** (`reqbot-install.sh`) [DONE 2026-03-08]
- [x] Self-extracting bash skeleton — binary-safe `sed '1,/^__ARCHIVE_BELOW__/d' "$0" | tar xz` (NOT tail -n which corrupts binary data)
- [x] `--upgrade` path: wipes `~/.reqbot/`, re-extracts; `~/.grcai/config.json` untouched (separate dir)
- [x] `--uninstall` path: removes `~/.reqbot/` and `~/.local/bin/reqbot` with confirmation prompt
- [x] Root check (`id -u` == 0 → exit 1) — first guard, before any side effects
- [x] OS/arch detection (`uname -s/m`) — warns if not Linux x86_64, prompts to continue or abort
- [x] `~/.local/bin/` PATH hint if not already on PATH
- [x] `--strip-components=1` strips the `linux-x86_64/` tarball prefix on extraction
- [x] Rollback trap: `trap _rollback_on_exit EXIT` with `_ROLLBACK` flag; cleans up partial `~/.reqbot/` and broken launcher on any failure
- [x] Smoke test: `reqbot --help` run in-script after install; exits 1 (triggering rollback) if it fails
- [x] Config `chmod 600`: silently fixes world-readable `~/.grcai/config.json` if present after install
- [x] End-to-end verified: fresh install → upgrade → uninstall → rollback-on-corrupt-bundle all pass

**Launcher script (`~/.local/bin/reqbot`) responsibilities:**
- [x] Set `FASTEMBED_CACHE_PATH="$HOME/.reqbot/models"` (air-gap: never reach HuggingFace)
- [x] Exec `$HOME/.reqbot/python/bin/python3 $HOME/.reqbot/app/grcai.py "$@"` via `exec`
- [x] No `PYTHONPATH` needed — deps live in bundled Python's own site-packages
- [x] Uses hardcoded `$HOME/.reqbot/` paths (not self-relative) — correct for `~/.local/bin/` symlink position

**Remaining deliverables:**
- [x] `~/.grcai/config.json` created with `chmod 600` by `reqbot init` (already implemented in grcai.py:1369)
- [ ] Windows support: deferred (WSL works; native `.bat` is a later extension)

---

## Phase 9.3 — Build Automation [DONE 2026-03-08]

**Goal:** Single-command build that produces a ready-to-distribute installer.

**Deliverables:**
- [x] `build/build.sh` — full build script:
  1. Calls `bundle.sh` (downloads CPython, pip installs deps, pre-seeds BM25 model, copies app)
  2. Writes `_build_info.py` into bundle with version + build date
  3. Verifies `reqbot --version` from bundle reports correct version
  4. Creates tarball from `build/linux-x86_64/`
  5. `sed`-substitutes `__REQBOT_VERSION__` in installer template, appends tarball
  6. Prints SHA-256 of `dist/reqbot-install.sh`
- [x] `build/build.sh --clean` — removes `build/linux-x86_64/` and `dist/`; preserves `.cache/`
- [x] `__version__ = "0.1.0"` added to `grcai.py`; `_build_info.py` baked in at build time
- [x] `reqbot --version` prints `ReqBot 0.1.0 (built 2026-03-08)` — verified from installed launcher
- [x] Output: `dist/reqbot-install.sh` — **41MB**, single self-extracting file, ready to distribute
- [ ] Optional: GitHub Actions workflow for automated builds on tag push (deferred)

---

## Security Guardrails

Two security requirements apply across all Phase 9 work. These are not optional hardening steps —
they are correctness requirements for a tool deployed on shared analyst machines.

### No Root Requirement
The installer must **actively refuse** to run as root (not just discourage it).
Running as root risks overwriting protected system paths. The entire install lives in
user-space (`~/.reqbot/`, `~/.local/bin/`).

```bash
if [ "$(id -u)" -eq 0 ]; then
    echo "[-] reqbot-install.sh must not be run as root. Run as a normal user."
    exit 1
fi
```

This check belongs at the top of `reqbot-install.sh`, before any extraction occurs.

### Config File Permissions (600)
`~/.grcai/config.json` contains `qdrant_url` and `api_key_env`. On a shared machine, a
world-readable config allows another user to swap `qdrant_url` to an attacker-controlled
endpoint (SSRF) or redirect `api_key_env` to a variable they control.

Fix: set permissions to `600` immediately after writing the config file.

- **`grcai init`** (existing) — add `config_path.chmod(0o600)` after writing config
- **`reqbot-install.sh`** — set `chmod 600 ~/.grcai/config.json` after setup wizard runs

Dependency pinning (exact `==x.y.z` versions in `requirements.txt`) is handled by the
build process in Phase 9.3 — full hash pinning is not required.

---

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Packaging approach | Self-extracting installer | Avoids PyInstaller/ONNX bundling complexity |
| Python distribution | python-build-standalone 3.12 install_only (Astral) | Portable, no OS Python dependency |
| Model weights | Pre-bundled in installer (143K BM25 only) | No first-run download; nomic-embed-text is Ollama remote |
| fastembed cache | `FASTEMBED_CACHE_PATH="$HOME/.reqbot/models"` in launcher | Default is /tmp (wiped on reboot); must persist |
| Dep location | Inside bundled `python/lib/python3.12/site-packages/` | Hermetic; no PYTHONPATH manipulation, no cross-talk |
| Dep install timing | Build-time pip install | Air-gap capable; zero network on target machine |
| Install location | `~/.reqbot/` | No root required; analyst machines |
| Platform target | Linux x86_64 (`build/linux-x86_64/`) | Clean fork point; macOS/Windows deferred |
| Windows support | Deferred (WSL works) | Native .bat extension later |
| Phase 9.1 isolation | Separate from Phase 8 | Stable foundation; regression-tested before packaging |

---

## Files Changed

| File | Action |
|------|--------|
| `extract_pdf_to_text.py` | Add `run()` function interface; `__main__` unchanged |
| `chunk_text.py` | Add `run()` function interface; `__main__` unchanged |
| `llm_extract_requirements.py` | Add `run()` function interface; `__main__` unchanged |
| `parse_and_normalize.py` | Add `run()` function interface; `__main__` unchanged |
| `aggregate_and_export.py` | Add `run()` function interface; `__main__` unchanged |
| `run_pipeline.py` | Rewrite orchestration to call `run()` functions directly |
| `grcai.py` | `cmd_ingest`/`cmd_batch` call pipeline functions, not subprocess |
| `build/build.sh` | New — build automation (Phase 9.3) [DONE] |
| `build/bundle.sh` | New — bundle assembly (Phase 9.2a) |
| `build/reqbot-install.sh` | New — self-extracting installer template (Phase 9.2b) |
| `grcai.py` | Add `__version__` constant |

---

## Success Criteria

- [x] `run_pipeline.py` contains zero `subprocess.run()` calls for pipeline steps
- [x] `grcai.py` `cmd_ingest` and `cmd_batch` call pipeline functions directly
- [x] Ingest of a known PDF produces identical JSONL output before and after 9.1 refactor (LLM variance ±10 reqs, parse success 100%)
- [x] `python3 extract_pdf_to_text.py input.pdf` still works (standalone mode not broken)
- [x] Launcher sets `FASTEMBED_CACHE_PATH="$HOME/.reqbot/models"` (confirmed offline, no HuggingFace call)
- [x] `build/build.sh` completes without errors and produces `dist/reqbot-install.sh` (41MB, SHA-256 verified)
- [x] Running `./reqbot-install.sh` on a fresh machine with no Python installs `reqbot` successfully (end-to-end verified 2026-03-08)
- [x] `reqbot` launches the interactive shell
- [x] `reqbot ingest NIST.pdf --index` completes successfully (no subprocess chain)
- [x] `reqbot --version` prints version and build date (Phase 9.3)
- [x] `reqbot-install.sh --upgrade` preserves `~/.grcai/config.json`
- [x] No `.py` files required on target machine after installation
- [x] `reqbot-install.sh` exits with error if run as root
- [x] `~/.grcai/config.json` has `600` permissions after install and after `reqbot init`
