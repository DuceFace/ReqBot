# ReqBot Phase 33 — Profile Vocabulary Deduplication, Skip-Section Gap Visibility & Actionability Spike

**Status:** Locked (drafted 2026-07-28; source: `docs/TODO_future_improvements.txt` items 4, 5, and
23 — the "Pipeline quality/cleanup" theme picked over UX continuation, retrieval experiments, and
toolchain hygiene as the other live candidates)
**Date:** 2026-07-28
**Preceded by:** Phase 32 (Evidence Pipeline Provenance Investigation & Evidence/Search UX Cleanup) —
closed 2026-07-28, all seven WPs complete.
**Followed by:** None currently planned — next work will be selected from the live backlog
(`docs/TODO_future_improvements.txt`) once Phase 33 closes.

---

## Status

This table is the live source of truth for Phase 33 WP status — update it here when a WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-33.1 — Deduplicate Profile Vocabulary Constants | Complete — 4 files now derive from `core.profiles.default_profile()`; `pipeline/parse_and_normalize.py`'s dead copies deleted outright |
| WP-33.2 — Surface the Skip-Section Docling-Only Gap | Complete — new `layout_mode_used`/`skip_sections_applied` fields in `stats.json`, surfaced via `reqbot docs`'s new Skip-Sect column; also fixed a discovered pre-existing bug where `mode` mislabeled every docling document as `pymupdf` |
| WP-33.3 — Spike: Actionability Self-Verification | Spike complete — real, sizable problem confirmed, but not the single-cause "vagueness" problem the backlog assumed; it decomposes into 4 distinct root causes. Prompt-wording-alone tested empirically and does not close the two largest. No fix shipped this phase — scoped as a follow-up backlog item (`docs/TODO_future_improvements.txt` item 23) |

---

## 1. Phase Framing

Unlike Phase 32 (triggered by one live walkthrough), this phase's items come from the existing
backlog (`docs/TODO_future_improvements.txt` items 4, 5, 23), each verified against current code
before being scoped here rather than trusting the backlog's own (in one case outdated) description.

**WP-33.1 and WP-33.2 are bounded fixes with an already-understood failure mode. WP-33.3 is a spike,
not a fix** — same "investigate before committing to a build" discipline Phase 32 used for WP-32.1/
WP-32.2 (see `archive/PHASE32_REQUIREMENTS.md`). Do not write a fix for WP-33.3 before its Success
Criteria are met.

No hard sequencing dependency exists between the three — WP-33.1 and WP-33.2 don't touch the same
code, and WP-33.3 is independent of both. Suggested order is smallest/most mechanical first
(WP-33.1), then WP-33.2, then WP-33.3 last since it's the most open-ended and might not produce a
same-phase fix at all.

