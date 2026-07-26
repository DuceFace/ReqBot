# ReqBot Phase 29 — Settings Screen & Evidence View UX

**Status:** Draft — pending review (drafted 2026-07-26; not yet reviewed)
**Date:** 2026-07-26
**Preceded by:** Phase 28 (Frontend Toolchain & CI Security Hardening)
**Followed by:** TBD

---

## Status

This table is the live source of truth for Phase 29 WP status — update it here when a WP lands,
not in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-29.1 — Evidence View: Configurable Result Depth | Not started |
| WP-29.2 — Evidence View: Expandable Sources & Context | Not started |
| WP-29.3 — Settings Screen: Config Service + API | Not started |
| WP-29.4 — Settings Screen: Frontend | Not started |

---

## 1. Phase Framing

Backlog item #17 (settings/configuration screen) was explicitly scoped out of Phase 28 on the
user's request, to keep that phase toolchain/CI-only. This phase picks it up, and bundles in two
adjacent small UX items from the same backlog section (items #9 and #10) that the backlog's own
text for #17 already called out as "the other UX items in this section" — smaller, additive work
alongside the settings screen.

Backlog item #11 (checklist assessor-note preservation on regeneration) was considered and
explicitly left out: it's not a small lift (it needs new file-discovery/merge logic against a
prior checklist export, plus a design decision on opt-in triggering — not just a UI change against
data the API already returns, unlike #9/#10), and with zero customers today, a QoL feature like
this doesn't earn its place ahead of MVP work. Stays backlogged.

Backlog item #8 (runtime validation for frontend API responses via Zod) was also left out — it's
a type-safety/contract-drift concern, not user-facing polish, and the backlog's own text already
scopes it to "revisit when the API surface grows further / contract drift causes a real debugging
issue," neither of which this phase's changes trigger on their own.

---

## 2. Goals

- Give evidence-view users control over result depth instead of a silently hardcoded `top_k: 20`
  in the frontend.
- Expose the sources and context data the evidence API can already provide (or, for context, can
  be made to provide with a small backend change) but the UI currently discards.
- Let users configure ReqBot (Ollama/Qdrant URLs, models, synthesis backend, remote model, API key
  env var name, top_k, min_score) from the GUI, closing the gap where the only way to change any
  of this is hand-editing `~/.config/reqbot/config.json` over SSH.
- Do this without creating a new place for CLI/API/GUI to drift: the settings screen's write path
  must go through a shared service function that `reqbot init` also uses, not a one-off inline
  write duplicated from `cli/reqbot.py`'s `cmd_init()`.

## 3. Non-Goals

- No checklist assessor-note preservation (backlog item #11) — not a small lift, deferred per
  above.
- No runtime frontend response validation / Zod (backlog item #8) — different category of work,
  not triggered by anything in this phase.
- No changes to `authority` / `authority_registry` (authority-weighting config) — the dataclass
  itself marks `authority` "not user-editable directly," and `cmd_init()` doesn't even write
  `authority_registry` today. Out of scope for this phase entirely, not just the settings screen.
- No settings-screen control over `processed_dir` — this is a filesystem path with corpus-integrity
  implications (see [[project_reqbot_watchouts]]-style Qdrant/JSONL drift risk); repointing it via
  a simple web form without also handling reindexing is a foot-gun this phase doesn't take on.
  Stays a `reqbot init`/config-file-only setting.
- No handling of the actual API key *value* anywhere in the settings screen — only
  `api_key_env` (the env var *name* config already stores). The browser never touches or persists
  a secret; the key itself stays in the server's environment, same as today. (Resolves the open
  design question backlog item #17 flagged — the doc's own lean is adopted as the final decision,
  not left open.)
- No retrieval-quality work, no broader CI changes, no other feature tracks — this phase is
  evidence-view UX + settings screen only.

---

## 4. Work Packages

### WP-29.1 — Evidence View: Configurable Result Depth

**Source:** Backlog item #9.

**Problem:** `frontend/src/views/EvidenceView.tsx` calls `api.evidence({ topic, top_k: 20 })` with
a literal `20` at both call sites (lines 79–84 and 105) — no state, prop, or user control feeds
this value. The API already accepts `top_k` today (`api/routes/evidence.py`'s `EvidenceRequest`,
`Field(default=10, ge=1, le=100)`) — this is a frontend-only gap, not a backend one.

**Scope:**
- Add a `top_k` control to `EvidenceView.tsx` (a numeric input or a small stepper, bounded to the
  API's existing `1–100` range) alongside the existing topic search form.
- Wire it into both `api.evidence()` call sites, replacing the hardcoded `20`.
- Pick a sensible default matching the current de facto behavior (`20`, not the API's own default
  of `10`) so existing usage patterns don't silently change.
- Persist the chosen value in the URL query string (matching how `EvidenceView` already handles
  `urlQ` for the topic), so a shared/bookmarked link reproduces the same result depth.

**Non-goals:**
- No change to `EvidenceRequest`'s server-side default or bounds.
- No config-level default for this (i.e., not reading from a new settings-screen field) — this is
  a per-search control, not a global preference. Revisit only if user feedback asks for a
  remembered default.

**Tests / verification:**
- Manual: change the control, confirm the request payload's `top_k` reflects it and result count
  changes accordingly.
- Confirm out-of-range input is clamped or rejected client-side before hitting the API's own
  `422` on an out-of-bounds value.

**Gate:** Evidence search results respect a user-adjustable `top_k`, bounded to `1–100`, with `20`
as the pre-filled default.

---

### WP-29.2 — Evidence View: Expandable Sources & Context

**Source:** Backlog item #10.

**Problem:** Evidence groups today only ever render `group.representative`
(`EvidenceView.tsx` line 200) — the count badge shows `"(N sources)"` but the other entries in
`group.sources` (which the API already fully populates, unconditionally) are silently discarded.
Separately, `context_text` per group is **not actually reachable via the API today**, despite the
backlog's original text assuming it was already returned: `api/routes/evidence.py`'s
`post_evidence()` hardcodes `show_context=False` (line 52) and `EvidenceRequest` has no field to
request it, so `evidence_service.build()`'s context-retrieval block never runs from this route —
every API response's `context_text` is currently always `None`. This is the same gap
`mcp_server/server.py`'s `map_evidence` has (also hardcodes `show_context=False`); only the CLI's
`--context` flag can reach it today.

**Scope:**
- **Backend (small, required for the context half of this WP):** add a `show_context: bool = False`
  field to `EvidenceRequest`, thread it into `post_evidence()`'s call to `evidence_service.build()`
  (replacing the hardcoded `False`). Mirrors the pattern already established for the CLI's
  `--context` flag — no changes to `evidence_service.build()` itself, which already supports this.
- **Frontend — show more sources:** render the non-representative entries in `group.sources`
  behind a toggle, reusing the one existing convention in this codebase for this kind of UI —
  `TraceView.tsx`'s "Show source context" pattern (lines 129–144/226–241): a null-state-driven
  button that becomes the content once revealed. No new component library or accordion needed.
- **Frontend — show context:** same lazy-reveal convention, gated behind the new `show_context`
  request field (only fetch/request context when the user asks, not on every search, so an
  evidence search that most users don't expand stays cheap — matches `TraceView`'s
  lazy-fetch-on-click behavior exactly, just via a request field instead of a second endpoint call).

**Non-goals:**
- No change to `mcp_server/server.py`'s `map_evidence` — it has the identical gap, but this phase
  is a GUI/API change; touching MCP's mirror of this route is separate work if wanted later (log
  to `docs/TODO_future_improvements.txt` if not folded into a future WP).
- No new shared `<Collapsible>`/`<Accordion>` component — reuse `TraceView`'s inline pattern as-is;
  extracting a shared component is only worth it if a third use case shows up.

**Tests / verification:**
- Confirm a group with >1 source shows all of them once expanded, matching the count badge.
- Confirm `context_text` is `null` until expanded, and populated correctly after, for a group that
  has it; confirm the toggle behaves the same for a group where it's genuinely absent (no crash on
  `null`).
- Confirm `EvidenceRequest` without `show_context` (the pre-existing default) behaves exactly as
  before — this must not become a breaking change for any existing caller.

**Gate:** Evidence view shows every source in a group (not just the representative) and can reveal
per-group context text on demand, without requesting context data on every search.

---

### WP-29.3 — Settings Screen: Config Service + API

**Source:** Backlog item #17 (backend half).

**Problem:** All of ReqBot's config lives in `~/.config/reqbot/config.json`, editable only by hand
over SSH. There is no save/write path anywhere in `core/config.py` (it only has `load()`) — the
only place config is ever written today is `cli/reqbot.py`'s `cmd_init()`, which constructs and
writes the file inline (lines ~1308–1324). No `services/config_service.py` exists, unlike every
other route in `api/routes/`, which all delegate to a matching `services/*.py` function. Building
a `GET`/`POST /config` pair directly against `cmd_init()`'s inline logic would create exactly the
kind of CLI/API divergence this project's architecture rule (and several Phase 27 WPs) exist to
prevent.

**Scope:**
- Add `services/config_service.py` with:
  - `get_config()` — wraps `core.config.load()`, plus computes which fields are currently sourced
    from a `REQBOT_*` env var (diff against `core.config._ENV_MAP`) rather than config.json/
    defaults. Returns both the effective values and that override set.
  - `update_config(partial: dict)` — **partial merge**, not full replace: reads the current
    config.json (or defaults if absent), overlays only the provided keys, validates, writes back
    with the same `chmod(0o600)` restrictive permissions `cmd_init()` already uses. Partial merge
    (not full-document PUT) so callers never need to know about every possible field to save a
    change to one of them, and can't accidentally clobber a field they don't set.
  - **Important:** `update_config()` itself accepts **any** valid `ReqBotConfig` field, including
    `processed_dir` and `authority_registry` — it is the same general-purpose write path
    `cmd_init()` needs (which must persist `processed_dir` on every init) and the settings API both
    use. The **editable-field restriction is enforced one layer up, in `api/routes/config.py`'s
    Pydantic request model**, not inside the service. (Codex/Gemini review, PR #129: the first
    draft of this WP had the service itself refuse `processed_dir`, which would have broken
    `cmd_init()`'s own write the moment it was refactored to call this function — the constraint
    belongs on the API's input schema, not the shared service capability.)
  - **API-editable field set** (enforced by `api/routes/config.py`'s request model, not by the
    service): `ollama_url`, `qdrant_url`, `default_model`, `extraction_model`, `enrichment_model`,
    `rewrite_model`, `synthesis_model`, `embedding_model`, `top_k`, `min_score`,
    `synthesis_backend`, `remote_provider`, `remote_model`, `api_key_env`. `processed_dir`,
    `authority_registry`, and `authority` are simply absent from that Pydantic model, so the API
    can't set them even though the underlying service function could if called directly (as
    `cmd_init()` does).
- Refactor `cmd_init()` to call `config_service.update_config()` (passing its full payload,
  `processed_dir` included) for the write, instead of constructing/writing the file inline a
  second time — one write path, matching this project's established "CLI/API/MCP share one
  service layer" rule.
- Add `api/routes/config.py`:
  - `GET /config` → `config_service.get_config()`'s result (effective values + override field
    names).
  - `POST /config` → validates the request body against the API-editable-field Pydantic model
    (above), then calls `config_service.update_config()` with the validated partial dict. (POST,
    not PUT — matches this codebase's existing convention; no route anywhere today uses PUT.)
  - Field bounds matching what's already implied elsewhere (`top_k`/`min_score` numeric ranges
    matching `EvidenceRequest`/`AskRequest` conventions; `synthesis_backend`/`remote_provider` as
    constrained string choices — confirm the actual valid `remote_provider` values, e.g.
    `anthropic`/`openai`, against `core/synthesis.py` during implementation rather than assuming).
  - **Loopback-only guard, specific to `POST`:** reject (403) any request whose `request.client.host`
    isn't `127.0.0.1`/`::1`, regardless of what interface `reqbot serve` is actually bound to. See
    Guardrail #7 for why this exists and what it isn't a substitute for.
