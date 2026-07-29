# ReqBot Phase 34 — Docling-Only Migration & Actionability Structural Fixes

**Status:** Locked (drafted 2026-07-29; source: WP-33.3's spike findings
(`docs/PHASE33_REQUIREMENTS.md`, PR #156) plus the docling-only architecture decision made during
this phase's own brainstorm (`docs/PHASE34_BRAINSTORM.md`, PR #157))
**Date:** 2026-07-29
**Preceded by:** Phase 33 (Profile Vocabulary Deduplication, Skip-Section Gap Visibility &
Actionability Spike) — closed 2026-07-28, all three WPs complete.
**Followed by:** None currently planned — WP-34.4's spike outcome may generate a follow-up WP or
phase for the actual description-grounding fix, depending on its findings.

---

## 1. Phase Framing

Unlike Phase 33 (three independent backlog items), Phase 34 has a hard sequencing dependency: WP-34.1
must land before WP-34.2 and WP-34.3 can be correctly scoped, because both assume
`section_title_path` is always available — true only once legacy chunking is gone. This phase started
from WP-33.3's own Reject-If outcome ("the problem is real and sizable... scope the actual fix as its
own WP") but diverged significantly from an initial, more speculative plan during a same-session
brainstorm (`docs/PHASE34_BRAINSTORM.md`) once the corpus was re-ingested via docling and turned out
to change which failure modes even occur. That document is the "why" for this phase's decisions in
more narrative detail than belongs here — read it first if a Scope section below raises a "why not X
instead" question; it also has the full three-round external-review history (Codex, PR #157) behind
these WPs' specifics.

**A scope correction made during drafting, worth stating up front:** WP-33.3's spike identified five
failure-mode categories and implicitly assumed each would need its own fix mechanism. Two turned out
not to need new pipeline code at all once the corpus was actually docling-ingested — the reference-list
misextraction category (WP-33.3's largest, at 17.5% of its sample) never occurs once `skip_sections`
actually applies, which only happens on the docling path. The WPs below are narrower and cheaper than
WP-33.3's own framing anticipated.

---

## 2. Goals

- Collapse ReqBot's PDF ingestion to a single, structure-aware path (docling), eliminating the legacy
  pymupdf/pdfplumber chunking path that has no section-hierarchy metadata and, per WP-33.3's spike,
  both permits and partially causes several actionability failure modes.
- Close the two remaining, well-evidenced actionability failure modes from WP-33.3's spike
  (heading-echoed/fragment quotes; a `skip_sections` heading-vocabulary gap) with deterministic,
  no-LLM-call Step D checks and configuration — not new pipeline stages or prompt changes.
- Determine, via a scoped spike, whether an NLI-based entailment check is a viable path to catching
  Step D.5's fabricated-description symptom — the highest-value gap WP-33.3 found, and the one still
  genuinely unscoped.

## 3. Non-Goals

- No new pipeline stage or Step C prompt rewrite for any of this phase's fixes — WP-33.3's spike
  already demonstrated, empirically and twice, that Step C prompt edits carry real regression risk on
  the current extraction model and don't reliably fix the categories they'd target.
- No production Step D.5 change from WP-34.4 — it's an investigation-only spike, mirroring WP-33.3's
  own discipline. A fix, if warranted, is explicit follow-up work.
- No re-ingestion of a broader corpus is required by this phase — useful eventually (heading-
  vocabulary coverage for WP-34.3), but the two-document re-ingest already done during brainstorming
  was sufficient to scope every WP below.
- No change to what `services/docs_service.py` reports for already-ingested legacy documents — its
  backward-compatible mode detection (WP-33.2) stays exactly as it is; this phase changes what future
  ingestion does, not how past ingestion is displayed.

---

## 4. Work Packages

### WP-34.1 — Deprecate Legacy Chunking, Docling-Only

**Source:** `docs/PHASE34_BRAINSTORM.md` §6, decided 2026-07-29. Migration scope surveyed against
current code across three external review rounds (Codex, PR #157), each claim independently verified
before being accepted.

**Problem:** ReqBot supports two PDF-ingestion backends — docling (structure-aware, produces
`section_title_path`/`section_ref_path` hierarchy metadata) and legacy pymupdf/pdfplumber chunking
(flat `{page_num, text, source_pdf}` records, no structure at all) — selected via `--layout-mode`
(`auto`/`docling`/`pymupdf`/`pdfplumber`), with `auto` silently falling back from docling to pymupdf
per-document on failure or when docling isn't installed (Decisions and Guardrails #9). Two problems
with this: (1) the legacy path's missing structure directly permits/causes actionability failure
modes WP-33.3's spike found (see WP-34.2/34.3 below — both need `section_title_path`, which legacy
chunking never produces); (2) the original reason docling was made optional — `pyproject.toml` gates
it out of the base install "purely for weight" (torch/torchvision), per
`archive/PHASE25_REQUIREMENTS.md` — doesn't hold for ReqBot's actual deployment context (self-hosted
by IT admins on a real network, not a storage-constrained device).

**Scope:**
- `pipeline/run_pipeline.py`: remove the legacy branch (the `extract_pdf_to_text.run()`/
  `chunk_text.run()` path) and `resolve_layout_mode()`'s auto-fallback (`_docling_available()`, the
  "auto → pymupdf on docling failure" behavior). Docling failure becomes a hard error
  unconditionally — the same "fail loudly, don't silently downgrade" principle
  `resolve_layout_mode()` already applies to an explicit `--layout-mode docling` request, extended to
  be the only behavior.
- Remove `pipeline/extract_pdf_to_text.py` entirely (Step A's legacy path) and
  `tests/unit/test_extract_pdf.py` (tests only that file's low-text-page logic).
- Remove `pipeline/chunk_text.py`'s legacy `run()` and its exclusive helpers (`chunk_text()`,
  `load_pages`, `build_page_index`, `pages_for_span`, `find_table_spans`, `table_span_at`,
  `validate_page_contiguity`). Keep `run_structure_aware()` and the shared helpers
  (`_should_skip_section`, `_normalize_heading`, `_should_skip_chunk` — WP-34.2/34.3 depend on
  these). This file's own standalone `main()`/CLI is dual-mode today (`input_path` means
  `pages.jsonl` in legacy mode vs. a PDF with `--docling` — legacy-only flags `--chunk-size`/
  `--overlap`/`--table-aware`) and calls the legacy `run()` directly in its non-`--docling` branch —
  restructure it to be docling-only (drop the legacy branch and its flags, `input_path` always a
  PDF), not just delete the function underneath it and leave the CLI referencing dead code.
- Remove the `pymupdf`/`pdfplumber`/`auto` `--layout-mode` choices from **three** independent
  argument definitions, not one shared source: `cli/reqbot.py`'s argparse subcommands,
  `cli/console.py`'s separate interactive-shell `ingest`/`batch` parsers, and
  `pipeline/run_pipeline.py`'s own standalone `main()` (`choices=["auto", "pymupdf", "pdfplumber",
  "docling"]`) — the direct-script entry point (`python pipeline/run_pipeline.py ...`), independent
  of both CLIs.
- Rewrite `tests/unit/test_layout_mode_auto.py` around "docling unavailable/failure is a hard error"
  (most of its current tests assert fallback behavior that no longer exists); `tests/unit/
  test_wp_20_3.py`'s `run_pipeline.run()` profile-plumbing test (currently patches
  `pipeline.extract_pdf_to_text.run`/`pipeline.chunk_text.run` directly — needs to patch the
  docling/`section_parser` path instead, not just lose the coverage); and `tests/unit/
  test_cli_ingest.py`'s `_args()` helper (hardcodes `layout_mode="pymupdf"` — `run_pipeline.run()`
  is mocked in these tests, so this won't fail on its own once `pymupdf` stops being a valid choice
  elsewhere, it'll just keep silently encoding a stale value).
- `pyproject.toml`: move the `docling` extra into the base install.
- `requirements.txt`: currently has no docling entry on either path and still pins
  `pymupdf==1.27.1`/`pdfplumber==0.11.9`. Decide during implementation whether to add
  `docling==2.84.0` and drop the legacy pins, or retire the file entirely in favor of `pip install .`
  (`README.md` already documents `requirements.txt` as a legacy, pre-WP-25.2-packaging path, "not
  recommended for new setups") — don't just delete two lines and leave that install path broken.
- Update `ARCHITECTURE.md`, `docs/OPERATIONS.md`, `README.md` wherever they describe
  `--layout-mode auto`/dual-path behavior (Decisions and Guardrails #9 is superseded by this WP).
  `CLAUDE.md` is gitignored (not part of this or any PR) and covers the same ground — edit it
  directly as part of implementing this WP, same as any other CLAUDE.md update, rather than treating
  it as in-scope for the PR diff.

**Non-goals:**
- No change to `services/docs_service.py`'s backward-compatible mode-detection fallback — keeps
  correctly labeling already-ingested legacy documents.
- No change to `skip_sections` matching logic itself (WP-34.3's territory).
- No requirement to re-ingest any existing legacy-chunked document as part of this WP — an
  operational follow-up, not something this WP's code needs to do.

**Tests/verification:**
- Full `pytest` suite passes with the legacy-path tests removed/rewritten per Scope above.
- `ruff check .` clean.
- Manual: a fresh `pip install .` (base, no extras) can run `reqbot ingest` on a real PDF with no
  additional flags. Uninstalling/blocking docling and attempting an ingest produces a clear,
  actionable error, not a silent fallback or a confusing downstream failure.

**Gate:** `--layout-mode` no longer accepts `pymupdf`/`pdfplumber`/`auto` as meaningful choices (or
they're explicitly rejected with a migration-pointing error message); docling is present in a base
install with no extra flags; existing legacy-ingested documents in `~/documents/processed/` still
display correctly via `reqbot docs`.

---

### WP-34.2 — Reject Heading-Echoed and Unrepairable-Fragment Quotes in Step D

**Source:** WP-33.3 spike categories 2 and 3 (`docs/PHASE33_REQUIREMENTS.md`), re-evidenced against
real docling re-ingests in `docs/PHASE34_BRAINSTORM.md` §3. Depends on WP-34.1 (assumes
`section_title_path` always exists).

**Problem:** Two related failure modes, both confirmed across both corpus documents' docling
re-ingests, 5 concrete examples total (not the original 2 from WP-33.3's smaller sample): (1) Step C
occasionally extracts a chunk's own structural heading text as if it were a body-content
requirement — e.g. `"COMPLIANCE WITH THIS PUBLICATION IS MANDATORY"` and `"All HAF Functionals,
MAJCOMs, DRUs, and FOAs will:"`, both of which are *exactly* their chunk's own
`section_title_path[-1]` value; (2) Step C extracts a truncated list-header sentence ending in a
colon with no following content (e.g. `"The process will be as follows:"`), and Step D.5 enrichment
then fabricates plausible-sounding `description` content to "complete" it — content that appears
nowhere in the actual `source_quote`, directly violating the "ingestion captures verbatim... do not
invent obligations" architecture principle.

**Scope:**
- New rejection check(s) in `pipeline/parse_and_normalize.py`'s existing per-requirement validation
  loop (same shape as `empty_source_quote`/`quote_not_grounded_in_chunk`/`errata_change_entry`):
  - **Heading-echo:** reject if `source_quote`, normalized, matches (equals or is contained
    by/contains) its own chunk's `section_title_path[-1]`, also normalized. Reuse
    `pipeline/chunk_text.py`'s `_normalize_heading()` (strips numbering prefixes, lowercases,
    collapses whitespace) for both sides of the comparison rather than inventing separate matching
    logic — it may need to move somewhere importable from both modules, or be imported directly.
  - **Unrepairable fragment:** reject if `source_quote` ends in a colon, is short, and has no
    obligation content after the colon (a compound rule — not a bare `endswith(":")`, which would
    also catch legitimate longer quotes that happen to contain a colon elsewhere).
  - Implementation ordering matters: `parse_and_normalize.run()` builds `chunk_hierarchy_map` before
    its per-requirement loop, but each requirement's own `section_title_path` isn't resolved from it
    until *after* the existing checks in that loop today (current code: hierarchy resolved around
    line 399, after the checks at lines 344–381). The new check needs to run after hierarchy is
    resolved, or the hierarchy lookup needs to move earlier — don't naively insert it alongside the
    existing checks without accounting for this.
  - New failure reason(s) recorded in `*_normalization_failures.jsonl`, matching the existing pattern.
