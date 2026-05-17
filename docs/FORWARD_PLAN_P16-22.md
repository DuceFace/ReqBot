# ReqBot — Forward Plan (Phases 16–22)

**Status:** Active — Phases 15–18 complete, Phase 19 next
**Date:** 2026-04-05 (updated 2026-05-17)
**Intent:** Gated phases with clear success criteria from Phase 16 through Phase 22. Phases 16–18 are fully defined here. Phase 19 (GUI capability expansion — compare, evidence, synthesis, docs, polish) is defined in `docs/PHASE19_REQUIREMENTS.md`. Phases 20–22 (domain profiles, checklist generation, evidence requests, gap analysis) are defined in `docs/PRODUCT_PRD.md`.

*This document is the single source of truth for Phase 16–18 planning. It incorporates planning from Claude, architectural review from GPT, and risk analysis from Gemini. It is intended as the Codex input and execution reference.*

---

## Design Philosophy

### The Pipeline Is the Product

ReqBot's value is in its extraction, indexing, and retrieval pipeline. Every decision in Phases 15–18 must protect that pipeline from brittleness introduced by new interfaces.

### API as Dumb Transport

The API is a thin wrapper over stable internal functions. It validates input, calls the same service function the CLI uses, and returns the result with minimal reshaping. The API never contains business logic.

### Repository Cohesion and AI-Assisted Development

ReqBot development is increasingly AI-assisted. Extremely large multi-purpose files create token inefficiency, difficult review workflows, fragile edits, poor diff readability, and increased regression risk.

Phase 16 therefore explicitly restructures the repository into smaller cohesive modules, stage-oriented pipeline organization, isolated service boundaries, and reusable typed schemas.

The goal is not abstraction for abstraction's sake. The goal is maintainability, debuggability, lower-risk refactoring, and faster AI-assisted iteration.

This restructuring also supports the broader product direction defined in `PRODUCT_PRD.md`: generalized requirements ingestion, domain profiles, audit checklist generation, evidence request generation, and future policy alignment workflows.

### The Stack

```
pipeline/core logic → service functions → CLI (direct call)
                                        → API (thin wrapper) → GUI
```

Both CLI and API call the same service layer. The GUI calls only the API. The CLI never depends on the API — if you kill the API server, the CLI works exactly as it does today.

### Safety Test

Before any phase ships, these must remain true:

- Can `/ask` call the same exact function the CLI `ask` command uses?
- Can you change the GUI without changing retrieval logic?
- Can you kill the API and still have the CLI work normally?

If any answer is no, the design is wrong.

---

## Phase 15 — Retrieval Validation (HyDE Spike)

**Goal:** Determine whether Hypothetical Document Embedding meaningfully improves retrieval quality for compliance queries.

### Scope (strict)

- Implement HyDE only (no HyPE)
- Use existing Ollama inference (default: llama3.1:8b-instruct-q4_K_M)
- Augment current retrieval — do not replace it:
  1. Embed raw query (baseline path, unchanged)
  2. Generate 1 hypothetical requirement via LLM
  3. Embed the hypothesis
  4. Fuse baseline + HyDE results using RRF (same mechanism already used for dense+sparse fusion)
- Use RRF for fusion. Do not experiment with other fusion strategies in this phase.

### Do NOT

- Add config flags or CLI options
- Add UI exposure
- Replace baseline retrieval
- Introduce paraphrase expansion (HyPE)
- Experiment with alternative fusion strategies

### HyDE Prompt Design

Generate a hypothetical requirement statement in the same register as the indexed corpus:

> *"Given this compliance question, write a single regulatory requirement statement that would answer it. Use formal language matching DoD/NIST style. Do NOT include specific control IDs, section numbers, or numeric thresholds. Describe only the semantic intent of the requirement."*

The closer the hypothesis sounds to actual indexed text, the better the embedding alignment.

**Critical constraint — anti-hallucination:** Compliance corpora are a high-risk domain for HyDE. If the LLM invents a control ID (e.g., "IA-5(1)") or a specific numeric threshold (e.g., "15-character minimum") in the hypothesis, BM25 will latch onto those exact tokens during sparse retrieval and pull irrelevant documents to the top, burying actual answers. The prompt must explicitly prohibit fabricated identifiers and numbers.

### Evaluation Plan

Define 10–15 representative queries:

- Mix of NIST SP 800-53, DoDI, AFI, CNSSI, and DAFI source types
- Include vague queries ("What are the access control requirements?") and precise queries ("What are the password length minimums for privileged accounts?")
- Include queries that cross document boundaries and queries scoped to a single document

Capture for each query:

