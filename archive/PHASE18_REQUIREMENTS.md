# ReqBot — Phase 18: Minimal GUI (Demo-Focused)

**Status:** COMPLETE 2026-05-17  
**Date:** 2026-05-16  
**Preceded by:** Phase 17 (Setup + Environment Standardization — COMPLETE)  
**Followed by:** Phase 19 (Domain Profile Foundation — per PRODUCT_PRD.md)

---

## Goal

Deliver a usable web interface for non-CLI users. Search and trace only. Demo-ready stability is the gate.

---

## Scope Summary

| What's In | What's Out |
|-----------|------------|
| Search view (query + filters + results) | Compare view |
| Trace view (requirement detail + provenance) | Evidence export |
| Document filter (from /docs) | Ingest functionality |
| `reqbot serve` delivers both API + GUI | Synthesis toggle (deferred — see below) |
| `frontend/` lives in the repo | Corpus analytics |
| TypeScript, Vite, React, Tailwind | User accounts / multi-tenancy |
| | Electron / Tauri desktop wrapper |
| | Streaming synthesis |

---

## Architecture

```
Browser (Vite dev or static)
   │
   ├── GET  /api/status
   ├── POST /api/ask
   ├── GET  /api/trace/{req_id}
   └── GET  /api/docs
          │
     FastAPI (reqbot serve)
          │
     service layer (same functions the CLI calls)
```

The GUI is a pure frontend client. It calls the API; it never contains retrieval or business logic. The API never changes behavior to suit the GUI shape.

---

## Critical Decision: API Routing Strategy

**This must be resolved before frontend work begins.**

The current API has no path prefix:

```
GET  /status
POST /ask
GET  /trace/{req_id}
GET  /docs
```

If the SPA is served at `/`, then the `/trace/{req_id}` API route directly shadows the client-side `/trace/:reqId` route. React Router uses client-side routing, so the browser's first request for `/trace/REQ-xxx` would hit FastAPI, not the SPA.

### Option A: Add `/api/` prefix to existing routes — recommended

```
GET  /api/status
POST /api/ask
GET  /api/trace/{req_id}
GET  /api/docs

GET  /           → index.html (SPA catch-all)
GET  /search     → index.html
GET  /trace/:id  → index.html
```

- Cleanest long-term separation.
- No client-side route conflicts.
- Technically a breaking change, but the API is not in production use by any external system yet — the CLI never calls it.
- Swagger moves to `/api/api-docs` (slightly awkward) or `/api-docs` under the prefix.

### Option B: Mount SPA at `/app` — not chosen

```
GET  /status, /ask, /trace/{req_id}, /docs  — unchanged
GET  /app        → index.html
GET  /app/search → index.html
GET  /app/trace/:id → index.html
```

Rejected: Option B preserves external API surface at the cost of a worse user URL and a forced `/app` prefix on all client-side routes. The API is not externally entrenched; now is the right time to add the prefix.

### Decision: Option A

Option A is the chosen strategy. WP-18.1 adds the `/api/` prefix to all existing routes. Swagger stays at `/api-docs` (no prefix needed — it does not conflict with browser routes). The SPA serves at `/`.

---

## Work Package Plan

### WP-18.1 — API Prefix + Static File Foundation (Python side)

**Goal:** Land the routing strategy before touching the frontend.

**Scope:**

1. Apply chosen routing strategy to `api/app.py` and all route files.
2. Add `StaticFiles` mount for `frontend/dist/` when the directory exists:
   - Resolve the dist path relative to `api/app.py`: `Path(__file__).resolve().parent.parent / "frontend" / "dist"`. This works identically in both a dev checkout and the installed app tree (where the same relative structure is preserved during bundling — see WP-18.5).
   - If `frontend/dist/index.html` is present → mount SPA catch-all.
   - If not present → skip mount and log one line: `Frontend build not found; serving API only`. No error; `reqbot serve` starts normally in API-only mode.
3. Add SPA catch-all route that returns `index.html` for any path not matched by an API route. The response must use the same resolved absolute path — not a CWD-relative string — so that it works identically in a dev checkout and the installed bundle:
   ```python
   _DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

   @app.get("/{full_path:path}")
   def spa_fallback(full_path: str):
       return FileResponse(_DIST_DIR / "index.html")
   ```
   `_DIST_DIR` is computed once at module load. The catch-all must come last in route registration order so it does not shadow any `/api/` route.
4. Update CORS to cover Vite default port (`:5173`) in addition to `:3000` and `:8080`.
5. Update Swagger URL if prefix changes.
6. Smoke test: `curl localhost:8000/api/ask` still works; `curl localhost:8000/` returns index.html or 404 gracefully.