- This WP assumes WP-34.1 has landed — `section_title_path` is always populated (docling-only), no
  fallback/empty-list handling needed for a "no hierarchy available" case.

**Non-goals:**
- No fix for category 1 (closed by WP-34.1) or category 4 (WP-34.3).
- No attempt to salvage/reconstruct a complete quote from a rejected fragment by pulling in
  surrounding chunk text — reject only. Matches this project's "ingestion captures verbatim"
  principle; don't invent or assemble content even structurally.
- No change to Step C's prompt or Step D.5's enrichment prompts.

**Tests/verification:**
- Positive (must-reject) fixtures: the 5 real examples already in hand —
  `"COMPLIANCE WITH THIS PUBLICATION IS MANDATORY"`, `"All HAF Functionals, MAJCOMs, DRUs, and FOAs
  will:"` (both `afpd_17-1.pdf`, docling re-ingest), `"The process will be as follows:"`, `"The KER
  may be sent either by scanned soft copy via SIPRNET or by mail to the address listed below:"` (both
  `CJCSI 6510.02G.pdf`, docling re-ingest), plus WP-33.3's original `"The MC4EB will:"` fixture.
- Negative (must-not-reject) fixtures: real short/terse quotes from the same corpus that must survive
  — e.g. `"KERs shall be approved by the MC4EB."` (7 words, no trailing colon, doesn't echo a
  heading) — confirming the compound rule doesn't over-reject genuinely terse-but-real requirements.
