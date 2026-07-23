# ReqBot - Phase 24: Product Cleanup and Sane Defaults

**Status:** Draft
**Date:** 2026-07-22
**Preceded by:** Phase 23 (Checklist Output Polish + Trust Hardening)
**Followed by:** Phase 25 candidate: MCP Tool Surface

---

## 1. Phase Framing

Phase 23 made ReqBot outputs easier to inspect and trust: checklist preview polish, XLSX export,
structural extraction warnings, profile skip-section filtering, and a truncation recovery flag.

Phase 24 should make ReqBot less weird to configure and operate. This is a cleanup phase focused
on first-run setup, indexing defaults, rebuild behavior, old flags that no longer match the
current product shape, and giving the resulting commands a real corpus to prove themselves against.

MCP remains strategically important, but it does not fit this phase's theme. MCP should wait until
the human-facing setup and operational paths are boring, predictable, and easy to explain.

Five findings drive this phase:

1. **First-run setup is fragmented, not just misnamed.** `reqbot setup`, `reqbot setup --advanced`,
   and `reqbot init` are three names for overlapping first-run behavior — `setup --advanced`
   already just calls `cmd_init` verbatim. There should be exactly one first-run command that asks,
   per service, whether to point at an existing instance or have ReqBot bootstrap one locally.
2. **`reqbot reindex` is incomplete.** It is the natural "rebuild ReqBot" command, but it does not
   rebuild everything a user expects. It rebuilds the requirements index only, does not rebuild
   `grc_context`, and has historically preferred normalized JSONL even when enriched JSONL exists.
   The requirements rebuild already has a safer temp-collection/alias-swap pattern; context should
   use the same pattern instead of being rebuilt in place if the current Qdrant helpers allow it.
   Because rebuilding context touches substantially more points than requirements and runs through
   a CPU-bound local embedding path, a fast requirements-only path must ship alongside the new
   default, not as an afterthought.
3. **Normal ingest should produce a usable document.** `reqbot ingest <pdf>` currently requires
   `--index` to make the document searchable. For normal users, forgetting `--index` is a footgun.
4. **HyDE already earned promotion; `--full-extraction` did not.** `--full-extraction` points back
   to the old single-pass extraction path with no supported use case. HyDE, by contrast, is a spike
   that already passed its Phase 15 evaluation gate (≥3 queries improved, none degraded, no
   hallucinated IDs) and was simply never wired into the main CLI. Leaving it in standalone-flag
   limbo indefinitely is the same kind of unresolved state this phase exists to close — it should
   be wired in and turned on by default, with a fast-mode opt-out, not kept experimental forever.
5. **The live corpus predates this phase's fixes and carries known quality warnings.** Phase 24's
   cleanup commands need a real refresh to prove themselves against, not just mocked tests — this
   phase should include a small, representative corpus refresh rather than deferring it again.

---

## 2. Goals

- Collapse `reqbot setup`, `reqbot setup --advanced`, and `reqbot init` into a single guided
  first-run command. The command asks, per service (vector DB, LLM/synthesis), whether to point at
  an existing instance or have ReqBot bootstrap one locally — no separate subcommand or hidden flag
  required to reach either path.
- Tighten guided synthesis configuration so "none/retrieval-only" is an explicit choice rather
  than falling through to local synthesis.
- Make `reqbot ingest <pdf>` index by default, with `--no-index` as the debug/artifact-only escape
  hatch.
- Make the normal reindex path rebuild the same usable system that normal ingest creates.
- Ensure reindex prefers enriched requirement JSONL when enrichment exists, falling back to
  normalized JSONL only when enrichment was skipped or unavailable.
- Rebuild the context collection from existing chunk JSONL through a clear command path, using a
  safe temp-collection/alias-swap pattern if supported by the existing Qdrant indexing helpers.
- Ship `reqbot reindex --requirements-only` as a first-class fast path in the same WP as the
  default-both behavior — rebuilding `grc_context` meaningfully increases reindex runtime on the
  CPU-bound embedding path, and a full rebuild should not be the only option.