**Success criteria:**
- All existing CLI commands unaffected (CLI never calls the API).
- API routes respond correctly under new paths.
- `reqbot serve` can serve a static index.html from `frontend/dist/`.

---

### WP-18.2 — Frontend Scaffold

**Goal:** Working Vite + React + TypeScript + Tailwind project in `frontend/`, with a typed API client.

**Prerequisites:**
- Node.js 20 LTS must be installed on the dev machine.
  - Not present as of 2026-05-16. Install via NodeSource: `curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs`
  - This is a dev machine dependency only. The built `frontend/dist/` is what ships.
- `frontend/` directory structure created.
- `frontend/dist/` added to `.gitignore`.

**Scaffold spec:**

```
frontend/
  package.json          # dependencies: react, react-dom, react-router-dom, tailwindcss, ...
  package-lock.json     # committed (lock file is source)
  tsconfig.json
  vite.config.ts        # dev proxy → localhost:8000; output to dist/
  tailwind.config.js
  index.html
  src/
    main.tsx            # React entry point
    App.tsx             # Router setup
    api/
      client.ts         # typed fetch wrappers for each endpoint
      types.ts          # TypeScript types mirroring API response shapes
    views/
      SearchView.tsx
      TraceView.tsx
    components/         # shared UI components (ResultCard, LoadingSpinner, etc.)
```

**Tooling choices:**
- Bundler: **Vite** (fast, standard, zero-config for React)
- Framework: **React 18**
- Language: **TypeScript** (strict mode) — types mirror API contract; drift becomes a compile error
- Styling: **Tailwind CSS v3** (stable; v4 still too new)
- Routing: **React Router v6** (lightweight; adequate for 2 views)
- Data fetching: **plain fetch + useState/useEffect** for MVP (avoid TanStack Query dependency unless the loading state complexity justifies it — see open question)

**API client (`api/client.ts`):**

Typed wrappers for all four endpoints. Example shape:
```typescript
export async function ask(req: AskRequest): Promise<AskResponse> { ... }
export async function trace(reqId: string, context?: boolean): Promise<TraceResponse> { ... }
export async function docs(): Promise<DocsResponse> { ... }
export async function status(): Promise<StatusResponse> { ... }
```

**Type definitions (`api/types.ts`):**

Must exactly mirror the canonical API contract from Phase 16C. Comments call out where Python source was verified.

```typescript
// Base payload fields present on every indexed requirement.
// confidence comes from the extraction pipeline and is optional —
// older records may not carry it.
export interface Requirement {
  requirement_id: string;
  description: string;
  source_quote: string;
  source_ref: string;
  document_id: string;
  source_pdf: string;
  domain_tags: string[];
  requirement_type: string;
  confidence?: number;          // extraction-time confidence; not always present
  page_start?: number;
  page_end?: number;
  section_title_path?: string;  // schema v2.0 hierarchy fields
  section_ref_path?: string;
  parent_context?: string;
  chunk_id?: number;
}

// Ask results merge the Qdrant retrieval score with the full payload.
// score is always present (added by ask_service before returning).
export interface AskResult extends Requirement {
  score: number;
  context_text?: string | null;  // included when ask is called with context=true
}

// filters mirrors ask_service.ask() return exactly:
//   document_id: document_ids or None → string[] | null
//   domain_tag:  domain_tags or None  → string[] | null
//   requirement_type: requirement_types or None → string[] | null
export interface AskResponse {
  query: string;
  filters: {
    document_id: string[] | null;
    domain_tag: string[] | null;
    requirement_type: string[] | null;
  };
  results: AskResult[];
  metadata: {
    top_k: number;
    result_count: number;
    retrieval_ms: number;
    synthesis: string | null;   // always null in Phase 18 (synthesis not exposed in GUI)
  };
}

export interface TraceResponse {
  requirement: Requirement;
  cross_matches: Requirement[];
  context_text: string | null;
}

export interface DocsEntry {
  doc_key: string;
  path: string;
  count: number;
  mode: string;
  run_date: string;
}

export interface DocsResponse {
  docs: DocsEntry[];
  total_reqs: number;
  total_docs: number;
}
```

**Vite dev proxy:**
```typescript
// vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```
During development: `vite dev` runs on `:5173`; API calls proxy to `:8000`. No CORS issues.

**Success criteria:**
- `npm run dev` starts without errors.
- `npm run build` produces `frontend/dist/`.
- The API client module type-checks cleanly.
- `reqbot serve` (separately) responds to `/api/status`; Vite proxy forwards correctly.

---

### WP-18.3 — Search View

**Goal:** A functional query interface that calls `/api/ask` and displays results.

