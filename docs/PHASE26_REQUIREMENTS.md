# ReqBot Phase 26 - MCP Tool Surface

**Status:** Draft
**Date:** 2026-07-23
**Preceded by:** Phase 25 (Packaging and Deployment Reset)
**Followed by:** TBD

---

## Status

This table is the live source of truth for Phase 26 WP status — update it here when a WP lands,
not in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-26.1 — MCP Design Lock + Backlog Cleanup | Not started |
| WP-26.2 — MCP Server Skeleton | Not started |
| WP-26.3 — Corpus + Search Tools | Not started |
| WP-26.4 — Compare + Evidence Tools | Not started |
| WP-26.5 — Checklist Tool | Not started |
| WP-26.6 — Integration Gate | Not started |

---

## 1. Phase Framing

Phase 25 made ReqBot easier to install, package, configure, and deploy. That clears the way for
ReqBot to become useful as a tool backend for other LLMs.

Phase 26 adds an MCP server so external assistants can query a self-hosted ReqBot instance using
structured tools instead of screen-scraping the UI or calling ad hoc endpoints.

ReqBot should not become an autonomous agent. ReqBot stays the compliance retrieval/provenance
engine. Claude, ChatGPT, Gemini, genai.mil, and similar systems stay the planners, writers, and
orchestrators.

---

## 2. Goals

- Expose ReqBot as an MCP server.
- Start with a small, reliable tool surface mapped to existing service behavior.
- Preserve provenance in every tool response.
- Keep MCP as a thin wrapper over existing service functions.
- Make ReqBot usable by external LLMs as a self-hosted compliance/RAG tool.
- Prove the interface with a real MCP client before declaring the phase complete.

---

## 3. Non-Goals

Explicitly out of scope for Phase 26:

- No autonomous agent framework inside ReqBot.
- No "do everything for me" mega-tool.
- No new retrieval logic unique to MCP.
- No MCP-only product capability that bypasses the service layer.
- No hosted/SaaS/multi-user/auth scope.
- No generated audit questions.
- No assessor-note merge/preservation logic.
- No new vector database abstraction.
- No binary/file export over MCP in the MVP.
- No deprecation of remote synthesis in this phase; document the question and revisit after MCP is
  proven useful.

---

## 4. Architecture Rules

1. **MCP calls services, not the CLI.** Tools call `services/*` and core functions directly, the same
   way API routes do. No subprocess calls to `reqbot`.
2. **MCP returns structured JSON by default.** Tool output should be parseable by an orchestrating
   LLM or downstream code.
3. **Generated prose is optional and labeled.** If a tool returns synthesis text, it must be a
   clearly named optional field and must never replace structured retrieval results.
4. **Provenance is mandatory.** Do not strip `requirement_id`, `source_pdf`, `source_ref`,
   `source_quote`, page fields, confidence, profile/domain metadata, or warning fields for
   "simplicity."
5. **Tool failures surface as structured MCP errors.** Unknown IDs, invalid document keys, invalid
   profiles, Qdrant/Ollama failures, and config errors must not be hidden as fake empty results.
6. **Tool wrappers stay thin.** If a tool needs nontrivial business logic, put that logic in
   `services/`, then call it from MCP.
7. **MCP startup uses normal ReqBot config.** It should read the same `~/.config/reqbot/config.json`
   and `REQBOT_*` environment variables as CLI/API.
8. **Prefer composable primitives.** Start with search, trace, list, compare, evidence, and checklist
   primitives. Do not create a single giant orchestration endpoint.

---

## 5. Initial Tool Surface

Phase 26 should start with tools that map directly to already-existing service/API behavior.

### `get_status`

Purpose: let an MCP client verify ReqBot readiness.

Output:
- configured service URLs
- configured model roles
- Qdrant/Ollama reachability
- installed/available model information where already exposed by status service

### `list_documents`

Purpose: let an orchestrator inspect the available corpus before asking targeted questions.

Output:
- document keys
- source PDF names
- requirement counts
- profile/domain metadata where available
- dates/mode fields already provided by docs service

### `search_requirements`

Purpose: retrieve source-backed requirements for a query.

Input:
- `question`
- optional `top_k`
- optional document filters
- optional domain tag filters
- optional requirement type filters
- optional context flag if existing service support is clean

Output:
- ranked requirement hits
- scores
- source quotes
- provenance metadata
- warnings

### `trace_requirement`

Purpose: retrieve full provenance for one known requirement.

Input:
- `requirement_id`
- optional `include_context`

Output:
- full requirement detail
- source quote
- source reference
- document/page metadata
- section path metadata
- cross-framework matches
- optional context window

### `compare_documents`

Purpose: compare two documents on a topic/control.

Input:
- `doc_1`
- `doc_2`
- `topic` or control ID

