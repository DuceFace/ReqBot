# ReqBot Phase 28 — Frontend Toolchain & CI Security Hardening

**Status:** Locked (all three WPs scoped 2026-07-25; revised same day after Codex review to
resolve open decisions below; implementation starts at WP-28.1)
**Date:** 2026-07-25
**Preceded by:** Phase 27 (Service-Layer Hardening)
**Followed by:** TBD

---

## Status

This table is the live source of truth for Phase 28 WP status — update it here when a WP lands,
not in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-28.1 — React Router Patch Bump | Complete |
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
- Keep the air-gapped/self-hosted packaging posture intact: new dev/scanner dependencies are fine,
  but Docker image build and package-install paths must stay boring and reproducible — no new
  runtime dependency on a hosted service the self-hosted deployment can't reach.

## 3. Non-Goals

- No product/feature work — the settings/configuration screen (backlog item #17) and any other
  UX polish is explicitly out of scope, scoped as its own separate track per the user's request.
- No retrieval quality work (reranking, multi-vector, etc.).
- No `requirements.txt` vs. `pyproject.toml` drift decision (backlog item #4) — unrelated
  toolchain question, not blocking this phase.
- No broader CI restructuring beyond adding the security-scanning job(s) themselves.
- No dependency-management philosophy change (npm vs. pnpm, Python lockfile strategy) — this phase
  may add or bump dependencies but doesn't decide tooling strategy questions like that.

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
- Keep the diff to `frontend/package.json` / `frontend/package-lock.json` unless the build surfaces
  an unavoidable import/API change.
- Confirm `npm run build` (or equivalent) succeeds and CI passes.
- Do **not** close PR #58 in this WP — it also carries the Vite bump, which isn't superseded until
  WP-28.2 lands. Closing it here would drop the Vite half unresolved. Leave #58 open; it gets
  closed as part of WP-28.2 once that PR supersedes both halves.

**Non-goals:**
- No Vite changes in this WP — kept deliberately separate so this can land fast.

**Tests / verification:**
- CI (lint/test/docker jobs) passes.
- Frontend build succeeds locally.
- Quick manual route smoke (`/search`, `/compare`, `/evidence`, `/corpus`, `/system`) to confirm no
  router errors — same-major patch bumps are low-risk but router internals are exactly the kind of
  thing that can silently regress a route.

**Gate:** `react-router-dom` is on 6.30.4 in `main`, CI passes, and this WP's diff is limited to
dependency metadata unless a documented route/build issue forced a code change. PR #58 stays open
until WP-28.2 supersedes it.

---

### WP-28.2 — Vite Major Upgrade (5.x → 8.x)

**Source:** Dependabot PRs #58 and #59. Backlog item #1.

**Problem:** `frontend/package.json` pins `vite` `^5.4.11`. Both open Dependabot PRs propose
5.4.21 → 8.0.16 — a 3-major-version jump (Vite 6, 7, 8), not a routine patch. Backlog item #1
already flags this needs to be treated as a toolchain migration, not a one-click Dependabot merge.

**Background:** The Dockerfile's frontend build stage pins `node:20-bookworm-slim`. Vite's Node
floor has moved with each major since 5.x and Vite 8's build pipeline has changed further from the
5.x defaults — treat both the exact Node floor and the scope of internal changes as things to pull
from the released Vite 8 changelog at implementation time, not assumptions baked into this doc now.

**Version target:** prefer the latest stable 8.x release available when WP-28.2 starts over the
stale Dependabot target (8.0.16) — no beta/pre-release. Record the chosen version in the PR
description along with the changelog link it was checked against.

**Scope:**
- Confirm the GitHub Actions runner's Node version and the Dockerfile's `node:20-bookworm-slim`
  both meet Vite 8's actual minimum Node requirement (check the released changelog, don't assume).
  If the current image tag falls short, bump to a newer `node:20` patch tag first, or to
  `node:22-bookworm-slim` if that's what Vite 8 actually needs — prefer the smaller bump unless
  verification shows it's insufficient.
- Update local developer Node version guidance (README/CONTRIBUTING) if it changes.
- Bump `vite` to the chosen stable 8.x version in our own PR.
- Inspect `frontend/vite.config.*`, `frontend/tsconfig*`, `frontend/postcss.config.*`, and
  `frontend/tailwind.config.*` for deprecated/renamed options the major bump affects. If nothing
  needs changing, say so explicitly in the PR rather than leaving it unaddressed.
- Run the frontend build; verify `@vitejs/plugin-react`, TypeScript, Tailwind, and PostCSS all
  still integrate correctly — these are exactly the integration points a Vite major tends to
  break silently (config option renames, plugin API changes).
- Manual smoke: `reqbot serve` with the rebuilt `frontend/dist/` — confirm the GUI actually loads
  and functions, and that `/assets/*` paths resolve correctly (a Vite migration can pass the build
  step but still serve wrong static asset paths under `reqbot serve`).
- Close PRs #58 and #59 once this PR supersedes them both (WP-28.1's router bump plus this WP's
  Vite bump together cover everything in #58).

**Non-goals:**
- The original Dependabot security concern was about the Vite *dev server*; ReqBot's production
  deployment serves static files through `reqbot serve`, a different risk surface (per backlog
  item #1's existing note) — this WP is a version currency migration, not a response to an active
  vulnerability in ReqBot's own deployment.

**Tests / verification:**
- `cd frontend && npm ci && npm run build`.
- CI (lint/test/docker jobs) passes, including the docker job's "Verify the packaged frontend/dist
  is served" step.
- Manual smoke test of the built GUI (not just a green build), including `/assets/*` loading.

**Gate:** `vite` is on 8.x, the frontend builds and serves correctly under `reqbot serve`, and
PRs #58 and #59 are both closed.

---

### WP-28.3 — CI Security Scanning

**Source:** `docs/TODO_future_improvements.txt` item #3.

**Problem:** Only GitHub's passive Dependabot alerts (dependency CVEs from manifest files,
surfaced on the Security tab) cover this repo today. No SAST, no secret scanning, no code-scanning
job runs in `.github/workflows/ci.yml` alongside the existing `lint`/`test`/`docker` jobs.

**Scanner stack (decided, not left open for implementation time):** CodeQL for Python +
JavaScript/TypeScript SAST, as its own GitHub code-scanning workflow (not a `ci.yml` step) —
it covers both languages without adding project dependencies, which fits the "keep the toolchain
boring" framing of this phase. Secret scanning is a separate control CodeQL does **not** provide —
add it explicitly (GitHub secret scanning if enabling it for this repo is available and free at
our plan tier, otherwise gitleaks as a CI step). Do not describe CodeQL as covering secret
scanning; it doesn't.

**Scope:**
- Add a CodeQL workflow covering Python (scoped to `core/`, `services/`, `api/`, `pipeline/`,
  `cli/`, `mcp_server/` — matching the existing `pytest --cov` module scope) and
  JavaScript/TypeScript (`frontend/`).
- Add secret scanning per the decision above (GitHub secret scanning or gitleaks-in-CI).
- If the repo still lacks a standalone frontend CI job after WP-28.2, this is a reasonable point
  to add one, rather than hiding frontend scanning inside the Docker image build.
- New job(s) must not block existing `lint`/`test`/`docker` jobs from running — additive, matching
  `ci.yml`'s existing `concurrency`/job structure.
- Prefer "report and gate on high-confidence issues" over an aggressive ruleset that floods the
  repo with low-value warnings on the first run. Document any intentional rule exclusions in
  scanner config, not as scattered inline suppressions, unless there's no cleaner option.

**Non-goals:**
- Not fixing every finding a new scanner surfaces in this WP — the goal is getting the *coverage*
  in place. A first run may surface pre-existing findings; triage those as their own follow-up
  work (log to `docs/TODO_future_improvements.txt` if not trivial), don't let this WP balloon into
  a full remediation pass.
- Not adding paid/vendor-hosted scanners beyond what's already free at our GitHub plan tier —
  keep the baseline usable without a new recurring cost.
- Not building automatic secret-revocation workflows — detecting a leaked secret is in scope,
  responding to one is not.

**Tests / verification:**
- New CI job(s) run successfully on a PR and report findings (or a clean pass) without breaking
  the existing `lint`/`test`/`docker` jobs.
- Confirm the job(s) actually gate on something meaningful (not a no-op scan with no rules
  enabled) and actually trigger on pull requests, not just `main` or manual dispatch — a scanner
  that doesn't run on the PR path doesn't protect the review path.
- Confirm a scanner failure produces a message a maintainer can act on from the Actions log
  without needing security-specialist background.

**Gate:** CI has a real, enforced security-scanning job for both Python and frontend code
(SAST + secret scanning), running on every PR alongside the existing checks.

---

## 5. Success Gate

Phase 28 is complete when:

1. All three WPs are merged.
2. Full unit suite passes; `ruff check .` passes; frontend build passes.
3. PRs #58 and #59 (the two stale Dependabot branches) are both closed.
4. CI runs real security scanning on every PR, not just passive Dependabot alerts.
5. Backlog items #1, #2, and #3 in `docs/TODO_future_improvements.txt` are marked resolved.
6. README/CONTRIBUTING/operations docs don't contain stale Node or Vite version guidance left over
   from before the migration.

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
5. Don't close PR #58 until *both* halves it bundles (router patch, Vite major) are actually
   superseded on `main` — see the fixed sequencing in WP-28.1/WP-28.2 above. Close both #58 and #59
   manually with a short comment referencing the superseding PR, rather than leaving them to
   whatever GitHub's auto-stale behavior does.
6. The WP-28.3 scanner job(s) must trigger on pull requests. A job that only runs on `main` or on
   manual dispatch doesn't gate the review path and doesn't satisfy this phase's goal.
7. Don't let a stale Dependabot-proposed version (Vite 8.0.16) dictate the final version merged if
   a newer stable 8.x release exists by implementation time.