- No caching to work around: every route already calls `core.config.load()` fresh per-request, so
  a `POST /config` write takes effect on the very next request for most fields — no server restart
  needed. **Exception: `embedding_model`** — see WP-29.4, this one needs different UX messaging,
  not the generic "takes effect immediately" framing.

**Non-goals:**
- No full-document replace semantics — see partial-merge design above.
- No change to `core.config.load()`'s precedence order (hardcoded → config.json → env) — the
  settings screen writes to config.json, same tier it already occupies; it does not add a new
  precedence tier or change how env vars interact with it.
- No general authentication/authorization system — that's backlog item "Authentication /
  multi-user hosting" (`docs/TODO_future_improvements.txt`, ROADMAP section), a materially bigger
  initiative than this phase takes on. The loopback guard above is a stopgap scoped to this one
  new mutating endpoint, not a first installment of that broader item.

**Tests / verification:**
- `GET /config` returns current effective values and correctly flags which fields are
  env-overridden (test with at least one `REQBOT_*` var set).
- `POST /config` with a partial body only changes the provided keys; re-`GET` confirms untouched
  fields (including `authority`/`authority_registry`/`processed_dir`, which aren't part of the
  *API's* editable set) are unaffected.
- `POST /config` rejects a request whose `request.client.host` isn't loopback, even when
  `reqbot serve` itself is bound to a non-loopback interface.
- `reqbot init` still produces an identical `config.json` after the `cmd_init()` refactor,
  `processed_dir` included — confirms the service-vs-route split above actually preserves this
  behavior rather than breaking it.
- Confirm a `POST /config` change is visible on the very next `GET /config` or any other route,
  with no server restart, for every field except `embedding_model` (see WP-29.4 for that one's
  actual, different behavior).

**Gate:** `GET`/`POST /config` exist, are backed by a shared `services/config_service.py` that
`cmd_init()` also uses (with `processed_dir` support intact), `POST /config` rejects non-loopback
requests, and the route correctly reports which fields are currently env-overridden.

---

### WP-29.4 — Settings Screen: Frontend

**Source:** Backlog item #17 (frontend half).

**Problem:** No `/settings` route exists (`frontend/src/App.tsx`'s current route list is `/search`,
`/compare`, `/evidence`, `/corpus(+detail)`, `/system`, `/checklists(+detail)`, `/trace/:reqId`),
and no nav entry exists in `SidebarNav.tsx`'s `NAV_ITEMS`. `/system` already displays 7 of these
fields today (`ollama_url`, `qdrant_url`, `embedding_model`, `extraction_model`,
`enrichment_model`, `rewrite_model`, `synthesis_model`) but read-only, sourced from `/api/status`,
not `/api/config` — the two screens serve different purposes (live health/status vs. editable
configuration) and should stay separate rather than merging, but the overlap in displayed fields
is worth being aware of so the two screens don't show inconsistent values if a user edits one and
doesn't realize the other exists.

**Scope:**
- New `/settings` route (`SettingsView`) + `SidebarNav.tsx` nav entry.
- Form covering WP-29.3's editable field set, following this codebase's existing conventions:
  - New `api.getConfig()` (GET, simple pattern) and `api.updateConfig()` (POST, detail-parsing
    error-handling pattern) in `frontend/src/api/client.ts`, plus corresponding types in
    `frontend/src/api/types.ts` (whose header comment tracking Python route files should be
    updated to include `config.py`).
  - Per-field validation matching the backend's bounds (client-side, backed by the server's own
    `422` as the actual source of truth — not a second, divergent validation implementation).
