# ReqBot Phase 16 Requirements Document
## Repository Reorganization + Service Layer Foundation

**Status:** Draft  
**Purpose:** Define the concrete requirements and execution scope for ReqBot Phase 16.

---

# 1. Phase Objective

Phase 16 restructures the ReqBot repository into cohesive modules, extracts reusable service-layer logic from the monolithic CLI, and introduces a minimal read-only API foundation.

This phase exists to:

- Reduce brittleness
- Improve maintainability
- Improve AI-assisted development workflows
- Reduce edit scope and token overhead
- Prepare the codebase for:
  - GUI support
  - generalized requirements ingestion
  - domain profiles
  - checklist generation
  - future policy alignment workflows

Phase 16 is foundational architecture work. It is not primarily an API feature phase.

---

# 2. Design Principles

## 2.1 The Pipeline Is Still the Product

The extraction, normalization, indexing, retrieval, and trace pipeline remains the core value of ReqBot.

Phase 16 must not compromise pipeline quality or retrieval behavior.

---

## 2.2 API as Dumb Transport

The API is a thin wrapper over reusable service functions.

The API:
- validates input
- calls service functions
- returns structured results

The API shall not contain business logic.

---

## 2.3 CLI Independence

The CLI must never depend on the API.

If the API server is stopped:
- the CLI must continue functioning normally
- pipeline scripts must continue functioning normally

---

## 2.4 AI-Assisted Maintainability

Large multi-purpose files create:
- token inefficiency
- difficult review workflows
- fragile edits
- higher regression risk

Phase 16 explicitly restructures the repository into smaller cohesive modules to improve:
- maintainability
- reviewability
- debuggability
- AI-assisted iteration speed

---

# 3. Repository Reorganization Requirements

## 3.1 Target Repository Structure

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

---

## 3.2 Pipeline Folder

The `pipeline/` folder shall contain the document-processing stages:

- extraction
- chunking
- normalization
- enrichment
- aggregation
- embedding
- indexing

These scripts shall remain independently runnable.

---

## 3.3 Services Folder

The `services/` folder shall contain reusable business logic extracted from the CLI.

Minimum required services:

- `ask_service.py`
- `trace_service.py`
- `docs_service.py`
- `status_service.py`

Optional during initial extraction:

- `compare_service.py`
- `evidence_service.py`

Services shall:
- return structured objects/dictionaries
- avoid direct console printing
- avoid API dependencies

---

## 3.4 Models Folder

The `models/` folder shall contain shared schemas and structured objects used across:

- pipeline
- services
- API
- GUI
- checklist generation

Initial model candidates:

- requirement model
- checklist model
- API response model

This layer exists to prevent schema drift.

---

# 4. Phase 16A — Repository Reorganization

## 4.1 Scope

Phase 16A performs repository reorganization only.

Allowed actions:
- move files into cohesive folders
- update imports
- establish folder structure

Disallowed actions:
- logic rewrites
- behavior changes
- opportunistic cleanup
- feature additions

---

## 4.2 Additional 16A Considerations

### Build Script Impact

`reqbot-install.sh` (and `bundle.sh`) bundle source files by path. Moving files into
subfolders will break the installer unless the build scripts are updated in the same PR.
16A must include updating all build scripts to reference the new paths.

### eval/ Folder

The `eval/` folder (gold set scripts, HyDE evaluation queries) is not part of the
reorganization target structure. It remains at `eval/` in the repo root. No move required.

### Python Package Strategy

Each new subfolder (`pipeline/`, `services/`, `core/`, `cli/`, `models/`) must contain
an `__init__.py` to be importable as a Python package. These files should be empty or
contain only a module docstring. Create them as part of 16A folder setup.

---

## 4.3 Success Criteria

- Existing CLI commands still work
- Existing pipeline scripts still run
- Existing outputs remain unchanged
- Imports resolve correctly
- Build scripts updated to reflect new paths
- Repository structure is easier to navigate

---

# 5. Phase 16B — Service Layer Extraction

## 5.1 Scope

Extract reusable command logic from `reqbot.py`.

Initial extraction targets:
- ask logic
- trace logic
- docs logic
- status logic

Optional:
- compare logic
- evidence logic

---

## 5.2 Requirements

The CLI shall:
- call services directly
- remain fully functional without API support

Service functions shall:
- return structured data
- avoid direct console output unless explicitly intended
- avoid API dependencies

Existing retrieval behavior shall remain unchanged.

---

## 5.3 Success Criteria

- `cli/reqbot.py` becomes substantially smaller
- CLI behavior matches pre-refactor behavior
- Services can be called directly from Python
- No regression in retrieval or trace functionality

---

# 6. Phase 16C — Read-Only API Foundation

## 6.1 Scope

Add a minimal FastAPI wrapper over the service layer.

Initial endpoints:

| Endpoint | Method |
|----------|--------|
| `/status` | GET |
| `/ask` | POST |
| `/trace/{req_id}` | GET |
| `/docs` | GET |

---

## 6.2 Explicit Exclusions

The following are out of scope for Phase 16:

- `/compare`
- `/evidence`
- `/analyze`
- `/ingest`
- `/checklist`
- `/alignment`
- background jobs
- streaming
- authentication
- stateful workflows

---

## 6.3 API Requirements

The API shall:
- call services directly
- avoid business logic
- use synchronous route handlers
- support CORS for future GUI use

---

## 6.4 Response Stability

API response structures shall be treated as versioned from day one.

The frontend shall not dictate API response shape.

---

## 6.5 Success Criteria

- API and CLI return equivalent results
- API works via curl/Postman
- Killing the API server does not impact CLI operation

---

# 7. Future Compatibility Requirements

Phase 16 shall support future capabilities already defined in the ReqBot Product Requirements Document.

The architecture shall support:
- domain profiles
- generalized requirement schemas
- checklist generation
- evidence request generation
- policy alignment workflows
- cross-domain ingestion

The shared architecture shall avoid cybersecurity-specific assumptions where possible.

Cybersecurity remains the first supported domain, not the only supported domain.

---

# 8. Anti-Patterns To Avoid

## 8.1 Premature Framework Abstraction

ReqBot shall prioritize:
- direct Python control
- explicit imports
- transparent service boundaries

Heavy orchestration frameworks shall not be adopted solely for architectural aesthetics.

---

## 8.2 GUI-Driven Backend Drift

The following architecture drift must be avoided:

```text
GUI needs feature
→ API adds special case
→ service layer bends
→ core logic bends
→ CLI and GUI diverge
```

The API and GUI shall adapt to the service layer, not the other way around.

---

# 9. Execution Order

## Step 1 — Repository Reorganization
- move files
- update imports
- preserve behavior

## Step 2 — Service Extraction
- extract reusable services
- shrink monolithic CLI

## Step 3 — API Foundation
- thin read-only FastAPI layer
- no business logic in routes

---

# 10. Final Gate

Phase 16 is complete when:

- the repository is modular and navigable
- service boundaries are established
- the CLI still works identically
- the API is functional and read-only
- future checklist and generalized-requirements work has a clear architectural home
