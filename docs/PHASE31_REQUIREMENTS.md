# ReqBot Phase 31 — Trace/Compare Type Fix, Citation Numbering & Profile Schema Docs

**Status:** Locked (drafted 2026-07-27; implementation starts at WP-31.1)
**Date:** 2026-07-27
**Preceded by:** Phase 30 (Frontend Test Infrastructure, SearchView Parity & Runtime Contract
Validation)
**Followed by:** None currently planned — next work will be selected from the live backlog
(`docs/TODO_future_improvements.txt`) once Phase 31 closes. The retrieval-quality track (reranker
spike and its prerequisites) is deliberately not this phase — see Non-Goals.

---

## Status

This table is the live source of truth for Phase 31 WP status — update it here when a WP lands,
not in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-31.1 — Fix `section_title_path` Type Mismatch | Not started |
| WP-31.2 — Citation Numbering & Linking (Search/Evidence) | Not started |
| WP-31.3 — Profile Schema Documentation | Not started |

---

## 1. Phase Framing

Three items, picked up together by explicit request rather than bundled for a shared theme — same
grab-bag character as Phase 30:

- **Backlog item #20** (`section_title_path` mistyped as `string`, not `string[]`) — found as a
  direct side-effect of WP-30.3: Zod validation rejected a real `evidence_service` response until
  `EvidenceRequirement`'s copy of this field was fixed to `string[]`. `Requirement` and
  `ComparePayload` were deliberately left mistyped in that WP (out of scope for a Zod-focused WP)
  and have sat as a known, unfixed bug since.
- **Backlog item #21** (citation numbering and linking) — synthesized answers already cite sources
  by number (`[N]`), but nothing in the GUI shows the user which result card `[N]` refers to.
- **Backlog item #22** (profile schema documentation pass) — `profiles/*.json`'s real schema has
  never had a dedicated write-up outside the loader's own code. Cheap, zero-risk, no reason to keep
  deferring it.

**Backlog item #11** (checklist assessor-note preservation on regeneration) was considered and
explicitly dropped from this phase, not deferred by default the way it had been several times
before. Rationale (Tyler, 2026-07-27): it protects a workflow — editing assessor notes, then
re-running `generate()` against the same `doc_key` — that no real user is currently doing. Revisit
only if that usage pattern actually starts happening; it is not a standing item on the active
backlog anymore.

No sequencing dependency between the three WPs — they touch unrelated files (frontend API types,
frontend result-card components, a new docs file) and can land in any order. Numbered 31.1/31.2/31.3
in the order they were discussed, not by priority.

---

## 2. Goals

- Fix `Requirement.section_title_path` and `ComparePayload.section_title_path` in
  `frontend/src/api/types.ts` to match what the backend actually sends (`list[str]`), and fix the
  one place that renders the wrong assumption (`TraceView.tsx`).
- Make the citation numbers already present in synthesized answers (`[1]`, `[2]`, ...) visible and
  navigable in the GUI — a user reading "[3]" in a Generated Answer should be able to see which
  result card that is.
- Give `profiles/*.json`'s schema a real, dedicated write-up so adding a profile beyond
  `cybersecurity` doesn't require reading `core/profiles.py` to reverse-engineer the contract.

## 3. Non-Goals

- No expansion of Zod runtime-validation coverage to `AskResponse`, `TraceResponse`, or
  `CompareResponse` — WP-30.3 deliberately scoped Zod to `ConfigResponse`/`EvidenceResponse` and
  expands incrementally; bundling schema coverage into a type-only bug fix would blur WP-31.1's
  scope. Stays backlog material.
- No change to backend citation numbering. `core/ask.py::format_evidence()` and
  `services/evidence_service.py`'s `enumerate(group_order, 1)` already number entries `[N]` in the
  exact order returned to the frontend (`results` / `group_order`), and `core/ask.py`'s
  `print_results_table()` already shows the same `[N]` numbering in the CLI. This phase only makes
  that existing, already-correct numbering visible and clickable in the GUI — it is not adding
  numbering that doesn't exist today.
- No citation numbering for `CompareView` — Compare has no synthesized-answer path
  (`SynthesisBox` is only used by `SearchView` and `EvidenceView`); there's nothing to number.
- No product decision on whether to add a profile beyond `cybersecurity` — WP-31.3 is a
  documentation task only, not a scoping exercise for a new domain.
- No retrieval-track work (reranker spike, eval-set construction, actionability
  self-verification) — those need an investigation/spike step before they're even scoped WPs, the
  wrong shape for this phase. Deliberately left for a dedicated later phase.

