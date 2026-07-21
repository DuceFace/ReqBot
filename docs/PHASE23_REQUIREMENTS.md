# ReqBot — Phase 23: Checklist Output Polish + Trust Hardening

**Status:** Draft
**Date:** 2026-07-20
**Preceded by:** Phase 22 (Browser Checklist Workflow — COMPLETE)
**Followed by:** Phase 24 candidate: MCP Tool Surface

---

## 1. Phase Framing

Phase 22 delivered a working browser checklist workflow: generate, preview, and export
CSV/JSON/Markdown. A non-CLI user can now create a checklist from the browser.

**Phase 23 should make the current product easier to trust and easier to try.** ReqBot does
not yet have real user adoption, so this phase should avoid advanced workflow features that
only matter after assessors are already living in generated checklists. Instead, Phase 23
focuses on the parts that help someone evaluate the MVP today:

1. **Checklist preview polish** — the browser checklist table needs reliable horizontal
   scrolling, and export should be a single scalable dropdown instead of several flat buttons.
2. **XLSX export** — Excel/LibreOffice output is the most practical assessor-facing format.
   CSV is portable, but a polished workbook is easier for normal users to inspect and use.
3. **Extraction quality warnings** — ReqBot should make extraction problems visible instead
   of letting downstream checklist/retrieval behavior look mysteriously wrong.
4. **Profile skip-section filtering** — profiles already define `skip_sections`, but the
   chunking pipeline does not consume them. Threading that field through can reduce avoidable
   noise from glossaries, references, acronym lists, and similar non-requirement sections.
5. **Step C truncation recovery flag** — when the LLM output is truncated and the existing
   recovery path activates, tag affected records with `recovered_truncated: true` so
   downstream stages can surface a caution signal without requiring new recovery logic.

Audit-question generation and assessor-note preservation remain useful ideas, but they are
not the right next build target. Audit questions are compute-heavy and can amplify noisy
requirements. Note preservation matters after users are actively annotating and regenerating
checklists. Both stay in the backlog until there is stronger evidence they are worth building.

MCP remains strategically important and is a strong Phase 24 candidate. It is not included in
Phase 23 so this phase can stay focused on making current ReqBot outputs more usable and more
trustworthy.

---

## 2. Goals

- Fix the checklist preview table so horizontal scrolling works without text-drag workarounds.
- Replace the flat export buttons with a single export dropdown that can hold additional
  formats cleanly.
- Add XLSX checklist export from the CLI and browser using the same backend export path.
- Add lightweight extraction-quality warnings/flags for conditions that can undermine trust in
  downstream requirements, retrieval, and checklist output.
- Implement profile-based skip-section filtering in the chunking path, using existing profile
  configuration rather than hardcoded section names.
- Tag raw extraction records with `recovered_truncated: true` when Step C's existing
  truncation recovery path activates; do not set the flag on normal extractions.
- Keep CLI, API, and GUI behavior aligned through the service/export/pipeline layers.
- No regressions to Phase 18/19/21/22 behavior.

---

## 3. Non-Goals

Explicitly out of scope for Phase 23:

- Audit-question generation.
- Evidence-to-request, test-step, pass-criteria, or failure-indicator generation.
- Editable `status` or `assessor_notes` fields in the browser.
- Assessor-note preservation or merge-on-regeneration.
- Server-side persistence of checklist runs or assessor annotations.
- MCP tool surface. Candidate for Phase 24.
- Profile management UI.
- Ingest UI, upload forms, job queue, or browser-triggered pipeline runs.
- Authentication, multi-user, hosted/SaaS deployment.
- Full OCR support.
- OSCAL output.
- Retrieval quality experiments such as HyDE, reranker, HyPE, or multi-vector indexing.
- Any new pip/npm dependency not listed in Section 4.

---

## 4. Approved New Dependencies

- **`openpyxl`** — approved only for XLSX write support in WP-23.2.

No other pip or npm dependency is approved in this phase without explicit discussion. In
particular:

- Do not add a frontend menu/dropdown package for WP-23.1.
- Do not add OCR dependencies for WP-23.3. Low-text detection is warning-only.

---

## 5. Architecture Rules

All Phase 18/19/20/21/22 architecture rules carry forward:

