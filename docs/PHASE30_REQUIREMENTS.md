# ReqBot Phase 30 — Frontend Test Infrastructure, SearchView Parity & Runtime Contract Validation

**Status:** Draft (drafted 2026-07-26; pending Codex/Gemini review before implementation starts)
**Date:** 2026-07-26
**Preceded by:** Phase 29 (Settings Screen & Evidence View UX)
**Followed by:** None currently planned — next work will be selected from the live backlog
(`docs/TODO_future_improvements.txt`) once Phase 30 closes.

---

## Status

This table is the live source of truth for Phase 30 WP status — update it here when a WP lands,
not in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-30.1 — Frontend Test Infrastructure | Not started |
| WP-30.2 — SearchView: Configurable Result Depth | Not started |
| WP-30.3 — Runtime Response Validation (Zod) | Not started |

---

## 1. Phase Framing

Three items, picked up together by explicit request rather than bundled for a shared theme the way
Phase 29's evidence-view items were:

- **Backlog item #19** (frontend test infrastructure) — Gemini has flagged the complete absence of
  a frontend test harness repeatedly across Phase 29's PRs (WP-29.1's `clampTopK`/`parseTopKParam`,
  WP-29.4's `buildDiff`/`extractErrorDetail`), each time correctly, each time declined with the same
  "no harness exists yet" answer. That answer stops being acceptable once there's a dedicated phase
  for it.