- Surface env-var overrides from `GET /config`'s response: any field currently sourced from a
  `REQBOT_*` env var shows an inline note ("currently overridden by `REQBOT_OLLAMA_URL`; this
  change will take effect once that variable is unset") rather than silently accepting an edit
  that won't do anything until the env var goes away. Still allow saving (pre-staging a value for
  later), just don't let the UI imply it took effect when it didn't.
- Confirmation/success messaging that reflects the real behavior confirmed in WP-29.3: changes
  take effect immediately (next request), not "restart required" — **except `embedding_model`**,
  which needs its own distinct warning instead of the generic success message (Codex review, PR
  #129): per `ARCHITECTURE.md`'s own documented behavior, `embedding_model` is "the highest-risk
  config edit in the system" — it takes effect for new indexing only, not retroactively; existing
  Qdrant points stay on the old model until a full `reqbot reindex`, and query time surfaces a
  non-blocking `warnings` entry on model/dimension mismatch (or fails loudly if the vector
  dimension itself differs). The settings screen must say this explicitly when this field
  changes — something like "Saved. This does not retroactively re-embed your existing corpus —
  run `reqbot reindex` afterward, or search results may show mismatch warnings until you do" — not
  the same "took effect immediately" copy used for every other field.
- `api_key_env` is rendered/edited as a plain text field for the *env var name* only — no field
  anywhere in this screen for an actual API key value, and no code path that could accept or
  display one.

**Non-goals:**
- No consolidation with `/system` — they stay separate screens with different jobs, per Problem
  above.
- No secret/API-key-value handling anywhere in this WP (see Phase-level Non-Goals).
- No automatic `reqbot reindex` trigger from the settings screen when `embedding_model` changes —
  reindexing is a substantial, potentially long-running operation (see
  [[project_reqbot_watchouts]]-style corpus-drift concerns); this WP only warns, it doesn't attempt
  to safely automate that operation from a web form.

**Tests / verification:**
- Manual: change a field other than `embedding_model`, save, confirm `GET /config` (and a
  subsequent unrelated request, e.g. `reqbot status`) reflects it without restarting the server.
- Manual: change `embedding_model` specifically, confirm the distinct reindex-warning message
  appears instead of the generic "took effect" success message.
- Manual: with a `REQBOT_*` env var set for a given field, confirm the UI surfaces the override
  note and does not claim the edit took effect.
- Confirm `api_key_env` never round-trips an actual secret value in any request/response body.

**Gate:** A working `/settings` screen lets a user view and edit every field in WP-29.3's
API-editable set from the GUI, correctly reflects env-var overrides, never touches an actual API
key value, and gives `embedding_model` changes their own accurate (not falsely reassuring) warning
rather than the generic "took effect immediately" message.

---

## 5. Success Gate

Phase 29 is complete when:

1. All four WPs are merged.
2. Full unit suite passes; `ruff check .` passes; frontend build passes.
3. Evidence view has a working `top_k` control and expandable sources/context.
4. A working `/settings` screen exists, backed by a shared `config_service.py` that both the API
   and `reqbot init` use — no duplicated config-write logic between them.
5. Backlog items #9, #10, and #17 in `docs/TODO_future_improvements.txt` are marked resolved.

---

## 6. Guardrails

1. No product-scope creep beyond the four WPs above — items #8 and #11 stay backlogged (see
   Non-Goals for why).
