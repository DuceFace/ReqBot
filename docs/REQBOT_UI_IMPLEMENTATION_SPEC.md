ReqBot UI Implementation Specification
================================================================

Purpose
----------------------------------------------------------------
This document is a practical frontend roadmap for Claude Code. It turns the UI
planning brief into buildable, PR-sized work while preserving ReqBot's core
architecture rule:

CLI, UI, API, and future MCP must all be thin interfaces over the same backend
service layer. The UI should not call the CLI, and it should not recreate service
logic in React.

Current UI capabilities:
- Search requirements
- Trace a requirement to source quote/provenance/context
- Compare documents
- Build evidence maps
- Browse indexed documents through DocsView
- Show a small backend/system status indicator

Current or upcoming backend capabilities:
- Ingest documents through CLI
- Index/reindex
- Ask/search
- Trace
- Compare
- Evidence pack
- Generate checklist
- Export checklist as CSV/JSON/Markdown
- Domain profiles at ingest/checklist time


================================================================
1. ROUTE MAP
================================================================

/ 
  Redirect to /search.

/search
  Query requirements. Existing SearchView.

/trace/:reqId
  Requirement detail and provenance. Existing TraceView. Trace is a drill-down
  detail route, not a top-level navigation item.

/compare
  Two-document topic comparison. Existing CompareView.

/evidence
  Topic-to-evidence map with optional synthesis. Existing EvidenceView.

/corpus
  Corpus browse. Rename/reframe current DocsView.

/corpus/:docId
  Single-document metadata page with quick actions. New route.

  MVP boundary:
  This page is document metadata plus action links only. Do not build a full
  per-document requirements browser unless a backend API supports that directly.

/checklists
  Checklist generation entry point. New route after /api/checklist exists.

/checklists/:docId?profile=<profile>
  Generated checklist preview and export. New route after /api/checklist exists.
  Both docId and profile are read from the URL so refresh/bookmark/share works without
  router state.

/system
  Health/readiness detail page. New route. The existing status dot should link
  here.

*
  Existing NotFoundView.

Primary navigation should become a persistent sidebar with:
- Search
- Compare
- Evidence
- Checklists
- Corpus
- System


================================================================
2. SCREEN-BY-SCREEN SPEC
================================================================

/corpus
----------------------------------------------------------------
Goal:
  Browse the indexed corpus and find a document to act on.

Controls:
  - client-side name filter
  - sort by name/count/date

Data:
  - GET /api/docs
  - show document name, requirement count, profile when available, run date, and
    extraction mode

Actions:
  - click row -> /corpus/:docId

Empty state:
  "No documents indexed yet. Ingest documents via the CLI."

Loading/error:
  - reuse LoadingSpinner
  - reuse ErrorBanner

Dependency:
  - docs_service.list_docs()
  - no new service logic for the rename


/corpus/:docId
----------------------------------------------------------------
Goal:
  Let the user act on one document without leaving context.

Controls:
  - none for MVP; read-only detail

Data:
  - document metadata from /api/docs, filtered client-side for MVP
  - if client-side lookup becomes awkward, add a lightweight GET /api/docs/{docId}
    that filters list_docs() server-side

Actions:
  - Search this doc -> /search?doc=<docId>
  - Compare from here -> /compare?doc1=<docId>
  - Generate checklist -> /checklists/:docId, hidden or disabled until checklist
    API exists

Empty/not found:
  - if docId is unknown, route to NotFoundView or show a document-not-found state

Loading/error:
  - shared patterns

Dependency:
  - docs_service only
  - a single-doc route, if added, must be a thin wrapper/filter over existing docs
    data, not a new document-analysis service


/search
----------------------------------------------------------------
Goal:
  Find relevant requirements.

Controls:
  - query input
  - document filter
  - future filters can include domain tag and requirement type if already exposed
    by the API

Data:
  - POST /api/ask
  - result cards with source quote, score, doc, source ref, section/page metadata
    when available

Actions:
  - Generate Answer remains explicit opt-in
  - click result -> /trace/:reqId

Loading/error/empty:
  - keep existing behavior, but move toward shared components

Dependency:
  - ask_service through existing /api/ask route


/trace/:reqId
----------------------------------------------------------------
Goal:
  Inspect requirement provenance and surrounding source context.