- Full `pytest` suite passes; `ruff check .` clean.
- Manual: re-running the docling ingest of both current corpus documents produces zero heading-echo
  or unrepairable-fragment quotes in `*_requirements_normalized.jsonl`.

**Gate:** All 5 known positive fixtures are rejected with a durable failure reason; all negative
fixtures pass through unaffected.

---

### WP-34.3 — Expand `skip_sections` Heading Vocabulary

**Source:** WP-33.3 spike category 4, `docs/PHASE34_BRAINSTORM.md` §3. Depends on WP-34.1.

**Problem:** `afpd_17-1.pdf`'s glossary/definitions section is headed literally `"Terms"` — not
covered by the cybersecurity profile's configured `skip_sections` list (`GLOSSARY`, `REFERENCES`,
`ACRONYMS`, `DEFINITIONS`, `ABBREVIATIONS`, `TABLE OF CONTENTS`), so its background/definitional
prose isn't filtered out before Step C and gets misextracted as a requirement (e.g. `"CFLs integrate
Total Force concepts, capabilities, modernization, and resourcing..."` — descriptive narrative, no
obligation language). `CJCSI 6510.02G.pdf` has no equivalent issue — this is a document-specific
heading-vocabulary gap, not evidence the whole mechanism is broken (`_should_skip_section` already
does case-insensitive, prefix-based matching correctly; it just doesn't know `"TERMS"` is a synonym).

**Scope:**
- Survey a handful of additional real documents' actual heading vocabulary for glossary/definitions/
  references-equivalent sections before committing to a specific expanded list — don't generalize
  from one document's idiosyncratic choice.
- Add confirmed synonyms to `profiles/cybersecurity.json`'s `skip_sections` (at minimum `"TERMS"`,
  confirmed already; others per the survey).

