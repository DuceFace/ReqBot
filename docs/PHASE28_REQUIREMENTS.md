# ReqBot Phase 28 — Frontend Toolchain & CI Security Hardening

**Status:** Locked (all three WPs scoped 2026-07-25; implementation starts at WP-28.1)
**Date:** 2026-07-25
**Preceded by:** Phase 27 (Service-Layer Hardening)
**Followed by:** TBD

---

## Status

This table is the live source of truth for Phase 28 WP status — update it here when a WP lands,
not in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-28.1 — React Router Patch Bump | Not started |
| WP-28.2 — Vite Major Upgrade (5.x → 8.x) | Not started |
| WP-28.3 — CI Security Scanning | Not started |

---

## 1. Phase Framing

Two Dependabot PRs have sat open against `frontend/` since 2026-06-04 (~7 weeks): #58 and #59,
both bumping Vite 5.4.21 → 8.0.16. #58 also bundles a same-major React Router patch bump
(6.30.3 → 6.30.4) into the same PR, which is why it couldn't just be fast-tracked — the trivial
patch bump is stuck behind the major-version migration decision. `docs/TODO_future_improvements.txt`
items #1–3 (Vite major upgrade, React Router maintenance updates, security scanning in CI) already
anticipated this work; this phase is where it actually gets done, plus finally clearing the two
stale Dependabot branches.