Controls:
  - Show source context button
  - back link preserving origin route

Data:
  - GET /api/trace/:reqId
  - source quote
  - source ref
  - document/page/section metadata
  - domain_profile when available
  - cross-framework matches
  - context when requested

Actions:
  - show source context
  - navigate to cross-match trace pages

Breadcrumb:
  Derive the parent label from "from" route state where available
  (e.g. "Compare / Trace" if navigated from Compare). Fall back to no parent
  label ("Trace" only) when no "from" state is present. Never hardcode
  "Search / Trace" — Trace is reachable from Search, Compare, Evidence, and
  future Checklist flows.

Dependency:
  - trace_service through existing /api/trace route


/compare
----------------------------------------------------------------
Goal:
  Compare two documents against a control ID or topic.

Controls:
  - doc picker 1
  - doc picker 2
  - topic/query input

Data:
  - POST /api/compare
  - sections for in-both, doc-1-only, doc-2-only

Actions:
  - click requirement -> /trace/:reqId

Dependency:
  - compare_service through existing /api/compare route


/evidence
----------------------------------------------------------------
Goal:
  Build a source-backed evidence map for a topic.

Controls:
  - topic input
  - Generate Answer button remains opt-in
  - future: top_k/result-depth control
  - future: flagged-only filter only if payload includes review fields

Data:
  - POST /api/evidence
  - evidence groups and representative requirements
  - optional synthesis text above results, never replacing source-backed results

Actions:
  - click evidence requirement -> /trace/:reqId
  - future: expand group to show all sources/context

Dependency:
  - evidence_service through existing /api/evidence route


/system
----------------------------------------------------------------
Goal:
  Tell the user whether ReqBot is healthy right now.

Controls:
  - manual refresh button

Data:
  - GET /api/status
  - Ollama reachability
  - Qdrant reachability
  - available models
  - processed document summary
  - synthesis model availability only if status_service already computes enough
    information to display it honestly

Actions:
  - refresh

Empty state:
  - not applicable

Loading/error:
  - skeleton or LoadingSpinner for loading
  - ErrorBanner for failed status check
  - status-page failure must not crash the rest of the app

Dependency:
  - status_service.check()
  - display existing return fields first; do not invent checks in the frontend


/checklists
----------------------------------------------------------------
Status:
  Blocked until /api/checklist exists.

Goal:
  Pick a document and profile, then generate a checklist.

Controls:
  - DocPicker populated from /api/docs
  - ProfilePicker, default cybersecurity for now
  - Generate button
  - output format should be chosen at export time, not generation time

Data:
  - none until submit

Actions:
  - Generate -> POST /api/checklist
  - on success, navigate to /checklists/:docId?profile=<profile>
    both values come from the form inputs, never derived from the response envelope

Empty state:
  - prompt to pick a document

Loading/error:
  - "Generating checklist..." spinner
  - shared ErrorBanner

Dependency:
  - new POST /api/checklist over checklist_service.generate()


/checklists/:docId?profile=<profile>
----------------------------------------------------------------
Status:
  Blocked until /api/checklist exists.

Goal:
  Review generated checklist and export it.

URL contract:
  Both docId and the profile query param are required. On load, the route reads both
  from the URL and calls POST /api/checklist to fetch the checklist. Refresh and direct
  links must work — do not rely on router state to supply the profile.

Controls:
  - flagged-only toggle (client-side .filter() on requires_human_review only)
  - export buttons for CSV/JSON/Markdown

Data:
  - checklist envelope and items
  - table columns grouped as Locate / Ask / Record / Verify / Trace

Actions:
  - export CSV/JSON/Markdown via POST /api/checklist/export
  - trigger download: fetch() + response.blob() + URL.createObjectURL() + programmatic
    anchor click; do not use window.location.href

Empty state:
  - no eligible checklist items generated
  - explain likely reason: no requirements had required provenance anchors

Loading/error:
  - table skeleton
  - shared ErrorBanner

Dependencies:
  - checklist_service.generate() via POST /api/checklist
  - pipeline/checklist_export.py to_csv/to_json/to_markdown via POST /api/checklist/export

Hard boundary:
  No client-side CSV or Markdown generation. Export formatting stays server-side.
  No inline editing of status or assessor_notes in the MVP checklist UI.
  ChecklistTable container must use overflow-x: auto; page body must not scroll
  horizontally.