- Baseline results (current hybrid retrieval: raw query embedding + BM25/RRF)
- HyDE-augmented results
- The generated hypothesis text (for prompt quality review)

**Hypothesis logging:** Log every generated hypothesis to a file (`hyde_hypotheses.jsonl`) during testing. Review them in batch after the evaluation run, not inline during execution. Pattern-level problems (e.g., the model consistently leaking control IDs despite the prompt constraint) are only visible in aggregate.

### Metrics

- Precision@5 (primary observation metric)
- New relevant hits surfaced that baseline missed
- Ranking changes (did good results move up?)
- Latency delta (measured, not gated)

### Success Criteria (gate)

- HyDE surfaces relevant requirements not found in baseline on ≥3 of the test queries
- No query shows degraded relevance vs. baseline
- No hypothesis contains hallucinated control IDs or numeric thresholds that corrupted retrieval
- Latency increase is observable but acceptable (measured and recorded, no hard cap)

### Outcome

- **If successful →** Proceed to Phase 16. HyDE becomes a candidate for default retrieval path.
- **If inconclusive →** Refine hypothesis prompt, try synthesis model (qwen2.5:14b) for generation, re-evaluate.
- **If negative →** Discard HyDE. Reassess retrieval strategy before proceeding to GUI work.

---

## Phase 16 — Repository Reorganization + Service Layer Foundation

**Goal:** Reorganize the repository into cohesive, AI-editable modules; extract command logic into reusable services; and introduce a minimal read-only API without breaking CLI behavior.

Phase 16 is no longer just an API phase. It is the architectural foundation for future GUI work, domain profiles, checklist generation, evidence workflows, and policy alignment. The API remains important, but the first priority is making the codebase easier to understand, edit, test, and extend.

### Key Principle

The pipeline is still the product. Phase 16 should move code into clearer homes and expose stable service contracts, but it must not change retrieval behavior, extraction behavior, or CLI behavior unless explicitly required.

The API is a thin wrapper, not the core interface. Phase 16 is mostly about defining stable internal service contracts such as `ask()`, `trace()`, `docs()`, and `status()`, then wrapping them for CLI and API use.

### Target Repository Structure

Proposed target structure:

```text
grc-ai-system/
  pipeline/
    extract_pdf_to_text.py
    chunk_text.py
    llm_extract_requirements.py
    parse_and_normalize.py
    enrich_requirements.py
    aggregate_and_export.py
    embed_and_index.py
    embed_context_index.py
    run_pipeline.py
    section_parser.py

  services/
    ask_service.py
    trace_service.py
    compare_service.py
    evidence_service.py
    docs_service.py
    status_service.py

  api/
    routes/
    models/

  cli/
    reqbot.py
    console.py

  core/
    config.py
    synthesis.py
    ask.py

  models/
    requirement.py
    checklist.py
    api_response.py
```

### Folder Responsibilities

#### `pipeline/`

The `pipeline/` folder contains the Step A-F document processing scripts and supporting pipeline utilities. These are the document ingestion, extraction, normalization, enrichment, aggregation, and indexing stages.

This move formalizes the idea that these scripts are pipeline stages. It also separates document processing from CLI command dispatch and API service logic.

#### `services/`

The `services/` folder contains business logic extracted from the monolithic CLI file.

Initial service candidates:

- `ask_service.py` — logic currently behind `cmd_ask`
- `trace_service.py` — logic currently behind `cmd_trace`
- `compare_service.py` — logic currently behind compare behavior
- `evidence_service.py` — logic currently behind evidence generation
- `docs_service.py` — document inventory and listing behavior
- `status_service.py` — Qdrant, Ollama, model, and config health checks

Services return structured Python objects or dictionaries. They do not print directly unless explicitly designed for CLI output. CLI formatting and API serialization happen at the edges.

#### `api/`

The `api/` folder contains FastAPI setup and route definitions.

Routes validate input, call service functions, and return service results. Routes do not contain retrieval logic, pipeline logic, or business logic.

#### `cli/`

The `cli/` folder contains command-line entrypoints, argparse wiring, console formatting, and command dispatch.

The CLI calls services directly. It never calls the API. If the API server is killed, the CLI must continue working normally.

#### `core/`

The `core/` folder contains cohesive core logic that is already functioning and should not be broken apart unnecessarily.

Examples:

- configuration loading
- synthesis helpers
- retrieval engine logic

`core/ask.py` may remain cohesive if it is already acting as the retrieval engine. Do not split stable cohesive modules just to satisfy a folder pattern.

#### `models/`

The `models/` folder contains shared data structures used across the pipeline, services, API, GUI, and future checklist work.