---

## 4. Work Packages

### WP-31.1 — Fix `section_title_path` Type Mismatch

**Source:** Backlog item #20.

**Problem:** `frontend/src/api/types.ts` declares `section_title_path?: string` on both `Requirement`
(line 33, used by `AskResult`/`TraceResponse.requirement`/`TraceResponse.cross_matches`) and
`ComparePayload` (line 146) — but the Python side (`pipeline/chunk_text.py`, `section_parser.py`,
`parse_and_normalize.py`) always produces a `list[str]` hierarchy breadcrumb. `EvidenceRequirement`
had the identical bug and was fixed to `string[] | null` in WP-30.3 after Zod validation caught it
against a real response; `Requirement`/`ComparePayload` were left mistyped since Zod doesn't cover
`/api/ask` or `/api/compare` yet. The live symptom: `frontend/src/views/TraceView.tsx:197` —
`{req.section_title_path && <> · {req.section_title_path}</>}` — renders a `string[]` directly into
JSX, which concatenates the array elements with no separator instead of the intended readable path.

**Scope:**
- Fix `Requirement.section_title_path` (`types.ts:33`) and `ComparePayload.section_title_path`
  (`types.ts:146`) to `string[]`. Match `EvidenceRequirement`'s nullability
  (`string[] | null`, optional) unless the Python source for these two specific paths is confirmed
  to never emit `null` — verify against `pipeline/parse_and_normalize.py` and
  `pipeline/chunk_text.py` rather than assuming parity with `EvidenceRequirement`'s reasoning.
