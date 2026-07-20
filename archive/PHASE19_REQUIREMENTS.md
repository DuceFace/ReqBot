# ReqBot — Phase 19: GUI Capability Expansion

**Status:** COMPLETE 2026-05-17  
**Date:** 2026-05-17  
**Preceded by:** Phase 18 (Minimal GUI — COMPLETE 2026-05-17)  
**Followed by:** Phase 20 (Domain Profile Foundation — previously Phase 19 in PRODUCT_PRD.md)

---

## Phase Reorder Note

Phase 19 was originally scoped in `PRODUCT_PRD.md` as the Domain Profile Foundation phase. That work is important and remains on the roadmap — it has shifted to Phase 20.

**Why the reorder:** ReqBot already has compare, evidence, and synthesis capabilities in the CLI and service layer. Those capabilities can be surfaced in the GUI immediately, without new backend work. Doing that first delivers meaningful user-visible value, produces stronger demos, and stabilizes the GUI shell before domain profiles are layered on top. Premature abstraction work (profiles, schemas, domain-neutral core refactors) should not block a GUI that is already 80% of the way there.

---

## Goal

Bring the browser UI to parity with the major read-analysis capabilities that already exist in the ReqBot CLI and service layer. After Phase 19, a non-technical user should be able to perform the full current ReqBot analysis workflow in the browser — not just search and trace.

Demo-readiness and coherence across views is the gate, not feature count.

---

## Scope Summary

| What's In | What's Out |
|-----------|------------|
| Compare view (two documents, one topic) | Ingest / pipeline UI |
| Evidence view (topic → mapped requirements) | Authentication / multi-user |
| GUI synthesis UX ("Generate answer") | Hosted SaaS / deployment platform work |
| Docs view improvements (corpus browsing) | Checklist generation |
| Shared polish across all four views | MICT export workflow |
| API completion where current endpoints are missing | Domain profile abstraction |
| Optional: richer Status surface | Streaming synthesis (unless trivial) |
| | Major backend rewrites to satisfy frontend convenience |

---

## Architecture Rules

These rules are unchanged from Phase 18 and must remain true through Phase 19.

**1. Frontend is a client only.** All business logic lives in the service layer. The GUI calls the API; it never reimplements retrieval, scoring, or synthesis logic.

**2. API remains thin.** Routes validate input, call a service function, and return the result. No query reshaping, no retrieval logic, no conditional business rules in route handlers.

**3. Service layer is the source of truth.** Every GUI-facing capability must flow through an existing or new service function. If compare or evidence logic does not yet have a clean API endpoint, the fix is to add the endpoint over the existing service — not to call internal functions from a new route or replicate logic in a new code path.

**4. CLI and GUI share the same backend paths.** `services/compare_service.py`, `services/evidence_service.py`, and synthesis all exist today. The GUI should call the same service functions the CLI calls, via the API. If the API contract for a capability does not exist yet, that is WP-19.1's job.

**5. No new pip dependencies without discussion.** Targets include air-gapped environments.

**Safety test (unchanged from Phase 16):**
- Can you kill the API server and still use `reqbot ask` normally? → **Yes**
- Can you change a GUI view without touching retrieval logic? → **Yes**
- Can the CLI and API call the same service function for the same operation? → **Yes**

If any answer becomes no, the design is wrong.

---

## Work Package Plan

### WP-19.1 — API Completion (Compare, Evidence, Synthesis)

**Goal:** Close the gap between what the service layer can do and what the API currently exposes. No new features — just endpoints over existing services.

**Current API endpoints (Phase 16C):**
```
GET  /api/status
POST /api/ask
GET  /api/trace/{req_id}
GET  /api/docs
```

**Endpoints to add:**

| Endpoint | Method | Maps to |
|----------|--------|---------|
| `/api/compare` | POST | `compare_service.compare()` |
| `/api/evidence` | POST | `evidence_service.evidence()` |

**`POST /api/compare` — request shape:**
```json
{
  "doc_id_1": "AFI-17-101",
  "doc_id_2": "NIST-SP-800-53r5",
  "topic": "multi-factor authentication"
}
```

**`POST /api/evidence` — request shape:**
```json
{
  "topic": "encryption at rest",
  "domain_tags": [],
  "requirement_types": [],
  "synthesize": false
}
```

Synthesis is passed through to the evidence service but defaults to `false` in Phase 19. The GUI surfaces it in WP-19.5.

**Synthesis in `/api/ask`:**

`POST /api/ask` already accepts `synthesize: bool` in its request body. The GUI has been passing `synthesize: false`. WP-19.5 will begin passing `synthesize: true` — no API change needed, only frontend changes.