================================================================
3. COMPONENT INVENTORY
================================================================

AppShell
  Sidebar + top strip + content outlet.

  Conceptual props:
  - children
  - optional breadcrumb/title slot

SidebarNav
  Persistent navigation with active route highlight.

  Conceptual props:
  - items: { label, path, icon? }[]

StatusDot
  Existing status indicator. Keep it, but make it link to /system.

  Conceptual props:
  - keep current props unless refactor is clearly needed

SourceQuoteBlock
  Consistent display for verbatim source text.

  Conceptual props:
  - quote: string
  - context?: string
  - expandable?: boolean

ProvenanceMeta
  Compact metadata block for document/source/page/profile/tag data.

  Conceptual props:
  - document/source_pdf
  - source_ref
  - sectionPath
  - pageRefs
  - domainProfile
  - domainTags
  - confidence

RequirementResultCard
  Shared result card for Search, Compare, and Evidence where payloads overlap.

  Conceptual props:
  - requirement
  - score?
  - from?
  - onClick or link target

ReviewFlagBadge
  Small amber badge for items requiring review.

  Conceptual props:
  - reasons: string[]

  Use only on screens whose API payload actually includes requires_human_review
  or review_reasons. Do not infer review state in the frontend.

DocPicker
  Reusable document dropdown populated from /api/docs.

  Conceptual props:
  - value
  - onChange
  - label
  - documents

ProfilePicker
  Domain profile select.

  Conceptual props:
  - value
  - onChange
  - options (populated from GET /api/profiles)

  Must use GET /api/profiles — do not hardcode profile names. Default value is
  "cybersecurity". If the endpoint is loading, render a disabled picker with
  "cybersecurity" pre-filled so the form remains usable.

ChecklistTable
  Dense checklist data grid.

  Conceptual props:
  - items
  - filterFlaggedOnly

  Column groups:
  - Locate: source_ref, section_title_path, page_refs
  - Ask: source_quote, audit_question
  - Record: status, assessor_notes
  - Verify: requires_human_review, review_reasons, confidence
  - Trace: checklist_item_id, requirement_ids, domain_tags

  Layout constraint: the table container must use overflow-x: auto. The page body
  must not scroll horizontally. source_quote values can exceed 300 characters —
  do not rely on truncation to prevent page-level overflow.

ExportButtonGroup
  CSV/JSON/Markdown export controls.

  Conceptual props:
  - onExport(format)
  - disabled

SystemHealthPanel
  Service readiness rows.

  Conceptual props:
  - checks: { name, ok, detail }[]

EmptyState / ErrorBanner / LoadingSpinner
  Reuse existing shared components. Do not duplicate equivalents.


================================================================
4. MVP CUT LINE
================================================================

Immediate, low-risk frontend work with no backend change:
- AppShell/sidebar navigation refactor
- rename Docs to Corpus in route/labels
- /corpus/:docId metadata page using existing /api/docs data
- /system page using existing /api/status payload
- shared SourceQuoteBlock and ProvenanceMeta components
- visual consistency pass across Search, Compare, Evidence, Trace
- render domain_profile in Trace if already present in the payload

After /api/checklist exists:
- /checklists generate screen
- /checklists/:docId preview screen
- ChecklistTable
- ExportButtonGroup
- flagged-only filter using existing requires_human_review boolean

Later, requires backend design first:
- editable checklist status/assessor_notes
- merge-on-regeneration for assessor-owned fields
- ingest-from-UI
- job history
- export history
- XLSX export
- profile management UI
- MCP tool surface


================================================================
5. IMPLEMENTATION ORDER
================================================================

PR1 - App shell and navigation
  - Create AppShell and SidebarNav.
  - Replace top NavBar usage.
  - Rename Docs route/label to Corpus.
  - Keep visual redesign modest.

PR2 - Shared source/provenance components
  - Extract SourceQuoteBlock and ProvenanceMeta from existing result/detail UI.
  - Apply across Search, Compare, Evidence, and Trace where data shapes allow.
  - Do not change backend responses.

PR2.5 - docs_service domain_profile (backend prerequisite for Corpus profile column)
  - Add domain_profile to docs_service.list_docs(): read from first JSONL record,
    req.get("domain_profile") or "cybersecurity" fallback.
  - Expose as "profile" in each document dict in the /api/docs response.
  - Add regression test: pre-Phase-20 fixture records return "cybersecurity".