**Layout:**
```
┌────────────────────────────────────────────────────┐
│  ReqBot                              [Status dot]  │
├────────────────────────────────────────────────────┤
│  [Query input .......................] [Search]     │
│  Filter by document: [All ▼]                       │
├────────────────────────────────────────────────────┤
│  Results (23)                       1,243ms        │
│  ┌──────────────────────────────────────────────┐  │
│  │ REQ-AFI17-abc123  ·  AFI 17-101  ·  0.847   │  │
│  │ The system shall enforce multi-factor...     │  │
│  │ Source: Section 3.4, pp. 12-13               │  │
│  └──────────────────────────────────────────────┘  │
│  [more cards...]                                   │
└────────────────────────────────────────────────────┘
```

**Behavior:**
- Enter key or Search button submits query.
- Document filter populated from `/api/docs` on mount.
- Top-k fixed at 20 for MVP (no slider — avoid over-building filters in v1).
- Results sorted by score descending (API already does this).
- Each result card is clickable → navigates to `/trace/:reqId`.
- URL reflects active query: `?q=encryption+at+rest&doc=AFI-17-101` (enables browser back/refresh).
- Loading state: spinner while waiting.
- Error state: plain message with retry button.
- Empty state: "No results found" with query echo.

**What's explicitly NOT in this view:**
- Synthesis toggle — **not in Phase 18**. Synthesis takes 30+ seconds and is poor UX without streaming. It will be added in a later phase with a deliberate UX (streaming or a clearly separated "Generate answer" action). The `synthesize: false` default in `AskRequest` is used for all GUI calls.
- Domain tag filter (defer to Phase 19 when domain profiles exist)
- Requirement type filter (defer)
- Pagination (top-k=20 fits on one screen; defer infinite scroll)
- min_score slider (default 0.02 is fine)

**Success criteria:**
- Query → results in <2s on localhost (retrieval only).
- Results display requirement ID, description snippet, source document, score.
- Document filter loads correctly from /api/docs.
- URL updates on search; back button restores previous query.

---

### WP-18.4 — Trace View

**Goal:** Full requirement detail with provenance and cross-framework matches.