Output:
- structured comparison groups
- exact/semantic mode information
- provenance per result
- warnings

### `map_evidence`

Purpose: build a source-backed evidence map for a topic/control.

Input:
- `topic`
- optional filters
- optional synthesize flag if existing service behavior is used

Output:
- grouped evidence results
- source groupings
- optional synthesis text
- provenance
- warnings

### `generate_checklist`

Purpose: generate a source-backed checklist envelope for a document.

Input:
- `doc_key`
- optional `profile`

Output:
- structured checklist envelope from `checklist_service.generate()`

MVP decision: this tool returns the structured checklist envelope only. CSV/JSON/Markdown/XLSX file
export remains CLI/API/GUI-only until a concrete MCP use case proves file export is needed.

---

## 6. Work Packages

### WP-26.1 - MCP Design Lock + Backlog Cleanup

**Goal:** lock the MCP implementation choices before code starts.

**Scope:**

- Create/finalize this Phase 26 requirements document.
- Scrub `docs/TODO_future_improvements.txt`:
  - move completed items out of `ACTIVE BACKLOG`
  - keep MCP as active Phase 26 work
  - leave experiments/backburner items intact where still useful
- Verify no current docs still describe MCP as the next active Phase 25 target. Historical Phase
  plans may keep historical language only if clearly archival.