**Response shape discipline:**
- Response shapes must be defined in the route module as Pydantic response models or documented inline.
- Match the shapes to what the existing CLI commands return — do not reshape for frontend convenience.
- If the existing service returns a field the frontend doesn't use yet, leave it in. Do not strip fields at the API layer.

**Smoke tests:**
- `curl -X POST localhost:8000/api/compare -d '{"doc_id_1":"...","doc_id_2":"...","topic":"..."}' -H 'Content-Type: application/json'`
- `curl -X POST localhost:8000/api/evidence -d '{"topic":"..."}' -H 'Content-Type: application/json'`

**Success criteria:**
- `/api/compare` and `/api/evidence` return valid responses for happy-path inputs.
- CLI behavior is unchanged (CLI never calls these routes).
- All existing `/api/` endpoints still work.
- Swagger at `/api-docs` reflects the new endpoints.

---

### WP-19.2 — Compare View

**Goal:** A browser interface for comparing requirements across two documents on a topic. Calls `/api/compare`.

**Route:** `/compare`

**Layout:**
```
┌────────────────────────────────────────────────────┐
│  ReqBot                              [Status dot]  │
├────────────────────────────────────────────────────┤
│  Document 1: [AFI-17-101 ▼]                        │
│  Document 2: [NIST-SP-800-53r5 ▼]                  │
│  Topic:      [multi-factor authentication.......]  │
│                                        [Compare]   │
├────────────────────────────────────────────────────┤
│  Exact matches (2)                                 │
│  ┌────────────────────────────────────────────┐    │
│  │ REQ-AFI17-abc ↔ REQ-NIST-xyz              │    │
│  │ "The system shall enforce MFA..."          │    │
│  └────────────────────────────────────────────┘    │
│                                                    │
│  From AFI-17-101 only (4)                          │
│  ┌────────────────────────────────────────────┐    │
│  │ REQ-AFI17-def  ·  0.83                    │    │
│  │ "Privileged accounts shall require..."    │    │
│  └────────────────────────────────────────────┘    │
│                                                    │
│  From NIST-SP-800-53r5 only (6)                    │
│  ...                                               │
└────────────────────────────────────────────────────┘
```

**Behavior:**
- Document dropdowns populated from `/api/docs` on mount (same pattern as Search view doc filter).
- Topic is a free-text input. Compare button submits. Enter key also submits.
- Results rendered in three sections: exact matches, doc-1-only, doc-2-only.
- Each result card links to `/trace/:reqId` with `state={{ from: location.search }}` so back-link returns to compare results.
- URL-driven state: `?doc1=AFI-17-101&doc2=NIST-SP-800-53r5&q=mfa` — browser back/refresh restores results.
- Loading, error, and empty states.

**What's NOT in this view:**
- Side-by-side diff UI (too complex for Phase 19)
- Export / download
- Filtering within compare results (defer)

**Navigation:**
- Add "Compare" to the app nav bar alongside "Search".

**Success criteria:**
- User can select two documents, enter a topic, and see three result sections.
- Each result links to trace view with back navigation preserved.
- URL state survives browser refresh.

---

### WP-19.3 — Evidence View

**Goal:** A browser interface for evidence mapping — topic or control → matched requirements. Calls `/api/evidence`.

**Route:** `/evidence`

**Layout:**
```
┌────────────────────────────────────────────────────┐
│  ReqBot                              [Status dot]  │
├────────────────────────────────────────────────────┤
│  Topic / control:  [encryption at rest............] │
│                                        [Map]       │
│  (optional filters below — collapsed by default)   │
├────────────────────────────────────────────────────┤
│  Evidence map for "encryption at rest" (12 reqs)   │
│  ┌────────────────────────────────────────────┐    │
│  │ Group: data_protection (5)                │    │
│  │  REQ-NIST-xxx  ·  NIST SP 800-53r5       │    │
│  │  "Data at rest shall be encrypted using.." │    │
│  └────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────┐    │
│  │ Group: access_control (4)                 │    │
│  │  ...                                      │    │
│  └────────────────────────────────────────────┘    │
│  [Generate Answer — see WP-19.5]                   │
└────────────────────────────────────────────────────┘
```

**Behavior:**
- Map button submits. Enter submits.
- Results grouped by domain tag (service layer already groups).
- Each requirement card links to trace view with back navigation.
- "Generate Answer" button is present but hidden until WP-19.5 — or rendered as disabled with tooltip "Available in a future phase."

  Decision: render the button as disabled in WP-19.3, wire it in WP-19.5. Avoids a dead placeholder but keeps the layout stable from the start.