1. **Frontend is a client only.** Checklist generation, export formatting, review reasons,
   confidence handling, extraction warnings, and skip-section behavior live in services or
   pipeline code. React renders returned data and sends user requests.
2. **API routes are thin.** `api/routes/*` validates request shape, calls services/export
   functions, maps known exceptions to HTTP responses, and returns results. No checklist or
   extraction business logic lives in the route layer.
3. **CLI and GUI share backend paths.** If the browser can export XLSX, the CLI must call the
   same export function.
4. **No client-side export formatting.** React never builds CSV, Markdown, JSON, or XLSX
   checklist content.
5. **Profiles drive domain assumptions.** Skip-section names must come from the active profile,
   not from new hardcoded cybersecurity-specific constants.
6. **Quality warnings are warnings, not silent behavior changes.** If the pipeline detects a
   potential issue, expose it in artifacts and logs where useful. Do not discard content unless
   the WP explicitly says so.
7. **One WP at a time.** Get Codex/Gemini review after each WP before proceeding.

**Safety test:**
- Can you kill the API server and still run `reqbot checklist` normally? -> **Yes**
- Can you change checklist UI presentation without touching checklist generation/export
  logic? -> **Yes**
- Do CLI and API call the same service/export functions for the same checklist operation?
  -> **Yes**
- Do extraction warnings preserve traceability instead of hiding source data? -> **Yes**
- Does skip-section filtering use the active profile instead of hardcoded section names?
  -> **Yes**

If any answer becomes no, the design has drifted.

---

## 6. Work Packages

### WP-23.1 — Checklist Preview Polish

**Goal:** Improve the existing browser checklist preview without backend changes.

**Scope:**
- Fix horizontal scrolling for `ChecklistTable`.
- Replace the current flat export buttons with a single dropdown/popup menu.
- Keep all export calls routed through the existing API client and backend export endpoint.

**Horizontal scroll requirements:**
- The checklist table must scroll horizontally inside its own container on a normal laptop
  viewport.
- The page body must not horizontally scroll.
- Users must not need to drag-select table text to reach hidden columns.
- The scrollbar or scroll affordance must remain discoverable on common browser/OS
  combinations where overlay scrollbars are hidden by default.
- The fix should address layout containment in the smallest responsible place, likely
  `ChecklistPreviewView`, `ChecklistTable`, or `AppShell`. Avoid broad visual redesign.

**Export dropdown requirements:**
- Replace the three visible export buttons with one `Export` control.
- The menu contains CSV, JSON, Markdown initially; XLSX is added in WP-23.2.
- The dropdown uses existing React state and Tailwind classes only.
- The menu closes after selection, on outside click or blur where practical, and on `Escape`.
- Loading/error behavior remains equivalent to WP-22.5.
- Disabled/loading states must prevent duplicate export requests.
- Keep the export implementation server-side. This WP must not introduce client-side
  formatting.

**Tests / verification:**
- Frontend build passes.
- Existing frontend tests pass, if present.
- Manual browser smoke:
  1. Open `/checklists/:docId?profile=cybersecurity`.
  2. Confirm the table scrolls horizontally via scrollbar/trackpad/mouse wheel gesture.
  3. Confirm the body itself does not scroll horizontally.
  4. Confirm each dropdown option still downloads the same server-produced file as WP-22.5.

**Gate:** no backend changes; export behavior unchanged; checklist table is usable on an
average-width screen.

---

### WP-23.2 — XLSX Export

**Goal:** Add Excel workbook export through the same service/export path used by CLI and GUI.

**Backend (`pipeline/checklist_export.py`):**
- Add an XLSX export function that returns `bytes`.
- Use `openpyxl`; do not hand-roll XLSX files.
- Preserve the existing checklist column order and Locate / Ask / Record / Verify / Trace
  grouping.
- Workbook requirements:
  - One worksheet named `Checklist`.
  - Group header row and column header row.
  - Freeze panes below the header rows and after the core locate/ask columns, if practical.
  - Auto-filter enabled for the column header row.
  - Wrapped text for `source_quote`, `audit_question`, and notes columns.
  - Top alignment for all data cells.
  - Reasonable fixed column widths so the workbook opens usefully without manual resizing.
  - Status column data validation using the checklist schema's allowed status values.
  - Flagged rows visually distinct but not loud.
  - Clear group-header styling for Locate / Ask / Record / Verify / Trace.
  - Formula-injection protection equivalent to the CSV export path for every user/source text
    cell that could be interpreted as a formula by spreadsheet software.