This phase is explicitly *not* about product features — no ReqBot behavior changes. It closes out
toolchain/CI debt that's been sitting on the backlog, on the user's explicit request to scope it
separately from the UX-polish work (settings/configuration screen, backlog item #17) picked as the
next feature track.

---

## 2. Goals

- Merge the React Router patch bump immediately (near-zero risk), unblocking PR #58's non-Vite
  half without waiting on the Vite migration.
- Migrate Vite 5.x → 8.x as our own deliberate PR (not a one-click Dependabot merge), following
  the migration checklist already in `docs/TODO_future_improvements.txt` item #1: confirm CI/local
  Node versions support Vite 8, run the frontend build, verify `@vitejs/plugin-react`, TypeScript,
  Tailwind, and PostCSS integration.
- Close PRs #58 and #59 once our own Vite PR supersedes them — no dangling redundant Dependabot
  branches left open.
- Add real CI-enforced security scanning (Python + frontend) — currently only GitHub's passive
  Dependabot alerts cover this repo; no SAST, no secret scanning, no code-scanning job runs
  alongside the existing pytest/ruff CI checks.

## 3. Non-Goals

- No product/feature work — the settings/configuration screen (backlog item #17) and any other
  UX polish is explicitly out of scope, scoped as its own separate track per the user's request.
- No retrieval quality work (reranking, multi-vector, etc.).
- No `requirements.txt` vs. `pyproject.toml` drift decision (backlog item #4) — unrelated
  toolchain question, not blocking this phase.
- No broader CI restructuring beyond adding the security-scanning job(s) themselves.

---

## 4. Work Packages

### WP-28.1 — React Router Patch Bump

**Source:** Dependabot PR #58 (bundles this with the Vite major bump). Backlog item #2.

**Problem:** `frontend/package.json` pins `react-router-dom` `^6.26.2`; Dependabot's PR #58 wants
6.30.3 → 6.30.4, a same-major patch release. Per backlog item #2 this class of update is
low-risk and should merge as soon as CI passes — but it's currently bundled into #58 alongside the
Vite major bump, so it can't be merged independently without manual intervention.

**Scope:**
- Bump `react-router-dom` (and `@remix-run/router` if pinned as a direct dependency) to 6.30.4 in
  our own small PR, independent of the Vite work.
- Confirm `npm run build` (or equivalent) succeeds and CI passes.
- Close PR #58 once superseded (its Vite half is picked up by WP-28.2 instead).

**Non-goals:**
- No Vite changes in this WP — kept deliberately separate so this can land fast.

**Tests / verification:**
- CI (lint/test/docker jobs) passes.
- Frontend build succeeds locally.

**Gate:** `react-router-dom` is on 6.30.4, PR #58 is closed (superseded), and this WP's diff
touches nothing else.

---

### WP-28.2 — Vite Major Upgrade (5.x → 8.x)

**Source:** Dependabot PRs #58 and #59. Backlog item #1.

**Problem:** `frontend/package.json` pins `vite` `^5.4.11`. Both open Dependabot PRs propose
5.4.21 → 8.0.16 — a 3-major-version jump (Vite 6, 7, 8), not a routine patch. Backlog item #1
already flags this needs to be treated as a toolchain migration, not a one-click Dependabot merge.

**Background:** The Dockerfile's frontend build stage pins `node:20-bookworm-slim`. Vite's Node
floor has moved with each major since 5.x; needs to be confirmed against whatever Vite 8 actually
requires before merging, not assumed.

**Scope:**
- Confirm the GitHub Actions runner's Node version and the Dockerfile's `node:20-bookworm-slim`
  both meet Vite 8's minimum Node requirement.
- Update local developer Node version guidance (README/CONTRIBUTING) if it changes.
- Bump `vite` to 8.0.16 (or whatever's current at implementation time) in our own PR.
- Run the frontend build; verify `@vitejs/plugin-react`, TypeScript, Tailwind, and PostCSS all
  still integrate correctly — these are exactly the integration points a Vite major tends to
  break silently (config option renames, plugin API changes).
- Manual smoke: `reqbot serve` with the rebuilt `frontend/dist/` — confirm the GUI actually loads
  and functions, not just that the build command exits 0.
- Close PRs #58 and #59 once this PR supersedes them both.

**Non-goals:**
- The original Dependabot security concern was about the Vite *dev server*; ReqBot's production
  deployment serves static files through `reqbot serve`, a different risk surface (per backlog
  item #1's existing note) — this WP is a version currency migration, not a response to an active
  vulnerability in ReqBot's own deployment.

**Tests / verification:**
- CI (lint/test/docker jobs) passes, including the docker job's "Verify the packaged frontend/dist
  is served" step.
- Manual smoke test of the built GUI (not just a green build).

**Gate:** `vite` is on 8.x, the frontend builds and serves correctly under `reqbot serve`, and
PRs #58 and #59 are both closed.

---

### WP-28.3 — CI Security Scanning

**Source:** `docs/TODO_future_improvements.txt` item #3.

**Problem:** Only GitHub's passive Dependabot alerts (dependency CVEs from manifest files,
surfaced on the Security tab) cover this repo today. No SAST, no secret scanning, no code-scanning
job runs in `.github/workflows/ci.yml` alongside the existing `lint`/`test`/`docker` jobs.

**Scope:**
- Add a Python SAST step (bandit, or equivalent) to CI, scoped to `core/`, `services/`, `api/`,
  `pipeline/`, `cli/`, `mcp_server/` — matching the existing `pytest --cov` module scope.
- Add a frontend security lint step (an ESLint security plugin) alongside whatever frontend CI
  step WP-28.2 needs (there is currently no standalone frontend build/lint CI job — only the
  `docker` job builds `frontend/dist` as part of the image; may need to add one, or hook the new
  check into that build step).
- Evaluate GitHub code scanning (CodeQL) as an alternative/addition — it runs as its own workflow
  rather than a `ci.yml` step, so decide whether it replaces or supplements bandit/ESLint-security.
- New job(s) must not block existing `lint`/`test`/`docker` jobs from running — additive, matching
  `ci.yml`'s existing `concurrency`/job structure.

**Non-goals:**
- Not fixing every finding a new scanner surfaces in this WP — the goal is getting the *coverage*
  in place. A first run may surface pre-existing findings; triage those as their own follow-up
  work (log to `docs/TODO_future_improvements.txt` if not trivial), don't let this WP balloon into
  a full remediation pass.

**Tests / verification:**
- New CI job(s) run successfully on a PR and report findings (or a clean pass) without breaking
  the existing `lint`/`test`/`docker` jobs.
- Confirm the job(s) actually gate on something meaningful (not a no-op scan with no rules
  enabled).

**Gate:** CI has a real, enforced security-scanning job for both Python and frontend code, running
on every PR alongside the existing checks.

---

## 5. Success Gate

Phase 28 is complete when:

1. All three WPs are merged.
2. Full unit suite passes; `ruff check .` passes; frontend build passes.
3. PRs #58 and #59 (the two stale Dependabot branches) are both closed.
4. CI runs real security scanning on every PR, not just passive Dependabot alerts.
5. Backlog items #1, #2, and #3 in `docs/TODO_future_improvements.txt` are marked resolved.

---

## 6. Guardrails

1. No product/feature changes in this phase — it's toolchain and CI only. The settings screen
   (item #17) and any other feature work stays out until Phase 28 closes.
2. Each WP lands as its own PR, reviewed before proceeding to the next — same cadence as Phase 27
   (one WP at a time).
3. Don't let WP-28.3 (CI security scanning) turn into a full remediation project — get coverage
   in place, log non-trivial findings as their own backlog items instead of fixing everything a
   new scanner surfaces in one PR.
4. Verify Vite 8's actual Node floor before merging WP-28.2 — don't assume `node:20-bookworm-slim`
   is sufficient without checking.