**A scope correction made during drafting, worth stating up front:** TODO item 4 said the duplicate
vocabulary constants live in "Step C and Step D.5." Checked against current code — they actually
live in **five files**, not two (`pipeline/parse_and_normalize.py`, `pipeline/enrich_requirements.py`,
`pipeline/llm_extract_requirements.py`, `core/ask.py`, `cli/console.py`), and two of those five
(`pipeline/parse_and_normalize.py`'s copies) are entirely dead — not referenced anywhere else in
their own file, and not imported anywhere else in the repo. WP-33.1's scope below reflects the
actual footprint, not the backlog note's.

---

## 2. Goals

- Collapse every hardcoded copy of the cybersecurity domain-tag/requirement-type vocabulary down to
  one real source of truth (`profiles/cybersecurity.json`, via `core.profiles`), so a future second
  profile (Decisions and Guardrails #8, still not built) doesn't have to hunt down and update five
  files to stay consistent.
- Stop `--layout-mode auto`'s docling→pymupdf fallback from silently making a profile's
  `skip_sections` configuration a no-op with no visible signal beyond a single mid-run log line.
- Determine whether "actionability" (syntactically obligation-shaped but not independently
  verifiable) is a real, sizable problem in the current corpus, and if so, find the cheapest fix
  that addresses it — not assume a new pipeline stage is necessary before checking.

## 3. Non-Goals

- No new pipeline stage for actionability checking, and no Step C prompt rewrite, until WP-33.3's
  investigation says one is actually warranted (see its Reject-If criteria).
- No legacy (pymupdf/pdfplumber) section-heading detection — WP-33.2 is scoped to making the
  existing gap *visible*, not building section-awareness into a chunking path that structurally
  doesn't have one today (Step A's legacy output is flat `{page_num, text, source_pdf}` records with
  no heading metadata at all). That would be its own, much larger WP if ever pursued.
- No change to `profiles/*.json`'s schema or `core/profiles.py`'s validation/loading logic — WP-33.1
  only changes what already-hardcoded Python constants derive from, not the profile system itself.
- No second real domain profile — still blocked on the same prerequisite Decisions and Guardrails #8
  names (no source documents for any candidate domain exist yet), unrelated to this phase's scope.

---

## 4. Work Packages

### WP-33.1 — Deduplicate Profile Vocabulary Constants

**Source:** `docs/TODO_future_improvements.txt` item 4, rescoped after verifying against current code
(see Phase Framing above).

**Problem:** The cybersecurity profile's `domain_tags` (18 tags) and `requirement_types` (5 types)
are hardcoded as literal Python constants in five separate files, all currently identical to
`profiles/cybersecurity.json`'s own lists but with no mechanism stopping them from drifting apart:

| File | Constants | Actually used at runtime? |
|---|---|---|
| `pipeline/parse_and_normalize.py:60-86` | `VALID_DOMAIN_TAGS`, `VALID_REQUIREMENT_TYPES` | **No** — dead code. `run()` derives `_valid_domain_tags`/`_valid_requirement_types` locally from its `profile` argument (line 314-315); the module-level constants aren't referenced anywhere else in the file or imported anywhere else in the repo. |
| `pipeline/enrich_requirements.py:29-56` | `VALID_DOMAIN_TAGS`, `VALID_REQUIREMENT_TYPES` | Only as unused-in-practice function defaults — `run()` (the real Step D.5 entry point) passes `profile["domain_tags"]`/`profile["requirement_types"]` explicitly, overriding the default every time it's actually called from `run_pipeline.py`. |
| `pipeline/llm_extract_requirements.py:35-59` | `VALID_DOMAIN_TAGS`, `VALID_REQUIREMENT_TYPES` | Same story as `enrich_requirements.py` — `run()` overrides via `profile["domain_tags"]`/`profile["requirement_types"]`. |
| `core/ask.py:60-71` | `VALID_DOMAIN_TAGS`, `VALID_REQUIREMENT_TYPES` | **Yes, live** — query-time `--domain-tag`/`--requirement-type` filter validation (warn-only, doesn't block filtering) and the query-rewrite LLM prompt's `{valid_tags}` placeholder. |
| `cli/console.py:98-125` | `_DOMAIN_TAGS`, `_VALID_REQUIREMENT_TYPES` | **Yes, live** — same warn-only validation for the interactive shell's inline `--domain-tag`/`--requirement-type` flags. Comment explains why it's inlined rather than imported: "avoid parse_and_normalize import side-effects" (i.e. avoid pulling in `pipeline.parse_and_normalize`'s own heavier import chain just for a validation set). |

This isn't a live correctness bug today (every list is currently identical, and the three ingest-time
files' real runtime values already come from the active profile via `run()` — this WP is closing a
latent-drift risk, not fixing broken behavior). `tests/unit/test_profiles.py` already has two tests
(`test_cybersecurity_domain_tags_match_pipeline_constants`, `test_cybersecurity_requirement_types_...`)
that assert `llm_extract_requirements.VALID_DOMAIN_TAGS`/`VALID_REQUIREMENT_TYPES` equal
`profiles/cybersecurity.json`'s own values — i.e. the drift risk this WP closes is one the test suite
already anticipated, just didn't structurally prevent.

**Scope:**
- Replace each file's hardcoded literal with a value derived from `core.profiles.default_profile()`
  at module load time (e.g. `VALID_DOMAIN_TAGS = default_profile()["domain_tags"]`), preserving each
  file's existing type (`set` where a file uses a set, `list` where a file uses a list) and existing
  variable name — this WP is removing the second source of truth, not renaming anything call sites
  depend on.
- `core.profiles` has no heavy import chain (`json` + `pathlib` only, confirmed by reading it) — safe
  to import from `cli/console.py` without triggering the import-side-effect concern its own comment
  raises about `pipeline.parse_and_normalize`. Update that comment once the constant is derived from
  `core.profiles` instead of inlined, since the reason for inlining no longer applies.
- `pipeline/parse_and_normalize.py`'s two constants are dead code today (see table above) — still
  worth deriving from `core.profiles` rather than deleting outright, for consistency with the other
  four files and in case a future caller reintroduces a default-value use site; deleting them instead
  is an acceptable alternative if that consistency argument doesn't hold up during implementation
  (call it during implementation, not here).
- Adapt (not remove) `test_profiles.py`'s two existing drift tests — after this WP, the equality they
  assert becomes structural rather than incidental, but keeping them as regression coverage against a
  future accidental re-hardcoding is still worth it. Add equivalent equality assertions for the other
  four files' constants too, closing the same drift risk for all five, not just the one file the
  existing tests happened to already cover.

**Non-goals:**
- No change to what `core/ask.py`'s query-time filter validation or `cli/console.py`'s shell
  validation actually does (still warn-only, still doesn't block filtering) — only where the
  compared-against set of "known" values comes from.
- No attempt to make query-time filtering profile-aware for a hypothetical multi-profile corpus
  (unlike WP-32.7's evidence-synthesis fix, there's no single "active profile" concept at query time
  against a corpus that could span documents from more than one profile) — out of scope here, and
  moot today since no second profile exists yet (Decisions and Guardrails #8).

**Tests/verification:**
- `test_profiles.py`'s adapted/added equality tests for all five files' constants against
  `profiles/cybersecurity.json`.
- Full `pytest` suite passes with no behavior change — this WP's data values don't change for the
  current cybersecurity-only corpus, so no existing test should need its expected values touched,
  only possibly its import target.
- `ruff check .` passes.
- Manual: `reqbot ingest` a small document end to end and confirm Step C/D/D.5 output is unchanged
  from a pre-WP baseline run (same domain_tags/requirement_type values assigned) — this WP's whole
  premise is "definitionally cannot drift," which should also mean "produces identical output today."

**Gate:** Exactly one place defines the cybersecurity vocabulary (`profiles/cybersecurity.json`,
read via `core.profiles`); every other file's copy is derived from it, not independently hardcoded.

**Resolution:** Implementation decided the consistency-vs-delete question this WP's Scope left open
for `pipeline/parse_and_normalize.py`'s two dead constants: deleted them outright (confirmed via a
new test asserting the module no longer has these attributes) rather than keeping them as unused
profile-derived constants, since nothing referenced them and the project's own convention prefers
deleting confirmed-unused code. The other four files' constants now derive from
`core.profiles.default_profile()` at module load time. `cli/console.py`'s own comment about avoiding
`pipeline.parse_and_normalize`'s import side-effects no longer applies (was never actually about
`core.profiles`, which has no heavy import chain) and was updated accordingly.

Verified: full `pytest` suite (648 tests, 7 new) plus a clean module-import + value-equality check
against `profiles/cybersecurity.json` directly for all four remaining files, plus a real 3-chunk
`--no-index` ingest of `afpd_17-1.pdf` through Steps A-E confirming the whole pipeline still runs
end to end with the refactored constants (Step D.5 correctly assigned `requirement_type: "policy"`
using the now-profile-derived value).

---

### WP-33.2 — Surface the Skip-Section Docling-Only Gap

**Source:** `docs/TODO_future_improvements.txt` item 5, rescoped (see this WP's Non-Goals and the
Phase Framing note above) after checking `pipeline/chunk_text.py`'s legacy path directly.

**Problem:** A profile's `skip_sections` field only takes effect when the docling chunking path
actually runs (`pipeline/chunk_text.py`'s `_should_skip_chunk`/`_should_skip_section`, fed by
`run_pipeline.py`). The legacy pymupdf/pdfplumber path has no section-heading metadata to filter on
at all (`chunk_text.py`'s legacy `run()`, line 623 on) and silently no-ops, logging one warning line
mid-run (`"Profile skip_sections configured, but legacy chunking has no section hierarchy..."`).
`--layout-mode` defaulting to `auto` (docling when installed, pymupdf fallback per-document on
failure — Decisions and Guardrails #9) narrowed how often this fires, but didn't close it: it's a
silent no-op whenever docling isn't installed, or a specific document's docling attempt fails and
falls back, or `--layout-mode pymupdf`/`pdfplumber` is passed explicitly. A user who configured
`skip_sections` (e.g. to drop `"REFERENCES"`/`"GLOSSARY"` boilerplate from their corpus) has no way
to know, after the fact, whether it actually took effect for a given ingest run without re-reading
that one log line.

**Scope:**
- Building real section-awareness into legacy chunking is explicitly out of scope (see Non-Goals) —
  this WP is about making the existing no-op *visible after the fact*, not eliminating it.
- Surface whether `skip_sections` actually applied somewhere a user will see it without having to
  scroll back through mid-run logs: candidates are the ingest run's end-of-run summary (CLI output),
  the processed-document's own metadata (so `reqbot docs`/the Corpus view can show it), or both —
  pick based on what's cheapest to thread through cleanly during implementation; both `run_pipeline.py`
  and `chunk_text.py`'s legacy `run()` already know the answer (`skip_sections` non-empty + legacy
  path used), it's just not surfaced anywhere durable today.
- If surfaced via processed-document metadata: this is new information, not a schema *change* to an
  existing field's meaning — check with the user before adding a new JSONL/Qdrant payload field per
  this project's stop-and-ask list, even though this WP's Non-Goals already rule out changing what
  existing fields mean.

**Non-goals:**
- No section-heading detection or awareness added to the legacy pymupdf/pdfplumber path — that's a
  standalone feature-sized WP if ever pursued (per the TODO item's own framing: "revisit if legacy
  chunking ever gains its own section awareness" is a prerequisite, not this WP's job to build).
- No change to `--layout-mode auto`'s fallback behavior itself (Decisions and Guardrails #9) — this
  WP only makes an existing consequence of that fallback more visible, not different.

**Tests/verification:**
- Unit test(s) confirming the new visibility signal is correctly populated/omitted for both legacy
  and docling paths, and for the case where `skip_sections` is empty (nothing to surface).
- Manual: ingest one document with `--layout-mode pymupdf` and a profile whose `skip_sections` is
  non-empty; confirm the no-op is now visible somewhere durable, not just in scrollback logs.

**Gate:** A user can tell, after an ingest run completes, whether their profile's `skip_sections`
actually took effect for that run — without reading pipeline logs.

**Resolution:** Chose `stats.json` (Step E's existing metrics file) over a requirement-record field —
it's pure diagnostics, not the requirement JSONL/Qdrant payload schema those files stop-and-ask
protects, so no schema-change consultation was needed. `run_pipeline.py` now passes the final
resolved `layout_mode` and the profile's `skip_sections` into `aggregate_and_export.run()`, which
computes `skip_sections_applied` (`None` if nothing was configured, `True`/`False` if something was
and either did or didn't apply) and writes both alongside the existing `layout_mode_used` field.
`docs_service.list_docs()` reads it and surfaces it through `reqbot docs`'s new Skip-Sect column
(CLI-only for now — GUI/Corpus-view surfacing is a natural follow-up, not done here to keep this WP
bounded to what the Scope called "cheapest to thread through cleanly").

While implementing, found and fixed (confirmed with the user first, since it's a separate bug) a
real pre-existing issue in the same function: `docs_service.py`'s `mode` field only ever checked for
a pdfplumber `TABLE_START` sentinel, so it silently mislabeled every already-ingested docling
document as `pymupdf`. Fixed using `section_ref_path` key presence (docling's own signature,
confirmed during Phase 32) as a second signal, with `stats.json`'s new authoritative
`layout_mode_used` preferred when present. Backward-compatible: documents ingested before this WP
(no `layout_mode_used` in their `stats.json`) fall back to the corrected heuristic instead of
showing nothing.

Verified: 660/660 `pytest` (13 new tests), `ruff` clean. Manual — ingested `afpd_17-1.pdf` with
`--layout-mode pymupdf` (cybersecurity profile's `skip_sections` is non-empty) and confirmed
`reqbot docs` showed `no (!)` for that document while a pre-existing (pre-WP) document correctly
showed `-` rather than being misreported as `no`.

---

### WP-33.3 — Spike: Actionability Self-Verification

**Source:** `docs/TODO_future_improvements.txt` item 23.

**Goal:** Determine whether syntactically-obligation-shaped-but-not-independently-verifiable
requirements ("too vague, contextual, administrative, or dependent on parent context" per the
backlog's own framing) are a real, sizable problem in the current corpus — and if so, find the
cheapest effective fix, rather than assuming a new pipeline stage or LLM call is necessary before
checking.

**Rationale:** Confirmed against current code that no auditability/actionability signal exists
anywhere in the pipeline today: Step C's prompt (`pipeline/llm_extract_requirements.py`) only screens
for obligation language (the profile's `obligation_verbs`); Step D normalization
(`pipeline/parse_and_normalize.py`) only drops empty `source_quote`, `"not explicitly stated"`
descriptions, short errata entries, and (since Phase 32) ungrounded quotes — none of which catch a
genuinely-extracted, genuinely-grounded requirement that's simply too vague to act on independently;
Step D.5 enrichment (`pipeline/enrich_requirements.py`) is pure classification
(`description`/`domain_tags`/`requirement_type`) with no judgment of verifiability. This is a real
gap, but its actual *size* — how many extracted requirements are affected, and whether the pattern is
even reliably distinguishable from genuinely actionable-but-terse requirements — is unknown; that's
what this spike is for.

**Scope:**
- Sample weak/borderline extracted requirements from the live corpus (start from records with a
  short `source_quote` or a `description` that reads as administrative/contextual rather than a
  discrete obligation) and hand-label failure modes, following the same manual-verification style
  used throughout Phase 32's spikes.
- Test whether stricter Step C prompt wording alone measurably reduces weak extractions — cheaper to
  try first than building a separate judgment pass, and might make a downstream check unnecessary or
  smaller in scope.
- If a downstream check still looks warranted after the above: prototype it as an extra key
  (`is_verifiable` + a reason string) on Step D.5's existing per-requirement/per-batch enrichment JSON
  output (`ENRICH_BATCH_PROMPT_TEMPLATE`/`ENRICH_SINGLE_PROMPT_TEMPLATE` in
  `pipeline/enrich_requirements.py`) rather than a new pipeline stage or separate LLM call — D.5
  already makes one LLM round-trip per requirement/batch, so this piggybacks on an existing call
  instead of adding ingest latency.
- For context-dependent cases specifically (a requirement that reads as vague/administrative in
  isolation but would be clear given its parent section): retry the verifiability judgment with
  `parent_context`/`section_title_path` included before concluding it's genuinely unverifiable — only
  available on docling-ingested documents (`section_ref_path`-bearing chunks), so this retry path is
  itself conditional on layout mode, matching the same docling/legacy asymmetry WP-33.2 documents.
- Measure false positive/negative rates against a small hand-labeled set, reusing
  `eval/eval_harness.py`'s existing gold-labeling pattern (`eval/gold_eval_chunks_curated.jsonl`'s
  shape: `{stem, source_pdf, processed_run_dir, chunk_id, chunk_text, ...}`) rather than building new
  eval infrastructure from scratch.

**Success Criteria:** A clear, evidence-backed answer to "is this a real, sizable problem, and if so
what's the cheapest fix" — not a guess. If a fix is prototyped, quantified precision/recall against
the hand-labeled sample, not just "seems better."

**Reject If / Next step:**
- If the sampled failure rate is small, or stricter Step C prompt wording alone closes most of the
  gap: document the finding in this doc's Findings section (once written), leave the remaining edge
  cases as a `docs/TODO_future_improvements.txt` note, and do not build a Step D.5 verifiability
  check this phase.
- If the problem is real and sizable, and prompt-wording alone doesn't close it: do not merge a
  Step D.5 prompt/schema change inside this spike. Write up the confirmed pattern and false-positive/
  negative rates, and scope the actual fix as its own WP (in this phase if there's room, or deferred
  to a follow-up phase if the fix carries real regression risk against `pipeline/enrich_requirements.py`'s
  existing, already-shipped behavior) — same discipline Phase 32 used for WP-32.1.
- Per the backlog's own note: if both this item and item 6 (optional LLM-backed audit question
  generation) end up warranted, implement them as one combined Step D.5 call, not two separate
  ingest-time LLM passes — but only decide that once (if) this spike concludes a fix is warranted at
  all.

**Findings:** The live corpus is small (2 documents, `afpd_17-1.pdf` and `CJCSI 6510.02G.pdf`,
173 enriched requirements total — the post-WP-32.1-nuke controlled rebuild hadn't grown past the
single-document loop yet) but real, not synthetic. A random uniform sample of 40/173 records was
hand-labeled; 15/40 (37.5%) showed some form of "cannot be trusted/verified as extracted," which
confirms the problem is real and sizable — but it does **not** decompose into one "too vague"
category the way the backlog item assumed. Four distinct root causes, each independently confirmed
against real corpus records and (for the two largest) against a live A/B prompt test on the actual
offending chunks via Ollama (`llama3.1:8b-instruct-q4_K_M`, the same extraction model the corpus was
built with):

1. **Reference/bibliography-list entries mis-extracted as requirements (7/40, 17.5% — the largest
   category).** A document's References section (e.g. `afpd_17-1.pdf` chunk 8, a dense list of
   `"DoDI 8500.01, Cybersecurity, March 14, 2014"`-shaped citations) gets extracted line-by-line as
   individual "requirements," even though the prompt already has an explicit "DO NOT extract...
   Cross-references to other controls" rule and a worked example (Example 3) showing a references
   section should yield `{"requirements": []}`. Worse, Step D.5 enrichment then fabricates a
   plausible-sounding `description` with content that appears nowhere in the `source_quote` (e.g.
   `source_quote: "JP 3-12, Cyberspace Operations, February 5, 2013"` →
   `description: "Provides guidance on cyberspace operations, including requirements for planning,
   executing, and assessing the effectiveness of these operations."` — invented, not grounded).
   **A/B test result:** a revised prompt adding an explicit "reference/bibliography lists of
   external documents, even when long" exclusion reduced chunk 8's extractions from 16 to 14 —
   effectively no improvement; the model still treats most citation lines as individual
   requirements. Prompt wording alone does not close this.
2. **Genuine vagueness/administrative meta-statements (5/40, 12.5% — the pattern the backlog
   originally hypothesized).** Real examples: `"COMPLIANCE WITH THIS PUBLICATION IS MANDATORY"`
   (standard AF publication boilerplate, all-caps, appears on page 1 of every AFPD), `"Ensure
   compliance with Electromagnetic Spectrum Operations (EMSO) policy"` (points at an external policy
   with no stated criteria), `"All alternative approaches... must be fully considered"` ("fully
   considered" has no independently checkable definition). **A/B test result (chunk 0, the MANDATORY
   line):** the revised prompt still extracted a reworded version of the same line, AND separately
   fabricated a second "requirement" that is a verbatim copy of the prompt's own Example 1 text
   (`"The information system enforces approved authorizations..."`) — text that does not appear
   anywhere in that chunk. This is the same few-shot-regurgitation failure mode WP-32.1's spike
   found (Phase 32) — confirmation that editing Step C's prompt carries real regression risk of
   *introducing* new fabrications, not just failing to fix old ones, on this model.
3. **Truncated/fragment quotes with fabricated completions (1/40, 2.5%; 2/173 corpus-wide).** A
   list-header sentence ending in a colon (e.g. `"The MC4EB will:"`, from `CJCSI 6510.02G.pdf`
   chunk 3) gets extracted as its own `source_quote` with nothing after the colon — but Step D.5's
   enrichment `description` for that same record contains full obligation text
   (`"...will: Address the operational readiness of cybersecurity solutions..."`) that isn't in the
   `source_quote` at all. Neither `ENRICH_SINGLE_PROMPT_TEMPLATE` nor `ENRICH_BATCH_PROMPT_TEMPLATE`
   passes `parent_context` to the enrichment call, so this can't be legitimate context-following —
   it's the enrichment LLM pattern-completing a truncated legal-style sentence. This is the most
   dangerous failure mode of the four: a low-word-count `source_quote` (which existing tooling could
   flag) accompanied by a *confident, complete-reading* `description` that quietly invents content.
   **A/B test result:** the revised prompt (explicitly instructing "do not extract a fragment ending
   in a colon") had zero effect — chunk 3 still produced `"The MC4EB will:"` as a standalone
   extraction both before and after.
4. **Background/definitional prose extracted despite no obligation language (1/40, 2.5%).** A
   glossary/definitions chunk (`afpd_17-1.pdf` chunk 9) yielded a "requirement" that is pure
   descriptive narrative (`"...the DoD current business and financial management infrastructure...
   are being transformed..."` — passive voice, no "shall/must/will"). **A/B test result:** this was
   the one category where the revised prompt actually helped — the background sentence was no
   longer extracted (4 extractions → 2, with the remaining 2 being genuine, differently-phrased
   sentences from elsewhere in the same chunk).

**Conclusion, per the Reject-If criteria above:** the second branch applies — the problem is real
and sizable (~37.5% of a random sample, well above noise), but stricter Step C prompt wording alone
does **not** close it for the two largest and most concerning categories (1 and 3), only helps
partially for the smallest (4), and measurably regressed category 2 by introducing a fresh
fabrication on the same chunk it was meant to fix. No Step D.5 prompt/schema change is merged in
this spike (per Guardrail #2 and the empirical result above). The actual fix is scoped as a follow-up
in `docs/TODO_future_improvements.txt` item 23, rewritten with these four categories and the
recommendation that they likely need different mechanisms rather than one `is_verifiable` classifier:
a chunk-level or Step-D structural filter for citation-list-shaped chunks (category 1), a minimum-
predicate/no-trailing-colon structural check in Step D similar to the existing `errata_change_entry`
check (category 3), and — the one gap most worth prioritizing — extending WP-32.1's Step D fuzzy
grounding check (which today only validates `source_quote` against its chunk) to also validate Step
D.5's generated `description` against `source_quote`, since categories 1 and 3 both involve
Step D.5 fabricating description content ungrounded in the quote it was given.

---

## 5. Success Gate

Phase 33 is complete when:

1. WP-33.1 and WP-33.2 are merged.
2. WP-33.3's spike has reached a documented conclusion (real-and-sizable-with-a-fix, or
   small-enough-to-defer), and any resulting fix work has either landed (if small enough to fit this
   phase) or been scoped as explicit follow-up (if not) — mirroring Phase 32's WP-32.1/WP-32.2
   pattern.
3. Full unit suite passes (`pytest`); `ruff check .` passes.
4. No second source of truth remains for the cybersecurity profile's `domain_tags`/`requirement_types`
   vocabulary anywhere in the codebase.

---

## 6. Guardrails

1. One WP at a time — each lands as its own PR, reviewed before proceeding to the next, same cadence
   as Phases 29–32.
2. WP-33.3 is investigation only — do not write a production fix inside the spike itself. If a fix
   turns out to be warranted, scope it as explicit follow-up work with its own review, not a rushed
   addition to the spike's PR.
3. WP-33.1 must not change any actual classification/filtering behavior for the current
   cybersecurity-only corpus — this is a single-source-of-truth refactor, not a vocabulary change.
4. WP-33.2 must not attempt legacy section-heading detection under any framing — that's a
   standalone, much larger WP if it's ever pursued, not a subtask of "surface the gap."
