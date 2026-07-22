# ReqBot — Phase 22: Browser Checklist Workflow

**Status:** Draft
**Date:** 2026-07-19
**Preceded by:** Phase 21 (Checklist Generator MVP — CLI/service/export, COMPLETE)
**Followed by:** TBD (evidence/test-step refinement, or later UI capabilities)

---

## 1. Phase Framing

Phase 21 delivered checklist generation, schema, and CSV/JSON/Markdown export entirely at the
CLI and service layer. No browser surface exists for it today — a non-technical assessor cannot
generate or export a checklist without the CLI.

**Phase 22 closes that gap.** It does two things, in order:

1. Lays down the minimum UI foundation the checklist screens need (sidebar nav slot, Corpus
   rename, shared provenance/quote components) — otherwise checklist UI gets built on
   throwaway scaffolding.
2. Adds a thin `/api/checklist` endpoint over the existing `checklist_service.generate()` and
   `pipeline/checklist_export.py`, then a generate screen and a preview/export screen.

Phase 22 does not add new checklist content (evidence-to-request, test steps, audit questions),
new generation logic, editable fields, ingest UI, or new export formats. It exposes exactly what
Phase 21 already built, in the browser.

---

## 2. Goals

- A non-technical user can generate a checklist for a document from the browser.
- A non-technical user can preview the generated checklist, grouped Locate/Ask/Record/Verify/Trace.
- A non-technical user can export the checklist as CSV, JSON, or Markdown from the browser,
  content-equivalent to what the CLI produces.
- The browser UI gains a persistent sidebar and a `/corpus/:docId` / `/system` foundation so the
  checklist screens (and future screens) have a stable home.
- CLI behavior is completely unchanged. Killing `reqbot serve` has zero effect on CLI checklist
  generation.

---

## 3. Non-Goals

Explicitly out of scope for Phase 22:

- Evidence-to-request or test-step generation (deferred; separate phase, PRODUCT_PRD Phase 22
  "Evidence Request and Test Step Refinement" naming collision is intentional — that work is
  **not** this phase).