Initial model candidates:

- `requirement.py`
- `checklist.py`
- `api_response.py`

The purpose of this layer is to prevent schema drift between CLI output, API responses, checklist generation, and future GUI views.

### Future Product Compatibility

Phase 16 must support the broader product direction documented in `PRODUCT_PRD.md`.

The structure should support future capabilities including:

- domain profiles
- generalized requirement schemas
- checklist generation
- evidence request generation
- policy alignment workflows
- cross-domain document ingestion

The shared service and model layers should avoid cybersecurity-specific names or assumptions unless the code is explicitly inside a cybersecurity domain profile or cybersecurity-specific feature.

Cybersecurity remains the first supported domain, not the only intended domain.

### Phase 16A — Repository Reorganization

**Goal:** Move files into cohesive folders without changing behavior.

Scope:

- Move Step A-F scripts into `pipeline/`
- Move CLI entrypoints into `cli/`
- Establish empty or minimal `services/`, `api/`, and `models/` folders
- Update imports
- Preserve existing commands
- Preserve existing outputs
- Do not change business logic

Rules:

- No logic cleanup during file moves
- No behavior changes during file moves
- No opportunistic refactors
- Every moved file must remain runnable or importable as before
- Gemini/Codex review should focus on import correctness and behavior parity

Success criteria:

- Existing CLI commands still work
- Existing pipeline scripts still run
- No regression in ingestion, extraction, indexing, ask, trace, compare, or evidence behavior
- The repository structure is easier to navigate

### Phase 16B — Service Layer Extraction

**Goal:** Extract command logic from the monolithic CLI into reusable services.

Scope:

- Extract `cmd_ask` logic into `services/ask_service.py`
- Extract `cmd_trace` logic into `services/trace_service.py`
- Extract document inventory behavior into `services/docs_service.py`
- Extract status behavior into `services/status_service.py`
- Optionally extract compare and evidence logic if they are already stable enough to move:
  - `services/compare_service.py`
  - `services/evidence_service.py`

Rules:

- CLI calls service functions directly
- Services must not depend on API
- Services should not print directly unless returning console-ready output is explicitly intended
- Services should return structured objects or dictionaries
- Keep retrieval logic in the existing retrieval engine if it is already cohesive
- Do not rewrite working internals during extraction

Rationale:

The current `reqbot.py` file is too large and does too many jobs. Editing anything in a large multi-purpose CLI file forces AI tools to load too much unrelated context. Smaller service files make future edits cheaper, safer, and easier to review.

Success criteria:

- `cli/reqbot.py` shrinks substantially and becomes mostly argparse + dispatch
- Ask, trace, docs, and status behavior match pre-refactor behavior
- Service functions can be called directly from Python
- Future API routes can call the same service functions without duplicating logic

### Phase 16C — Read-Only API Foundation

**Goal:** Add a minimal FastAPI layer over the service layer.

Scope:

| Endpoint | Method | Maps to |
|----------|--------|---------|
| `/status` | GET | `status_service` |
| `/ask` | POST | `ask_service` |
| `/trace/{req_id}` | GET | `trace_service` |
| `/docs` | GET | `docs_service` |

Explicit exclusions:

- No `/compare`
- No `/evidence`
- No `/analyze`
- No `/ingest`
- No `/checklist`
- No `/alignment`
- No background jobs, streaming, or stateful operations
- No authentication initially (localhost only)

These are deferred, not rejected. They get added when the read path is boring and reliable.

### Refactor Rules

- Do not rename or rewrite stable core functions during the first pass.
- Move first, wrap second, refactor later.
- All reusable behavior should flow through `services/`.
- CLI calls services directly.
- API calls services directly.
- API routes do not contain business logic.
- The GUI, when built later, calls only the API.
- The CLI never depends on the API.

### Fallback Path

If the full `services/` extraction introduces instability or slows progress:

- Keep the repository reorganization from Phase 16A
- Implement API routes that call existing functions directly
- Defer deeper internal restructuring until after the read-only API and GUI are proven
- Do not let perfect architecture block a working product

The abstraction is correct in theory, but it is not worth breaking working behavior.

### Response Format

Treat the `/ask` response as versioned from day one, even if version negotiation is not exposed yet. Lock the canonical shape early so the frontend cannot dictate it later:

