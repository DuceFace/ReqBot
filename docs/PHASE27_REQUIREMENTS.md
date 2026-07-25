# ReqBot Phase 27 — Service-Layer Hardening (Phase 26 Review Cleanup)

**Status:** Complete — all three WPs shipped and merged
**Date:** 2026-07-24
**Preceded by:** Phase 26 (MCP Tool Surface)
**Followed by:** TBD

---

## Status

This table is the live source of truth for Phase 27 WP status — update it here when a WP lands,
not in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-27.1 — Validate `document_ids` in `core/ask.py` | Complete |
| WP-27.2 — Evidence Remote-Synthesis Backend Hardening | Complete |
| WP-27.3 — Evidence `document_ids` Filter | Complete |

---

## 1. Phase Framing

Phase 26 added ReqBot's MCP server. Codex and Gemini's automated reviews on PR #114 and PR #115
caught four real bugs in the *shared* service layer — code that predates MCP and is used
identically by the CLI and API — while reviewing the MCP tools that happen to call it. Per this
project's thin-wrapper rule, none of them were patched inside `mcp_server/server.py`; each was
logged as its own backlog item in `docs/TODO_future_improvements.txt` (items #12–15) for a
properly planned WP instead.

Phase 27 is that WP work: close out all four findings at the shared service layer so CLI, API,
and MCP all benefit identically, before starting any new feature phase.

---

## 2. Goals

- Fix all four Phase-26-discovered bugs at their actual root (service layer or shared route
  logic), not in MCP alone.
- Leave CLI, API, and MCP behaviorally consistent with each other for every change.
- Keep each WP small and independently reviewable, matching Phase 26's cadence (one WP at a
  time, review before proceeding).
- No unrelated cleanup — this phase is scoped to the four specific findings, not a general
  service-layer audit.

## 3. Non-Goals

- No new MCP tools, no new CLI commands, no new API routes beyond what's needed to expose an
  existing fix consistently.
- No retrieval quality work (reranking, multi-vector, etc. — tracked separately under
  "RETRIEVAL EXPERIMENTS" in `docs/TODO_future_improvements.txt`).
- No broader `document_id` vs. `source_pdf` naming/schema unification across the whole codebase
  — WP-27.3 resolves this only for evidence's filter, not everywhere the ambiguity exists.
- No touching `compare_service.py` — its `doc_keys`/`source_pdf` handling was reviewed in
  WP-26.4 and wasn't flagged.

---

## 4. Work Packages

### WP-27.1 — Validate `document_ids` in `core/ask.py`

**Source:** Codex review, WP-26.3 / PR #114. Backlog item #12.

**Problem:** `core/ask.py`'s `retrieve()` passes caller-supplied `document_ids` straight into a
Qdrant `MatchAny` filter (on the `source_pdf` field — confirmed via `build_query_filter()`) with
no existence check against the actual corpus. A typo'd or stale value doesn't error, it just
silently produces an empty or reduced hit set — indistinguishable from a legitimate no-match
query. This violates the Phase 26 architecture rule that invalid document keys must not be
hidden as fake empty results.

**Confirmed (2026-07-24):** hard error, not a warning. A stale/typo'd `document_ids` value is
invalid input, not a weak-search condition — returning empty results plus a warning is still too
easy to misread as "ReqBot searched correctly and found nothing." Raise a clear error listing the
bad document key(s). CLI/API/MCP must all surface the same behavior (API: 4xx; MCP: `ToolError`;
CLI: a clear error message, not a silent empty table).

**Confirmed (2026-07-24):** accept caller-friendly values. Callers should not need to know
internal storage details — accept both bare `doc_key` (`"afi17-101"`) and full `source_pdf`
(`"afi17-101.pdf"`) values, normalizing/resolving before searching, matching the tolerance
`compare_documents`/`compare_service` already have for the `.pdf` suffix.