- `audit_question` generation of any kind (still reserved per Phase 21 WP-21.3).
- Editable `status` / `assessor_notes` fields in the browser.
- Merge-on-regeneration / assessor-note persistence (TODO #17) — undesigned, stays undesigned.
- Ingest UI, upload forms, or browser-triggered pipeline runs.
- XLSX export.
- Profile management UI (create/edit/delete). A read-only `GET /api/profiles` endpoint for picker options is in scope (see Section 5); creating, editing, or deleting profiles is not.
- Job history, export history.
- Authentication, multi-user, hosted/SaaS deployment.
- MCP tool surface (separate future phase; noted in TODO #13).
- Any new npm/pip dependency not already in use, without explicit approval.

---

## 4. Architecture Rules

Unchanged from Phase 18/19/21 and binding for Phase 22:

1. **Frontend is a client only.** All checklist logic lives in `services/checklist_service.py`
   and `pipeline/checklist_export.py`. The GUI calls the API; it never regenerates, reformats,
   or reshapes checklist content.
2. **The UI must not call the CLI.** All browser requests go through `/api/*` routes calling
   service functions directly — never subprocess/CLI invocation from the API or frontend.
3. **API remains thin.** `api/routes/checklist.py` validates input, calls the service/export
   functions, and returns the result. No formatting, grouping, or filtering logic in the route.
4. **No client-side checklist generation or export formatting.** CSV/JSON/Markdown are produced
   exclusively by `pipeline/checklist_export.py`. React never builds a CSV string, a Markdown
   string, or re-derives `page_refs`/`review_reasons`/`checklist_item_id`.
5. **CLI and GUI share the same backend paths.** The new endpoint calls the exact same
   `checklist_service.generate()` signature the CLI's `cmd_checklist()` calls.
6. **No new pip/npm dependencies without discussion.** Air-gapped environments remain a target.
7. **Work one WP at a time.** Get Codex/Gemini review after each WP before proceeding, per
   existing project convention.
8. **Review cadence:** lightweight Codex/Gemini review is welcome per individual PR. The
   formal gate blocking the next WP is at WP completion, not individual PR completion. A WP
   that produces multiple PRs proceeds to the WP gate after all its PRs are merged.

**Safety test (unchanged pattern from Phase 16/19):**
- Can you kill the API server and still run `reqbot checklist` normally? → **Yes**
- Can you change a checklist screen without touching `checklist_service.py` or
  `checklist_export.py`? → **Yes**
- Do CLI and API call the same service/export functions for the same operation? → **Yes**

If any answer becomes no, the design is wrong.

---

## 5. API Scope

**New endpoint:**

| Endpoint | Method | Maps to |
|---|---|---|
| `/api/checklist` | POST | `checklist_service.generate(processed_dir, doc_key, profile_name)` |
| `/api/checklist/export` | POST | `pipeline/checklist_export.py` (`to_csv`/`to_json`/`to_markdown`) |
| `/api/profiles` | GET | `core.profiles` — list available profile names from the `profiles/` directory |

**`POST /api/checklist` — request shape:**
```json
{
  "doc_key": "afi17-101",
  "profile": "cybersecurity"
}
```
Returns the full checklist envelope (format, generator, document, profile, summary, items) —
unmodified, matching what `checklist_service.generate()` returns.

**`POST /api/checklist/export` — request shape:**
```json
{
  "doc_key": "afi17-101",
  "profile": "cybersecurity",
  "format": "csv"
}
```
Returns the exported file content (CSV/JSON/Markdown as text) with an appropriate
`Content-Type` and `Content-Disposition: attachment` header for browser download. The route
calls `generate()` then the matching `to_*()` function — it does not cache or persist
checklist state.

**Frontend download pattern (required):** Use `fetch()` + `response.blob()` +
`URL.createObjectURL()` + a programmatic `<a>` click to trigger the download. Do not
redirect `window.location.href` to this endpoint — it is a POST, not a GET.

**`GET /api/profiles` — response shape:**
```json
{ "profiles": ["cybersecurity"] }
```
Returns available profile names discovered from the `profiles/` directory. No request body.
The frontend's `ProfilePicker` must use this endpoint — do not hardcode profile names in the
frontend. An unknown `profile` in any checklist endpoint → 400 (maps the existing
`FileNotFoundError` from `load_profile()`).

**Response shape discipline:**
- Match shapes to what the service/export functions already return. Do not strip or rename
  fields for frontend convenience.
- Errors: unknown `doc_key` or invalid `profile` → surface the same `ValueError`/
  `FileNotFoundError` conditions the CLI already handles, mapped to 404/400 — do not add new
  validation logic in the route beyond existing service exceptions.

**Smoke tests:**
- `curl -X POST localhost:8000/api/checklist -d '{"doc_key":"...","profile":"cybersecurity"}' -H 'Content-Type: application/json'`
- `curl -X POST localhost:8000/api/checklist/export -d '{"doc_key":"...","profile":"cybersecurity","format":"csv"}' -H 'Content-Type: application/json'`

---

## 6. UI Scope

**Foundation (prerequisite, no backend dependency):**
- `AppShell` + `SidebarNav` replacing the current top `NavBar`, with items: Search, Compare,
  Evidence, Checklists (disabled until WP-22.4, when the generate screen exists), Corpus, System.
- Rename `DocsView`/`/docs` route and label to Corpus/`/corpus`.
- `/corpus/:docId` — document metadata + quick-action links (Search this doc, Compare from
  here; Generate checklist link present but disabled until WP-22.5 lands).
- `/system` — health page from existing `/api/status`; StatusDot links here.
- Shared `SourceQuoteBlock` and `ProvenanceMeta` extracted from current result/detail UI and
  applied across Search, Compare, Evidence, Trace (visual consistency, no behavior change).

**Checklist screens (post-API):**
- `/checklists` — `DocPicker` + `ProfilePicker` (default `cybersecurity`, options from
  `GET /api/profiles`) + Generate button. Calls `POST /api/checklist`; on success navigates
  to `/checklists/:docId?profile=<profile>`.
- `/checklists/:docId?profile=<profile>` — `ChecklistTable` (columns grouped
  Locate/Ask/Record/Verify/Trace), `ReviewFlagBadge` per flagged row, flagged-only
  client-side filter (pure `.filter()` over the existing `requires_human_review` boolean —
  no new logic), `ExportButtonGroup` wired to `POST /api/checklist/export`. Both `docId` and
  `profile` are read from the URL so the page is refresh/bookmark/share safe.
- Fields `status` and `assessor_notes` render **read-only** (plain text display, not inputs).

**Not in Phase 22 UI scope:** ingest forms, profile editor, job history, export history,
inline editing of any checklist field.

---

## 7. Work Packages

### WP-22.1 — UI Foundation: Shell, Nav, Corpus Rename

**Goal:** Sidebar navigation shell; rename Docs → Corpus. No backend change.

**Tasks:**
- Add `AppShell` and `SidebarNav` components.
- Replace top `NavBar` usage across all views.
- Rename `/docs` route and nav label to `/corpus` / "Corpus".
- Add "Checklists" nav item, disabled/greyed with a tooltip ("Available after checklist screens ship") until
  WP-22.4 lands.

**Gate:** All existing views (Search, Trace, Compare, Evidence, Corpus) render through the new
shell with no regressions. No new API calls introduced. Existing frontend unit tests pass.

**Breadcrumb rule (implement from the start):** Do not hardcode `Search / Trace`. The
breadcrumb on drill-in routes must derive the parent label from `from` route state where
available; fall back to `Trace` with no parent label when no `from` state is present. Trace
is reachable from Search, Compare, Evidence, and (future) Checklist — each must produce the
correct crumb.

---

### WP-22.2 — Corpus Document Detail + System Page

**Goal:** `/corpus/:docId` and `/system`, both over existing endpoints only.

**Tasks:**
- Add `domain_profile` to `docs_service.list_docs()`: read from the first JSONL record using
  `req.get("domain_profile") or "cybersecurity"` (same null-safe fallback pattern from Phase
  20 — pre-Phase-20 records correctly return `"cybersecurity"`). Expose as `"profile"` in
  each document dict in the `/api/docs` response. `list_docs()` currently reads the first
  record for `source_pdf` only; this change extends that read to also capture `domain_profile`.
- Add `/corpus/:docId`: metadata (name, req count, profile, date, mode) filtered client-side
  from `/api/docs`; quick-action links (Search this doc, Compare from here; Generate checklist
  link present but disabled).
- Add `/system`: render `/api/status` fields via `SystemHealthPanel`; manual refresh button;
  `StatusDot` becomes a link to `/system`.
- Extract `SourceQuoteBlock` / `ProvenanceMeta` only where it reduces duplication safely. Do not
  force a broad visual refactor into this WP.

**Gate:** `/corpus/:docId` and `/system` work off `/api/docs` and `/api/status` data. Corpus
table shows a "Profile" column populated from the `domain_profile` field added to `list_docs()`
in this WP; pre-Phase-20 documents show `"cybersecurity"`. Visual consistency confirmed across
the four existing views. No checklist-layer changes made.

---

### WP-22.3 — Checklist API

**Goal:** Add `POST /api/checklist` and `POST /api/checklist/export` as thin wrappers.

**Tasks:**
- Add `api/routes/checklist.py`: `POST /api/checklist` → `checklist_service.generate()`.
- Add `POST /api/checklist/export` → `pipeline/checklist_export.py` `to_csv`/`to_json`/
  `to_markdown`, selected by a `format` field. Return `Content-Disposition: attachment` so the
  browser treats the response as a file download. The frontend triggers download via
  `fetch()` + `response.blob()` + `URL.createObjectURL()` + programmatic anchor click — not
  `window.location.href`.
- Add `GET /api/profiles` → scan the `profiles/` directory and return `{"profiles": [...]}`.
  No request body. Unknown profile in checklist endpoints maps `FileNotFoundError` → 400.
- Define typed Pydantic request models for checklist endpoints. Do not rename or strip
  service-layer fields.
- Register all three routes in `api/app.py`; confirm Swagger reflects them.

**Gate:**
- `curl` smoke tests for both endpoints return valid responses for a known-good `doc_key`.
- Unknown `doc_key` / invalid `profile` return clear 4xx errors matching existing service
  exception behavior.
- `GET /api/profiles` returns at minimum `["cybersecurity"]`.
- Export endpoint returns a file download (correct `Content-Disposition: attachment` header),
  not a JSON body.
- `reqbot checklist` CLI behavior is unchanged.
- Swagger at `/api-docs` reflects all three new endpoints.

---

### WP-22.4 — Checklist Generate Screen

**Goal:** `/checklists` — pick document + profile, generate.

**Tasks:**
- Add `DocPicker` (reuse pattern from Compare's doc dropdowns) and `ProfilePicker` populated
  from `GET /api/profiles`, defaulting to `cybersecurity`.
- Generate button calls `POST /api/checklist`; on success, navigate to
  `/checklists/:docId?profile=<profile>`. Both values come from the form inputs — never
  derive them from the response envelope.
- Loading state: "Generating checklist..." spinner. Error state: shared `ErrorBanner`.
- Enable the "Checklists" nav item (still disabled/tooltipped since WP-22.1).

**Gate:** User can pick a document and profile and reach a checklist result (even if
WP-22.5's table isn't polished yet — a raw envelope render is acceptable as an interim check).
No client-side computation of any checklist field.

---

### WP-22.5 — Checklist Preview + Export

**Goal:** `/checklists/:docId` — full table view and export.

**Tasks:**
- The preview route reads both `docId` and `profile` from the URL
  (`/checklists/:docId?profile=<profile>`) and refetches via `POST /api/checklist` on load.
  Refresh and direct links must work without router state.
- Add `ChecklistTable`: columns grouped Locate (`source_ref`, `section_title_path`,
  `page_refs`) / Ask (`source_quote`, `audit_question`) / Record (`status`, `assessor_notes`,
  read-only) / Verify (`requires_human_review`, `review_reasons`, `confidence`) / Trace
  (`checklist_item_id`, `requirement_ids`, `domain_tags`). The table container must use
  `overflow-x: auto` — the page body must not scroll horizontally. `source_quote` cells can
  exceed 300 characters; do not rely on truncation to prevent page-level overflow.
- Add `ReviewFlagBadge` on flagged rows; add flagged-only toggle (client-side `.filter()` on
  `requires_human_review` only).
- Add `ExportButtonGroup` (CSV/JSON/Markdown) wired to `POST /api/checklist/export`; trigger
  browser download of the returned content — no client-side formatting.
- Empty state: "No requirements had sufficient provenance to generate checklist items" (or
  equivalent, matching why `items` may be empty).
- Enable "Generate checklist" link from `/corpus/:docId` (added disabled in WP-22.2).

**Gate:**
- Checklist renders with correct column grouping for a known-good document.
- Exported CSV/JSON/Markdown from the browser are content-equivalent to CLI output for the
  same `doc_key`/`profile`/`format`, ignoring harmless transport differences such as headers,
  trailing newline, or JSON whitespace.
- Flagged rows are visually distinct; flagged-only filter works.
- No inputs exist for `status`/`assessor_notes` — display only.

---

### WP-22.6 — Integration Gate

**Goal:** Confirm the full browser checklist workflow works end-to-end without regressing any
existing capability.

**Demo walkthrough (must complete without CLI assistance):**
1. Open the app; sidebar shows Search, Compare, Evidence, Checklists, Corpus, System.
2. Browse Corpus; open a document detail page; use "Search this doc."
3. Open System page; confirm health data renders.
4. From a document detail page, click "Generate checklist."
5. Pick a profile, generate; land on the preview screen.
6. Toggle "flagged only"; confirm filtering works.
7. Export CSV, then JSON, then Markdown; confirm each downloads and is content-equivalent to
   CLI-generated output for the same inputs.
8. Confirm Search, Trace, Compare, Evidence still work exactly as before (Phase 19 gates).

**Gate:**
- Demo walkthrough above completes without errors or workarounds.
- `reqbot checklist` CLI command is unaffected.
- No regression in Phase 18/19/21 functionality or tests.
- No new pip/npm dependency was introduced without prior approval.

---

## 8. Test Expectations

- **API layer:** unit tests for `api/routes/checklist.py` covering happy path, unknown
  `doc_key`, invalid `profile`, and all three export formats — mirroring the existing
  `test_cli_checklist.py` pattern but for the route layer.
- **Service/export layer:** no new tests required — Phase 21's 240 passing tests already cover
  `checklist_service.py` and `checklist_export.py`; Phase 22 must not modify their behavior.
- **Frontend:** component tests for `ChecklistTable` (column grouping, flagged-row rendering)
  and `ExportButtonGroup` (correct format param sent); route-level smoke test for
  `/checklists` and `/checklists/:docId`.
- **Regression:** full existing frontend test suite and `pytest tests/unit/` must pass
  unchanged after each WP.
- **Manual smoke:** `curl` commands from Section 5 re-run after WP-22.3; full demo walkthrough
  re-run at WP-22.6.

---

## 9. Success Gate

Phase 22 is complete when:

1. A non-technical user can generate, preview, and export a checklist entirely from the
   browser, with no CLI use required.
2. Exported CSV/JSON/Markdown from the browser are content-equivalent to CLI-generated output
   for the same document/profile/format, ignoring harmless transport differences such as
   headers, trailing newline, or JSON whitespace.
3. The sidebar-based navigation foundation (Corpus rename, `/corpus/:docId`, `/system`) is in
   place and used by the checklist screens.
4. No checklist field is editable in the browser; `status`/`assessor_notes` remain read-only.
5. `reqbot checklist`, `reqbot ask`, `reqbot trace`, `reqbot compare`, `reqbot evidence`, and
   `reqbot docs` all work exactly as before — zero CLI regressions.
6. Killing `reqbot serve` has zero effect on any CLI command.
7. No new pip/npm dependency was introduced without explicit prior approval.

---

## 10. Explicit Risks / Guardrails

- **Do not generate or format checklist content in the frontend.** Every field, every export
  format, comes from `checklist_service.py` / `checklist_export.py` unmodified.
- **Do not add editable `status`/`assessor_notes` inputs.** This is blocked on the
  regeneration/merge design named in TODO #17 — a real persistence problem, not a Phase 22
  concern. Read-only display only.
- **Do not build ingest UI, job history, or export history.** Out of scope regardless of how
  small it seems once the checklist screens exist.
- **Do not add XLSX export.** Requires an unapproved dependency (`openpyxl`/`XlsxWriter`);
  stays CSV/JSON/Markdown only.
- **Do not add profile management UI.** `ProfilePicker` must use `GET /api/profiles` (added
  in WP-22.3) to populate its options — do not hardcode profile names. Create/edit/delete
  profile UI is out of scope.
- **Do not let the API route call the CLI.** `api/routes/checklist.py` calls
  `checklist_service.generate()` and `pipeline/checklist_export.py` directly, in-process —
  never subprocess or shell out to `reqbot`.
- **Do not reshape API responses for frontend convenience.** If the frontend needs a field the
  service doesn't return, add it to the service response additively — don't compute it in the
  route or in React.
- **Do not skip WP gates.** One work package at a time; Codex/Gemini review after each before
  proceeding, per existing project convention.
- **Do not introduce a new frontend framework or state library.** Stay on React + TypeScript +
  Tailwind + react-router.