PR3 - Corpus document detail
  - Add /corpus/:docId.
  - Derive document metadata from /api/docs (now includes profile field).
  - Add quick links: Search this doc, Compare from here.
  - Keep Generate checklist hidden/disabled until checklist API exists.

PR4 - System page
  - Add /system.
  - Reuse /api/status.
  - Make StatusDot link to /system.
  - Add manual refresh.

PR5 - Checklist API
  - Add api/routes/checklist.py.
  - POST /api/checklist calls checklist_service.generate().
  - POST /api/checklist/export calls pipeline/checklist_export.py to_csv/to_json/to_markdown;
    returns Content-Disposition: attachment for browser download (not a JSON body).
  - GET /api/profiles: scan profiles/ directory, return {"profiles": [...]}.
    Unknown profile in checklist endpoints maps FileNotFoundError -> 400.
  - Keep endpoints thin over existing service/export functions.

PR6 - Checklist generation screen
  - Add /checklists.
  - Add DocPicker and ProfilePicker (populated from GET /api/profiles, default cybersecurity).
  - Generate checklist through POST /api/checklist.
  - On success, navigate to /checklists/:docId?profile=<profile>.

PR7 - Checklist preview screen
  - Add /checklists/:docId?profile=<profile>; read both from URL, refetch via POST /api/checklist.
  - Render ChecklistTable with overflow-x: auto container.
  - Add flagged-only client-side filter based only on existing requires_human_review boolean.

PR8 - Checklist export buttons
  - Wire ExportButtonGroup to POST /api/checklist/export.
  - Trigger download via fetch() + response.blob() + URL.createObjectURL() + programmatic
    anchor click. Do not use window.location.href (POST endpoint).
  - Do not build CSV/Markdown formatting in React.

PR9 - Corpus checklist quick action
  - Unhide/enable Generate checklist link from /corpus/:docId.

PR10 - Demo walkthrough and polish
  - Verify loading/error/empty states across all new screens.
  - Check keyboard/browser back behavior.
  - Run frontend build and existing unit tests.


================================================================
6. RISKS AND GUARDRAILS
================================================================

1. No client-side business logic
   Grouping, scoring, confidence thresholds, review-reason logic, provenance
   validation, and CSV/Markdown formatting stay in services/ or pipeline/.

   Allowed frontend-only filtering:
   - simple filtering over fields the backend already computed, such as
     requires_human_review === true.

2. No ingest UI yet
   Do not add upload forms or browser-triggered pipeline runs until a job/task
   abstraction is designed.

3. No editable checklist fields yet
   status and assessor_notes should render read-only until regeneration and
   persistence are designed. Do not ship inputs whose content will be silently
   lost on regenerate.

4. No new frontend framework or state library
   Stay on the existing React + TypeScript + Tailwind + react-router stack.
   Do not add Redux, Zustand, or similar state management for this scope.

5. No new dependencies without discussion
   This blocks XLSX export and runtime validation libraries such as Zod for now.
   Keep them in the backlog until explicitly approved.

6. Every new screen needs a real service/API basis
   If a screen needs data not currently returned, add the field through the
   service/API path in an additive, non-breaking way. Do not compute backend
   concepts inside the route handler or the frontend just for convenience.

7. Do not reshape API responses for frontend convenience
   Mirror what service/CLI workflows already return unless there is a deliberate
   API contract change.

8. Trace remains a drill-down route
   Do not put Trace in the primary sidebar. Users should reach trace detail from
   Search, Compare, Evidence, Checklist, or Corpus flows.

9. Checklist UI is blocked by checklist API
   Do not start checklist screens by hardcoding fixture data or reading local
   files from the browser. Add the API first (POST /api/checklist, POST
   /api/checklist/export, GET /api/profiles).

9a. ProfilePicker must not hardcode profile names
    Use GET /api/profiles. Hardcoded names will break silently when new profiles
    are added.

9b. ChecklistTable horizontal overflow
    The table container must use overflow-x: auto. Never accept a state where the
    page body scrolls horizontally — fix it before the WP gate.

10. UI, CLI, API, and MCP must stay aligned
    The desired product shape is one backend engine with several interfaces, not
    several independent implementations.