- **Backlog item #18** (SearchView's hardcoded `top_k: 20`) — found as a direct side-effect of
  WP-29.1: `EvidenceView.tsx` got a proper URL-persisted top-k control, but `SearchView.tsx` has the
  exact same gap at both of its `api.ask()` call sites and was explicitly out of WP-29.1's scope
  (which was scoped to backlog item #9, evidence view only).
- **Backlog item #8** (Zod runtime validation) — explicitly deferred out of Phase 29 (see that
  phase's Non-Goals) with three named revisit triggers: API surface growth, external clients
  consuming the API, or contract drift causing a real debugging issue. Phase 29 itself grew the API
  surface — `GET`/`POST /config` (WP-29.3) is a moderately complex new contract (nullable
  role-model fields with real-vs-inherited ambiguity, an `env_overridden` side-channel, an
  API-editable field subset that's narrower than the service layer's actual capability) — the first
  of backlog item #8's three named triggers. Doing this now, deliberately, beats waiting for trigger
  three (an actual production debugging session caused by drift).

**Sequencing is deliberate, not arbitrary:** WP-30.1 (harness) lands first so WP-30.2's new
URL-parsing logic ships with test coverage from day one instead of repeating the exact gap this
phase exists to close. WP-30.3 (Zod) lands last so its schemas can be validated against the test
harness WP-30.1 establishes, rather than being the first thing exercising an unproven harness.

---

## 2. Goals

- Give the frontend an actual test harness (Vitest + React Testing Library) and get it running in
  CI, closing a gap raised on essentially every Phase 29 PR.
- Close the `SearchView`/`EvidenceView` top-k parity gap so both search surfaces expose the same
  URL-persisted, clamped numeric control, using one shared implementation rather than two copies.
- Add runtime validation of API responses at the client boundary so a backend/frontend contract
  mismatch surfaces as a clear, visible failure instead of `undefined` silently propagating into the
  UI.

## 3. Non-Goals

- No full component-test backfill for the ~10 existing views that have zero coverage today
  (`SearchView`, `EvidenceView`, `SettingsView`, `CompareView`, etc.) — WP-30.1 is scoped to the
  existing *pure utility functions* only, per backlog item #19's own explicit scoping text. Whether
  to backfill component tests is a separate, later decision.
- No CI coverage-percentage gate — WP-30.1 adds a `test` job that runs and must pass; it does not
  add a coverage threshold that blocks a PR.
- No behavior change to `EvidenceView.tsx` beyond relocating `clampTopK`/`parseTopKParam` into
  shared code (WP-30.2) — same clamping, same defaults, same URL param name.
- No schema-driven codegen (generating `types.ts` from Zod schemas, or the reverse) — both stay
  hand-written and manually kept in sync, matching this codebase's existing "keep in sync with X"
  header-comment convention in `api/types.ts`.
- No CLI/API/MCP behavior changes anywhere in this phase — all three WPs are frontend/test-tooling
  only.

---

## 4. Work Packages

### WP-30.1 — Frontend Test Infrastructure

**Source:** Backlog item #19.

**Problem:** The frontend has zero test harness today — no `test` script in `package.json`, no
Vitest/Jest/React Testing Library anywhere, and no frontend job in `.github/workflows/ci.yml` (only
the `docker` job builds `frontend/dist` as part of the image; that's a build check, not a test run).
Gemini has flagged this as a finding on multiple Phase 29 PRs, most recently WP-29.1's
`clampTopK`/`parseTopKParam` and WP-29.4's `buildDiff`/`extractErrorDetail` having no unit coverage.

**Scope:**
- Add devDependencies: `vitest`, `@testing-library/react`, `@testing-library/jest-dom`,
  `@testing-library/user-event`, `jsdom`.
- Add a `test` block to `vite.config.ts` (Vitest reads its config from the same file — no separate
  config file needed): `environment: 'jsdom'`, a `setupFiles` entry pointing at a new
  `src/test/setup.ts` that imports `@testing-library/jest-dom`'s matchers.
- Add a `test` script to `package.json` (`vitest run` — non-watch, for CI and one-shot local runs).
- Write unit tests for the existing pure utility functions only:
  - `docValue`/`pageRange` in `frontend/src/utils/ui.ts`.
  - `clampTopK`/`parseTopKParam`, currently private to `frontend/src/views/EvidenceView.tsx` —
    export them so they're directly unit-testable rather than only exercised indirectly through
    full component rendering. **Note the ordering interaction with WP-30.2:** WP-30.2 relocates
    these two functions into `utils/ui.ts` as shared code (see that WP's scope) — WP-30.1 tests them
    at their current `EvidenceView.tsx` location; WP-30.2 is responsible for moving the tests along
    with the functions when it does that relocation, not leaving stale tests importing from the old
    path.
- Add a `frontend-test` job to `.github/workflows/ci.yml`: `actions/setup-node@v4` with
  `node-version: 20` (matching the `node:20-bookworm-slim` image the `Dockerfile`'s frontend build
  stage already pins), `npm ci`, `npm run test`, run from `frontend/`.

**Non-goals:**
- No component tests for any view — pure-function coverage only, per backlog item #19's own scope
  note ("not a mandate to backfill component tests for the ~10 existing views").
- No coverage threshold enforcement in CI.

**Tests/verification:**
- `npm run test` passes locally and in the new CI job.
- `npm run build` (`tsc && vite build`) still passes unaffected by the new devDependencies.
- The new CI job actually appears and passes on the PR that introduces it.

**Gate:** `npm run test` exists, covers `clampTopK`/`parseTopKParam` and `docValue`/`pageRange` with
real edge-case assertions (not just a happy-path smoke test), and runs in CI on every PR.

---

### WP-30.2 — SearchView: Configurable Result Depth

**Source:** Backlog item #18.

**Problem:** `frontend/src/views/SearchView.tsx` calls `api.ask()` with a fixed `top_k: 20` literal
at both of its call sites (the initial search effect and `handleGenerateAnswer`) — the exact pattern
WP-29.1 just fixed in `EvidenceView.tsx`. Not touched by WP-29.1, which was scoped to backlog item
#9 (evidence view specifically).

**Scope:**
- Relocate `clampTopK`/`parseTopKParam` from `EvidenceView.tsx` into `frontend/src/utils/ui.ts` as
  shared exports (alongside `docValue`/`pageRange`) — this codebase's established convention keeps
  shared pure functions there rather than duplicating identical logic across two view files.
  Update `EvidenceView.tsx` to import them from `utils/ui.ts`; this is a pure relocation, no behavior
  change to `EvidenceView.tsx` itself. Move WP-30.1's tests for these two functions to match the new
  location as part of this WP.
- Add the same `topK`/`urlTopK` state split `EvidenceView.tsx` uses (WP-29.1's pattern): `topK`
  tracks the number input, `urlTopK` tracks the committed URL value; they diverge while editing.
- Add a numeric top-k control to `SearchView`'s form, submitted together with the query (and doc
  filter) on form submit — same UX shape as `EvidenceView`'s.
- Update both `api.ask()` call sites (initial search effect, `handleGenerateAnswer`) to use the
  committed `urlTopK` instead of the `20` literal.
- Update `handleDocChange` to carry the committed `top_k` forward too — it currently rebuilds the
  URL params from scratch with only `q`/`doc` (`SearchView.tsx`'s `params.q`/`params.doc`
  construction), so changing the document filter would silently drop `top_k` back to the default 20
  the moment this control exists, unlike `EvidenceView.tsx` (which has no equivalent second filter
  control to lose the param against, so this failure mode is specific to `SearchView`, not a copy of
  something WP-29.1 already handled).

**Non-goals:**
- No change to the default top-k value (still 20) or to the 1–100 clamp range.
- No change to `EvidenceView.tsx`'s behavior beyond the import-path relocation above.

**Tests/verification:**
- Unit tests (via WP-30.1's harness) for `clampTopK`/`parseTopKParam` at their new shared location,
  covering both callers.
- Manual: loading `/search?...&top_k=N` respects `N` on both the initial search and Generate Answer.
- Manual: submitting a new query preserves/updates `top_k` in the URL correctly, mirroring
  `EvidenceView`'s existing behavior.

**Gate:** `SearchView` has a working top-k control using the exact WP-29.1-established pattern, with
the shared clamp/parse logic now living in one place (`utils/ui.ts`) instead of duplicated.

---

### WP-30.3 — Runtime Response Validation (Zod)

**Source:** Backlog item #8.

**Problem:** `frontend/src/api/types.ts`'s interfaces only protect at compile time — nothing catches
drift between the actual Python/FastAPI response shape and the TypeScript contract at runtime.
Phase 29 grew the API surface with a moderately complex new contract (`GET`/`POST /config`:
nullable role-model fields with a real-vs-inherited ambiguity the frontend already has to work
around, an `env_overridden` side-channel, an API-editable field subset narrower than what the
service layer actually accepts) — satisfying the first of backlog item #8's three named revisit
triggers ("API surface grows further").

**Scope:**
- Add `zod` as a frontend dependency.
- Define Zod schemas mirroring `api/types.ts`'s existing interfaces, starting with the newest/most
  complex contracts first (`ConfigResponse`, `EvidenceResponse`) rather than attempting full
  coverage in one pass — decide the remaining rollout order during implementation based on which
  types have actually drifted or caused confusion, not upfront guessing.
- Wire schema parsing into the relevant `api/client.ts` fetch wrappers as **fail-closed**: a schema
  mismatch throws, surfacing as a visible error through this codebase's existing
  `ErrorBanner`/`try`/`catch`/`setError` convention — same path a network failure already takes.
  Fail-open (log and pass the raw response through anyway) is ruled out, not left as an
  implementation choice: it would let `undefined` propagate into the UI exactly as it does today,
  directly contradicting this phase's own Goal of surfacing contract mismatches as clear, visible
  failures (Codex review, PR #136) — a warning nobody looks at isn't a fix for that. A `console.warn`
  alongside the thrown error is fine as an additional diagnostic aid, but does not replace the throw.
- Keep snake_case field naming in the Zod schemas, matching `types.ts`'s existing documented
  convention — no camelCase conversion layer.

**Non-goals:**
- No requirement to reach 100% schema coverage before this WP is considered done — start with
  `ConfigResponse`/`EvidenceResponse`, expand incrementally afterward.
- No schema-driven codegen — see Phase Non-Goals above.

**Tests/verification:**
- Unit tests asserting a known-good fixture response parses successfully against each new schema.
- Unit tests asserting a deliberately malformed fixture is caught (not silently accepted as valid).
- Manual: confirm real responses from a live `reqbot serve` still parse cleanly against the new
  schemas (no false-positive rejections of legitimate data).

**Gate:** At least `ConfigResponse` and `EvidenceResponse` are Zod-validated at the `api/client.ts`
boundary, and a schema mismatch fails closed — a tested, visible error, not a logged-and-ignored
pass-through.

---

## 5. Success Gate

Phase 30 is complete when:

1. All three WPs are merged.
2. Full unit suite passes (`pytest`); `ruff check .` passes; frontend build passes; the new frontend
   test suite passes and runs in CI.
3. `SearchView` has a working top-k control matching `EvidenceView`'s established pattern, with
   shared clamp/parse logic living in one place.
4. At least `ConfigResponse` and `EvidenceResponse` are runtime-validated at the API client
   boundary.
5. Backlog items #8, #18, and #19 in `docs/TODO_future_improvements.txt` are marked resolved.

---

## 6. Guardrails

1. One WP at a time — each lands as its own PR, reviewed before proceeding to the next, same
   cadence as Phases 27/28/29.
2. WP-30.1 stays scoped to harness setup + pure-function tests only — no mandate to backfill
   component tests for existing views; that's a separate, later decision (see Non-Goals).
3. WP-30.2 must relocate `clampTopK`/`parseTopKParam` into `utils/ui.ts` as shared code, not
   duplicate them into `SearchView.tsx` — matches this codebase's established convention for shared
   pure functions (`docValue`/`pageRange`).
4. WP-30.3 must fail closed on a schema mismatch (throw, surface via the existing `ErrorBanner`
   convention) — fail-open (log and pass the malformed response through) is explicitly ruled out,
   since it would defeat this phase's own Goal of surfacing contract drift as a visible failure
   (Codex review, PR #136).
5. No CLI/API/MCP behavior changes anywhere in this phase — all three WPs are frontend/test-tooling
   only.
6. WP-30.2 must update every `SearchView` code path that rebuilds the URL's search params
   (`handleSubmit` and `handleDocChange` both), not just the form-submit path — `handleDocChange`
   rebuilds params from scratch today and would silently drop `top_k` back to the default the
   moment the new control exists otherwise (Codex review, PR #136).