- URL-driven state: `?q=encryption+at+rest`.
- Loading, error, and empty states.

**What's NOT in this view:**
- Synthesis (wired in WP-19.5)
- Export to Markdown/JSON (Phase 20+)
- Domain tag filter UI (can be added as a collapsed advanced section if scope permits; default is collapsed / not shown)

**Navigation:**
- Add "Evidence" to the app nav bar.

**Success criteria:**
- User can enter a topic and see evidence groups with linked requirements.
- Each result links to trace with back navigation preserved.
- URL state survives refresh.

---

### WP-19.4 — Docs / Corpus Browsing Improvements

**Goal:** Make the document list more useful as a corpus-browsing surface, not just a dropdown data source.

**Route:** `/docs` (currently: no dedicated view; docs are only a filter dropdown in Search)

**Layout:**
```
┌────────────────────────────────────────────────────┐
│  ReqBot                              [Status dot]  │
├────────────────────────────────────────────────────┤
│  Corpus  ·  45 documents  ·  31,734 requirements   │
├────────────────────────────────────────────────────┤
│  [Filter by name.........]                         │
│  ┌────────────────────────────────────────────┐    │
│  │ NIST SP 800-53r5                          │    │
│  │ 1,247 requirements  ·  enriched  ·  2026-04│    │
│  │           [Search this doc ↗] [Trace ↗]   │    │
│  └────────────────────────────────────────────┘    │
│  [more rows...]                                    │
└────────────────────────────────────────────────────┘
```

**Behavior:**
- Dedicated `/docs` route — not just a dropdown source.
- Corpus summary at the top: total docs, total requirements.
- Sortable by name, requirement count, or run date (client-side sort; data is already in /api/docs).
- Client-side text filter (no API call on keypress — filter the loaded list).
- Each row has a "Search this doc" link that navigates to `/search?doc=<doc_id>`, prefilling the document filter. This provides a natural drill-down path.
- Add "Docs" to the app nav bar.

**What's NOT in this view:**
- Ingest trigger
- Per-document analytics / histograms
- Delete / reindex actions

**Success criteria:**
- User can browse the full corpus, see counts and dates, filter by name.
- "Search this doc" navigates to a pre-filtered search.
- Nav link in header works.

---

### WP-19.5 — GUI Synthesis UX

**Goal:** Expose synthesis in the GUI with understandable UX. Available in Evidence view first, optionally in Ask results.

**Design principles:**
- Synthesis is a deliberate action — user must click "Generate Answer." It is never triggered automatically on query submit. This avoids 30+ second waits on every search.
- Loading state must be explicit and patient — "Generating answer (this may take 30–60 seconds)..."
- Error state must be informative — "Synthesis failed. Retrieval results are still available below."
- Synthesis output is rendered alongside retrieval results, not instead of them. Provenance is always visible.
- No streaming required in this phase unless it falls out of the API naturally. Polling or a single-request-with-timeout approach is acceptable.

**Evidence view integration (primary):**

After WP-19.3 lands, wire the "Generate Answer" button in Evidence view:
1. Button click sets `synthesize: true` in the `/api/evidence` request body.
2. Spinner with patience message ("Generating...").
3. On response: render synthesis text in a clearly labeled "Generated Answer" section above the evidence groups.
4. Retrieval groups remain visible below. The synthesis does not replace them.
5. On error: show error message; retrieval groups remain.

**Ask / Search view integration (secondary):**

Add a "Generate Answer" button to the Search results header. Clicking it re-submits the same query with `synthesize: true` and renders the synthesis text above the result list. The result list does not change.

- This is opt-in: the Search view default behavior (no synthesis) is unchanged.
- If synthesis is slow, a spinner with elapsed time ("Generating... 12s") reduces perceived wait.

**Model awareness:**
- The synthesis model (`qwen2.5:14b`) may not be pulled yet on a given machine. The API will return an error; the frontend should surface "Synthesis model not available" as a specific message distinct from generic errors, if the API signals this distinction.
- Do not expose model selection in the GUI — single synthesis model, opaque to the user.

**What's NOT in WP-19.5:**
- Streaming (WebSocket, SSE) — deferred
- Model picker
- Temperature / token controls

**Success criteria:**
- "Generate Answer" action available in Evidence view; output renders above evidence groups.
- "Generate Answer" action available in Search results.
- Loading, error, and success states are clear and distinct.
- Retrieval results remain visible alongside synthesis output.
- Slow synthesis (30–60s) does not freeze or crash the UI.

---

### WP-19.6 — Polish, State Consistency, and Demo-Readiness