**API (`api/routes/checklist.py`):**
- Extend the checklist export format enum to include `xlsx`.
- Return XLSX as binary content.
- Use content type:
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- Return `Content-Disposition: attachment` with a deterministic `.xlsx` filename.
- Keep the route thin: call `checklist_service.generate()` and the XLSX export function.

**CLI (`cli/reqbot.py`):**
- Add `--format xlsx`.
- Write binary output correctly when `--output` is provided.
- If stdout output for binary formats is not appropriate, fail clearly and require
  `--output` for `xlsx`.

**Frontend:**
- Add XLSX to the export dropdown from WP-23.1.
- Add `xlsx` to the frontend export format type.
- Use the same fetch/blob download pattern from WP-22.5.
- Do not inspect or build workbook contents client-side.

**Tests / verification:**
- Unit tests for XLSX export:
  - workbook opens with `openpyxl.load_workbook`;
  - expected sheet name;
  - expected column order;
  - freeze panes set;
  - auto-filter set;
  - status data validation exists;
  - formula-like source text is escaped/protected;
  - flagged row styling exists for flagged sample item.
- API tests:
  - `format: "xlsx"` returns binary response with correct content type/disposition;
  - unsupported format still returns 400;
  - existing CSV/JSON/Markdown export tests still pass.
- CLI tests:
  - `reqbot checklist --format xlsx --output <file>` writes a readable workbook;
  - existing CSV/JSON/Markdown CLI behavior unchanged.
- Frontend build passes.

**Gate:** browser and CLI XLSX exports are content-equivalent for the same document/profile,
and all existing export formats still work.

---

### WP-23.3 — Pipeline Structural Guardrails

**Goal:** Add lightweight, deterministic pipeline checks for structural conditions that can make
downstream requirements/checklists less trustworthy. This is a trust-hardening WP, not an OCR
or LLM-recovery rewrite.

**Scope:**

1. **Low-text page detection / OCR warning**
   - Detect pages with unusually low extracted text counts after Step A parsing.
   - Surface a warning that the page may be scanned/image-heavy or otherwise OCR-dependent.
   - Do not add OCR. Do not fail ingest solely because a low-text page exists.

2. **Page number contiguity validation**
   - Validate that Step A page records are monotonically increasing with no gaps or duplicates
     before Step B chunking. Do not assert on the starting page number — some PDFs begin at 0
     or have unconventional front-matter numbering.
   - Missing or duplicate page numbers produce a clear warning; ingest continues.

3. **Chunk overlap guard**
   - Raise a ValueError when overlap is greater than or equal to chunk size in Step B.
   - This prevents an infinite-loop class of bug if a bad caller/config value is introduced.

**Out of scope for WP-23.3:**
- Truncated JSON recovery flag (Step C LLM output tagging) — deferred; see Section 9.
- Ollama `finish_reason` / token metadata investigation — deferred with truncated JSON work.

**Output requirements:**
- Warnings are visible in logs/CLI output; no new artifact files required.
- Do not break existing JSONL consumers. No schema changes in this WP.
- Low-text warnings must not become compliance findings or checklist review reasons unless a
  later WP explicitly defines that behavior.
- Keep warnings domain-neutral. These are structural/extraction-quality checks, not
  cybersecurity vocabulary checks.

**Tests / verification:**
- Unit tests for low-text detection thresholds using synthetic page records.
- Unit tests for page contiguity success/failure cases (gaps, duplicates, non-standard start).
- Unit tests for overlap guard rejecting invalid chunk settings.
- Existing ingest/checklist/retrieval tests continue to pass.

**Gate:** quality issues are easier to see, but normal valid documents still ingest without
behavioral regression.

---

### WP-23.4 — Profile-Based Skip-Section Filtering

**Goal:** Make the existing `skip_sections` profile field affect chunking so non-requirement
sections can be filtered by profile instead of hardcoded logic.

**Context:**
Phase 20 introduced profile files with `skip_sections`, but the chunking pipeline does not yet
consume that field. This was identified earlier as useful behavior that should be implemented
as a planned feature because it changes extraction behavior.

