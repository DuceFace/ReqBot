# Phase 34 Brainstorm — Actionability Fix Options

**Status:** Superseded by the locked phase doc — `docs/PHASE34_REQUIREMENTS.md`. Kept as-is for the
narrative "why" behind that doc's decisions (including the full three-round external-review history)
in more detail than belongs in a locked phase doc; the phase doc is the source of truth for current
WP scope/status.

**Original status note (accurate for most of this doc's life, kept for context):** this started as a
brainstorm / discussion draft, explicitly not a locked phase doc, carrying more "why" narrative than a
normal phase doc would (see `~/reqbot-agent-docs/reqbot/references/work-package-workflow.md` for the
normal format) — the goal was to react to and refine the approach before locking it into WP scope,
success criteria, and guardrails. That process is what produced `docs/PHASE34_REQUIREMENTS.md`.

**Source:** WP-33.3's spike (`docs/PHASE33_REQUIREMENTS.md`'s WP-33.3 Findings, PR #156).

**Revision note (2026-07-29):** the first version of this doc (reviewed by Codex, see §5) assumed
the corpus it was reasoning about was representative. It wasn't — see §2. Re-ingesting via docling
changed the picture enough that this is close to a rewrite, not a patch. Kept for the record: Codex's
review of the first draft was directionally right (Step D as the home for these checks, use
`section_title_path` context, don't rely on citation-list quote-shape alone) even though the specific
scenario it was reasoning about (our corpus) turned out to be an edge case, not the norm.

---

## 1. The problem, briefly

WP-33.3 hand-labeled a random sample of the live corpus and found 37.5% of requirements show some
form of "cannot be trusted/verified as extracted," decomposing into five failure modes (full detail:
`docs/PHASE33_REQUIREMENTS.md`'s WP-33.3 Findings). **Why this matters enough to fix:** ReqBot's
value proposition is verbatim, trustworthy extraction — "ingestion captures verbatim... do not invent
obligations" is a core architecture principle, and at least one of these failure modes (fabricated
`description` content completing a truncated quote) already violates it in production today.

## 2. Correction: the corpus this was all based on was an edge case, not the norm

Both documents in the current corpus (`afpd_17-1.pdf`, `CJCSI 6510.02G.pdf` — the only two re-ingested
since WP-32.1's corpus nuke) turned out to have been ingested via **legacy pymupdf chunking**, not
docling — despite `--layout-mode auto` defaulting to docling when available, and despite docling
being installed and working fine in this environment right now (confirmed live, 2026-07-29). Root
cause is most likely that docling wasn't installed yet at the time of that specific ingest
(2026-07-27); not a reproduced bug.

This matters because legacy chunking has no section-hierarchy metadata at all — every finding in
WP-33.3's spike, and everything Codex's review of this doc's first draft reasoned about, was
implicitly scoped to a corpus that doesn't represent how ReqBot is actually meant to run. So before
going further, both documents were re-ingested via `--layout-mode docling` (`--no-index`, so this
didn't touch Qdrant) to see whether the same failure modes even look the same under real conditions.
They don't, uniformly.

**This also reframes an earlier open question in this doc's first draft** ("is a 2-document corpus
enough to validate a detection rule on") — re-ingesting the existing two documents via docling alone
already surfaced a materially different, better picture. A broader re-ingest is still worth doing
eventually (see §6), but it's no longer a blocker for scoping Tier 1.

## 3. Revised findings, per category (now evidence-based across both documents' docling re-ingests)

### Category 1 (reference-list misextraction) — likely already solved, no new code needed

**Zero occurrences across both documents.** Not because the model got smarter — the References/
Glossary section chunks never reached Step C at all. `stats.json` confirms `skip_sections_applied:
true` for both; `skip_sections` (`['GLOSSARY', 'REFERENCES', 'ACRONYMS', 'DEFINITIONS',
'ABBREVIATIONS', 'TABLE OF CONTENTS']`) already covers this — it's WP-33.2's own shipped feature
working exactly as designed. The riskiest part of this brainstorm's first draft — a citation-shape
detection regex, with real false-positive risk against genuinely dated real requirements — likely
doesn't need to be built at all. **The actual "fix" is: make sure the corpus is ingested via docling.**
Worth validating on 1-2 more documents before fully closing this one out, but the signal from two
documents (afpd_17-1: a dense multi-line reference list; CJCSI: no distinct references section at
all) is a good sign, not a coincidence tied to one document's structure.

### Category 4 (background/definitional prose) — narrow, low-risk config gap

`afpd_17-1.pdf`'s glossary section is headed literally `"Terms"` — not in the configured
`skip_sections` list, so it wasn't dropped, and its prose still got misextracted as a requirement.
CJCSI has no equivalent issue (no comparably-named section). This looks like a heading-vocabulary
gap in `skip_sections`'s matching, not a new mechanism (`_should_skip_section` in
`pipeline/chunk_text.py` already does case-insensitive, prefix-based matching — it just doesn't know
about `"TERMS"` as a synonym for `"DEFINITIONS"`/`"GLOSSARY"`). **Open question:** worth surveying a
few more real documents' actual heading vocabulary before locking in a specific expanded list, rather
than guessing synonyms from one example.

### Categories 2 + 3 (boilerplate meta-statements + fragment quotes) — still real, better evidence now

These are the ones that still need a real Step D structural check. Found 5 concrete cross-document
examples (not the original 2), decomposing into two distinguishable, complementary signatures:

- **Quote echoes its own `section_title_path` heading verbatim.** `afpd_17-1.pdf`'s
  `"COMPLIANCE WITH THIS PUBLICATION IS MANDATORY"` and `"All HAF Functionals, MAJCOMs, DRUs, and
  FOAs will:"` both got extracted as body-content quotes, but both are *exactly* the chunk's own
  `section_title_path[-1]` value — Step C extracted a structural heading as if it were prose. This is
  a strong, precise, cheap signal precisely because it's grounded in docling's own structural ground
  truth, not a fragile text-pattern guess (this generalizes Codex's `section_title_path` suggestion —
  it applies to more than just citation detection).
- **Quote ends in a colon with no obligation content after it.** Didn't recur in CJCSI's fragment
  case from WP-33.3 (`"The MC4EB will:"` — that exact one didn't repeat under docling, most likely
  LLM run-to-run variance, not a structural fix), but two *new* colon-fragments showed up in CJCSI's
  docling re-ingest instead (`"The process will be as follows:"`, `"The KER may be sent either by...
  or by mail to the address listed below:"`) — under `section_title_path: ['UNCLASSIFIED']`, a
  repeated classification-marking artifact, not a real heading, so the heading-echo signal above
  wouldn't have caught these two. The two signals are complementary, not redundant — worth combining
  (OR'd), not picking one.

Recommendation unchanged from the first draft on *where* this lives: Step D
(`pipeline/parse_and_normalize.py`), same shape as the existing `errata_change_entry`/grounding
checks — deterministic, no LLM call, durable failure reason. This is docling-only by nature (needs
`section_title_path`), which is a fine tradeoff given the direction in §6, not something to build a
legacy-chunking fallback for.

**Implementation detail, verified against current code (Codex review round 2):**
`parse_and_normalize.run()` builds `chunk_hierarchy_map` before its per-requirement loop (line 319),
but each requirement's own `section_title_path` isn't resolved from it until line 399 — *after* the
existing `empty_source_quote`/`quote_not_grounded_in_chunk`/`errata_change_entry` checks (lines
344–381). A new check naively slotted in next to those existing ones would reference
`section_title_path` before it's populated. The new check needs to either move the hierarchy lookup
earlier or run after line 402. Also: reuse `pipeline/chunk_text.py`'s existing `_normalize_heading()`
(strips numbering prefixes like `"3.14."`, lowercases, collapses whitespace) for the quote-vs-heading
comparison rather than inventing separate matching logic — it's currently module-private, so this
either means importing it directly or moving it somewhere shared.

### Category 5 (form/questionnaire content) — unchanged, not re-examined this round

Still rare (1/40 in the original sample), still low priority. Didn't specifically re-check it against
the docling re-ingests; not worth chasing further before there's a bigger sample.

## 4. Description-grounding (Tier 2) — now with a real technique to point at, not just a gap

Quick literature pass (not exhaustive) on "does a generated summary/description actually follow from
its source" — this is the established **faithfulness hallucination** detection problem, not something
to design from scratch:

- **NLI (natural language inference) cross-encoder entailment scoring** — `premise=source_quote`,
  `hypothesis=description` — is the standard lightweight technique. Same architectural slot as
  WP-32.1's existing `rapidfuzz` grounding check, just semantic instead of literal. Purpose-built
  compact models exist for this (Vectara's HHEM is specifically tuned for RAG-style groundedness;
  MiniCheck/FactCG are newer lightweight options) — runs locally, no API call, no per-record LLM cost,
  fits the self-hosted/air-gapped angle. This is a **new dependency** — per direct guidance, that's
  fine to bring with a real reason and test results, not a heavy blocker. Worth a small spike
  (analogous to `eval/docling_spike.py`'s "test a candidate library, look at real results" pattern)
  before committing to shipping it.
- **Having Step D.5 self-report whether its own description is grounded** (this doc's original Tier 2
  option (b)) should be deprioritized, not just left as one of several roughly-equal options — the
  literature is fairly clear that a model checking its own output is one of the weakest forms of
  verification (a model that fabricates a claim tends to also validate that same fabrication when
  asked to check it).

Still recommend scoping this as its own investigation (WP-34.4, spike-first, mirroring WP-33.3's own
discipline) rather than bundling it with the Tier 1 structural checks above — it's the highest-value
fix (directly targets the fabricated-description symptom) but the least scoped, and per Codex's
original review, it correctly can't just reuse WP-32.1's verbatim-matching check as-is (a real
paraphrase legitimately fails a literal substring match).

**Refined spike guidance (Codex review round 2):** start with HHEM or MiniCheck, not FactCG — FactCG
reads as newer research aimed at graph/multi-hop fact-checking, not an obvious first local dependency
for this use case. Keep the spike scoped as an eval-only dependency trial (`eval/`, like
`docling_spike.py`), not a production change. And the actual gate for the spike isn't "the literature
says NLI is standard" — it's concrete: **does it catch the known fabricated-description examples
already in hand (the citation-list ones, the fragment-completion one) without rejecting normal,
faithful paraphrases** from the rest of the corpus.

## 5. What changed from Codex's review of the first draft, and why

Codex's review (full text on PR #157) made four substantive points. Revisiting each against the new
evidence:

1. **Category 3 structural check lives in Step D, avoid a bare `endswith(":")` rule** — still agrees;
   now have 5 real examples (not 2) to build the compound rule and test set against, per §3.
2. **Category 1 should use `section_title_path`/chunk context, not date-shape** — correct in
   principle, and the underlying idea (lean on docling's real structure) generalizes well — it just
   turned out the *problem itself* mostly stops existing once you're actually on docling with
   `skip_sections` applied, so there's no citation-detection rule left to design in the first place.
3. **Use existing gold/seeded fixtures instead of requiring new ingest** — **retracted.**
   `eval/gold_eval_chunks*.jsonl` (including `_curated`) is unfinished, abandoned work with an
   estimated ~20% noise rate in `gold_requirements` (confirmed directly by the person who started it) —
   not reliable ground truth without a fresh audit pass. Also moot for category 1 now that no
   citation regex is being built. The Tier 1 checks in §3 can be validated against real fixtures
   pulled directly from the two documents already re-ingested this round.
4. **Description-grounding deserves a spike, not Tier 1** — still agrees; §4 above.

Codex re-reviewed the rewritten draft (round 2) and raised five more points — folded in above (the
Step D implementation detail and NLI model guidance) or below (§6, §7). One point is now moot given
§6's decision: Codex suggested making `skip_sections_applied=False` "hard to ignore" (not just visible
via `reqbot docs`'s Skip-Sect column) *if* the legacy path stayed supported — since it didn't, there's
no silent-no-op case left to make loud.

**Round 3** (after the docling-only decision landed) found real gaps in §6's migration list — folded
in above: `cli/console.py` has its own separate `--layout-mode` parser, `test_extract_pdf.py` and
`test_wp_20_3.py` both need attention, and (the more consequential one, extending Codex's point rather
than just confirming it) `requirements.txt` doesn't just pin the legacy libraries — it has no docling
option at all today, so it needs either updating or retiring, not just having two lines deleted. One
claim in round 3 didn't hold up: `build/bundle.sh` doesn't exist anywhere in this repo (checked
directly) — likely a stale reference to the bundle installer `CLAUDE.md` already documents as retired
in WP-25.4. Not folded in.

**Round 4** (after the locked phase doc was drafted) found four more real gaps, all verified and
folded in above: a *third* independent `--layout-mode` argparse definition, this time in
`pipeline/run_pipeline.py`'s own standalone `main()` (missed by rounds 2 and 3, which only caught the
two CLI-level parsers); `pipeline/chunk_text.py`'s own standalone CLI is dual-mode and would be left
calling a deleted function if only the underlying `run()` were removed without restructuring the CLI
around it; `tests/unit/test_cli_ingest.py` hardcodes a now-stale `layout_mode="pymupdf"` in a way that
won't fail on its own (the function it tests is fully mocked); and a correctly-hedged question about
whether `CLAUDE.md` — absent from the PR tree — was in scope on purpose. It is: confirmed gitignored,
edited directly, not part of any PR diff.

## 6. Decided: ReqBot goes docling-only

**Decision (2026-07-29): drop pymupdf/pdfplumber legacy chunking entirely, docling becomes the only
ingestion path.** This resolves what §3/§7 could otherwise assume — WP-34.2's Step D check can assume
`section_title_path` always exists, category 1 needs no defensive code (§3's "already solved" finding
now holds unconditionally, not just "as long as docling was actually used"), and WP-34.3 is purely
the `skip_sections` vocabulary work, not also a process/visibility fix for a fallback path.

This isn't free, though — it's a real migration, scoped here from an actual read of the code so it's
not hand-waved:

- **`pipeline/run_pipeline.py`**: remove the legacy branch (`extract_pdf_to_text.run()` +
  `chunk_text.run()` path, roughly lines 195–265) and `resolve_layout_mode()`'s silent auto-fallback
  (`_docling_available()`/the "auto → pymupdf when docling fails" behavior, Decisions and Guardrails
  #9). Docling failure should become a hard error, not a silent downgrade — same "fail loudly instead
  of silently downgrading" principle `resolve_layout_mode()` already applies to an *explicit*
  `--layout-mode docling` request, just extended to be the only behavior.
- **`pipeline/extract_pdf_to_text.py`** (264 lines) — Step A's legacy PDF-to-text path. Removable
  entirely once nothing calls it. `tests/unit/test_extract_pdf.py` (88 lines) exists solely to test
  this file's low-text-page detection (`_LOW_TEXT_THRESHOLD`/`warn_low_text_pages`) — verified, should
  be removed alongside it, not left testing dead code.
- **`pipeline/chunk_text.py`** (797 lines) — legacy-only: `run()` (the pymupdf/pdfplumber chunker,
  ~60 lines) plus its supporting helpers (`chunk_text()`, `load_pages`, `build_page_index`,
  `pages_for_span`, `find_table_spans`, `table_span_at`, `validate_page_contiguity` — another ~250
  lines combined). `run_structure_aware()` (the docling chunker) and the shared helpers
  (`_should_skip_section`, `_normalize_heading`, `_should_skip_chunk`) stay. This file's own
  standalone `main()`/CLI is dual-mode today (verified) — `input_path` means `pages.jsonl` in legacy
  mode vs. a PDF with `--docling`, and legacy-only flags (`--chunk-size`/`--overlap`/`--table-aware`)
  feed the legacy branch directly — needs restructuring to be docling-only, not left calling a
  deleted function.
- **`--layout-mode` CLI flag**: drop the `pymupdf`/`pdfplumber`/`auto` choices, or keep them
  rejected-with-a-clear-error for one release as a migration aid — worth a call at implementation
  time, not here. Exists in **three** independent places, not one: `cli/reqbot.py`'s argparse
  subcommands, `cli/console.py`'s separate interactive-shell `ingest`/`batch` parsers, and (Codex
  review round 4, verified) `pipeline/run_pipeline.py`'s own standalone `main()`
  (`choices=["auto", "pymupdf", "pdfplumber", "docling"]`) — the direct-script entry point, separate
  from both CLIs.
- **`tests/unit/test_layout_mode_auto.py`**: this file's whole point today is testing the
  auto-fallback behavior — most of it needs rewriting around "docling failure is a hard error," not
  incremental patching.
- **`tests/unit/test_wp_20_3.py`**: patches `pipeline.extract_pdf_to_text.run` and
  `pipeline.chunk_text.run` directly (verified, lines 218-219) as part of its `run_pipeline.run()`
  profile-plumbing test — needs rewriting around the docling/`section_parser` path instead of just
  deleted, since the profile-plumbing behavior it's actually testing still needs coverage.
- **`tests/unit/test_cli_ingest.py`** (Codex review round 4, verified): its `_args()` helper
  hardcodes `layout_mode="pymupdf"`. `run_pipeline.run()` is fully mocked in these tests, so removing
  `pymupdf` as a valid choice elsewhere won't make this test fail on its own — it'll just keep
  silently encoding a stale value forever unless explicitly updated.
- **Dependency declarations — two separate files, both need attention, not just one:**
  `pyproject.toml`'s `docling` extra (`archive/PHASE25_REQUIREMENTS.md`'s "gated purely for weight"
  decision) should move into the base install. Separately, `requirements.txt` still pins
  `pymupdf==1.27.1`/`pdfplumber==0.11.9` and — checked directly — **has no docling entry at all
  today**, on either path. `README.md` already documents `requirements.txt` as a legacy,
  pre-WP-25.2-packaging install path ("kept for compatibility, not recommended for new setups",
  `pip install .` being "the supported path going forward") — so this WP either needs to add
  `docling==2.84.0` to it (so that path doesn't go from "works" to "can't ingest anything" once
  pymupdf/pdfplumber are dropped) or retire the file entirely in favor of `pip install .` — a real
  decision, not pre-made here, but one this WP can't skip.
- **Keep, don't remove**: `services/docs_service.py`'s backward-compatible mode-detection fallback
  (WP-33.2) — it correctly labels already-ingested legacy documents that predate this migration; no
  reason to break display of historical data just because new ingestion is docling-only.
- **Docs**: `ARCHITECTURE.md`, `docs/OPERATIONS.md`, `README.md` all reference `--layout-mode auto`
  and/or dual-path behavior (Decisions and Guardrails #9) — need updating, not just the pipeline code.
  `CLAUDE.md` covers the same ground but is gitignored (confirmed via `.gitignore:208`) — it's edited
  directly as part of implementing this WP, not part of any PR diff. Codex's round-4 review correctly
  flagged that it can't see this file in the PR tree and asked whether that was expected — it is.

This is real enough scope that it should land as its own WP, first (see §7 — this became WP-34.1
once the strawman below was renumbered) — the actionability fixes get simpler once it's done, not the
other way around.

## 7. Revised strawman WP breakdown

- **WP-34.1 — Deprecate legacy pymupdf/pdfplumber chunking, docling-only.** New, per §6's decision.
  Goes first because WP-34.2/34.3 both get simpler once it's done, not the other way around. Real
  migration scope (code removal, hard-error-on-docling-failure behavior change, test rewrite,
  dependency/docs updates) — see §6 for the concrete file-by-file list already surveyed against
  current code.
- **WP-34.2 — Reject heading-echoed and unrepairable-fragment quotes in Step D.** Categories 2+3,
  combined (they turned out to share a Step D home and complementary detection signals). Deterministic,
  can now assume `section_title_path` always exists (no legacy-fallback branch to design for). 5 real
  cross-document fixtures already in hand. Implementation detail from Codex round 2: the hierarchy
  lookup ordering trap in `parse_and_normalize.run()`, and reuse `_normalize_heading()` — see §3.
- **WP-34.3 — Expand `skip_sections` heading vocabulary.** Category 4 only now (category 1 is closed
  out entirely by WP-34.1, no separate process step needed). Small config change. Test design per
  Codex round 2: both positive fixtures (`Terms`, `Glossary`, `References` actually getting skipped)
  and negative fixtures (a heading that merely *contains* one of those words in a valid,
  non-skippable context, e.g. something like "References to External Systems" as a real content
  section — `_should_skip_section`'s prefix-match rule would need checking against exactly this kind
  of near-miss before the vocabulary list grows).
- **WP-34.4 (own phase if it needs one) — Description-grounding spike.** Investigation-only, including
  a small NLI-model try-it-and-look-at-results pass per §4. Unchanged from the first draft, just
  renumbered.

Category 5 stays a `docs/TODO_future_improvements.txt` note, not a WP.

## 8. Remaining open questions

§6's legacy-chunking question is decided (docling-only). What's left:

1. The `skip_sections` heading-vocabulary survey (§3, category 4 / WP-34.3) — worth doing against a
   few more documents before writing that WP, or expand the list now and iterate later?
2. Is the NLI-entailment approach (§4 / WP-34.4) worth spiking now as part of Phase 34, or genuinely
   deferred further out given it's still the least-scoped piece?
3. §6's migration scope (WP-34.1) is real but bounded — worth confirming the file-by-file list there
   matches expectations before it gets locked into a full phase doc, since it's the one piece of this
   plan that wasn't in either of the first two drafts.
