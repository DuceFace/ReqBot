# ReqBot — Phase 23: Checklist Assessor Workflow

**Status:** Shell / Draft — Codex to flesh out
**Date:** 2026-07-20
**Preceded by:** Phase 22 (Browser Checklist Workflow — COMPLETE)
**Followed by:** TBD

---

## 1. Phase Framing

Phase 22 delivered a working browser checklist workflow: generate, preview, and export
(CSV/JSON/Markdown). An assessor can now use the browser end-to-end without the CLI.

**Phase 23 makes the workflow production-usable for a real assessor.** It addresses four gaps
identified in the Phase 22 integration gate:

1. **Preview polish** — the checklist table overflows without a visible scrollbar on some
   browser/OS combinations; the three flat export buttons should become a single dropdown.
2. **XLSX export** — assessors live in Excel. CSV is portable, but Excel workbooks with frozen
   headers, column filters, and wrapped cells are what auditors actually use.
3. **Audit question generation** — `audit_question` has been blank since Phase 21. An opt-in
   LLM step can generate plain-language audit questions grounded in `source_quote`.
4. **Assessor note preservation** — re-running generate for a document already annotated
   silently resets all `assessor_notes` and `status` fields. Deterministic `checklist_item_id`
   makes merge-on-regeneration possible.

Phase 23 does not add new document types, ingest UI, profile management, authentication, or
MCP surface. It deepens the checklist path only.

---

## 2. Goals

- Fix the checklist preview table so horizontal scrolling works without text-drag workarounds.
- Replace three flat export buttons with a single dropdown that accommodates future formats.
- Assessors can export a checklist as an Excel workbook (XLSX) from the browser and CLI.
- Assessors can generate checklists with plain-language audit questions via an opt-in flag.
- Re-running generate for a previously exported document offers to merge saved
  `assessor_notes` and `status` back in by `checklist_item_id` rather than silently resetting.
- No CLI regressions; all Phase 18/19/21/22 tests pass after each WP.

---

## 3. Non-Goals

Explicitly out of scope for Phase 23:

- Editable `status`/`assessor_notes` fields in the browser (read-only display only).
- Profile management UI (create/edit/delete profiles).
- Ingest UI, upload forms, or browser-triggered pipeline runs.
- MCP tool surface.
- Authentication, multi-user, hosted/SaaS deployment.
- OCR support.
- OSCAL output.
- Retrieval quality experiments (HyDE, reranker, HyPE).
- Any new pip/npm dependency not listed in Section 4 below.

---

## 4. Approved New Dependencies

- **`openpyxl`** — XLSX write support for WP-23.2. No other new pip or npm dependencies
  without explicit discussion.

---

## 5. Architecture Rules

All Phase 18/19/21/22 architecture rules carry forward unchanged:

1. Frontend is a client only. Checklist logic lives in `services/checklist_service.py` and
   `pipeline/checklist_export.py`. The browser calls the API; it never formats or reshapes
   checklist content.
2. API routes are thin. No formatting, grouping, or filtering logic in `api/routes/`.
3. CLI and GUI share the same backend paths.
4. No new checklist logic in the route layer or React components.
5. One WP at a time. Codex/Gemini review after each before proceeding.

---

## 6. Work Packages

### WP-23.1 — Preview Polish

**Goal:** Fix horizontal scrolling on the checklist preview table and replace the three flat
export buttons with a single dropdown control.

**Horizontal scroll:**
- Diagnose why `overflow-x: auto` on `ChecklistTable`'s container div is not producing a
  visible scrollbar on average-width screens. Root cause is likely a parent container in
  `AppShell` or `ChecklistPreviewView` that is constraining width or hiding overflow.
- Fix so the table scrolls horizontally within its container without requiring text-drag.
- Page body must never scroll horizontally.

**Export dropdown:**
- Replace `ExportButtonGroup` (three flat buttons) with a single "Export ▾" control.
- Clicking opens a small menu/popover with the format options (CSV, JSON, Markdown — XLSX
  added in WP-23.2, so the dropdown must be extensible).
- Loading and error state behavior is unchanged from WP-22.5.
- No new npm dependency for the dropdown; implement with existing Tailwind + React state.

**Deliverables:** modified `ChecklistTable.tsx`, `ExportButtonGroup.tsx` (or replacement),
`ChecklistPreviewView.tsx` as needed. No backend changes.

---

### WP-23.2 — XLSX Export

**Goal:** Add Excel workbook export to the backend and expose it in the browser and CLI.

**Backend (`pipeline/checklist_export.py`):**
- Add `to_xlsx(items: list[ChecklistItem]) -> bytes` using `openpyxl`.
- Workbook features (Codex to specify exact implementation):
  - Frozen header rows (group row + column row).
  - Auto-filter on all columns.
  - Wrapped text in `source_quote` cells; all other cells top-aligned.
  - Data validation dropdown for `status` column (valid values from schema).
  - Clear visual separation of column groups (fill color matches table group headers).
  - Formula injection prevention consistent with `to_csv()` approach.

