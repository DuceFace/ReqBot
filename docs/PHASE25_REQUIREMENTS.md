# ReqBot Phase 25 — Packaging and Deployment Reset

## Summary

Phase 25 changes ReqBot’s deployment strategy from “self-contained Linux bundle” to a normal, maintainable product shape:

- Primary deployment: Docker image running reqbot serve
- Foundation: real Python package install with a reqbot console entry point
- External services: Qdrant and Ollama are configured by URL, not installed/managed by ReqBot code
- Air-gap story: export/import Docker images and pre-pulled dependency/model artifacts, not a custom self-extracting installer
- MCP: deferred to Phase 26 candidate because packaging/deployment must be boring first

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

### WP-25.6 — Embedding Model Configurability + Provenance Tracking

Independent of the WP-25.1–25.5 packaging/Docker sequence — does not block, and is not blocked
by, any of them. Can land in any order relative to the rest of Phase 25.

- Add `embedding_model` to `reqbot init`/config, alongside the existing `extraction_model`,
  `enrichment_model`, `synthesis_model` fields. Default: `nomic-embed-text` (unchanged).
- Replace the hardcoded `EMBEDDING_MODEL = "nomic-embed-text"` constants in `core/ask.py`,
  `pipeline/embed_and_index.py`, `pipeline/embed_context_index.py` — and the inline
  `"nomic-embed-text"` literals in `services/compare_service.py` and
  `services/evidence_service.py` — with the configured value. Today none of these read from
  config; the embedding model is the one model role that isn't configurable yet, unlike
  extraction/enrichment/synthesis.
- **Track embedding provenance as Qdrant payload metadata, not a JSONL field.** Set
  `embedding_model` in the payload dict built in `embed_and_index.py`/`embed_context_index.py`
  (same place `domain_profile` is already copied in) at index time. This is deliberately
  different from `domain_profile`: domain_profile is a fact about *extraction*, captured once
  from JSONL; embedding_model is a fact about *indexing*, and the same JSONL file can be
  reindexed multiple times with different models over its lifetime. Writing it into JSONL would
  mean mutating a verbatim-capture pipeline artifact after the fact just to record indexing
  state — it belongs on the index side of the line, not the source-of-record side.
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
    - changing `embedding_model` in config changes which model `core/ask.py`,
      `embed_and_index.py`, `embed_context_index.py`, `compare_service`, and `evidence_service`
      actually call — no leftover hardcoded reference wins over the configured value
    - `embed_and_index.py`/`embed_context_index.py` write `embedding_model` into the Qdrant
      payload at index time
    - `retrieve()` surfaces a `warnings` entry when a result's payload `embedding_model` differs
      from the currently configured one, and surfaces nothing when they match
    - a mismatched-embedding-model query still returns its results (warning, not a hard failure)

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

## Open Question For Phase 26 (Not Decided, Not In Scope Here)

Remote synthesis (`reqbot ask --synthesize` calling out to Anthropic/OpenAI from inside
ReqBot) was designed before MCP was on the roadmap. Once MCP is the primary interface, an
orchestrating LLM (Claude, etc.) already has the structured evidence in its own context and
will synthesize the answer itself — that's the actual MCP design intent
(`docs/FUTURE_MCP_IDEA.md`: "synthesis never replaces structured output; it augments it").
Remote synthesis calling out to a second LLM from inside ReqBot is likely redundant in that
flow and may be worth deprecating. Local Ollama synthesis is a different case — it still
serves users with no LLM client at all who want a self-contained/offline answer, and isn't
affected by this question. Phase 25 keeps `reqbot[remote]` in the packaging plan as-is since
this is a feature-scope decision, not a packaging one — revisit when Phase 26/MCP work is
scoped, not before.
