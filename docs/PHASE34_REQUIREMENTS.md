# ReqBot Phase 34 — Docling-Only Migration & Actionability Structural Fixes

**Status:** Locked (drafted 2026-07-29; source: WP-33.3's spike findings
(`docs/PHASE33_REQUIREMENTS.md`, PR #156) plus the docling-only architecture decision made during
this phase's own brainstorm (`docs/PHASE34_BRAINSTORM.md`, PR #157))
**Date:** 2026-07-29
**Preceded by:** Phase 33 (Profile Vocabulary Deduplication, Skip-Section Gap Visibility &
Actionability Spike) — closed 2026-07-28, all three WPs complete.
**Followed by:** No phase opened yet. WP-34.4's spike concluded viable-with-a-fix — a production
Step D.5 description-grounding entailment gate is real, scoped-but-unimplemented follow-up work,
tracked as `docs/TODO_future_improvements.txt` item 31, not yet promoted to its own WP/phase.

---

## Status

This table is the live source of truth for Phase 34 WP status — update it here when a WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-34.1 — Deprecate Legacy Chunking, Docling-Only | Complete — legacy pymupdf/pdfplumber chunking removed (`pipeline/extract_pdf_to_text.py` deleted, `pipeline/chunk_text.py`'s legacy `run()`/helpers removed); `--layout-mode` removed from all three independent locations (`cli/reqbot.py`, `cli/console.py`, `pipeline/run_pipeline.py`'s own `main()`); docling failure is now an unconditional hard error; docling moved into the base install (`pyproject.toml`); `requirements.txt` retired in favor of `pip install .` (CI/Dockerfile updated accordingly) |
| WP-34.2 — Reject Heading-Echoed and Unrepairable-Fragment Quotes in Step D | Complete — `_is_heading_echo`/`_is_unrepairable_fragment` added to `pipeline/parse_and_normalize.py`'s validation loop; hierarchy resolution moved earlier so `section_title_path` is available to the new checks; heading-echo uses `fuzz.ratio` (not literal substring containment — a real false-positive risk found during implementation, see §4 below) |
| WP-34.3 — Expand `skip_sections` Heading Vocabulary | Complete — `"TERMS"` added to `profiles/cybersecurity.json`'s `skip_sections`, confirmed via a 6-document heading-vocabulary survey (see §4 below); no change to `_should_skip_section`'s matching algorithm — a real over-matching tradeoff was investigated (independently re-flagged by Codex on PR #163, confirmed still unfixable without regressions) and deliberately left as-is (documented in the function's docstring and pinned by regression tests) |
| WP-34.4 — Spike: Description-Grounding Entailment Check | Spike complete, viable-with-a-fix — MiniCheck (flan-t5-large) caught 5/6 known-real fabricated-description examples (1 miss found by Codex review, a distinct modality-fabrication case) with zero false positives on 9 real faithful paraphrases (see §4 below); production integration scoped as explicit follow-up (`docs/TODO_future_improvements.txt` item 31), not implemented in this spike per its own Non-Goals |

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

**Implementation note (deviation from the Scope above):** the heading-echo check does not use literal
substring containment ("is contained by/contains"). Tested against a realistic adversarial case before
locking it in: a short, generic heading like `"Purpose"` appears verbatim as a substring inside plenty
of genuine, unrelated requirements (e.g. `"Access badges shall be issued for the sole purpose of
controlling entry to restricted areas."`) — literal containment would reject those as heading echoes,
which they are not. Used `rapidfuzz.fuzz.ratio` (whole-string similarity, threshold 90) instead of
`in`/`==`: both real fabrication fixtures score 100 (exact match after normalization) and pass the
threshold comfortably, while the "Purpose" adversarial case scores low and survives. Same rapidfuzz
dependency already in use for WP-32.1's grounding check, applied with the comparison shape (`ratio`,
not `partial_ratio`) suited to "are these two full strings basically the same," not "does a short
string appear somewhere in a much longer one." The unrepairable-fragment check's threshold
(`UNREPAIRABLE_FRAGMENT_MAX_WORDS = 25`) is a judgment call, not a calibrated sweep like WP-32.1's —
chosen with headroom above the longest known real fixture (20 words); revisit if a future false
positive/negative surfaces on a broader corpus.

Manually verified against real data: re-ran Step D only (`--skip-to D`) against the existing docling
extraction outputs for both `afpd_17-1.pdf` and `CJCSI 6510.02G.pdf` (from the Phase 34 brainstorm
re-ingest). All 5 known fixtures were caught with the expected failure reason and no others; the
pre-existing `quote_not_grounded_in_chunk` rejection counts were unchanged (3 and 16 respectively) —
confirming zero collateral rejections among requirements the new checks weren't meant to touch.

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

**Survey findings (implementation):** ran Steps A+B only (docling parse + chunk, no Ollama needed)
on 6 real documents beyond the two already covered by the Phase 34 brainstorm (`afpd_17-1.pdf`,
`CJCSI 6510.02G.pdf`) — `afi17-101.pdf`, `DODI 8500.01.pdf`, `NIST.SP.800-171r3.pdf`, and
`dafman17-1203.pdf` — and inspected every unique `section_title_path` heading against the current
`skip_sections` list. (`CNSSI_No1253.pdf` was also attempted but its parse was accidentally killed
by a scratch-directory cleanup mid-run; not retried since the other 6 documents already gave
strong, independently-replicated evidence.)

- `"Terms"` is confirmed **not** a one-document idiosyncrasy: it appears independently in
  `afpd_17-1.pdf`, `afi17-101.pdf`, **and** `dafman17-1203.pdf` (all AFI/AFPD/DAFMAN-series), a
  real convention for that document family, not a fluke. Added as the sole new entry.
- Every other glossary/definitions/references-equivalent heading found across all 6 documents was
  already correctly matched by the existing list — `"PART II.  DEFINITIONS"`,
  `"PART I.  ABBREVIATIONS AND ACRONYMS"`, `"REFERENCES"`/`"References"`, `"Appendix B. Glossary"`.
  No other new synonym was needed.
- `CJCSI 6510.02G.pdf` (already surveyed during brainstorming) has no glossary/definitions/
  references-equivalent section at all — confirmed again, not a gap.
- **A real, separate gap found and deliberately left out of scope:** `NIST.SP.800-171r3.pdf`'s
  acronym-list entries (e.g. `CFR`, `CISA`, `CUI`) each get docling-parsed as their own standalone,
  parentless heading (`section_title_path == ["CFR"]`, no enclosing "Acronyms" ancestor at all) —
  not a vocabulary problem `skip_sections` can fix by adding words, since there's no parent heading
  text to match against. This is a docling/HybridChunker structural-parsing gap, not this WP's
  territory (which is `profiles/cybersecurity.json` vocabulary, not chunking logic). Not fixed here;
  logged as item 30 in `docs/TODO_future_improvements.txt`.
- **Over-matching risk investigated, not fixed:** confirmed empirically (not just hypothetically)
  that `_should_skip_section(["References to External Systems"], ["REFERENCES"])` returns `True` —
  a real false-positive shape. No live instance of this shape was found across the 6-document
  survey, and a stricter matching rule (e.g. requiring nothing follow the skip word) would break the
  confirmed-real `"Abbreviations and Acronyms"` case, which has the identical shape
  (skip-word + more free words) but must stay skipped. Left the algorithm unchanged — the tradeoff
  is now documented in `_should_skip_section`'s docstring and pinned by two regression tests
  (`test_over_matches_references_to_external_systems`, `test_over_matches_terms_of_the_agreement`)
  so a future change to the algorithm has to consciously decide to alter this rather than silently
  regress one case while fixing the other.

**Review outcome (PR #163):** Codex independently flagged the exact same `"TERMS"` over-matching
risk (P2) and suggested treating it as an exact match or restricting to known suffixes. Tried that
concretely rather than dismissing it: it breaks the pre-existing, already-passing
`test_heading_starts_with_skip_phrase` test (`"Glossary of References and Supporting Information"`
has the identical "skip-word + of + more words" shape and must keep matching) — confirming no cheap
syntactic fix exists, consistent with the finding above. Replied on the thread with this evidence;
no code change. Gemini's one finding (claimed `test_terms_not_skipped_without_being_added` would
fail at runtime) was a false alarm — it assumed `CYBERSECURITY_SKIPS` might be loaded from
`profiles/cybersecurity.json`; it's actually a hardcoded test fixture representing the pre-TERMS
list on purpose, and the test passes (confirmed via `pytest`, 50/50 in this file).

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

**Spike results (implementation):** `eval/entailment_spike.py`; full output in
`eval/spike_results/wp_34_4/report.md` and `results.json`.

- **HHEM tried first, rejected on compatibility, not quality.** Its custom `trust_remote_code`
  modeling code (`vectara/hallucination_evaluation_model`) raises
  `AttributeError: 'HHEMv2ForSequenceClassification' object has no attribute
  'all_tied_weights_keys'` against this repo's already-pinned `transformers==5.5.0`. Downgrading
  `transformers` to chase HHEM compatibility risks breaking docling itself (also a `transformers`
  consumer) — well outside a spike's blast radius. Moved to MiniCheck without spending further
  effort forcing HHEM to work.
- **A real PyPI name collision, worth recording so it isn't hit again:** `pip install minicheck`
  installs an unrelated formal state-machine model checker (explicit-state FSM verification, ~2900
  lines, nothing to do with NLI/fact-checking) that happens to squat the same package name. The
  actual MiniCheck (Liyan06/MiniCheck, Bespoke Labs/UPenn) installs from its GitHub source:
  `pip install --user --break-system-packages "git+https://github.com/Liyan06/MiniCheck.git"`
  (`--break-system-packages` matches how this environment's other ML dependencies — docling,
  torch, transformers — are already installed; confirmed via `pip show docling`'s install path).
  Also needs one NLTK resource: `python3 -c "import nltk; nltk.download('punkt_tab')"`.
- **Test set: 15 real (source_quote, description) pairs, zero synthetic data** — 6 known-fabricated
  (pulled by flagging short/colon-terminated quotes paired with a much longer, low-similarity
  description across every enriched JSONL under `~/documents/processed/`, then hand-verified each
  against its source document) and 9 known-faithful (hand-picked to span a real range of
  quote/description similarity, not just near-verbatim echoes — most of this corpus's Step D.5
  output turned out to be close-to-verbatim copies rather than true paraphrases, itself a minor
  observation worth noting, so genuinely-paraphrased examples had to be deliberately sought out to
  actually stress-test the model rather than trivially pass on lookalike text).
- **Result: 1/6 false negatives (17%), 0/9 false positives.** The 5 caught known-bad pairs and all 9
  known-good pairs separate with a wide margin — caught known-bad scores 0.026–0.133, known-good
  0.852–0.978, no pair from either set within 0.7 of the other's range. This held even against two
  deliberately-hard cases: a faithful paraphrase with a mild inferential step (`"I declare..."` →
  `"The system administrator declares..."`) and a subtle fabrication (`"Distribution: A, B, C"` →
  adds an invented `"as per Reference J-6"` attribution).
- **The one miss (`support_prob=0.9197`, scored as supported when it should not have been) — found
  by Codex review on PR #164, not by this WP's own initial pass.** This pair was originally
  (mis-)classified as known-good: `"Cybersecurity - Prevention of damage to..."` → `"Implement
  cybersecurity measures to prevent damage..."`. Codex correctly flagged that reframing a
  dictionary-style definition as an imperative obligation isn't a faithful paraphrase — the source
  never states anyone must *implement* anything, only what the word means. Checking the full
  record confirmed it's worse than even that: `section_title_path=["Terms"]` — this is a
  glossary/definitions entry (WP-33.3 category 4, background/definitional prose misextracted as a
  requirement), a chunk WP-34.3's `skip_sections` fix now filters before Step C in a fresh ingest,
  though this historical record predates that fix. Reclassified as known-bad; the corrected numbers
  above reflect that. **This is a real, distinct limitation, not noise:** an entailment check scoped
  to factual content (do the named facts appear in the quote) does not by itself catch obligation/
  modality invented on top of otherwise-faithful facts — every individual fact in that description
  does appear in the quote, only the "you must implement this" framing is fabricated.
- **Caveats, honestly stated:** small test set (15 pairs, per the WP's own "small, real" framing —
  not a quantified precision/recall eval), drawn from only 2 documents (`afpd_17-1.pdf`,
  `CJCSI 6510.02G.pdf` — this phase's whole corpus), and CPU inference on `flan-t5-large` (770M
  params) took ~230ms/pair batched, fast enough to plausibly gate every Step D.5 output but not
  load-tested at real corpus scale.

**Conclusion, per Success Criteria and Reject-If above:** viable-with-a-fix, with a named limitation.
The signal is clear and evidence-backed on the factual-fabrication failure mode this WP targets (5/5
of the citation/fragment-completion cases caught cleanly, 0 false positives on real faithful
paraphrases) — not "seems promising." The one miss is a distinct failure mode (modality/obligation
fabrication on top of otherwise-faithful facts) worth flagging explicitly to whoever implements the
follow-up, not evidence the overall approach doesn't work. Per this WP's own Non-Goals, no production
Step D.5 change is made in this spike. Scoped as explicit follow-up:
`docs/TODO_future_improvements.txt` item 31, updated to carry this caveat forward.

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
