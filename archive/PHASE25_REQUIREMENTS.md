# ReqBot Phase 25 — Packaging and Deployment Reset

## Summary

Phase 25 changes ReqBot’s deployment strategy from “self-contained Linux bundle” to a normal, maintainable product shape:

- Primary deployment: Docker image running reqbot serve
- Foundation: real Python package install with a reqbot console entry point
- External services: Qdrant and Ollama are configured by URL, not installed/managed by ReqBot code
- Air-gap story: export/import Docker images and pre-pulled dependency/model artifacts, not a custom self-extracting installer
- MCP: deferred to Phase 26 candidate because packaging/deployment must be boring first

## Status

This table is the live source of truth for Phase 25 WP status — update it here when a WP lands,
not in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-25.1a — Node/npm build prerequisite cleanup | Merged (PR #98) |
| WP-25.1b — `reqbot init` becomes config-only | Merged (PR #99) |
| WP-25.1c — local synthesis fails clearly instead of auto-pulling | Merged (PR #102) |
| WP-25.2 — Real Python package foundation | Merged (PR #103) |
| WP-25.3 — Docker image + compose examples | Merged (PR #104) |
| WP-25.4 — Remove legacy bundle system | Merged (PR #105) |
| WP-25.5 — Docs + integration gate | Merged (PR #109) |
| WP-25.6a — Model role documentation | Merged (PR #106) |
| WP-25.6b — LLM model config consistency (extraction/enrichment/rewrite/HyDE/synthesis) | Merged (PR #107) |
| WP-25.6c — Embedding model configurability + index provenance | Merged (PR #108) |

## Key Changes

### WP-25.1 — Standard Build Prerequisites + Init Cleanup

Split into three separate sub-WPs (separate commits/PRs) rather than one combined WP — these
are three independent behavior changes with no shared code, no reason to review as one unit
(Codex review, Phase 25 draft feedback):

#### WP-25.1a — Node/npm build prerequisite cleanup
- Simplify build/build-frontend.sh to the standard path only:
    - require npm
    - **also check the actual Node version, not just npm's presence** (Codex review) — run
      `node --version`, parse the major version, fail clearly if it's below 20 (e.g. "Node 18
      found, this project requires Node 20 LTS or newer"). Checking only for npm doesn't catch
      an old Node behind it.
    - run npm ci then npm run build
    - fail clearly if npm is missing
    - no VS Code Server node search, no /tmp/code-server search, no REQBOT_BUILD_NODE

#### WP-25.1b — reqbot init becomes config-only
- remove local Qdrant Docker bootstrap from app code (installing/running the Qdrant
  service itself is no longer ReqBot's job)
- remove local Ollama installer bootstrap from app code (installing/running the Ollama
  service itself is no longer ReqBot's job)
- reqbot init only configures service URLs and model name preferences
- keep reqbot setup only as a deprecated alias to reqbot init
- Runtime service URLs continue to come from config/env:
    - REQBOT_OLLAMA_URL
    - REQBOT_QDRANT_URL

#### WP-25.1c — local synthesis fails clearly instead of auto-pulling
- Drop the lazy model-pull convenience entirely (`synthesize_local()`'s existing
  auto-pull-on-first-use, Phase 17). ReqBot shouldn't guess or presume which model a
  customer wants on their own endpoint. If a configured model isn't available on the
  configured Ollama endpoint, fail clearly and actionably: name the missing model and
  say `ollama pull <model>` (or point at a different one) rather than silently pulling
  anything. Document recommended models informationally (README/OPERATIONS — "here's
  what we run on our own hardware") rather than the app enforcing/fetching any of it.

### WP-25.2 — Real Python Package Foundation

- Add package metadata in pyproject.toml so ReqBot can be installed normally.
- Add console script:
    - reqbot = cli.reqbot:main

- Include package data needed at runtime:
    - profiles/*.json
    - frontend dist/ only when present for packaged/container builds

- Split dependencies deliberately — `docling` is the *only* heavy optional extra; everything
  else that ships a real, normal feature stays in base (Codex review: don't over-fragment
  extras for features that are just normal parts of the product now):
    - base install: pymupdf, pdfplumber (both legacy layout modes), qdrant-client, ollama,
      fastapi/uvicorn/aiofiles (serve), and **openpyxl** — XLSX checklist export is a
      normal shipped feature (WP-23.2), not something worth its own extra
    - reqbot[docling]: Docling + its torch/torchvision weight — the one dependency actually
      big enough to justify gating behind an extra
    - reqbot[remote]: anthropic, openai clients for remote synthesis
    - reqbot[dev]: test/lint/dev-only dependencies

- Keep --layout-mode docling available, but if the extra is not installed, fail with a clear “install reqbot[docling]” message.

- Update existing stale pip-install error messages now that packaging exists — these
  predate the extras split and currently point at bare pip installs of individual packages,
  which will be wrong/confusing once `reqbot[docling]`/`reqbot[remote]` exist:
    - pipeline/chunk_text.py:500 — docling ImportError → "Install the Docling extra:
      pip install reqbot[docling]"
    - pipeline/section_parser.py:369 — same docling ImportError message, same fix (Codex
      review — chunk_text.py isn't the only place this needs to change)
    - core/synthesis.py:146 — anthropic ImportError → "Install the remote extra:
      pip install reqbot[remote]"
    - core/synthesis.py:162 — openai ImportError → same, reqbot[remote]
    - core/synthesis.py:71 — ollama ImportError: ollama itself is a base dependency once
      packaged, so this becomes a defensive-only message (shouldn't trigger in a properly
      installed base package) — leave as-is or note it's now unreachable in normal use

### WP-25.3 — Docker Image + Compose Examples

- Add a Dockerfile that builds the frontend, installs reqbot[docling], and runs:
    - reqbot serve --host 0.0.0.0 --port 8000
- Use a multi-stage build: pin the frontend build stage to an official `node:20-*` base
  image, not whatever Node happens to be on the machine building the image. This is what
  actually makes Docker solve the Node-version problem end to end — anyone building the
  Docker image never needs Node/npm on their own host at all, regardless of what
  WP-25.1 requires for a bare source/dev build.

- The Docker image must not start, install, or manage Qdrant/Ollama.
- Add .dockerignore to keep processed artifacts, caches, local envs, and build junk out of images.
- Add docker-compose.example.yml for local convenience:
    - ReqBot service
    - Qdrant service
    - Ollama as optional/profiled example only, because GPU/host setups vary

- Compose remains static deployment config, not Python code controlling containers.

- **Network exposure — resolved, not just flagged:** `reqbot serve` inside the container
  must bind `0.0.0.0` — Docker port-publishing can't forward traffic to a process only
  listening on the container's own loopback, this isn't a security choice, it's a Docker
  requirement. The actual security boundary belongs at the port-publishing layer, not the
  app's bind address: `docker-compose.example.yml` must scope its published port to the
  host's loopback by default (`"127.0.0.1:8000:8000"`, not bare `"8000:8000"`) — this keeps
  the exact same reachability as today's `--host 127.0.0.1` default (host-machine-only),
  zero regression, out of the box. Publishing wider (for a real remote/multi-user
  deployment) is then a deliberate operator decision, not something this phase defaults
  anyone into — document it clearly: operators who do so are responsible for their own
  reverse proxy/TLS/firewall until real auth exists. There is currently no authentication
  anywhere in the API layer (the CORS allow-list in `api/app.py` is browser-enforced only
  and does nothing against a direct script, curl, or MCP client). Full authentication is
  explicitly deferred to Phase 26+, tied to the MCP work — not in scope here, and Phase 25
  should not add a stopgap auth mechanism either; the loopback-scoped default port binding
  is the complete mitigation for this phase.

### WP-25.4 — Remove Legacy Bundle System

Strict ordering (Codex review: keep this dependency explicit, don't let it slip) — this WP
does not start until WP-25.2 (pip package) and WP-25.3 (Docker image) have both passed their
own gate checks. Deleting the bundle before its replacement is proven working would leave a
gap with no working install path at all.

- Delete the self-extracting bundle scripts:
    - build/bundle.sh
    - build/build.sh
    - build/reqbot-install.sh

- Remove bundle-specific docs and references.
- Remove stale operations guidance about ~/.local/bin/reqbot being a generated bundle launcher.
- Keep git history as the rollback path; do not keep dead bundle code labeled “legacy.”

### WP-25.5 — Docs + Integration Gate

- Update README to show three supported paths:
    - Docker deployment
    - source/dev install
    - air-gapped Docker image transfer

- Update docs/OPERATIONS.md to separate Tyler’s private environment notes from general build/deploy instructions.
- Update docs/TODO_future_improvements.txt and docs/FUTURE_MCP_IDEA.md:
    - MCP becomes Phase 26 candidate
    - remove or close stale bundle/fallback items

- Add a Phase 25 gate walkthrough:
    - clean source install works
    - reqbot init configures existing Qdrant/Ollama URLs only
    - Docker image starts API/UI
    - container can reach configured Qdrant/Ollama
    - checklist/search/trace work from the container
    - no bundle scripts remain

### WP-25.6 — Model Agnosticism (split into three sub-WPs)

"Make ReqBot model-agnostic" is really three problems of increasing risk, not one — split into
separate commits/PRs so a low-risk docs fix doesn't sit blocked behind the one genuinely
dangerous change (Codex review, same reasoning as the WP-25.1a/b/c split). Recommended work
order is 25.6a → 25.6b → 25.6c (increasing risk), but none of the three blocks the WP-25.1–25.5
packaging/Docker sequence or each other in a hard technical sense.

#### WP-25.6a — Model Role Documentation

Low risk; mostly docs/wording, no behavior change.

- State ReqBot's model needs as **roles**, not specific model names: embedding, extraction,
  enrichment, query-rewrite/HyDE, and optional synthesis. Today's defaults
  (`nomic-embed-text`, `llama3.1:8b-instruct-q4_K_M`, `qwen2.5:14b`) are recommended
  consumer-hardware defaults, not universal requirements — don't write docs that imply
  otherwise.
- **Fix a specific inaccuracy this phase already introduced:** `ARCHITECTURE.md`'s model table
  (added responding to Codex's WP-25.1b review) currently folds "extraction / enrichment /
  query rewrite / HyDE" into one row and claims all of it is configurable via `extraction_model`
  / `enrichment_model`. That's wrong for the query-rewrite/HyDE role specifically — see WP-25.6b;
  `rewrite_model` has no config-file presence at all today. Split that row and correct the claim
  when this WP lands.

#### WP-25.6b — LLM Model Config Consistency

Medium risk — audits and fixes real, already-confirmed inconsistency in how the *non-embedding*
model roles are configured, not just documented.

- **Confirmed gap:** `extraction_model`, `enrichment_model`, and `synthesis_model` are real
  config fields (`core/config.py`), settable via `reqbot init`, with env var overrides
  (`REQBOT_EXTRACTION_MODEL` etc.). `rewrite_model` (query rewriting + HyDE hypothesis
  generation) is **not** — it's a CLI-flag-only setting (`--rewrite-model` in `cli/reqbot.py`)
  whose default (`llama3.1:8b-instruct-q4_K_M`) is hardcoded as a literal in the argparse call
  *and* separately as `DEFAULT_REWRITE_MODEL` in `core/ask.py` — two hardcoded copies of the
  same default, not one source of truth. Add `rewrite_model` to config/`reqbot init` the same
  way the other three roles work.
- **Confirmed gap:** `reqbot status` shows which models are *available on the Ollama server*
  (`services/status_service.py`), not which models ReqBot is actually *configured* to use for
  each role. Add the configured extraction/enrichment/rewrite/synthesis model names to the
  status output so a user can see what's actually selected, not just what's installed.
- Audit CLI/API/frontend for any other place a model name is hardcoded outside config for these
  four roles (not embedding — that's WP-25.6c) and wire it to config instead.
- Update `ARCHITECTURE.md`'s model table per the WP-25.6a fix once `rewrite_model` is real
  config, so the table's configurability claim becomes true rather than needing a correction.

#### WP-25.6c — Embedding Model Configurability + Index Provenance

The dangerous one — embedding models define the actual vector shape stored in Qdrant, so a
mismatch between what indexed a point and what's querying it doesn't error, it silently returns
wrong-but-confident results.

- Add `embedding_model` to `reqbot init`/config, alongside the (now, post-25.6b) consistent
  extraction/enrichment/rewrite/synthesis fields. Default: `nomic-embed-text` (unchanged).
- Replace the hardcoded `EMBEDDING_MODEL = "nomic-embed-text"` constants in `core/ask.py`,
  `pipeline/embed_and_index.py`, `pipeline/embed_context_index.py` — and the inline
  `"nomic-embed-text"` literals in `services/compare_service.py` and
  `services/evidence_service.py` — with the configured value.
- **Track embedding provenance as Qdrant payload metadata, not a JSONL field.** Set
  `embedding_model` (and vector dimension) in the payload dict built in
  `embed_and_index.py`/`embed_context_index.py` (same place `domain_profile` is already copied
  in) at index time. This is deliberately different from `domain_profile`: domain_profile is a
  fact about *extraction*, captured once from JSONL; embedding_model is a fact about *indexing*,
  and the same JSONL file can be reindexed multiple times with different models over its
  lifetime. Writing it into JSONL would mean mutating a verbatim-capture pipeline artifact after
  the fact just to record indexing state — it belongs on the index side of the line, not the
  source-of-record side.
- At query time (`core/ask.py`'s `retrieve()`, plus `compare_service`/`evidence_service`),
  compare each result's `embedding_model` payload against the currently configured embedding
  model. On any mismatch, surface a `warnings` field (CLI output, API response, frontend) rather
  than silently returning the results as-is — e.g. "3 of 10 results were indexed with a
  different embedding model (nomic-embed-text) than your current config (X) and may be
  unreliable; run `reqbot reindex` to refresh them." **Do not block the query on a mismatch** —
  a partially reindexed corpus is a valid, common state (the corpus is in exactly this state
  today, post-Phase-24-nuke), not an error condition.
- Qdrant already enforces vector-dimension compatibility at the API level — switching to a model
  with a *different* dimension than the collection's current one fails loudly and immediately;
  nothing new needs to be built for that case. The payload-metadata check exists specifically for
  the case Qdrant's own guardrail can't catch: two different models that happen to share a
  dimension, where a query succeeds and returns confident-looking, semantically wrong results
  with no error at all.
- `reqbot reindex` must handle the configured embedding model correctly — re-embed with
  whatever model is currently configured, write the matching provenance metadata, and this is
  the documented recovery path after an embedding-model config change (full reindex of both
  collections, not a partial one).
- Document in README/OPERATIONS: `nomic-embed-text` remains the recommended, validated default;
  advanced users may configure a different embedding model where ReqBot's configuration supports
  it, understanding that doing so requires a full `reqbot reindex` (both collections) to clear
  the mismatch warning across their corpus.
- Out of scope for this WP: automatically triggering a reindex on embedding-model config change,
  or hard-blocking/erroring queries on a mismatch. Both are more aggressive behaviors that can be
  revisited later if warn-only proves insufficient in practice.

## Tests And Verification

- Unit tests:
    - reqbot init no longer calls Docker, curl install scripts, or ollama pull
    - reqbot setup still aliases to init
    - missing Docling extra produces a clear error only when docling mode is requested
    - synthesis against a missing/unpulled model fails with a clear, actionable message
      (names the model, suggests `ollama pull <model>`) instead of silently auto-pulling
    - WP-25.6b: `rewrite_model` is a real config field, settable via `reqbot init`, with the
      same env var override pattern as `extraction_model`/`enrichment_model`/`synthesis_model`
    - WP-25.6b: `reqbot status` output includes the configured extraction/enrichment/rewrite/
      synthesis model names, not just what's available on the Ollama server
    - WP-25.6c: changing `embedding_model` in config changes which model `core/ask.py`,
      `embed_and_index.py`, `embed_context_index.py`, `compare_service`, and `evidence_service`
      actually call — no leftover hardcoded reference wins over the configured value
    - WP-25.6c: `embed_and_index.py`/`embed_context_index.py` write `embedding_model` into the
      Qdrant payload at index time
    - WP-25.6c: `retrieve()` surfaces a `warnings` entry when a result's payload
      `embedding_model` differs from the currently configured one, and surfaces nothing when
      they match
    - WP-25.6c: a mismatched-embedding-model query still returns its results (warning, not a
      hard failure)
    - WP-25.6c: `reqbot reindex` re-embeds using the currently configured embedding model and
      writes matching provenance metadata

- Build checks:
    - bash build/build-frontend.sh succeeds with Node 20+ and npm
    - Python package builds cleanly
    - installed console command reqbot --help works

- Docker checks:
    - image builds from a clean checkout **on a host with no Node/npm installed at all**
      (Codex review) — this is the actual proof that the multi-stage build's pinned
      `node:20-*` build stage works, not just a nice-to-have; if this fails, Docker isn't
      really delivering on "you only need Docker on your host"
    - container starts reqbot serve
    - /api/status responds
    - configured REQBOT_OLLAMA_URL and REQBOT_QDRANT_URL are honored
    - docker-compose.example.yml's default port publish is loopback-scoped
      (127.0.0.1:8000:8000), not reachable from another host on the network out of the box
    - **CI now runs this automatically** (`.github/workflows/ci.yml`'s `docker` job, added
      WP-25.3 follow-up): builds `docker-compose.example.yml`, waits for `/api/status` to
      respond, asserts `qdrant_url`/`ollama_url` are honored and Qdrant is reachable from
      inside the container, and asserts the packaged `frontend/dist` is served at `/`. No real
      Ollama in CI, so this doesn't cover actual ask/search behavior — only that the image
      builds, starts, and wires config correctly. GitHub-hosted runners have Docker built in
      already (no nested-container/DinD problem, unlike the Coder dev sandbox this WP was
      built in) — first real run happens when this lands on GitHub, not verified locally here.

- Regression checks:
    - pytest tests/unit/ -q
    - ruff check .
    - frontend npm ci && npm run build
    - no references to deleted bundle scripts remain outside archive/history docs

## Assumptions And Defaults

- Phase 25 is packaging cleanup, not MCP implementation.
- Qdrant and Ollama are external dependencies from ReqBot’s perspective.
- Docker is the primary deployable artifact for real users/teams.
- A normal pip package is the foundation under Docker and remains first-class for CLI/dev use.
- Node 20 LTS or newer plus npm is the supported frontend build requirement.
- The old self-extracting Linux bundle is deleted after the Docker/pip replacement lands, not quarantined indefinitely.
- `nomic-embed-text` remains the recommended, validated embedding default after WP-25.6 — making
  it configurable does not change what ReqBot ships or suggests out of the box.

## Phase 25 Gate Walkthrough (WP-25.5)

Executed live against this environment's real configured Ollama and Qdrant instances on
2026-07-23, after WP-25.6c merged.

- **Clean source install works** — verified: `pip install .` into a fresh throwaway venv, then
  `reqbot --help` lists every subcommand and `reqbot status` reads the existing config and
  reaches both services correctly from that fresh install.
- **`reqbot init` configures existing Qdrant/Ollama URLs only** — no bootstrap capability exists;
  covered by `tests/unit/test_cli_init.py`'s `test_no_bootstrap_functions_remain`, which asserts
  the Docker/Ollama-installer bootstrap helpers were removed entirely in WP-25.1b, not just
  unused.
- **Docker image starts API/UI; container can reach configured Qdrant/Ollama** — not re-verified
  in this environment (this Coder sandbox can't run a Docker daemon at all — nested-container/
  DinD limitation, documented in WP-25.3). Verified instead via `.github/workflows/ci.yml`'s
  `docker` job (WP-25.3 follow-up), which runs on GitHub-hosted runners with native Docker
  support and checks exactly this: image builds from a clean checkout with no Node/npm on the
  build host, container starts, `/api/status` responds, configured `REQBOT_QDRANT_URL`/
  `REQBOT_OLLAMA_URL` are honored and Qdrant is reachable from inside the container. That job has
  run green on every Phase 25 PR since it was added.
- **Checklist/search/trace work** — verified directly via CLI against the real corpus. The CLI
  and the container's API both call the same service layer (`services/ask_service.py`,
  `services/checklist_service.py`, `services/trace_service.py` — the CLI/GUI/API/MCP-thin-
  interfaces architecture rule), so this is the same code path a browser session in the
  container would exercise:
    - `reqbot ask "access control"` — returned ranked results.
    - `reqbot trace REQ-9a753fdeec40` — returned full provenance (document, source ref, page,
      extraction model, run date).
    - `reqbot checklist --doc afi17-101 --format json` — generated a 247-item checklist.
  The browser GUI's own click-through of these same endpoints is **not verified in this pass** —
  no Node/browser in this sandbox — and still needs a manual pass from Tyler.
- **No bundle scripts remain** — verified: searching for `bundle*.sh`/`reqbot-install.sh` finds
  nothing outside this doc's own historical narrative of WP-25.4's removal; no live code or
  other doc references the deleted scripts.

Everything CLI/API/CI-verifiable is done. Phase 25's only remaining open item is a manual
browser-GUI click-through (search/trace/compare/evidence/checklist screens, Docker container
reachable from an actual browser) — not something this environment can drive, so Phase 25
closure is Tyler's call once that pass happens, not declared here.

**Update, 2026-07-23 — manual pass complete, Phase 25 closed.** Tyler ran `reqbot serve` and
clicked through search/trace/compare/evidence/checklist in a real browser. The pass caught a
real bug the CLI/CI checks above didn't: Qdrant only held 247 points (one leftover test
document from an ad hoc `reqbot ingest` the day before) against a 31,725-requirement JSONL
corpus across 45 documents — search worked mechanically but returned irrelevant results for
almost any query, since HyDE/RRF ranking can't fix an index that's missing 99% of the corpus.
Fixed with `reqbot reindex` (no re-extraction needed — JSONL is the system of record;
re-embedding all 45 documents took ~3 minutes, not the 12+ hour original ingest). Re-verified
via `reqbot ask` and in the browser afterward — all five screens confirmed good. This is the
gate doing its job: an API/CLI-only verification pass would have missed this.

## Open Question For Phase 26 (Not Decided, Not In Scope Here)

Remote synthesis (`reqbot ask --synthesize` calling out to Anthropic/OpenAI from inside
ReqBot) was designed before MCP was on the roadmap. Once MCP is the primary interface, an
orchestrating LLM (Claude, etc.) already has the structured evidence in its own context and
will synthesize the answer itself — that's the actual MCP design intent
(`archive/FUTURE_MCP_IDEA.md`: "synthesis never replaces structured output; it augments it").
Remote synthesis calling out to a second LLM from inside ReqBot is likely redundant in that
flow and may be worth deprecating. Local Ollama synthesis is a different case — it still
serves users with no LLM client at all who want a self-contained/offline answer, and isn't
affected by this question. Phase 25 keeps `reqbot[remote]` in the packaging plan as-is since
this is a feature-scope decision, not a packaging one — revisit when Phase 26/MCP work is
scoped, not before.