```json
{
  "query": "...",
  "filters": {
    "document_id": null,
    "domain_tag": null,
    "requirement_type": null
  },
  "results": [
    {
      "requirement_id": "REQ-...",
      "description": "...",
      "source_ref": "...",
      "source_quote": "...",
      "document_id": "...",
      "source_pdf": "...",
      "domain_tags": [],
      "requirement_type": "...",
      "confidence": 0.0,
      "page_start": 0,
      "page_end": 0,
      "score": 0.0
    }
  ],
  "metadata": {
    "top_k": 20,
    "result_count": 0,
    "retrieval_ms": 0,
    "synthesis": null
  }
}
```

This shape mirrors what the CLI already prints. Do not reshape it for frontend convenience.

### Shared Models and Schema Discipline

Structured data objects shared between pipeline, services, API, GUI, and checklist generation should live in a centralized `models/` or schema layer.

This is especially important for:

- requirement objects
- checklist objects
- API responses
- trace responses
- error responses

The goal is to prevent response drift and duplicated schema definitions.

### Implementation Notes

**Sync routes only.** The existing pipeline is synchronous Python. Use standard `def` route handlers, not `async def`. FastAPI runs `def` routes in a threadpool automatically. Do not introduce `async`/`await` into the pipeline to satisfy the web framework.

**CORS middleware — add on day one.** The Phase 18 GUI will run in a browser and will be blocked from calling the API without CORS headers. Add this to the FastAPI setup immediately, not as a Phase 18 fix:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Entry Point

`reqbot serve --port 8000` as a new subcommand. The API server is optional. The CLI never requires it.

### Anti-Pattern: Premature Framework Abstraction

Phase 16 shall prioritize direct Python control, explicit imports, transparent service boundaries, and understandable code.

ReqBot shall not adopt heavy orchestration frameworks solely to satisfy architectural trends. The repository structure should remain understandable without framework-specific knowledge.

### Success Criteria (gate)

- Existing pipeline behavior still works after folder reorganization
- Existing CLI behavior still works after service extraction
- `cli/reqbot.py` is reduced to command parsing and dispatch as much as practical
- CLI and API return identical results for the same queries
- No regression in CLI functionality
- API is usable via curl/Postman without friction
- Killing the API server has zero impact on CLI operation
- Future checklist and domain-profile work has a clear place to live without bending the API or CLI layers

---

## Phase 17 — Setup and Environment Standardization

**Goal:** Make ReqBot runnable on a fresh Linux system with minimal manual effort.

### Command

```bash
reqbot setup
```

### Behavior (default path)

1. Check for Docker → if missing, **fail with clear instructions** (no auto-install — Docker requires distro-specific handling and often sudo)
2. Start Qdrant container (`docker run -d qdrant/qdrant` on default port)
3. Check for Ollama → install via official script if missing (transparent, user-visible)
4. Pull **core models only** — enough to make search work immediately:
   - `nomic-embed-text` (~274MB) — required for embeddings
   - `llama3.1:8b-instruct-q4_K_M` (~4.7GB) — required for extraction and HyDE
5. Write config with localhost defaults
6. Run `reqbot status` to confirm everything is green

**Total initial download: ~5GB.** User has a working `reqbot ask` immediately after setup.

### Lazy-Load Synthesis Model

The synthesis model (`qwen2.5:14b`, ~9GB) is **not pulled during setup.** It is pulled automatically on first use of `--synthesize` or any command that requires synthesis. The user sees a one-time progress message:

```
[*] Synthesis model qwen2.5:14b not found locally. Downloading (~9GB)...
```

This cuts initial setup friction from ~14GB to ~5GB and avoids blocking users who only need search and trace.

### Advanced Path

```bash
reqbot setup --advanced
```

Same as current `reqbot init` — manual URL entry, custom model selection, remote synthesis configuration. Advanced users can pre-pull the synthesis model here if they want.

### Constraints

- Must be transparent: no silent installs beyond Ollama (which uses the official installer)
- Must show progress, especially model downloads
- Must fail cleanly with actionable error messages
- Docker is a hard prerequisite, not an auto-install target

### Air-Gapped Path (design only — not built in this phase)

Concept: offline bundle containing pre-pulled model files + Qdrant Docker image. `reqbot setup --offline /path/to/bundle`. Worth designing the setup command to accept this path from the start, even if the bundle itself isn't built yet.

### Success Criteria (gate)

- Fresh machine with Docker installed → working `reqbot ask` in one command
- No manual config file edits required
- Synthesis model pulls transparently on first use without user intervention
- Clear, actionable failure messaging for every error path

---

## Phase 18 — Minimal GUI (Demo-Focused)

**Goal:** Deliver a usable web interface for non-CLI users. Scoped to search + trace only.

### Architecture