**Scope:**
- Thread the active profile's `skip_sections` list into Step B/chunking.
- Detect section headings that match configured skip-section names.
- Exclude the skipped section's body from requirement extraction chunks, while preserving
  enough logging/metadata for users to understand what was skipped.
- Keep existing structural ToC filtering separate from profile skip-section filtering.

**Design constraints:**
- Section names come from the active profile only.
- Matching should be case-insensitive and whitespace-normalized.
- Do not hardcode cybersecurity-specific skipped sections in `chunk_text.py`.
- Do not skip arbitrary text merely because a word appears inside a paragraph. This should be
  section-heading based, not substring filtering across body text.
- If section hierarchy boundaries are ambiguous, choose the conservative behavior that avoids
  accidentally dropping real requirements.
- Emit a summary such as skipped section names and approximate page/chunk ranges where
  practical.

**Risk note:**
This WP can become large if heading detection is weak. Stop and convert WP-23.4 into a
design/spike instead of forcing a risky behavior change if any of the following are true:
- Implementation requires touching hierarchy or ancestry logic across more than one pipeline
  step.
- The heading-detection approach requires non-additive schema changes to existing JSONL
  artifacts.
- Reliable section boundary detection requires restructuring how `chunk_text.py` reads its
  input.

**Tests / verification:**
- Unit tests with synthetic structured text covering:
  - exact heading match;
  - case-insensitive match;
  - heading with numbering/punctuation;
  - body text mentioning a skipped term without being skipped;
  - skipped section ending when the next peer/higher heading starts;
  - no configured skip sections.
- Integration smoke on at least one real-ish document sample confirming glossary/reference-like
  content is skipped and normal requirement sections remain.
- Existing chunking and extraction tests continue to pass.

**Gate:** configured skip sections reduce obvious non-requirement noise without dropping normal
requirement sections.

---

### WP-23.5 — Step C Truncation Recovery Flag

**Goal:** When Step C's existing truncated JSON recovery path activates, tag the affected raw
extraction records with `recovered_truncated: true` so downstream stages can preserve a
caution signal. This is a flag-only WP — no new recovery algorithm.

**Background:**
Step C already contains a fallback that attempts to salvage a truncated JSON array from partial
LLM output. Currently that recovery is silent: if it succeeds, the records proceed identically
to non-truncated records. This WP makes the recovery visible in the output artifacts.

**In scope:**
- Detect the existing recovery code path in `pipeline/llm_extract_requirements.py`.
- Add `recovered_truncated: true` to each record produced from a recovered (truncated) chunk.
- Normal extraction records must not carry `recovered_truncated` or must carry
  `recovered_truncated: false` — whichever is less invasive to downstream consumers.
- Preserve the flag through `pipeline/parse_and_normalize.py` if the change is purely
  additive (pass-through of an unknown field); do not propagate if it requires schema changes.
- Unit tests covering: recovery path sets the flag; normal path does not set the flag.

**Out of scope:**
- New truncation recovery algorithm or retry logic.
- Ollama `finish_reason` / token metadata investigation.
- Re-prompting or multi-attempt extraction.
- Checklist review reasons driven by `recovered_truncated`.
- Confidence score changes.
- Any UI or API surface for the flag in this WP.

**Output requirements:**
- `recovered_truncated: true` appears in the raw extraction JSONL for affected records.
- No behavioral change to the extraction process itself; only the output record is augmented.
- No new pip dependencies.

**Tests / verification:**
- Unit tests with synthetic chunk data exercising the recovery branch and the normal branch.
- Confirm flag is present on recovered records and absent (or false) on normal records.
- Existing Step C and normalization tests continue to pass.

**Gate:** `recovered_truncated` flag appears in affected raw records; no regression to
extraction behavior or downstream pipeline steps.

---

### WP-23.6 — Integration Gate

**Goal:** Confirm all Phase 23 features work end-to-end and no Phase 18/19/21/22 capability
has regressed.

**Prerequisites:**
- Re-ingest or use a known-good processed corpus with current Phase 21+ profile metadata.
- Confirm checklist review noise is explainable. If nearly every item is flagged for missing
  domain tags, low confidence, or missing `source_ref`, diagnose the processed data before
  declaring Phase 23 complete.