- Keep low-level `index` and `index-context` commands available for repair/debug workflows.
- Remove or explicitly retire unsupported legacy flags such as `--full-extraction`.
- Wire HyDE into the main `reqbot ask` CLI path and turn it on by default — it already passed its
  Phase 15 evaluation — with an explicit opt-out for users who want faster baseline-only retrieval.
  User-facing framing: HyDE-on is normal mode; the opt-out is presented as a speed tradeoff ("fast
  mode" / "lightning mode" — exact label TBD) across CLI help, docs, and the frontend, not as an
  advanced/experimental toggle. The underlying flag/field stays `--no-hyde` / `hyde: false` for
  consistency with existing `--no-*` CLI naming (`--no-rewrite`, `--no-index`) — only the
  user-facing copy changes, not the technical name.
- Keep context **indexing** default-on for normal ingest/reindex, but keep context **display** opt-in
  until the output quality/noise tradeoff is tested.
- Refresh a representative slice of the indexed corpus (4-5 documents) using the current pipeline,
  to resolve known quality warnings and to validate this phase's ingest/reindex defaults against
  real data.
- Update README and operations docs so normal users see the simple path first.

---

## 3. Non-Goals

Explicitly out of scope for Phase 24:

- MCP tool surface implementation. Candidate for Phase 25.
- Re-running LLM extraction as part of reindex.
- Migrating or backfilling old Step C cache artifacts.
- Changing JSONL schema or file naming.
- Replacing Qdrant, Ollama, or the embedding model.
- Removing local/offline setup support — local bootstrap becomes a branch of the single first-run
  command, not a removed capability.
- Rewriting Docker setup or the local-stack bootstrap mechanics from scratch — reuse the existing
  install/pull logic, just invoke it conditionally from the merged flow.
- Adding authentication, multi-user hosting, or SaaS deployment assumptions.
- Adding ingest/upload UI.
- Adding job history or long-running task orchestration.
- Adding audit-question generation.
- Adding assessor-note persistence or merge-on-regeneration.
- Adding new retrieval experiments beyond promoting the already-evaluated HyDE spike — rerankers,
  multi-vector indexing, and HyPE remain out of scope. HyPE specifically was tried and set aside:
  ingest-time hypothetical-question generation produced hallucinated/off-target questions, and
  doing it across the current corpus would have added multiple days to ingestion. It may have
  merit at a different scale or with a different prompting approach, but not for this corpus today.
- Re-running the Phase 15 HyDE evaluation from scratch — the existing gate is the promotion
  evidence; this phase wires it in, it does not re-litigate it.
- Making `--context` output default-on across `ask`, `trace`, and `evidence` without testing.
- Re-ingesting the full 45-document corpus — the refresh targets a representative 4-5 document
  subset, not a full corpus rebuild.
- Gold-set curation for retrieval quality (still deferred from Phase 15).
- Adding new pip/npm dependencies unless explicitly approved in this document.

---

## 4. Approved New Dependencies

No new dependency is approved by default for Phase 24.

This phase should be mostly CLI/config/orchestration cleanup. If a proposed implementation requires
a new dependency, stop and get explicit approval before adding it.

---

## 5. Architecture Rules

All Phase 18 through Phase 23 architecture rules carry forward:

1. **Setup is a single command, service-agnostic by default.** There is one first-run entry point;
   it asks per-service whether to use an existing instance or bootstrap one locally. There is no
   separate `setup` / `setup --advanced` split.
2. **Lazy model pulls must be explicit/local-only.** Auto-pulling synthesis models is acceptable
   only for local Ollama synthesis users and must be documented or warned before use.
3. **Normal CLI commands should do the normal product thing.** `ingest` should make a document
   usable unless the user explicitly asks for artifact-only/debug behavior.
4. **JSONL remains the source of record.** Qdrant is rebuildable state. Reindex must read existing
   artifacts and must not invoke Step C or Step D.5 LLM work.
5. **Prefer enriched artifacts when available.** If both `*_requirements_enriched.jsonl` and
   `*_requirements_normalized.jsonl` exist for a document run, indexing should use enriched JSONL.
   Fallback to normalized JSONL is correct only when enrichment was skipped or failed.
6. **Context indexing is part of retrieval readiness, but it must not be the only rebuild speed.**
   A fully usable indexed corpus includes both `grc_requirements` and `grc_context` when chunk
   artifacts exist, rebuilt with the same safe alias-swap pattern where supported — but a
   requirements-only fast path must exist for users who don't need the slower full rebuild.
7. **Context output is a presentation choice.** Do not make surrounding context text default-on in
   command output until the noise/usefulness tradeoff is tested.
8. **Low-level commands stay available.** `index <requirements_jsonl>` and
   `index-context <chunks_jsonl>` remain advanced repair/debug commands.
9. **Do not keep dead flags.** If a flag points to an unsupported legacy/spike path, either make it
   a real product feature or remove it. `--full-extraction` fails this test and is removed; HyDE
   passes it (it already has a positive evaluation) and is promoted.
10. **HyDE is default-on retrieval with a fast-mode opt-out.** This reflects a passed Phase 15
    evaluation gate, not a new experiment — no further retrieval-quality evaluation is required to
    ship it.
11. **One WP at a time.** Get Codex/Gemini review after each work package before proceeding.

**Safety test:**

- Can a user configure ReqBot against existing Qdrant/Ollama/remote synthesis services without
  Docker installation or local model pulls? -> **Yes**
- Can `reqbot ingest <pdf>` produce a searchable/indexed document by default? -> **Yes**
- Can `reqbot ingest <pdf> --no-index` still produce artifacts only for debugging? -> **Yes**
- Can `reqbot ingest <pdf>` and `reqbot reindex` produce equivalent retrieval readiness from the
  same artifacts? -> **Yes**
- Can `reqbot reindex --requirements-only` skip the context rebuild entirely for a fast partial
  rebuild? -> **Yes**
- Can `reqbot reindex` run without Ollama generation work? -> **Yes**
- Can `ask --context` work after a rebuild without a manual context indexing loop? -> **Yes**
- Can `ask` without `--context` still return tight requirement-focused output? -> **Yes**
- Does `reqbot ask` use HyDE by default while still offering a fast baseline-only path via flag?
  -> **Yes**

If any answer becomes no, the design has drifted.

---

## 6. Current Behavior Audit

### Setup/config behavior

This audit is the starting assumption for WP-24.1 and should be verified against the current code
before implementation:

| Command | Current behavior | Problem |
|---|---|---|
| `reqbot setup` | Opinionated local-stack bootstrap: Docker Qdrant, local Ollama install/pulls, localhost config. | Sounds generic but assumes a niche all-local install; should not exist as a separate documented first-run path once merged. |
| `reqbot setup --advanced` | Delegates verbatim to `cmd_init`. | Already a second name for `reqbot init` — redundant, not just "hidden behind advanced." |
| `reqbot init` | Interactive config wizard, including local/remote synthesis prompts. | Correct concept; becomes the single first-run command once `setup`/`setup --advanced` fold into it. Missing UX: an explicit none/retrieval-only synthesis choice, and the per-service local-bootstrap branch that `setup` currently owns separately. |
| Lazy synthesis model pull | Pulls local synthesis model on first local synthesis use. | Correct only for local Ollama users; surprising if the merged command did not make that clear. |
| `~/.local/bin/reqbot` launcher | May point at an old install path on some systems. | Tiny but high-value operations cleanup if confirmed. |

Known problem:

- Users with managed Qdrant, remote Ollama, company LLM endpoints, or no admin rights should not
  be pushed into a Docker/local model installer as the default first-run experience.
- Existing config prompts already cover local vs remote synthesis, provider, model, and API-key
  environment variable names. The current gap is narrower: users need an explicit
  none/retrieval-only choice so declining remote synthesis does not silently become local synthesis.
- Three overlapping first-run entry points (`setup`, `setup --advanced`, `init`) make it unclear
  which one a new user should run — `setup --advanced` is functionally redundant with `init` today.
- A stale local launcher path can make the correct codebase appear broken from the user's shell.

### Indexing behavior

This audit is the starting assumption for WP-24.2 and WP-24.3 and should be verified against the
current code before implementation:

| Command | Requirements indexing | Context indexing | Notes |
|---|---|---|---|
| `reqbot ingest <pdf> --index` | Yes | Yes | Happy path already indexes both collections. |
| `reqbot ingest <pdf>` | No | No | Creates artifacts but leaves the document unusable until indexed. |
| `reqbot batch <pdf_dir>` | Yes | Yes | Batch currently indexes unconditionally. |
| `reqbot reindex` | Yes | No | Rebuilds requirements only and may prefer normalized JSONL. |
| `reqbot index <jsonl>` | Caller supplied | No | Low-level repair/debug command. |
| `reqbot index-context <chunks_jsonl>` | No | Caller supplied | Low-level repair/debug command. |

Known problem:

- `reindex` is the command users reach for after Qdrant is deleted or restored, but it does not
  rebuild `grc_context`.
- If `reindex` uses normalized JSONL when enriched JSONL exists, it can silently drop description,
  domain tags, and requirement type from the live requirements index.
- `ingest` requires a flag to do the normal user-facing thing.

### Flag/default behavior

This audit is the starting assumption for WP-24.3 and should be verified against the current code
before implementation:

| Flag/behavior | Current state | Phase 24 direction |
|---|---|---|
| `--index` on `ingest` | Required to index after ingest. | Promote indexing to default; add `--no-index`. |
| `--index` on `run_pipeline.py` | Explicit lower-level script flag. | Likely keep explicit because this is a developer/debug script. |
| `--context` on `ask`, `trace`, `evidence` | Opt-in output expansion. | Keep output opt-in for now; improve docs/help. |
| Context indexing | Happens on `ingest --index` and batch. | Keep/default as part of normal indexing. |
| `--full-extraction` on `pipeline/run_pipeline.py` | Legacy single-pass extraction path on the developer script, not the friendly `reqbot ingest` CLI. | Remove or quarantine the dev-script branch if no supported use case remains. |
| `--hyde` in standalone ask path | Experimental/spike flag not wired into main CLI; already passed Phase 15 evaluation. | Wire into `cli/reqbot.py`'s `cmd_ask` and the interactive shell; flip default to on; add `--no-hyde` opt-out. |
| `--layout-mode` | Real extraction backend choice. | Keep. |
| `--skip-enrichment` | Real cost/time escape hatch. | Keep. |
| `--synthesize` | Real output-mode choice. | Keep. |
| `--no-rewrite` | Real fast/exact-query escape hatch. | Keep. |
| `--skip-to` | Operational resume tool. | Keep. |
| Filter flags | Scope narrowing. | Keep. |

---

## 7. Work Packages

### WP-24.1 - First-Run Setup Cleanup

**Goal:** Collapse first-run configuration into a single guided command that is service-agnostic by
default.

**Problem:**

ReqBot currently has three overlapping first-run entry points: `reqbot setup` (opinionated
local-stack installer — Docker, local Qdrant, local Ollama, local model pulls), `reqbot setup
--advanced` (which already just calls `cmd_init` verbatim), and `reqbot init` (the interactive
config wizard). A new user has no clear signal for which one to run, and `setup --advanced` is
functionally a duplicate of `init` today. The right shape is one command that asks, service by
service, whether to point at something that already exists or have ReqBot install it locally.

**Scope:**

- Merge `reqbot setup`, `reqbot setup --advanced`, and `reqbot init` into a single first-run
  command. Proposed name: `reqbot init` (keeps the name already understood to be "the correct
  one"). Keep `reqbot setup` as a deprecated alias for at least this phase — it runs the merged
  flow with a one-time notice — rather than removing it outright. This merge is already the bigger
  of the two changes (one command with real per-service branching, not just a rename); don't
  compound that implementation risk with a breaking command removal in the same phase, and don't
  break existing docs/scripts that still invoke `reqbot setup`. Only drop the alias outright if
  implementation review finds it clearly harmless. The success gate is that README/help point users
  to one path (`reqbot init`), not that the old name disappears.
- For each externally-facing service — vector DB (Qdrant) and LLM/synthesis (Ollama or remote) —
  the merged flow asks independently whether to point at an existing instance (prompt for URL, test
  the connection) or bootstrap one locally. These choices are independent per service: a user with
  managed Qdrant but no remote LLM access should be able to point at Qdrant and still get local
  Ollama bootstrapped, and vice versa.
- Reuse today's local-bootstrap mechanics (Docker check, Qdrant container start/create, Ollama
  install check, core model pull) as-is — invoke them conditionally from within the merged flow
  instead of behind a separately named command. Do not rewrite the bootstrap steps themselves.
- Keep the existing local/remote/API-key-env synthesis prompts; add the missing explicit
  `none`/retrieval-only choice so declining remote synthesis doesn't silently become local
  synthesis.
- Ensure lazy pulling of `qwen2.5:14b` or any local synthesis model happens only for users who
  explicitly chose local Ollama synthesis in the merged flow.
- Check whether `~/.local/bin/reqbot` or other documented launcher paths point at stale install
  locations. If confirmed, fix or document the correct launcher target.
- Update README and operations docs to describe one first-run command with per-service branching,
  not two separate setup stories.

**Non-goals:**

- Do not remove local/offline bootstrap capability — it becomes a branch inside the single command,
  not a deleted feature.
- Do not add authentication or multi-user hosting.
- Do not rewrite the Docker/Ollama bootstrap mechanics beyond what's needed to invoke them
  conditionally.
- Do not implement MCP in this WP.
- Do not add new remote LLM providers unless current config already supports them.

**Tests / verification:**

- The merged command handles all four combinations of (existing vs. bootstrap) × (Qdrant vs.
  Ollama/LLM) correctly.
- `reqbot init` can select retrieval-only/no-synthesis without causing a later local synthesis
  model pull.
- Remote synthesis config prompts do not require local Ollama model pulls.
- Local synthesis still supports the existing local model workflow.
- The old `reqbot setup` invocation aliases cleanly to the merged flow (with a one-time deprecation
  notice) rather than silently diverging into different behavior or breaking outright.
- Local `reqbot` launcher path, if present, points at the active project entrypoint or is clearly
  documented as user-managed.
- Existing setup tests, if present, pass or are updated for the merged flow.

**Gate:** there is exactly one first-run command recommended in README/help (`reqbot init`). It
asks, per service, whether to use an existing instance or bootstrap locally, in any combination.
`reqbot setup` may still work as a deprecated alias, but it is not the documented path.

---

### WP-24.2 - Unified Reindex Workflow

**Goal:** Make `reqbot reindex` rebuild ReqBot's normal usable index state from existing artifacts,
with a fast path for when the full rebuild isn't needed.

**Scope:**

- Audit the current `cmd_reindex` implementation and document exact artifact selection behavior.
- For each document/run, prefer `*_requirements_enriched.jsonl` when present.
- Fall back to `*_requirements_normalized.jsonl` when enriched output does not exist.
- Rebuild `grc_requirements` from the selected requirement JSONL files.
- Rebuild `grc_context` from available `*_chunks.jsonl` files.
- Use the existing temp-collection/alias-swap rebuild pattern for `grc_context` if the current
  Qdrant helpers support parameterized collection names. Do not accept context downtime unless an
  implementation review proves alias-swap is not practical.
- Add `reqbot reindex --requirements-only` in the same WP as the default-both behavior — this is
  not an optional nice-to-have. Rebuilding `grc_context` touches substantially more points than
  `grc_requirements` (chunk count typically exceeds requirement count) through the CPU-bound local
  embedding path, so making full reindex the only option would make a currently-fast admin
  operation noticeably and silently slower.
- Keep `index <requirements_jsonl>` and `index-context <chunks_jsonl>` as advanced commands.
- Update user-facing help text so `reindex` is clear about rebuilding requirements and context by
  default, and about `--requirements-only` as the fast path.

**Default behavior:**

- `reqbot reindex` rebuilds both requirements and context by default.
- `reqbot reindex --requirements-only` skips the context rebuild entirely and completes in roughly
  the same time as today's requirements-only reindex.

**Context rebuild requirements:**

- Find chunk files from processed run directories.
- Index each `*_chunks.jsonl` file through the same function used by `index-context`, or extract a
  shared helper if the current command wrapper is not reusable.
- Prefer an alias-swap rebuild for `grc_context`, matching the safer `grc_requirements` rebuild
  approach.
- If a chunks file is missing for a document, log a warning and continue.
- If context indexing fails for one document, log the failure and continue with the rest unless
  existing project patterns require fail-fast behavior.
- Do not call Step A/B/C/D/D.5.

**Enriched artifact preference requirements:**

- If both enriched and normalized files exist for the same document/run, use enriched.
- If only normalized exists, use normalized.
- If multiple runs exist for the same document, preserve the existing "latest run wins" behavior
  unless the current implementation uses a different documented rule.
- Reuse or extract the artifact resolver pattern from `services/checklist_service.py`
  (`_resolve_doc_path()`) rather than creating a second independent enriched/normalized resolver.
  If that helper is too checklist-specific, move the shared resolver into a neutral module and have
  both checklist generation and reindex call it.

**Operations docs:**

- Replace manual Qdrant rebuild instructions with the normal command:
  `python3 cli/reqbot.py reindex`
- Document `--requirements-only` as the fast path for users who only touched requirement JSONL.
- Move manual `index` / `index-context` loops into a repair/debug subsection.
- Explain the safe rebuild path for both `grc_requirements` and `grc_context`. If context cannot
  use alias-swap for a concrete implementation reason, document the temporary downtime explicitly.

**Tests / verification:**

- Unit test that reindex selects enriched JSONL over normalized JSONL when both exist.
- Unit test that reindex falls back to normalized when enriched is absent.
- Unit test that reindex invokes context indexing for chunk files by default.
- Unit test that `--requirements-only` skips context indexing entirely and does not touch
  `grc_context`.
- Unit test or integration smoke that context rebuild uses the intended target collection name /
  alias-swap path when mocked.
- Unit test that missing chunk files do not prevent requirements indexing.
- CLI help/smoke check for the new flag and updated help text.
- Existing unit suite passes.

**Gate:** after deleting Qdrant collections, one documented `reqbot reindex` path rebuilds the
requirements and context indexes from existing JSONL/chunk artifacts without LLM extraction, using
safe swap-style rebuild behavior for both collections where supported, and `--requirements-only`
provides a fast partial rebuild when the full rebuild isn't needed.

---

### WP-24.3 - Ingest Defaults and Legacy Flag Cleanup

**Goal:** Make the friendly CLI defaults match normal user expectations and remove unsupported
legacy/spike paths.

**Scope:**

- Make `reqbot ingest <pdf>` index by default.
- Add `--no-index` to `ingest` for artifact-only/debug runs.
- Ensure default indexing includes both requirements and context chunks.
- Leave `pipeline/run_pipeline.py --index` explicit unless implementation review finds a strong
  reason to change the lower-level developer script too.
- Confirm `--full-extraction` is not exposed on friendly CLI paths such as `reqbot ingest`.
- Remove `--full-extraction` from `pipeline/run_pipeline.py` if no supported developer use case
  remains.
- Remove or clearly quarantine the old single-pass extraction branch if it is reachable only
  through `--full-extraction`.
- Keep `--layout-mode`, `--skip-enrichment`, `--synthesize`, `--no-rewrite`, `--skip-to`, and
  filter flags.
- Improve help/docs for `--context` so users understand it retrieves surrounding raw chunk text.
- HyDE default-on promotion is scoped separately in WP-24.5 — this WP does not touch HyDE.

**Context decision:**

- Context indexing should be part of normal ingest/reindex readiness.
- Context display/output should remain opt-in for `ask`, `trace`, and `evidence` in this phase.
- Do not make context text default-on in CLI output until a small manual review confirms it improves
  usefulness without making normal answers noisy.
- Future option: test context-on-by-default for synthesis input separately from context-on-by-default
  in printed output.

**Non-goals:**

- Do not change extraction quality logic.
- Do not make surrounding context output default-on everywhere.
- Do not remove real operational/debug flags.

**Tests / verification:**

- `reqbot ingest <pdf>` indexes by default in mocked/unit coverage.
- `reqbot ingest <pdf> --no-index` writes artifacts and skips both requirements and context
  indexing.
- CLI help clearly documents the new default and escape hatch.
- `--full-extraction` cleanup does not leave dead parser/help references in `pipeline/run_pipeline.py`.
- Existing unit suite passes.

**Gate:** the normal ingest command makes a document usable by default, artifact-only ingest remains
available, and unsupported legacy/spike flags no longer clutter the product path.

---

### WP-24.4 - Batch Indexing Controls

**Goal:** Make batch indexing behavior explicit without breaking existing callers.

**Current behavior:** `reqbot batch <pdf_dir>` indexes requirements and context unconditionally.

**Scope:**

- Decide whether to add `--no-index` to `batch`.
- If added, keep current default behavior unchanged: batch continues to index unless `--no-index`
  is provided.
- Ensure `batch --no-index` still writes all pipeline artifacts.
- Update CLI help and documentation.

**Non-goals:**

- Do not add job queues.
- Do not add browser batch ingest.
- Do not change default batch indexing semantics.

**Tests / verification:**

- Existing batch behavior remains unchanged without `--no-index`.
- `batch --no-index` skips both requirements and context indexing.

**Gate:** batch behavior is explicit and documented, with no regression for existing usage.

This WP is lower priority than WP-24.1 through WP-24.3 and may be deferred.

---

### WP-24.5 - HyDE Default-On Promotion

**Goal:** Wire the existing HyDE spike into the main CLI as default-on retrieval, with an explicit
fast-mode opt-out, closing out the Phase 15 evaluation instead of leaving it in permanent limbo.

**Problem:**

HyDE (`core/ask.py`: `generate_hyde_hypothesis()`, 3-leg RRF fusion) already passed its Phase 15
evaluation gate — ≥3 queries improved (encryption at rest, incident response, supply chain), no
query degraded, no hallucinated IDs in hypotheses. It was left as a standalone `--hyde` flag on
`core/ask.py`'s own CLI, never wired into `cli/reqbot.py`'s `cmd_ask`, the interactive shell, or the
API. Architecture Rule 9 says spike flags get promoted or removed — the evaluation already answered
which way HyDE goes.

**Scope:**

- Wire `hyde=` through `cli/reqbot.py`'s `cmd_ask` and argparse, and through the interactive shell
  (`cli/console.py`).
- Flip the default to on for `reqbot ask`, interactive `ask`, `services/ask_service.py`'s `ask()`
  (already has a `hyde: bool = False` parameter), and the API's `AskRequest.hyde` field
  (`api/routes/ask.py`, already `hyde: bool = False` and already forwarded to `ask_service.ask()`).
  This is a default flip across plumbing that already exists end-to-end, not new integration work —
  CLI, shell, service, and API should all default to HyDE-on unless there's a deliberate documented
  exception.
- Add an explicit opt-out: CLI/interactive `--no-hyde`; API requests can pass `"hyde": false`.
- The frontend never sets `hyde` in its request payload today (`frontend/src/api/types.ts` has it
  as an unused optional field) — once `AskRequest.hyde` defaults to `True`, the browser will
  silently start using HyDE on every query with no way to opt out from the GUI. Add a frontend
  fast-mode toggle for parity with CLI `--no-hyde` — this is not optional/decide-later; a GUI user
  should have the same speed/quality tradeoff a CLI user gets.
- Fix hypothesis logging before shipping default-on: `generate_hyde_hypothesis()` currently appends
  to `hyde_hypotheses.jsonl` in the working directory on every successful hypothesis,
  unconditionally (`core/ask.py`, inside `generate_hyde_hypothesis()`). That was fine when HyDE was
  an opt-in spike flag reviewed in batches; it is not fine as default-on behavior — normal `reqbot
  ask` usage would start silently creating/growing a JSONL file on disk. Gate this logging behind
  an explicit debug/eval flag so default-on HyDE does not write it during normal use.
- Keep the existing fail-open behavior — hypothesis generation/embedding failure falls back to
  baseline retrieval silently. This is what makes default-on safe.
- Confirm `rewrite_model` (local Ollama) remains the model used for hypothesis generation
  regardless of whether synthesis is local or remote — HyDE hypothesis generation should not
  require a remote API call.
- Document that `--no-rewrite` and `--no-hyde` are independent controls — `--no-rewrite` disables
  query rewriting, `--no-hyde` disables the hypothetical-document retrieval leg — and that the
  fastest pre-Phase-24 retrieval behavior is `--no-rewrite --no-hyde` together. Users passing only
  `--no-rewrite` should not be surprised that the HyDE model still runs.
- Update `reqbot ask --help` and docs to describe HyDE as default-on retrieval augmentation, not an
  experimental flag.

**Non-goals:**

- Do not add new retrieval experiments (rerankers, HyPE, multi-vector indexing).
- Do not change RRF fusion weighting beyond what the Phase 15 spike already implemented.
- Do not re-run the Phase 15 evaluation from scratch — the existing gate is the promotion evidence;
  a lightweight manual spot-check against the WP-24.6 refreshed corpus is enough.

**Tests / verification:**

- `reqbot ask <query>` uses HyDE by default in mocked/unit coverage.
- `--no-hyde` disables the HyDE leg and falls back to the pre-Phase-24 baseline+BM25 RRF.
- `services/ask_service.py`'s `ask()` and `POST /api/ask` both default to `hyde=True`; passing
  `"hyde": false` in the API request disables it.
- Hypothesis generation/embedding failure still fails open to baseline (regression test if not
  already covered).
- Unit test confirming `hyde_hypotheses.jsonl` is NOT written during normal default-on usage —
  only when the debug/eval flag is explicitly enabled.
- Manual comparison of a handful of queries against the refreshed corpus (WP-24.6), spot-checking
  against the Phase 15 findings.
- Existing unit suite passes.

**Gate:** `reqbot ask` uses HyDE by default with no CLI/shell/service/API wiring gaps, a documented
and tested opt-out exists at every layer (`--no-hyde` / `"hyde": false` / frontend fast-mode
toggle), hypothesis-generation failures degrade gracefully rather than breaking retrieval, and
default-on usage does not write `hyde_hypotheses.jsonl` unless an explicit debug/eval flag is set.

---

### WP-24.6 - Corpus Refresh

**Goal:** Refresh a representative slice of the indexed corpus using the current pipeline, to
resolve known quality warnings and to give this phase's ingest/reindex defaults something real to
prove themselves against.

**Problem:**

The live corpus (45 documents, ~32,000 requirements) was built incrementally across many pipeline
versions. The Phase 23 audit surfaced structural/quality warnings that predate current chunking and
extraction behavior. Mocked tests can verify the new commands are wired correctly; they can't
verify the pipeline actually produces a clean result on a real PDF.

This WP is a manual/integration validation step against live Qdrant/Ollama and real PDFs. It is
not unit-testable code work — the checklist below is an operator runbook, not pytest coverage (see
Section 8).

**Scope:**

- Select a representative 4-5 document subset — a mix that exercises both `--layout-mode pymupdf`
  and `--layout-mode pdfplumber`, and at least one document that previously triggered a Phase 23
  structural warning.
- Delete and rebuild the `grc_requirements` and `grc_context` entries for the selected documents
  (full Qdrant nuke + re-ingest of just this subset, or a targeted delete — pick whichever is
  operationally simpler at implementation time).
- Re-ingest the subset using `reqbot ingest` (indexing by default per WP-24.3) or `reqbot batch`,
  through the current pipeline, profiles, and chunking/skip-section logic.
- Confirm the Phase 23 structural warnings (low-text pages, contiguity, overlap) do not reappear on
  the refreshed subset.
- Spot-check `reqbot ask`, `reqbot ask --context`, and `reqbot trace` against the refreshed
  documents.
- Run this after WP-24.2, WP-24.3, and WP-24.5 land, so the refresh exercises this phase's final
  ingest/reindex/HyDE defaults rather than mid-phase behavior.

**Non-goals:**

- Do not re-ingest the full 45-document corpus — this WP targets the representative subset only.
- Do not change extraction/chunking logic — this WP exercises the existing pipeline, it doesn't
  change it.
- Do not treat this as retrieval-quality gold-set curation (still deferred from Phase 15).

**Tests / verification:**

- Refreshed documents show no structural warnings the current pipeline is supposed to catch.
- `reqbot ask`, `reqbot trace`, and `reqbot ask --context` return sane results for the refreshed
  documents.
- Refreshed JSONL artifacts pass the same schema/quality checks as the rest of the corpus.

**Gate:** the selected document subset is nuked and re-ingested cleanly through the current
pipeline via this phase's cleaned-up commands, with no reappearance of the Phase 23 quality
warnings.

---

### WP-24.7 - Documentation + Integration Gate

**Goal:** Close Phase 24 by proving setup, indexing, CLI defaults, HyDE promotion, and the corpus
refresh work together without regressions.

**Scope:**

- Update README setup guidance for the single merged first-run command.
- Update README command descriptions for ingest, reindex, index, and index-context, including
  `--requirements-only`.
- Update `docs/OPERATIONS.md` with the simplified setup and rebuild workflows.
- Update `docs/TODO_future_improvements.txt` by removing or moving completed items (including the
  HyDE promotion backlog item, now closed).
- Move MCP tool surface into Phase 25 candidate/backlog docs.
- Confirm the WP-24.6 corpus refresh gate passed.
- Confirm Phase 24 gates and mark the phase complete.

**Demo walkthrough:**

1. Confirm the documented first-run path is the single merged command, and it correctly branches
   per service between "use existing" and "bootstrap locally."
2. Start from existing processed artifacts.
3. Rebuild indexes using the documented `reqbot reindex` path; confirm both collections rebuild.
4. Confirm `reqbot reindex --requirements-only` completes without touching `grc_context`.
5. Confirm `reqbot ask "access control"` returns requirements, using HyDE by default.
6. Confirm `reqbot ask "access control" --no-hyde` still returns tight, sane results.
7. Confirm the frontend's fast-mode toggle disables HyDE for a browser search and the toggle's
   labeling matches the CLI's framing (normal mode = HyDE on, fast mode = HyDE off).
8. Confirm `reqbot ask "access control" --context` can retrieve surrounding context when requested.
9. Ingest a small test PDF with `reqbot ingest <pdf>` and confirm it indexes by default.
10. Ingest a small test PDF with `reqbot ingest <pdf> --no-index` and confirm it writes artifacts
    without indexing.
11. Confirm `reqbot checklist --doc <doc> --format xlsx --output /tmp/checklist.xlsx` still works.
12. Confirm the browser UI still loads and checklist export still works.
13. Confirm the active `reqbot` launcher path, if present, invokes the current project entrypoint.
14. Confirm the WP-24.6 refreshed documents behave correctly end-to-end (ask/trace/context).

**Gate:** Phase 24 is complete when setup is a single guided command, ingest/reindex defaults
produce a usable system with a fast partial-rebuild path, HyDE is default-on with a working
opt-out, old flags are removed or quarantined, the refreshed corpus subset is clean, docs match
real commands, and existing CLI/API/GUI behavior does not regress.

---

## 8. Test Expectations

- Full unit test suite passes after each WP.
- CLI help for changed commands is manually checked.
- `ruff` passes.
- Reindex tests use temporary processed directories and mocked indexing calls where possible.
- Setup tests avoid installing Docker/Ollama or pulling models unless explicitly marked manual.
- Ingest default-index tests mock indexing functions instead of requiring live Qdrant/Ollama.
- HyDE default-on tests mock hypothesis generation/embedding rather than requiring live Ollama.
- Corpus refresh (WP-24.6) is the one WP in this phase expected to run against live
  Qdrant/Ollama — treat it as a manual/integration step, not part of the mocked unit suite.
- No new dependency is added without explicit approval.

---

## 9. Success Gate

Phase 24 is complete when:

1. There is exactly one first-run command, and it is the clear recommended path in README/help.
2. That command asks, per service, whether to use an existing instance or bootstrap one locally —
   there is no separate `setup`/`setup --advanced` split as a *documented* path (a deprecated
   `setup` alias may still exist for compatibility).
3. Remote/local/none synthesis choices are explicit during setup or documented clearly.
4. `reqbot ingest <pdf>` indexes by default.
5. `reqbot ingest <pdf> --no-index` remains available for artifact-only/debug runs.
6. `reqbot reindex` no longer silently drops enrichment when enriched JSONL exists.
7. `reqbot reindex` can rebuild both `grc_requirements` and `grc_context` from existing artifacts,
   using safe swap-style rebuild behavior where supported, with `--requirements-only` available as
   a fast partial path.
8. Context indexing is default for normal ingest/reindex readiness.
9. Context output remains opt-in unless future testing proves a better default.
10. `--full-extraction` is removed or explicitly quarantined as unsupported legacy behavior.
11. HyDE is wired into the main CLI, interactive shell, ask service, and API, all default-on, with
    a working opt-out at every layer (`--no-hyde` / `"hyde": false` / frontend fast-mode toggle),
    and hypothesis logging to `hyde_hypotheses.jsonl` no longer happens during normal default-on
    usage.
12. Operations documentation has one normal rebuild path and a separate repair/debug section.
13. No LLM extraction is triggered by reindex.
14. A representative 4-5 document corpus subset has been refreshed through the current pipeline
    with no reappearance of Phase 23 quality warnings.
15. Existing ask, trace, compare, evidence, checklist, browser export, and CLI export behavior still
    works.
16. Any stale local launcher path discovered during WP-24.1 is fixed or documented.

---

## 10. Explicit Risks / Guardrails

- **Do not make local bootstrap a separate command from the generic first-run path.** Bootstrap is
  a per-service branch inside the single first-run command, not its own entry point.
- **Do not surprise-pull large models for remote users.** Lazy local model pulls must be limited to
  local Ollama synthesis flows.
- **Context rebuild should not accept avoidable downtime.** Prefer the same temp-collection and
  alias-swap approach used for requirements. Only document a temporary `grc_context` gap if
  implementation review proves the safe path is not practical.
- **Do not make full reindex the only option.** A fast `--requirements-only` escape hatch ships in
  the same WP as the default-both behavior, not as a maybe.
- **Do not hide partial failures.** If some context files fail to index, print a summary.
- **Do not make reindex call the LLM.** Reindex is an artifact-to-Qdrant operation only.
- **Do not turn output context into noise.** Context indexing should be default; context display
  should stay opt-in until tested.
- **Do not re-litigate HyDE's evaluation.** The Phase 15 gate already passed; this phase wires it
  in, it does not re-run the experiment.
- **Do not ship HyDE default-on with unconditional hypothesis logging.** `hyde_hypotheses.jsonl`
  must become opt-in (behind a debug/eval flag) before HyDE goes default-on, or normal `reqbot ask`
  usage will silently create/grow a file in the user's working directory.
- **Do not let the corpus refresh grow into a full re-ingest.** Keep it to the representative
  subset; a full 45-document rebuild is a separate, larger effort.
- **Do not remove advanced commands.** Keep low-level repair commands even if normal docs emphasize
  the unified workflow.
- **Do not build MCP in Phase 24.** MCP remains a strong Phase 25 candidate after setup and
  operational defaults are cleaned up.