**Scope:**
- Validate requested `document_ids` against the corpus's known documents before querying. **Do
  not reuse `api/routes/compare.py`'s `_canonical()` for this** (Codex review, PR #118) — it's
  intentionally forgiving, fabricating `<doc_key>.pdf` for anything it can't resolve, which is
  correct for compare's fallback UX but would defeat the hard-error requirement here by silently
  "resolving" an invalid name instead of rejecting it. Only normalize a value into its canonical
  `source_pdf` form after confirming it matches a known document.
- **As implemented (Codex P1 finding, PR #119) — resolve against the live Qdrant
  `grc_requirements` collection via `client.count()`, not `docs_service.list_docs()` /
  `resolve_source_pdfs()` (the JSONL/`processed_dir` layer originally scoped here).**
  `processed_dir` is not equivalent to what's actually indexed and searchable — `reqbot ingest
  --output-dir` and `reqbot index <arbitrary path>` can index a document whose JSONL never
  touches `processed_dir`, which would make a JSONL-based check wrongly reject real, searchable
  `document_ids` values. Qdrant is the only source of truth for "is this actually searchable."
  Landed as `core.ask.resolve_document_ids(client, document_ids)`.
- On any unresolved value(s), raise a clear error naming the bad document key(s) — do not query
  Qdrant with them.
- Apply the fix in `core/ask.py` / `services/ask_service.py` so `search_requirements` (MCP),
  `/ask` (API), and `reqbot ask` (CLI) all inherit it identically — no MCP-only code.

**Non-goals:**
- No change to `compare_service.py` (already resolves doc_key/source_pdf; not flagged) or to
  `evidence_service.py`'s `document_ids` handling (WP-27.3's concern).

**Tests / verification:**
- Unit test: a `document_ids` value not present in the corpus raises a clear error naming the bad
  value(s) — never a silent empty/reduced result.
- Unit test: a valid `document_ids` value works identically whether passed as `doc_key` or as
  `source_pdf`.
- Unit test: `search_requirements` (MCP), `/ask` (API), and `reqbot ask` (CLI) all raise/surface
  the same error for the same bad input — no forked logic.
- Regression: existing `ask`/`search_requirements` tests continue passing.

**Gate:** A stale or typo'd `document_ids` value always raises a clear, actionable error —
never a fake empty success — identically across CLI, API, and MCP.

---

### WP-27.2 — Evidence Remote-Synthesis Backend Hardening

**Source:** Codex review (wrong model field) + Gemini review (`None` crash risk), both
WP-26.4 / PR #115. Backlog items #13 and #15. Bundled into one WP because both bugs live in the
exact same few lines, in the exact same two call sites (`api/routes/evidence.py`'s
`post_evidence()` and `mcp_server/server.py`'s `map_evidence()`) — fixing one without the other
means touching this code twice.

**Problem 1 (item #13):** Both call sites always pass `cfg.synthesis_model` (the local Ollama
model) into `evidence_service.build()`'s `synthesis_model` kwarg, even when
`synthesis_backend == "remote"`. `core.config.ReqBotConfig` has a separate `remote_model` field
(default `"claude-sonnet-4-6"`) specifically for the remote path. Today, a remote-configured
evidence synthesis request sends a local Ollama model name to Anthropic/OpenAI, the call fails,
and `core.synthesis.synthesize()`'s caller swallows the exception — so the caller just gets an
empty `synthesis_text` with no visible error, silently degrading instead of using the remote
model that was actually configured.

**Problem 2 (item #15):** Both call sites call `os.environ.get(cfg.api_key_env, "")`
unconditionally when `synthesis_backend == "remote"`. `api_key_env` defaults to
`"ANTHROPIC_API_KEY"` but has no `REQBOT_*` env var mapping — it's only settable by hand-editing
`~/.config/reqbot/config.json`. `ReqBotConfig.load()` uses `values.get(key, default)`, so an
explicit `null` in the file is not replaced by the default. `os.environ.get(None, "")` raises
`TypeError` — an unhandled crash instead of the intended graceful fallback to the local backend.

**Confirmed (2026-07-24):** direction as drafted — centralize remote/local synthesis model
selection and guard `api_key_env=None` so CLI/API/MCP cannot drift on either again.

**Scope:**
- Select `cfg.remote_model` when `synthesis_backend == "remote"`, `cfg.synthesis_model` when
  `"local"`. Centralize this selection in one place both call sites use — a small helper
  (candidate location: `core/config.py` or a new function in `services/evidence_service.py`
  itself, since the backlog note flagged that `evidence_service.build()` doing this internally
  would prevent CLI/API/MCP from drifting on it again) rather than duplicating an if/else in
  three places (CLI's `cmd_evidence` has its own copy of this pattern too — worth checking
  whether it has the same bug while this code is being centralized).
- Guard `os.environ.get(cfg.api_key_env, "")` against `cfg.api_key_env` being `None` — either
  `if cfg.api_key_env else ""` at the call sites, or (better, since it prevents the invalid state
  from being reachable at all) make `ReqBotConfig.load()` reject/normalize a `null`
  `api_key_env` at load time.

**Non-goals:**
- No change to `core/synthesis.py` itself — the bug is in what gets passed in, not in the
  synthesis functions.
- No new remote providers or provider-selection logic.

**Tests / verification:**
- Unit test: `synthesize=True` with `synthesis_backend="remote"` and a real key present passes
  `cfg.remote_model` to the synthesis call, not `cfg.synthesis_model`.
- Unit test: `synthesis_backend="local"` still passes `cfg.synthesis_model` (no regression).
- Unit test: `cfg.api_key_env = None` with `synthesis_backend="remote"` falls back to local
  cleanly instead of raising `TypeError`.
- Regression: existing evidence tests (API, MCP, CLI) continue passing.

**Gate:** A correctly configured remote synthesis backend is actually used for evidence
synthesis, and a misconfigured one degrades gracefully instead of crashing — verified for
CLI, API, and MCP.

---

### WP-27.3 — Evidence `document_ids` Filter

**Source:** Gemini review, WP-26.4 / PR #115. Backlog item #14.

**Problem:** `api/routes/evidence.py`'s `EvidenceRequest` and `mcp_server/server.py`'s
`map_evidence` both hardcode `document_ids=None` into `evidence_service.build()`, even though
the service itself accepts a `document_ids` filter and the CLI exposes it
(`reqbot evidence --document-id`). The API and MCP surfaces are narrower than the CLI here.

**Background:** `evidence_service.build()`'s existing `document_ids` filter matches on the Qdrant
payload's internal `document_id` field (a hash like `"b25aadb2b57dd930"`), *not* `source_pdf`
(`"afi17-101.pdf"`) or `doc_key` (`"afi17-101"`) the way `core/ask.py`'s `document_ids` filter or
`compare_service`'s `doc_keys` do. The CLI's existing `reqbot evidence --document-id` flag
already has this same problem today — a user would have to already know an opaque internal hash
to filter by document, which isn't discoverable anywhere in normal usage. Pre-existing CLI UX
gap, not something WP-26.4/MCP introduced.

**Confirmed (2026-07-24):** option 2 — fix the root problem, not just the API/MCP surface.
Change `evidence_service.build()`'s `document_ids` filter to match on caller-facing `doc_key`/
`source_pdf` values, the same resolution approach `compare_service`/`ask.py` use, not the
internal hash. The hash-based filter is thin-wrapper-correct but product-wrong — it exposes an
identifier normal users and MCP clients cannot reasonably know. This fixes the CLI's existing
`--document-id` behavior at the same time; API and MCP then mirror the corrected behavior rather
than each independently working around the old hash-based filter. Wider blast radius than the
other two WPs in this phase, but accepted because it fixes the root problem across all surfaces
in one pass instead of leaving the CLI broken while API/MCP get a new parameter.

**Scope:**
- Change `evidence_service.build()`'s `document_ids` filtering to resolve/match on `doc_key`/
  `source_pdf`, not the internal `document_id` hash. **As implemented — reuses
  `core.ask.resolve_document_ids()` (WP-27.1's Qdrant-backed resolver), not
  `docs_service.resolve_source_pdfs()`.** Keeps a single resolution implementation instead of two
  parallel ones (JSONL-based vs. Qdrant-based) that could drift, and avoids reintroducing the
  exact `processed_dir` != indexed-corpus gap WP-27.1's Codex P1 finding fixed. The Qdrant filter
  field itself also changed from `document_id` to `source_pdf` to match.
- Update `reqbot evidence --document-id` (CLI) to pass through caller-facing values now that the
  service accepts them correctly — confirmed no CLI-side translation layer was relying on the old
  hash behavior; the flag already passed `document_ids` straight through, so the service-layer fix
  alone resolved the CLI's UX gap. Help text updated to name `doc_key`/`source_pdf` explicitly.
- Add `document_ids: list[str] | None` to `EvidenceRequest` (API) and thread it through
  `post_evidence()`.
- Add the matching `document_ids` parameter to `map_evidence` (MCP), mirroring the corrected API
  exactly — MCP should not get a filter shape the API doesn't already expose (thin-wrapper rule).
- Unknown `document_ids` raise the same `ValueError` → 404 (API) / `ToolError` (MCP) / rc=1 (CLI)
  shape WP-27.1 established for `/ask`, `search_requirements`, and `reqbot ask`.

**Non-goals:**
- No change to `search_requirements`'s or `compare_documents`'s existing `document_ids`/
  `doc_keys` handling — those already resolve caller-facing values correctly; only evidence's is
  being touched.

**Tests / verification:**
- Unit test: `evidence_service.build()` accepts `doc_key` and `source_pdf` values and filters
  correctly (no more hash requirement).
- Unit test: `map_evidence` and `/evidence` both pass a supplied `document_ids` through to
  `evidence_service.build()` correctly.
- Unit test: `reqbot evidence --document-id` works with a caller-facing value end-to-end.
- Unit test: omitting `document_ids` behaves exactly as it does today (no regression).
- Manual smoke: filtering an evidence request to one known document (by `doc_key`) returns only
  that document's sources, via CLI and via MCP.

**Gate:** `reqbot evidence --document-id`, `/evidence`, and `map_evidence` all support the same
document-scoping using a filter value a caller can actually be expected to have — no interface
still requires the internal hash.

---

## 5. Success Gate

Phase 27 is complete when:

1. All three WPs are merged.
2. Full unit suite passes; `ruff check .` passes.
3. None of the four original findings (backlog items #12–15) remain open in
   `docs/TODO_future_improvements.txt` — remove or mark resolved as each WP lands.
4. CLI, API, and MCP behave identically for every change in this phase — no interface-specific
   forks introduced while fixing these.
5. No new bugs of the same shape (MCP-only patches, un-validated filter inputs, silently
   swallowed remote-backend failures) introduced in the process.

---

## 6. Guardrails

Carried forward from Phase 26, still binding:

1. Do not add MCP-only business logic. Every fix in this phase lands in the shared service/route
   layer; MCP inherits it, it does not implement its own copy.
2. Do not hide backend failures as empty results — this is the exact failure mode WP-27.1 and
   WP-27.2 are fixing; don't introduce a new instance of it while doing so.
3. Do not widen scope beyond the four findings this phase exists to close, plus what WP-27.3
   explicitly takes on (fixing `reqbot evidence --document-id`'s hash-filter bug as part of
   fixing `evidence_service.build()`'s filter at its root — that's in scope, not an example of
   scope creep). New ideas surfaced while working these WPs beyond what's already scoped above
   (e.g. whether `evidence_service.build()`'s call-site duplication should be refactored further)
   go back into `docs/TODO_future_improvements.txt`, not into this phase's diff.