**Layout:**
```
┌────────────────────────────────────────────────────┐
│  ← Back to search                                  │
├────────────────────────────────────────────────────┤
│  REQ-AFI17-abc123                                  │
│  AFI 17-101 · Section 3.4 · pp. 12-13             │
├────────────────────────────────────────────────────┤
│  DESCRIPTION                                        │
│  The system shall enforce multi-factor...          │
│                                                    │
│  SOURCE QUOTE                                      │
│  "Systems processing CUI shall require MFA..."     │
│                                                    │
│  PROVENANCE                                        │
│  Document ID:  AFI-17-101                          │
│  Source PDF:   AFI_17-101.pdf                      │
│  Domain tags:  access_control, identification_auth │
│  Type:         mandatory                           │
│  Confidence:   0.95                                │
├────────────────────────────────────────────────────┤
│  CROSS-FRAMEWORK MATCHES (3)                       │
│  ┌──────────────────────────────────────────────┐  │
│  │ REQ-NIST-xxx · NIST SP 800-53r5 IA-2(1)     │  │
│  │ "Implement multi-factor authentication..."   │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

**Behavior:**
- Route: `/trace/:reqId` — calls `GET /api/trace/{req_id}` on mount.
- Use `encodeURIComponent(reqId)` when constructing the fetch URL. Corpus IDs are path-safe (no `/` in the ID format), but encoding is still correct practice and costs nothing.
- "Back to search" preserves the previous search URL (use React Router state or `?q=` param).
- Cross-framework matches are cards; each is clickable → navigates to its own trace view.
- Context text (raw chunk) is hidden by default, optional expand (calls `/api/trace/{req_id}?context=true`).
- Loading state while fetching.
- 404 state: "Requirement not found" with back link.
- 503 state: "Backend unavailable" with retry.

**Success criteria:**
- All payload fields are displayed.
- Cross-framework matches load and are navigable.
- Context expand works (calls context=true variant).
- 404 and 503 error states display cleanly.

---

### WP-18.5 — Build Integration + Polish

**Goal:** Single `reqbot serve` command delivers both API and GUI. Build step integrated into existing toolchain.

**Build integration:**

1. `build/build-frontend.sh` — new tracked script:
   ```bash
   #!/usr/bin/env bash
   set -e
   cd "$(dirname "$0")/../frontend"
   npm ci
   npm run build
   echo "[+] Frontend built → frontend/dist/"
   ```

2. `build/bundle.sh` — add two steps after the existing Python source copy (Step 5):
   - Run the frontend build: `bash build/build-frontend.sh`
   - Copy the built dist into the installed app tree at the path `api/app.py` resolves to at runtime:
     ```bash
     cp -r "$ROOT_DIR/frontend/dist" "$BUNDLE_DIR/app/frontend/dist"
     ```
   At install time `__file__` is `$BUNDLE_DIR/app/api/app.py`, so `parent.parent / "frontend" / "dist"` resolves to `$BUNDLE_DIR/app/frontend/dist/` — exactly where this copy lands. The existing `APP_FILES` list covers Python source; `frontend/dist/` is a directory copy and is handled separately.

   `build/bundle.sh` must also install `aiofiles` alongside the existing pip installs. FastAPI's `StaticFiles` mount depends on Starlette's file-serving path, which uses synchronous I/O and does not strictly require `aiofiles` — but the Starlette dependency tree pulls it in implicitly. To be explicit, add it to the pinned pip install block in Step 3 and to `requirements.txt`.

3. `frontend/dist/` added to `.gitignore` (dist is a build artifact, not source).

4. `package-lock.json` IS committed (lock file is source, reproducible builds).

**`reqbot serve` serving the GUI:**

When `frontend/dist/index.html` is present, `reqbot serve` serves the GUI automatically. No flag needed — the API is always available; the GUI is served when the build exists.

Users during development: `vite dev` in `frontend/` for hot-reload, `reqbot serve` for API.
Users running the installed binary: `reqbot serve` serves both.

**Status indicator in app header:**

A small colored dot (green/red) calls `/api/status` on mount and every 30s. Shows "Ollama ✓ Qdrant ✓" or specific failure. This doubles as a quick smoke test during demos.

**Tailwind cleanup:**

Remove unused CSS classes via Tailwind's purge/content configuration. Keep bundle size minimal — this is a local tool, but a 2MB CSS bundle is still a bad look.

**Success criteria:**
- `npm run build` completes without errors.
- `reqbot serve` responds to API calls AND serves the SPA from a single port.
- `build/build-frontend.sh` runs clean in a fresh checkout.
- A non-technical user can navigate to `localhost:8000`, run a query, and drill into a trace without assistance.
- No crashes or confusing error states during a live walkthrough.

---

## Resolved Design Decisions

The following questions were raised in the draft and resolved before implementation begins:

| Question | Decision |
|----------|----------|
| Routing strategy | **Option A** — `/api/` prefix on all API routes; SPA served at `/` |
| Requirement ID URL safety | Standard `{req_id}` param; `encodeURIComponent` on frontend; no `{req_id:path}` needed |
| TanStack Query vs. plain fetch | **Plain fetch** — 2 views, 4 endpoints; MVP complexity does not justify the dependency |
| Synthesis in Phase 18 | **Out of scope** — omitted entirely; add later with streaming UX |
| `reqbot serve` locating `frontend/dist/` | Resolved relative to `api/app.py`: `Path(__file__).resolve().parent.parent / "frontend" / "dist"`; bundling preserves this relative structure; no config entry |
| Node.js as build dependency | **Yes** — dev/CI build dependency only; end users receive pre-built static files |

## Remaining Open Questions

None. All design questions are resolved. Implementation may begin with WP-18.1.

---

## What's NOT Changing

- The service layer is untouched. The GUI calls the same functions the CLI does, via the API.
- The CLI is untouched. `reqbot ask`, `reqbot trace`, etc. work exactly as before.
- The pipeline is untouched.
- One new pip dependency: `aiofiles` (added in WP-18.5 for `StaticFiles` serving). No others.
- JSONL is still the source of record.

---

## Success Gate (Phase 18)

1. A non-technical user can enter a query, view results, and drill into a trace without instructions.
2. Demo-ready stability: no crashes or blank error states during a live walkthrough.
3. GUI and CLI return visually consistent results for the same query.
4. `reqbot serve` delivers both API and GUI from a single command on a single port.
5. All existing CLI commands still work (the GUI changes nothing in the Python stack).
6. Killing `reqbot serve` has zero impact on `reqbot ask` (CLI independence preserved).

---

## Sequencing

Do one WP at a time, gate with Codex/Gemini review after each:

| WP | Description | Gate before next |
|----|-------------|-----------------|
| 18.1 | API prefix + static file serving | curl smoke test; CLI regression check |
| 18.2 | Frontend scaffold + API client | `npm run dev` starts; types compile; proxy works |
| 18.3 | Search view | Query → results; document filter; URL sync |
| 18.4 | Trace view | Full detail; cross-matches; 404/503 states |
| 18.5 | Build integration + polish | `reqbot serve` delivers both; non-technical user walkthrough passes |