**API (`api/routes/checklist.py`):**
- Extend `POST /api/checklist/export` format enum to include `'xlsx'`.
- `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- `Content-Disposition: attachment; filename="checklist_<doc_key>.xlsx"`.

**CLI (`cli/reqbot.py` / `cmd_checklist`):**
- Add `--format xlsx` option.

**Frontend:**
- Add XLSX to the export dropdown introduced in WP-23.1.
- Add `'xlsx'` to `ChecklistExportRequest['format']` in `api/types.ts`.
- Filename handling: `.xlsx` extension extracted from `Content-Disposition` or derived from
  format, consistent with existing pattern in `api/client.ts`.

**Deliverables:** `pipeline/checklist_export.py`, `api/routes/checklist.py`, CLI, types, client,
export dropdown. Unit tests for `to_xlsx()` covering column order, formula injection
prevention, and freeze/filter configuration.

---

### WP-23.3 — Audit Question Generation (Opt-In)

**Goal:** Add an opt-in LLM step that generates a plain-language audit question for each
checklist item, grounded in `source_quote`. `audit_question` has been blank since Phase 21.

**Design constraints (non-negotiable):**
- Off by default. Must be explicitly requested via CLI flag and browser toggle.
- Generated questions are marked: a field such as `audit_question_generated: true` should
  accompany any LLM-produced question so downstream tooling can distinguish generated from
  human-authored text.
- Blank is better than an unsupported rephrase. If the LLM returns a low-quality or
  irrelevant question, the field stays blank; do not surface a bad question.
- `source_quote` remains primary. The audit question is a human-convenience rephrasing only;
  it must not be treated as a source of truth.
- Same Ollama model used elsewhere; no new model dependency.

**Codex to design:**
- Where in the pipeline this runs (new step in `checklist_service.generate()` or a separate
  enrichment pass).
- Prompt design and quality gate.
- CLI flag name and UI toggle placement.
- How `audit_question_generated` flows through the schema, API, and frontend table.

**Deliverables:** updated service/pipeline, CLI flag, API schema addition, frontend column
renders `audit_question` when present. Unit tests for the generation path.

---

### WP-23.4 — Assessor Note Preservation on Re-Generation

**Goal:** When a user re-generates a checklist for a document they have already annotated,
offer to merge saved `assessor_notes` and `status` back in by `checklist_item_id` rather
than silently resetting all assessor work.

**Design constraints:**
- Merge must be opt-in. Silent merging is not acceptable.
- `checklist_item_id` is deterministic from `requirement_id`, so a re-ingested document that
  produces the same requirement IDs will correctly re-associate notes.
- The merge source is a prior export file (CSV or JSON). ReqBot does not maintain a server-side
  database of assessor annotations.

**Codex to design:**
- Where the merge flag/option lives (CLI and browser).
- How the prior export is supplied (file path on CLI; upload or stored reference in browser).
- Schema for the merge operation.
- What happens when a `checklist_item_id` from the prior export no longer exists in the new
  checklist (item dropped from re-ingest) — warn, skip, or surface as orphaned.
- Unit tests for merge logic covering: exact match, dropped item, new item, changed item.

**Deliverables:** merge logic in service layer, CLI option, API endpoint or extension, browser
surface. Tests per above.

---

### WP-23.5 — Integration Gate

**Goal:** Confirm all Phase 23 features work end-to-end and no Phase 18/19/21/22 capability
has regressed.

**Prerequisites:**
- Re-ingest the corpus under the current Phase 21 profile to produce fresh enriched data.
  Validate that flagging noise (almost every item flagged for missing domain tags / low
  confidence / missing source_ref) resolves after re-ingest. If noise persists, diagnose
  before declaring the gate passed.

**Demo walkthrough (Codex to expand into a full checklist):**
1. Generate checklist; land on preview; scroll the table horizontally via scrollbar (not drag).
2. Use the export dropdown; download all four formats (CSV, JSON, Markdown, XLSX).
3. Open the XLSX in Excel or LibreOffice; confirm frozen headers, filters, and wrapped quotes.
4. Re-generate for a previously annotated document; confirm merge prompt appears; confirm
   notes survive.
5. Generate with audit questions enabled; confirm `audit_question` column populates.
6. Confirm all Phase 22 gates still pass.
7. Confirm CLI — `reqbot checklist --format xlsx` and `reqbot checklist --audit-questions`
   work as expected.

**Gate:** all above steps complete without errors. All unit tests pass. No new unapproved
dependencies.

---

## 7. Test Expectations

Codex to fill in detailed test expectations per WP. Baseline:

- All 255 Phase 22 unit tests continue to pass after each WP.
- New tests added per WP for: XLSX export (column order, freeze, filter, injection prevention);
  audit question generation (on/off behavior, blank-on-bad-quality gate); merge logic
  (match, orphan, new-item cases).
- Manual smoke after each WP before proceeding.

---

## 8. Success Gate

Phase 23 is complete when:

1. Horizontal scrollbar is visible and functional on the checklist preview table on an
   average-width screen without text-drag workarounds.
2. A single export dropdown replaces the three flat buttons; all four formats download correctly.
3. `reqbot checklist --format xlsx` produces a valid Excel workbook; browser XLSX export
   matches it content-equivalent.
4. `reqbot checklist --audit-questions` populates `audit_question` for each item; blank
   fallback when LLM output is low quality.
5. Re-generating a checklist for a previously annotated document offers merge; assessor notes
   and status survive for matching `checklist_item_id` values.
6. All Phase 18/19/21/22 CLI commands and unit tests pass unchanged.
7. No new pip/npm dependency other than `openpyxl` was introduced.