**Non-goals:**
- No change to `_should_skip_section`'s matching algorithm (prefix-based, case-insensitive) unless
  the survey specifically finds a heading shape it can't handle (e.g. a compound heading needing
  substring rather than prefix matching) — call that during implementation if it comes up, not
  pre-decided here.
- No profile beyond cybersecurity affected (no second profile exists yet).

**Tests/verification:**
- Positive fixtures: headings that should be skipped (`"Terms"`, `"Glossary"`, `"References"`, and
  whatever the survey confirms) actually get filtered.
- Negative fixtures: a heading that merely *contains* one of those words in a valid, non-skippable
  context (e.g. something shaped like `"References to External Systems"` as a real content section)
  does **not** get incorrectly dropped by the prefix-match rule — a real risk as the vocabulary list
  grows, not just a hypothetical.
- Full `pytest` suite passes; `ruff check .` clean.
- Manual: re-ingesting `afpd_17-1.pdf` via docling no longer produces category-4-shaped
  misextractions from its `"Terms"` section.

**Gate:** The heading-vocabulary survey is documented (which documents, which headings, what was
added and why); `afpd_17-1.pdf`'s `"Terms"` section content is filtered on re-ingest; the negative
fixture set confirms no over-matching.

---

### WP-34.4 — Spike: Description-Grounding Entailment Check

**Source:** WP-33.3 spike's identified gap (no verification exists anywhere in the pipeline for
whether Step D.5's `description` is actually grounded in `source_quote`), `docs/PHASE34_BRAINSTORM.md`
§4. Independent of WP-34.1/34.2/34.3 — can run in parallel or any order relative to them.