**Goal:** Tighten shared UI consistency, fix any rough edges across all four views, and confirm the GUI is coherent for a live demo walkthrough.

**Shared consistency items:**

- Nav bar present and correct across all views: Search, Compare, Evidence, Docs.
- Status indicator (green/red dot) visible in the header on all views.
- Back navigation works consistently: any view reached from another view has a contextual back link or browser back preserves state.
- Loading and error states use a shared pattern — no view has its own ad-hoc spinner or error string.
- Result cards are visually consistent across Search, Compare, and Evidence views.
- Tailwind classes are not duplicated — shared components are in `components/`.

**State consistency:**
- URL-driven state on all views that take input (`?q=`, `?doc1=`, `?doc2=`, etc.). Browser refresh restores results.
- Navigation between views does not leave stale state behind (confirm all `useEffect` cleanup hooks are in place).
- No view holds onto results from a previous query after a new one is submitted.

**Demo-readiness walkthrough:**

Before Phase 19 is declared complete, run this demo scenario end-to-end without CLI assistance:

1. Open `localhost:8000`.
2. Run a search query on a GRC topic.
3. Drill into a trace; navigate a cross-match; use the back link.
4. Run a compare between two documents on the same topic.
5. Run an evidence map on the same topic.
6. Generate a synthesis answer from the evidence view.
7. Browse the corpus docs; use "Search this doc" on one document.

If any step fails, crashes, or requires workarounds, it is not a polish issue — it is a bug. Fix it before declaring Phase 19 complete.

**Success criteria:**
- Demo walkthrough above completes without errors or confusing states.
- Nav bar, header, status dot, and card layouts are consistent across all views.
- No stale-state bugs observable during normal navigation.

---

## Explicit Non-Goals for Phase 19

These are not rejected — they are out of scope to keep the phase focused.

- **No ingest UI** — pipeline initiation stays in the CLI.
- **No authentication or multi-user** — localhost only, per Phase 18 design.
- **No hosted SaaS or deployment platform work.**
- **No checklist generation** — Phase 21+.
- **No MICT export workflow.**
- **No domain profile abstraction** — that is Phase 20.
- **No major backend rewrites** to satisfy frontend convenience. If a service function does not return the right shape, update the service — do not move logic into the route or duplicate it in the frontend.
- **No frontend reimplementation of ReqBot business logic.** If compare or evidence behavior needs to change, change the service. The GUI reads results; it does not compute them.

---

## Success Gate (Phase 19)

A non-technical user can use the browser GUI for the full current ReqBot read-analysis workflow:

1. Run a search query and drill into a trace. *(Search + Trace — from Phase 18)*
2. Compare two documents on a topic in the browser.
3. Map evidence for a topic in the browser.
4. Generate a synthesized answer from the GUI.
5. Browse the corpus document list and navigate to a filtered search from a document row.
6. The demo walkthrough in WP-19.6 completes without errors.

Plus the unchanged Phase 18 gates:
- CLI commands (`reqbot ask`, `reqbot compare`, `reqbot evidence`) work exactly as before.
- Killing `reqbot serve` has zero impact on CLI operation.
- No duplicated business logic in the frontend.

---

## Sequencing

Do one WP at a time. Get Codex/Gemini review after each before proceeding.

| WP | Description | Gate before next |
|----|-------------|-----------------|
| 19.1 | API completion (compare + evidence endpoints) | curl smoke tests; Swagger reflects new endpoints; no CLI regression |
| 19.2 | Compare view | Two-doc comparison works; result links to trace; URL state survives refresh |
| 19.3 | Evidence view | Topic → grouped requirements; back links; URL state; synthesis button disabled/pending |
| 19.4 | Docs view | Corpus list; name filter; "Search this doc" link; nav entry |
| 19.5 | Synthesis UX | "Generate Answer" works in Evidence and Search; loading/error states clear; retrieval results preserved |
| 19.6 | Polish + demo walkthrough | Full demo scenario completes cleanly; shared component consistency |

**Why synthesis is last:**

Synthesis introduces the longest latency in ReqBot. Surfacing it in the GUI before the surrounding views are stable would mean every UX issue gets entangled with synthesis timing. The simpler views (compare, evidence, docs) should land first so the GUI shell is solid before the slow path is layered in.

---

## What's Not Changing

- The service layer. Phase 19 adds no new service logic — only API endpoints over existing services (WP-19.1) and frontend views that call them.
- The CLI. Every CLI command works identically after Phase 19. No CLI regressions.
- The pipeline. No changes to steps A–F.
- JSONL remains the source of record.
- The Phase 18 Search and Trace views — they must remain stable throughout. Phase 19 work must not regress them.