**Demo walkthrough:**
1. Open ReqBot browser UI.
2. Generate a checklist for a known document/profile.
3. Confirm the preview table scrolls horizontally inside its container.
4. Use the export dropdown to download CSV, JSON, Markdown, and XLSX.
5. Open XLSX in Excel or LibreOffice and confirm:
   - header rows are frozen;
   - filters are enabled;
   - source quotes wrap;
   - status dropdown exists;
   - flagged rows are visually distinct.
6. Confirm CSV/JSON/Markdown exports still match Phase 22 behavior.
7. Confirm `reqbot checklist --format xlsx --output <file>` writes a valid workbook.
8. Run or inspect an ingest where quality warnings should trigger; confirm warnings are visible
   and valid documents still process normally.
9. If a truncated-recovery ingest is available, confirm `recovered_truncated: true` appears in
   the raw extraction JSONL for affected records and is absent from normal records.
10. Run or inspect an ingest with configured `skip_sections`; confirm skipped sections are
    logged and ordinary requirement sections remain.
11. Confirm `reqbot checklist`, `reqbot ask`, `reqbot trace`, `reqbot compare`,
    `reqbot evidence`, `reqbot docs`, and `reqbot serve` still work.

**Gate:** all implemented features pass, all unit tests pass, frontend build passes, and no
unapproved dependencies were introduced.

---

## 7. Test Expectations

Baseline:

- All Phase 22 unit tests continue to pass after each implementation WP.
- Frontend TypeScript/build checks continue to pass after each frontend WP.
- Manual smoke is required after each WP before proceeding.

WP-specific expectations:

- **WP-23.1:** frontend build; browser smoke for scroll containment and dropdown export.
- **WP-23.2:** unit/API/CLI tests for XLSX behavior; regression tests for existing export
  formats; workbook inspection with `openpyxl`.
- **WP-23.3:** unit tests for low-text warning, page contiguity validation (gaps, duplicates,
  non-standard start), and chunk overlap guard. Warning-only; no schema changes.
- **WP-23.4:** unit tests for profile-driven skip-section matching and conservative boundary
  handling. Integration smoke on representative document text.
- **WP-23.5:** unit tests for `recovered_truncated` flag — recovery path sets the flag;
  normal extraction path does not. Flag preserved (or safely absent) through parse/normalize.
- **WP-23.6:** full regression smoke across CLI/API/browser.

---

## 8. Success Gate

Phase 23 is complete when:

1. Horizontal checklist table scrolling is visible/discoverable and functional on an
   average-width screen without text-drag workarounds.
2. A single export dropdown replaces the flat export buttons.
3. CSV, JSON, Markdown, and XLSX download correctly from the browser.
4. `reqbot checklist --format xlsx --output <file>` produces a valid Excel workbook.
5. Browser XLSX export and CLI XLSX export are content-equivalent for the same
   document/profile.
6. Existing CSV/JSON/Markdown exports are not regressed.
7. Extraction-quality warnings exist for the WP-23.3 checks and do not break normal ingest.
8. Profile-based skip-section filtering uses active profile config and does not hardcode domain
   section names.
9. `recovered_truncated: true` is set on raw extraction records when Step C's existing recovery
   path activates; it is not set on normal extractions.
10. All Phase 18/19/21/22 CLI/API/GUI capabilities continue to work.
11. No new pip/npm dependency other than `openpyxl` was introduced.

---

## 9. Deferred After Phase 23

These remain valuable, but they are not part of Phase 23 unless explicitly re-scoped:

- MCP tool surface. Strong Phase 24 candidate.
- Audit-question generation.
- Assessor-note preservation and browser editing.
- Evidence-to-request generation.
- Test-step/pass-criteria/failure-indicator generation.
- XLSX import or round-trip editing.
- Server-side saved checklist runs.
- Profile management UI.
- Ingest UI and job history.
- Runtime API response validation.
- OCR support beyond low-text warnings.
- **Ollama finish_reason / token metadata** — investigate whether Ollama exposes
  `finish_reason` or token-count metadata that could detect truncation upstream of the
  JSON recovery step. Explicitly out of scope for WP-23.5; schedule separately if valuable.