**Goal:** Determine whether a lightweight NLI (natural language inference) cross-encoder entailment
check (`premise=source_quote`, `hypothesis=description`) can reliably catch the fabricated-description
symptom WP-33.3's spike found — e.g. a citation-shaped quote paired with an invented, plausible-
sounding description, or a truncated fragment paired with a description that completes it with
content from nowhere — without rejecting normal, faithful paraphrases (which is what `description` is
supposed to be; Step D.5's own prompt asks for "one precise sentence summarizing," not verbatim text).

**Rationale:** This is the established **faithfulness hallucination** detection problem in current
literature, not something to design from scratch. WP-32.1's existing Step D grounding check (fuzzy
substring match between a verbatim quote and its verbatim chunk) is the wrong mechanism for this —
confirmed via Codex review, PR #157 — because it assumes both sides are the same literal text, which
a faithful paraphrase legitimately isn't.

**Scope:**
- Eval-only spike (mirrors `eval/docling_spike.py`'s "try a candidate library, look at real results"
  pattern) — not a production change to Step D.5.
- Start with HHEM or MiniCheck (compact, purpose-built RAG-groundedness/factual-consistency models)
  rather than FactCG, which reads as newer research aimed at graph/multi-hop fact-checking, not an
  obvious first local dependency for this use case.
- New dependency for the spike — bring it with the reasoning above and real results to look at, per
  standing guidance on this project (new dependencies aren't a heavy blocker if justified).
- Test against the known fabricated-description examples already documented in WP-33.3's Findings and
  this phase's own re-ingests, plus a set of real, faithful `description`/`source_quote` pairs
  already in the corpus (must NOT be flagged).

**Non-goals:**
- No production Step D.5 change inside this spike — investigation only, same discipline WP-33.3 used.
  If a fix is warranted, it's explicit follow-up work with its own review.
- No commitment to a specific model/library before results are in.
- Does not need to solve categories 1–4 above — WP-34.1/34.2/34.3 already close those; this spike is
  specifically about the `description`-fabrication symptom that survives even a clean `source_quote`.

**Success Criteria:** A clear, evidence-backed answer on whether the chosen technique(s) catch the
known fabrication examples without flagging real faithful paraphrases — not "seems promising."

**Reject-If:** If no candidate model achieves an acceptable false-positive/negative rate on the
(small, real) test set, document the finding and defer further work rather than forcing a fix into
this phase.

---

## 5. Success Gate

Phase 34 is complete when:

1. WP-34.1 is merged — ReqBot ingests via docling only; no legacy pymupdf/pdfplumber path remains.
2. WP-34.2 and WP-34.3 are merged — the two remaining evidenced actionability failure modes from
   WP-33.3's spike (heading-echo/fragment quotes, `skip_sections` vocabulary gap) are closed.
3. WP-34.4's spike has reached a documented conclusion (viable-with-a-fix, or not-viable-enough), and
   any resulting fix work has been scoped as explicit follow-up — mirroring WP-33.3's own Reject-If
   discipline, not folded silently into this phase.
4. Full unit suite passes (`pytest`); `ruff check .` passes.
5. `docs/PHASE33_REQUIREMENTS.md`'s WP-33.3 Findings' five failure-mode categories are all either
   closed (1–4) or have a documented spike outcome (the description-fabrication symptom underlying
   parts of 1 and 3, via WP-34.4) — category 5 (rare, low-priority) stays a
   `docs/TODO_future_improvements.txt` note, not a WP, per WP-33.3's own original disposition.

---

## 6. Guardrails

1. One WP at a time — each lands as its own PR, reviewed before proceeding to the next, same cadence
   as Phases 29–33. WP-34.1 must land and merge before WP-34.2/34.3 start (a hard dependency, not
   just a suggested ordering — both assume `section_title_path` always exists).
2. WP-34.4 is investigation only — do not write a production fix inside the spike itself. If a fix
   turns out to be warranted, scope it as explicit follow-up work with its own review.
3. WP-34.2's structural checks reject only — no salvage/reconstruction of rejected fragment quotes
   from surrounding chunk text, even though the content is technically available. Don't invent or
   assemble content that wasn't in the original `source_quote`.
4. WP-34.1's dependency-file decision (update `requirements.txt` to include docling vs. retire it)
   must actually be made and documented, not defaulted to "delete the pymupdf/pdfplumber lines and
   move on" — that would leave a documented, still-supported install path broken.