- Fix `TraceView.tsx:197` to join the array into a readable breadcrumb instead of rendering it
  directly. Reuse the join behavior `ChecklistTable.tsx`'s local `formatPath()` already established
  (`frontend/src/components/ChecklistTable.tsx:20`, `parts.join(' › ')`) rather than inventing a
  second convention — move it into `frontend/src/utils/ui.ts` as a shared export (matching this
  codebase's established pattern for shared pure functions, e.g. `docValue`/`pageRange`) and update
  `ChecklistTable.tsx` to import it from there instead of keeping a private copy.
- Grep for any other render site assuming `section_title_path` is a string before calling this
  done — confirmed during phase planning that `TraceView.tsx:197` is currently the only one
  (`CompareView.tsx`/`SearchView.tsx` don't render this field at all today), but re-check at
  implementation time in case that's changed.

**Non-goals:**
- No Zod coverage for `AskResponse`/`CompareResponse` (see Phase Non-Goals).
- No change to `ChecklistTable.tsx`'s rendering behavior or separator glyph — only relocating the
  existing `formatPath` function, not altering its output.

**Tests/verification:**
- Unit test for the relocated `formatPath` in `utils/ui.ts` (via the WP-30.1 harness), covering
  empty array and multi-element cases.
- `npm run build` (`tsc && vite build`) passes — confirms no other code relied on the old `string`
  type in a way that breaks under `string[]`.
- Manual: open a Trace view for a requirement with a real multi-level `section_title_path` and
  confirm it renders as a readable breadcrumb, not a concatenated string.

**Gate:** `Requirement`/`ComparePayload` correctly type `section_title_path` as `string[]`,
`TraceView` renders it as a proper joined breadcrumb, and the join logic lives in one shared place.

---

### WP-31.2 — Citation Numbering & Linking (Search/Evidence)

**Source:** Backlog item #21.

**Problem:** `core/ask.py::format_evidence()` builds synthesis input with `[N]` citations in the
exact order of the `results` list, and `services/evidence_service.py` does the same for evidence
groups via `enumerate(group_order, 1)` — both already match the order returned to the frontend. But
`ResultCard.tsx` and `EvidenceCard` (inline in `EvidenceView.tsx`) show no number at all, and
`SynthesisBox.tsx` renders the synthesis text as plain, unparsed text. A user reading "cite [3]" in
a Generated Answer currently has no way to find which card that refers to.

**Scope:**
- Add a 1-indexed `index` prop to `ResultCard.tsx`, matching the card's position in `SearchView`'s
  `results` array. Render it as a small visible badge and give the card a stable DOM id
  (e.g. `id={`result-${index}`}`).
- Add the same to `EvidenceCard` in `EvidenceView.tsx`, indexed by the group's position in
  `group_order` (one number per group/section, not per individual source row within a group) —
  this matches `evidence_service.py`'s existing group-level numbering exactly.
- Update `SynthesisBox.tsx` to parse `[N]` tokens out of `text` and render each as a clickable
  anchor that scrolls to and briefly highlights the matching card/section by id. This is the one
  piece of genuinely new logic in this WP — everything else is threading an index prop through
  existing components.
- If a `[N]` in the synthesis text has no matching card (e.g. `min_score` trimmed it after
  synthesis ran against a larger pre-trim set — check whether that's actually possible given
  current trim-order in `retrieve()`), render it as plain non-clickable text rather than a broken
  link or a thrown error.

**Non-goals:**
- No backend changes — see Phase Non-Goals; the numbering this WP exposes already exists and is
  already correct.
- No changes to `CompareView` (no synthesis path) or the CLI (`print_results_table` already numbers
  correctly).
- No visual redesign of `ResultCard`/`EvidenceCard` beyond adding the number badge and id.

**Tests/verification:**
- Unit test for the `[N]`-parsing logic added to `SynthesisBox` (via WP-30.1's harness) — covers
  multiple citations, no citations, and a citation number with no matching card.
- Manual: run a synthesized search/evidence query, confirm card numbers match the `[N]`s in the
  generated answer, and confirm clicking a citation scrolls to and highlights the right card.

**Gate:** Search and Evidence result cards show stable visible numbers matching the synthesis
citation order, and clicking a `[N]` in a Generated Answer jumps to the matching card.

---

### WP-31.3 — Profile Schema Documentation

**Source:** Backlog item #22.

**Problem:** `profiles/*.json`'s real schema — required vs. optional fields, defaults, validation
rules, the `checklist_guidance` sub-schema — exists only as code in `core/profiles.py`
(`REQUIRED_FIELDS`, `OPTIONAL_FIELDS`, `_OPTIONAL_DEFAULTS`, `_LIST_OF_STRINGS_FIELDS`,
`_NON_EMPTY_LIST_FIELDS`). Nothing outside that file documents it for a human deciding whether to
add a new profile.

**Scope:**
- Add `docs/PROFILES.md` documenting: required fields (`name`, `obligation_verbs`, `skip_sections`,
  `domain_tags`, `requirement_types`), optional fields and their defaults (`description`,
  `checklist_guidance`, `version`), the non-empty-list validation rule on
  `obligation_verbs`/`domain_tags`/`requirement_types` (`skip_sections` is intentionally allowed to
  be empty), and `checklist_guidance.evidence_categories`'s shape.
- Explicitly document that `skip_sections` only takes effect on the docling structure-aware
  chunking path (`pipeline/chunk_text.py`'s legacy pymupdf path logs a warning and no-ops on it) —
  this is currently a code-only fact (see backlog item #5) that trips people up.
- Note that `profiles/test-domain.json` is a minimal pipeline-plumbing test fixture, not a second
  real domain — worth calling out so a reader doesn't mistake it for precedent.
- Link the new doc from README's "Project Docs" list.

**Non-goals:**
- No decision on whether to add a profile beyond `cybersecurity` (see Phase Non-Goals).
- No changes to `core/profiles.py`'s validation logic — documentation only.

**Tests/verification:**
- None beyond `git diff --check` / normal doc review — no code touched.

**Gate:** `docs/PROFILES.md` exists, accurately describes the schema `core/profiles.py` actually
enforces, and is linked from README.

---

## 5. Success Gate

Phase 31 is complete when:

1. All three WPs are merged.
2. Full unit suite passes (`pytest`); `ruff check .` passes; frontend build passes; frontend test
   suite passes.
3. `Requirement`/`ComparePayload` correctly type `section_title_path` as `string[]`, and
   `TraceView` renders it as a readable breadcrumb.
4. Search and Evidence result cards show numbers matching synthesis citations, with working
   click-to-jump.
5. `docs/PROFILES.md` exists and is linked from README.
6. Backlog items #20, #21, and #22 in `docs/TODO_future_improvements.txt` are marked resolved.

---

## 6. Guardrails

1. One WP at a time — each lands as its own PR, reviewed before proceeding to the next, same
   cadence as Phases 28/29/30.
2. WP-31.1 must relocate `ChecklistTable.tsx`'s `formatPath` into `utils/ui.ts` as shared code, not
   duplicate the join logic into `TraceView.tsx` — matches this codebase's established convention
   (`docValue`/`pageRange`, `clampTopK`/`parseTopKParam`).
3. WP-31.2 must not touch `core/ask.py`, `services/evidence_service.py`, or `print_results_table` —
   the citation numbering they produce is already correct; this phase only surfaces it in the GUI.
4. WP-31.3 is documentation-only — no `core/profiles.py` behavior changes.
5. No CLI/API/MCP behavior changes anywhere in this phase.