2. Each WP lands as its own PR, reviewed before proceeding to the next — same cadence as Phases
   27/28 (one WP at a time).
3. The settings screen must never handle an actual API key value — only `api_key_env` (the name).
   Any implementation detour toward accepting/displaying/round-tripping a real secret is a stop-
   and-ask moment, not a judgment call to make solo.
4. `config_service.update_config()` must be a partial merge, never a full-document replace — any
   field not included in a given call is preserved as-is, not reset to a default. This is what
   keeps a settings-screen save (which only ever sends the API-editable subset) from wiping
   `authority`/`authority_registry`/`processed_dir`, even though the service function itself is
   capable of writing those fields when a trusted caller like `cmd_init()` explicitly includes
   them.
5. The restriction to the API-editable field set belongs in `api/routes/config.py`'s Pydantic
   request model, never inside `config_service.update_config()` itself (Codex/Gemini review, PR
   #129 — the first draft got this backwards and would have broken `cmd_init()`'s own
   `processed_dir` write the moment it was refactored to share this function).
6. `cmd_init()`'s write path and the new API's write path must be the same function
   (`config_service.update_config()`), not two implementations that can drift — this is the whole
   point of WP-29.3 existing before WP-29.4.
7. `POST /config` must reject any request not originating from loopback (Codex review, PR #129 —
   ReqBot ships with no API authentication at all today, and CORS origin allowlisting is a
   browser-enforced convention that does nothing against a direct HTTP client). This is a stopgap
   scoped to this one new mutating, system-config-changing endpoint — it is not, and should not be
   described as, a first installment of the separate "Authentication / multi-user hosting" backlog
   item.
8. `embedding_model` changes must get their own accurate warning in the settings UI, not the
   generic "took effect immediately" message every other field gets (Codex review, PR #129 —
   `ARCHITECTURE.md` documents this as the highest-risk config edit in the system; it doesn't
   retroactively re-embed the existing corpus without a manual `reqbot reindex`).
9. Verify `remote_provider`'s actual valid values against `core/synthesis.py` during
   implementation — don't assume `anthropic`/`openai` are the only two without checking.