- React + Tailwind
- Calls FastAPI backend (Phase 16 endpoints only)
- No separate backend logic — the GUI is a pure frontend client
- Lives in `frontend/` within the ReqBot repo (same repo, same version, no drift)
- CORS is already configured in the API (Phase 16)

### Views (strict MVP)

**1. Search**

- Query input bar
- Minimal filters (document selector at most — do not overbuild filters in v1)
- Results list with requirement ID, description, source document, confidence score
- Click-through to trace view

**2. Trace**

- Full requirement detail: description, source quote, source ref, page numbers
- Provenance: extraction model, run date, document hash
- Cross-framework matches

### Explicit Exclusions

- No compare view
- No evidence export
- No corpus analytics / analyze view
- No ingest functionality
- No advanced dashboards
- No user accounts or multi-tenancy
- No Electron/Tauri desktop wrapper

### Why Not Electron

ReqBot depends on Docker (Qdrant), Ollama, and a Python backend. Packaging all of that into a desktop binary is extreme complexity for zero user benefit over a browser tab pointed at localhost. A web GUI served by the FastAPI backend is simpler to build, simpler to deploy, and simpler to maintain. Desktop packaging is only worth revisiting if a specific deployment scenario (air-gapped laptop with no browser) demands it.

### UX Priorities

- Fast response (query → results in <2s on localhost)
- Clear traceability (every result links back to source)
- Minimal cognitive load (no learning curve)

### Success Criteria

- A non-technical user can enter a query, view results, and drill into a trace without assistance
- Demo-ready stability: no crashes or confusing error states during a live walkthrough
- GUI and CLI return visually consistent results for the same query

---

## Cross-Phase Constraints

### 1. Retrieval Is the Foundation

If Phase 15 fails, later phases lose value. Do not proceed to GUI work without confidence in retrieval quality. The HyDE gate exists for a reason.

### 2. API Contract Stability

The GUI depends on API response shapes being stable. Define the canonical `/ask` response format in Phase 16 and do not change it without versioning. Avoid expanding endpoints until the initial contract is proven in production use.

### 3. State Consistency

Before the GUI ships, ensure:

- Stable document IDs across reindex operations
- Consistent embedding/version behavior
- Deterministic retrieval results for the same query and filters

### 4. Configuration Consistency

Both CLI and API must load configuration from the exact same path and schema (`~/.config/reqbot/config.json`). No environment-variable overrides that apply to one interface but not the other. If the CLI and API can silently load different configs, results will diverge and the parity gate becomes meaningless.

### 5. The Anti-Pattern to Avoid

```
GUI needs feature → API adds special case → core logic bends to satisfy UI shape → CLI and GUI diverge
```

If you catch this happening, stop and fix the service layer. The API should never reshape core logic to satisfy frontend assumptions.

---

## Sequencing Summary

| Phase | Focus | Gate |
|-------|-------|------|
| 15 | HyDE retrieval validation | ≥3 queries improved, none degraded, no hallucinated IDs |
| 16 | Repository reorganization + service layer + read-only API | CLI/API parity, no CLI regression, smaller cohesive modules |
| 17 | Automated setup with lazy-load synthesis model | Fresh machine → working search in one command |
| 18 | Minimal GUI (search + trace, React + Tailwind) | Non-technical user can query and trace unassisted |

---

## Future Considerations (Not Scoped)

These are acknowledged but explicitly deferred:

- **HyPE (paraphrase expansion):** Only if HyDE works but coverage gaps remain on broad queries
- **Distribution packaging:** PyPI (`pip install reqbot`) is low-effort and worth doing alongside or after Phase 17. Snap/AppImage/DEB are polish-tier.
- **Docker Compose full stack:** API + GUI + Qdrant in one `docker-compose up`. Natural extension of Phases 16–18 but not a gated phase.
- **Write endpoints:** `/ingest`, `/evidence`, `/compare` via API. Deferred until read path is stable.
- **Streaming synthesis:** WebSocket support for streaming LLM responses in the GUI. Not needed for MVP.
- **Electron/Tauri desktop app:** Only if a specific deployment scenario demands it. Web GUI is the correct default.
- **Streamlit/Gradio:** Viable for a throwaway prototype but not for the product GUI. React + Tailwind has a higher ceiling for iteration.

---

*This document is a coordination artifact for review by Codex and Claude Code. It incorporates input from Claude (architecture, gating, repository reorganization), GPT (API philosophy, anti-patterns, config drift, response versioning, future product compatibility), and Gemini (HyDE hallucination risk, sync/async, CORS, lazy-load models). No implementation should begin until Phase 15 evaluation criteria, Phase 16 repository structure, and Phase 16 service/API contract boundaries are agreed.*