- Decide and document the MCP dependency choice (exact package name — see below).
- Decide and document the first transport.
- Decide and document the server command shape.
- Confirm the initial tool list and what is deferred.
- Confirm the checklist-tool promotion: `archive/FUTURE_MCP_IDEA.md` originally placed checklist
  generation in the "good future tools, after primitives are stable" bucket (as
  `generate_checklist_candidates`), not the first five tools. This doc promotes it to WP-26.5,
  in-scope for Phase 26, as `generate_checklist`. That's a reasonable call — `checklist_service.
  generate()` is already a stable, existing feature rather than a new "candidates" generator the
  original note was hedging against — but WP-26.1 should confirm it's an intentional promotion,
  not scope creep that slipped in unnoticed.
- Record the remote-synthesis question as deferred, not decided.

**Preferred decisions for review:**

- Dependency: **`mcp`** (`pip install mcp`), the official Python MCP SDK maintained by the
  Model Context Protocol project — use its bundled `mcp.server.fastmcp.FastMCP` decorator API,
  not the separate third-party `fastmcp` package on PyPI (jlowin's, 3.x). Decided in favor of
  the official SDK: it's the reference implementation for the spec (mainstream/stable over
  new/actively-churning), and it's a single dependency rather than adding a second competing
  FastMCP implementation on top of it — consistent with "no new dependencies without
  discussion." The bundled FastMCP API is frozen at what was "1.0," so it will lag the
  standalone package's newer conveniences; that trade is acceptable for an MVP tool surface.
- First transport: stdio.
- Command shape: `reqbot mcp`.
- HTTP/SSE transport: later phase only if there is a real deployment need.

**Tests / verification:**

- Docs reference the selected dependency/transport/command shape.
- TODO file no longer lists already-completed Phase 23/24/25 work as active future work.
- No code changes in this WP unless explicitly approved.

**Gate:** Phase 26 is scoped tightly enough that WP-26.2 can start without reopening library,
transport, command, or first-tool decisions.

---

### WP-26.2 - MCP Server Skeleton

**Goal:** add the MCP server with one low-risk status tool.

**Scope:**

- Add the approved MCP dependency.
- Add an MCP module, likely `integrations/mcp/` or `mcp_server/`.
- Add `reqbot mcp`.
- Load normal ReqBot config.
- Expose `get_status`.
- Ensure the MCP server can run without `reqbot serve`.

**Non-goals:**

- No search/trace/checklist tools yet.
- No HTTP/SSE transport unless WP-26.1 explicitly changes the transport decision.

**Tests / verification:**

- Unit test: server module imports without starting network services.
- Unit test: `get_status` calls existing status/config logic.
- Unit test: status output contains configured model/service fields.
- Unit test: service/config failure becomes a structured MCP error.
- Manual smoke: an MCP client can connect over stdio and call `get_status`.

**Gate:** `reqbot mcp` starts and exposes one working status tool with tested error behavior.

---

### WP-26.3 - Corpus + Search Tools

**Goal:** expose the core retrieval/provenance value.

**Scope:**

- Add `list_documents`.
- Add `search_requirements`.
- Add `trace_requirement`.
- Use existing docs/ask/trace service logic.
- Preserve warnings and provenance fields.

**Non-goals:**

- No compare/evidence/checklist tools in this WP.
- No new search ranking behavior.
- No generated prose by default.

**Tests / verification:**

- Unit test: each tool calls the expected service/core function.
- Unit test: required provenance fields are present in successful outputs.
- Unit test: search warnings pass through.
- Unit test: unknown `requirement_id` becomes a structured MCP error.
- Unit test: Qdrant/service failure becomes a structured MCP error.
- Manual smoke: MCP client can list docs, search a topic, and trace one returned requirement.

**Gate:** an external MCP client can discover corpus documents, search requirements, and trace a
result back to source.

---

### WP-26.4 - Compare + Evidence Tools

**Goal:** expose higher-level compliance workflows after search/trace are stable.

**Scope:**

- Add `compare_documents`.
- Add `map_evidence`.
- Use existing compare/evidence services.
- Return structured groups and optional synthesis fields exactly as service outputs support.
- Preserve warnings and provenance.

**Non-goals:**

- No checklist tool.
- No new evidence generation logic.
- No new synthesis behavior.

**Tests / verification:**

- Unit test: compare tool calls compare service with expected parameters.
- Unit test: evidence tool calls evidence service with expected parameters.
- Unit test: exact/semantic compare outputs preserve provenance fields.
- Unit test: evidence grouped outputs preserve sources and warnings.
- Unit test: service errors become structured MCP errors.
- Manual smoke: MCP client can compare two docs and build an evidence map.

**Gate:** MCP can perform the same compare/evidence workflows available through CLI/API without
forking behavior.

---

### WP-26.5 - Checklist Tool

**Goal:** expose source-backed checklist generation to MCP clients.

**Scope:**

- Add `generate_checklist`.
- Call `checklist_service.generate()`.
- Return the structured checklist envelope.
- Preserve checklist item IDs, source quotes, review flags, review reasons, confidence, profile,
  and provenance fields.

**Non-goals:**

- No CSV/Markdown/JSON/XLSX file export over MCP.
- No assessor-field editing.
- No assessor-note preservation/merge logic.
- No generated audit questions.

**Tests / verification:**

- Unit test: tool calls `checklist_service.generate()` with `doc_key` and profile.
- Unit test: checklist envelope output preserves required top-level fields.
- Unit test: checklist items preserve provenance/review fields.
- Unit test: invalid doc key/profile becomes a structured MCP error.
- Manual smoke: MCP client generates a checklist for a known document.

**Gate:** MCP client can generate a structured checklist envelope with stable IDs and provenance.

---

### WP-26.6 - Integration Gate

**Goal:** prove MCP is a working third interface beside CLI/API/GUI.

**Manual walkthrough:**

Use Claude Code as the primary MCP client where possible, configured to call `reqbot mcp` over
stdio. If Claude Code cannot be used in the environment, use another MCP-capable client and record
which one was used.

1. Start from a configured ReqBot environment with Qdrant/Ollama reachable.
2. Run `reqbot mcp`.
3. Connect from the MCP client.
4. Call `get_status`.
5. Call `list_documents`.
6. Call `search_requirements` for a known compliance topic.
7. Call `trace_requirement` on one returned requirement ID.
8. Call `compare_documents` for two known documents.
9. Call `map_evidence` for a known topic/control.
10. Call `generate_checklist` for a known document.
11. Confirm every result includes expected provenance.
12. Confirm CLI/API still work without MCP running.

**Tests / verification:**

- Full unit suite passes.
- Ruff passes.
- MCP unit tests from each WP pass.
- Manual MCP walkthrough above is recorded in the Phase 26 doc.

**Gate:** MCP is proven useful end-to-end without introducing a forked behavior path.

---

## 7. Success Gate

Phase 26 is complete when:

1. `reqbot mcp` exists and starts.
2. MCP uses the approved dependency/transport chosen in WP-26.1.
3. MCP loads normal ReqBot config.
4. MCP exposes status, list, search, trace, compare, evidence, and checklist tools.
5. Tool outputs preserve provenance.
6. Tool errors are structured MCP errors, not fake empty successful responses.
7. Each tool has focused unit coverage.
8. A real MCP client can complete the WP-26.6 walkthrough.
9. CLI/API/GUI behavior does not regress.
10. ReqBot remains a tool engine, not an autonomous agent framework.

---

## 8. Open Questions Deferred Beyond Phase 26

- Should remote synthesis (`reqbot[remote]`) be deprecated once MCP is available?
- Should MCP eventually expose HTTP/SSE transport for remote agent clients?
- Should binary/file export over MCP ever be supported, or should file export stay API/GUI/CLI-only?
- Should future composed tools exist, such as `build_audit_plan` or
  `find_gaps_across_authorities`?
- Should MCP eventually require auth when exposed beyond local stdio?

---

## 9. Guardrails

- Do not build agent planning inside ReqBot.
- Do not strip provenance from tool outputs.
- Do not hide backend failures as empty results.
- Do not add MCP-only business logic.
- Do not make synthesis replace structured retrieval output.
- Do not start with composed "magic" tools before primitives are stable.
- Do not widen deployment/security scope in this phase.
