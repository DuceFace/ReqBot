# ReqBot Phase 32 — Evidence Pipeline Provenance Investigation & Evidence/Search UX Cleanup

**Status:** Locked (drafted 2026-07-27; source: Tyler's manual walkthrough of a live Evidence query
against a real result page — the specific `requirement_id`/document/page values cited in WP-32.1
and WP-32.2 below are the reproduction evidence, transcribed directly from that walkthrough)
**Date:** 2026-07-27
**Preceded by:** Phase 31 (Trace/Compare Type Fix, Citation Numbering & Profile Schema Docs) —
closed 2026-07-27, all three WPs complete. See this doc's Non-Goals for how WP-32.7 relates to
WP-31.3's `docs/PROFILES.md`.
**Followed by:** None currently planned — next work will be selected from the live backlog
(`docs/TODO_future_improvements.txt`) once Phase 32 closes.

---

## Status

This table is the live source of truth for Phase 32 WP status — update it here when a WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-32.1 — Spike: Provenance Mismatch / Possible Extraction Hallucination | Complete — fix shipped and validated against 2 fresh re-ingests; rest-of-corpus re-ingest tracked separately, not part of this WP |
| WP-32.2 — Spike: Ligature/Text-Extraction Corruption | Complete — isolated to `NIST.SP.800-53Ar5.pdf`, no layout-mode fixes it; repair tool shipped (`pipeline/repair_ligatures.py`), validated against real archived data; actual re-ingest of the document deferred with the rest of the corpus |
| WP-32.3 — Evidence Grouping Fallback Fix | Complete — shipped and verified live against the current corpus |
| WP-32.4 — Context Excerpt Labeling | Complete — caption added above the context block in `EvidenceView.tsx`; verified against a real truncated excerpt from the live corpus |
| WP-32.5 — Evidence/Search Card Visual Hierarchy Rework | Complete — `ResultCard.tsx` and `EvidenceView.tsx`'s `EvidenceCard` both swapped to promote doc name/page/source_ref, demote `requirement_id` |
| WP-32.6 — Render Generated Answer as Markdown | Complete — `react-markdown` added (Tyler's call over hand-rolling, see WP-32.6 notes below); citation-token linking preserved through nested lists |
| WP-32.7 — Profile-Aware Evidence Synthesis Vocabulary | Not started |

---

## 1. Phase Framing

Every item here came out of one live manual test: Tyler ran an Evidence query for "how long should
my password be?" against the real corpus, walked through the rendered result page end to end, and
found it confusing/wrong in more places than expected for a screen that's supposedly finished
product work. That page was saved locally as a diagnostic aid during the walkthrough but was never
committed to this repo and no longer exists — it isn't available as a reproduction artifact. Every
finding below instead cites the exact `requirement_id`/document/page/quote values transcribed
directly from that walkthrough at the time, in-line in each WP's own text, so nothing here depends
on a file that doesn't exist in the tree.

**This phase mixes two very different kinds of work, and the doc is organized so that distinction
stays visible:**

- **WP-32.1 and WP-32.2 are spikes, not fixes.** Both are triggered by a single data point each
  (one mismatched context, one corrupted document) — the *first* job is to find out whether each is
  an isolated incident or a systemic pipeline defect, because that answer determines whether a fix
  even belongs in this phase, a later phase, or a one-off data cleanup. Do not write a fix for
  either before its spike's Success Criteria are met. This mirrors this project's own established
  practice — verify empirically before fixing (see `archive/PHASE15_EXTENSION_RETRIEVAL_HARDENING.md`
  for the precedent on spike-shaped WPs with Reject-If criteria).
- **WP-32.3 through WP-32.7 are ordinary, boundable fixes** — the failure mode is already
  understood, only the implementation is left.

**Priority order, most to least urgent:**

1. WP-32.1 (provenance/trust — if this is systemic, it undermines the entire "cite your source"
   premise the product is built on)
2. WP-32.2 (data corruption, but scoped to whatever documents share the responsible font/encoding)
3. WP-32.3 (a UI-visible correctness bug users will keep hitting on any query with unreferenced
   requirements)
4. WP-32.4 / WP-32.5 / WP-32.6 (independent UX fixes, no particular order, can interleave with the
   spikes)
5. WP-32.7 (the largest single WP here — touches the synthesis prompt and needs profile schema
   context; do last)

No hard sequencing dependency forces this order — WP-32.3 through WP-32.6 don't depend on WP-32.1/
WP-32.2's findings — but severity does. Do the spikes first.

---

## 2. Goals

- Determine whether the two data-quality findings below (mismatched provenance, corrupted text) are
  isolated incidents or systemic pipeline defects, and fix them if the latter.
- Stop the Evidence view's grouping fallback from silently merging unrelated requirements from
  different documents under one meaningless label.
- Make the Evidence/Search card layout lead with what's actually useful to a human (document,
  page, paragraph/control reference) instead of an opaque internal ID.
- Render the Generated Answer's markdown instead of showing raw `**`/`-` syntax.
- Stop hardcoding cybersecurity-specific vocabulary ("Dominant Control Families: AC, IA...") into
  the evidence synthesis prompt, so it doesn't silently produce nonsense for a future non-cybersecurity
  profile.

## 3. Non-Goals

- No retroactive correction/flagging of the pre-WP-32.1 corpus — superseded by what actually
  happened: the corpus was disposable test data, so it was nuked outright (both Qdrant collections
  deleted, `~/documents/processed/` archived, not migrated) rather than patched in place. Re-ingesting
  the remaining 43 documents through the fixed pipeline is a separate, later decision, not assumed by
  this phase.
- No markdown rendering anywhere except the Generated Answer synthesis text (WP-32.6) —
  `source_quote`/`description`/context excerpts stay as plain escaped text; they're verbatim source
  material and rendering them as markdown risks misrepresenting the original document.
- No general redesign of the profile schema — WP-32.7 only changes what the evidence synthesis
  prompt is fed, not `core/profiles.py`'s validation/loading logic. If WP-31.3's `docs/PROFILES.md`
  isn't merged yet when WP-32.7 starts, read the profile JSON schema directly instead of blocking on
  it — the two are unrelated in git terms, WP-32.7 just benefits from that context existing.
- No attempt to fix every possible PDF-extraction encoding issue as a general capability — WP-32.2
  is scoped to understanding and addressing the specific ligature-drop pattern found, not building a
  general garbled-text detector.

---

## 4. Work Packages

### WP-32.1 — Spike: Provenance Mismatch / Possible Extraction Hallucination

**Source:** Live Evidence query walkthrough, 2026-07-27 (Tyler; the saved page no longer exists, see Phase Framing above -- citations below are transcribed directly).

**Goal:** Determine whether the mismatched context found on one requirement is an isolated
chunk_id error or a systemic Step C extraction defect affecting an identifiable class of records.

**Rationale:** Citation 7 in the walkthrough (`REQ-fde1b60fd22c`, `NIST.SP.800-37r2.pdf`, p.20)
shows the quote *"shall conform to NIST SP 800-63B guidelines. Minimum password length is 12
characters."* — but its context panel shows unrelated introductory text about information systems
and the Defense Science Board Task Force. Traced this to `services/evidence_service.py`'s context
batch-fetch: when a requirement's `source_quote` is not found verbatim inside the chunk its own
`chunk_id` points to, the code falls back to showing the first 600 characters of that (wrong) chunk
instead (`services/evidence_service.py`, the `else` branch after `if quote and quote in ctx:`).
That fallback firing proves this requirement's `chunk_id` does not correspond to where its quote
actually appears in the source document — a provenance bug, independent of whatever else is true
about the quote's content.

What makes this worth a full spike rather than a one-line fix: the *exact same* sentence (or a
near-identical variant) appears as the `source_quote` on at least 10 records across completely
unrelated documents in the same result set:

| requirement_id | document | page |
|---|---|---|
| `REQ-bab91b924879` | CJCSI6510_01F.pdf | 92 |
| `REQ-17d90bb7ebb9` | NIST.SP.800-30r1.pdf | 86 |
| `REQ-ce2b0bdb95e7` | NIST.SP.800-161r1.pdf | 73 |
| `REQ-7bed3f871501` | NIST.SP.800-53r5.pdf | 449 |
| `REQ-e65442cdc985` | DODI 5200.01_vol3.pdf | 116–117 |
| `REQ-e0e6e01bed53` | NIST.SP.800-137.pdf | 54 |
| `REQ-45a5bfbcc550` | NIST.SP.800-30r1.pdf | 72 |
| `REQ-becc727498db` | NIST.SP.800-53Ar5.pdf | 696 |
| `REQ-57bf28f6726f` | NIST.SP.800-92.pdf | 69 |
| `REQ-fde1b60fd22c` | NIST.SP.800-37r2.pdf | 20 (confirmed mismatched above) |

Some of this could be genuine shared boilerplate — DoD instructions commonly copy identical clauses
from a template. But confirming a real chunk_id/quote mismatch on one of these, combined with this
volume of exact-duplicate text across documents as topically unrelated as continuous monitoring
(800-137), risk assessment (800-30), and log management (800-92), raises a real possibility that
Step C is pattern-completing a memorized/expected sentence rather than only extracting what's
actually present in a given chunk — an LLM extraction hallucination, not a data-plumbing bug.

**Scope:**
- For each of the 10 records above (and any others found sharing this exact `source_quote` text),
  fetch its `chunk_id`'s actual context from `grc_context` and check whether the `source_quote`
  appears verbatim in it.
- Quantify: how many are genuine matches (real boilerplate, correctly attributed) vs. mismatches
  (wrong chunk_id) vs. matches-but-suspicious (need closer reading)?
- Check whether all 10 came from the same ingest run / extraction model / prompt version, which
  would point at a specific Step C regression rather than a general risk.
- If mismatches are found, check `raw_responses.jsonl` for the affected chunk(s) (Step C's
  logged raw LLM output — see `pipeline/llm_extract_requirements.py`'s header) to see whether the
  LLM actually output this sentence for a chunk that doesn't contain it (confirms hallucination) or
  whether a downstream normalization/indexing step (`parse_and_normalize.py`, `embed_and_index.py`)
  corrupted a correct chunk_id in transit (confirms a pipeline bug instead).
- Sample a few *other* frequently-repeated `source_quote` strings across the corpus (not just this
  one sentence) to check whether this is a one-phrase fluke or a broader pattern.

**Success Criteria:** A clear answer to "isolated or systemic," backed by the specific counts and
evidence above — not a guess.

**Reject If / Next step:**
- If isolated to a small number of records: document the finding precisely (which records, why),
  leave a note in `docs/TODO_future_improvements.txt`, and consider a one-off data correction. No
  pipeline fix needed this phase.
- If systemic: do not attempt the fix inside this WP. Write up the confirmed root cause and scope a
  dedicated follow-up WP (likely its own small phase, given a Step C prompt/pipeline fix carries
  real regression risk against the existing corpus) rather than bolting a rushed fix onto a spike.

**Findings (2026-07-27) — SYSTEMIC, root cause confirmed:**

Checked all 10 records above against `grc_context` using the exact logic
`services/evidence_service.py` uses (`quote in ctx`). **10/10 mismatched** — every single one's
`chunk_id` points to a References/Glossary/Definitions/Introduction-type section that has nothing
to do with password policy. All 10 share the same `extraction_model`
(`llama3.1:8b-instruct-q4_K_M`) but span 8 different ingest runs on different dates, ruling out a
one-off bad run.

Pulled the actual raw Step C output for one case directly (`NIST.SP.800-37r2.pdf`, chunk_id 51,
`documents/processed/NIST.SP.800-37r2_20260405_064552/NIST.SP.800-37r2_raw_responses.jsonl`).
Chunk 51's real text is the document's introduction — definitions of "information system," "risk,"
a citation to a Defense Science Board report — nothing about passwords or MFA. The LLM's raw
response for that chunk was:

```json
[
  {"source_quote": "shall implement multi-factor authentication for all privileged user accounts.", "source_ref": "3.2.1"},
  {"source_quote": "shall conform to NIST SP 800-63B guidelines. Minimum password length is 12 characters.", "source_ref": "3.2.2"}
]
```

That is a near-verbatim copy of `PASS1_PROMPT_TEMPLATE`'s own **Example 2** few-shot content
(`source_ref` values `3.2.1`/`3.2.2` match the example exactly). **Root cause: the model regurgitates
its own few-shot example when a chunk has no real extractable requirements, instead of correctly
returning `{"requirements": []}`** — which is exactly what the prompt's Example 3 (a References
section) tells it to do in that situation. It isn't following that instruction reliably on
low-signal chunks.

**Correction (2026-07-28, found during WP-32.2):** the paragraph below, as originally written, is
wrong. It claimed every affected record here came from the pymupdf path with `skip_sections`
unavailable. Checked the actual chunk-text signature (docling's `run_structure_aware()` prefixes
`text` with `[{breadcrumb}]\n\n`, per `pipeline/chunk_text.py`; legacy `chunk_text()` never does —
a code-verified signature, not inferred from `_ancestry.json`'s mere presence, which Codex correctly
flagged as unreliable on PR #145) for all 8 distinct source documents in the table above: **6 of 8
were docling, not pymupdf** (`CJCSI6510_01F`, `NIST.SP.800-161r1`, `NIST.SP.800-53r5`,
`DODI 5200.01_vol3`, `NIST.SP.800-92`, `NIST.SP.800-37r2` — including chunk_id 51 itself, the exact
smoking-gun chunk cited above). ~~Only `NIST.SP.800-30r1` and `NIST.SP.800-137` were pymupdf.~~ **See
the second correction below — this specific claim is also wrong.**

**Correction #2 (2026-07-28, found while answering a follow-up question about docling's real-world
impact):** the "6 of 8" / "31 docling, 14 legacy" numbers above (and in WP-32.2's Findings, below)
were computed by checking only each document's *first* chunk for docling's signature. That method
is flawed — a document's first chunk is frequently title-page/cover content that predates any
heading, so it legitimately lacks docling's breadcrumb even in a fully-docling-produced document.
Redone properly: check for the `section_ref_path` *key's presence* anywhere in the file (legacy
`chunk_text()` never writes that key at all, not even empty — a stronger signature than a single
sampled chunk). Re-verified all 45 archived documents individually, plus all 8 documents cited in
the table above specifically: **every single one, all 45, all 8, was docling.** There was no
legacy-mode document anywhere in the archived corpus. `NIST.SP.800-30r1` and `NIST.SP.800-137` are
docling too.

None of this changes the actual conclusion — chunk 51's `section_title_path` is `["INTRODUCTION"]`,
which isn't in `skip_sections`' list regardless of backend, so the diagnosis below was wrong either
way. It does mean the "6 of 8 were docling" framing understated how wrong the original paragraph
was — it wasn't a backend split at all, every cited record came from docling.

This doesn't change WP-32.1's shipped fix — the grounding check rejects fabricated quotes by
comparing them against their own chunk's real text, which works identically regardless of which
backend produced that chunk. Only the "why does this happen" narrative below was wrong; leaving the
original paragraph in place (struck through in spirit, not literally) for the record, corrected here
rather than silently rewritten.

~~Contributing factor: these are exactly the kind of chunks `skip_sections` (`GLOSSARY`,
`REFERENCES`, `DEFINITIONS`, etc.) exists to filter out — but per `docs/PROFILES.md`
(WP-31.3), that filter only applies under `--layout-mode docling`. Every affected record here came
from the default pymupdf path, which sends these sections to Step C at all.~~

Ran a corpus-wide check (not just the original 10) for `source_quote` matching each example
sentence via Qdrant full-text match against all 31,725 indexed requirements:

| Example sentence (from `PASS1_PROMPT_TEMPLATE`'s Example 2) | Matches |
|---|---|
| "shall implement multi-factor authentication for all privileged user accounts." | 165 |
| "All DoD information systems shall implement multi-factor authentication for all privileged user accounts." | 14 |
| "conform to NIST SP 800-63B guidelines. Minimum password length is 12 characters." | 30 |

(Qdrant's full-text match is token-based, not exact-substring, so treat these as order-of-magnitude,
not precise counts — but confirms this is not a 10-record fluke; it recurs corpus-wide.)

**Recommended fix direction for the follow-up WP (not implemented here, per Reject-If above):** the
most robust fix is a cheap, deterministic, non-LLM guard — reject any extracted requirement whose
`source_quote` does not literally appear as a substring of the actual chunk text being processed.
This would catch this failure mode (and any other hallucination shaped like it) regardless of which
few-shot example got copied, without needing to re-tune the prompt or model. Applying
`skip_sections` filtering to the default pymupdf path too would reduce exposure but wouldn't fully
close the hole on its own — any sufficiently low-signal chunk could trigger the same regurgitation,
not just labeled Glossary/References sections.

**This is a real data-integrity bug with corpus-wide reach, not a cosmetic finding.** Recommend
deciding explicitly whether the fix (likely a small, low-risk addition to Step D normalization) gets
folded into this phase as its own WP or deferred to a dedicated follow-up — flagging for Tyler
rather than deciding unilaterally, given it changes ingest-pipeline behavior with corpus-wide blast
radius.

**Resolution (2026-07-27):** Tyler's call — fold the fix into this WP. The existing corpus is
disposable test data, not worth preserving/flagging/migrating; nuke it and rebuild through a
controlled, single-document iteration loop rather than trying to patch or retroactively flag what's
already indexed. Full design went through a formal plan-mode review before any code changed (Tyler's
explicit ask: high-risk decisions get debated, not one-shotted).

**Implementation — three things changed from the original naive idea:**

1. **Exact substring matching would have been a worse bug than the one it fixed.** Testing a random
   30-record sample of the original raw flags showed 16/30 were real quotes reformatted from tabular
   source text (heavy in `NIST.SP.800-53Ar5`'s assessment-procedure tables, e.g.
   `"CA-2(2) Integrity.M = ."`), not fabrications. Switched to `rapidfuzz.fuzz.partial_ratio` — the
   right tool specifically because it scores how well a *short* string matches the best-aligned
   *substring* of a *long* one, unlike `eval/eval_harness.py`'s existing `fuzz.token_sort_ratio`
   usage (built for comparing two same-length quotes, not a quote against a whole chunk).
2. **The corrected corpus-wide fabrication rate is ~5.6%, not 21.55%.** Re-running the fuzzy check
   (threshold 80) against all 45 locally-processed documents flagged 1,888/33,462 requirements — most
   of the original raw 21.55% really was reformatting noise, not fabrication, confirming finding #1.
3. **Threshold calibrated empirically, not guessed.** Swept thresholds 50-80 against both
   `eval/gold_eval_chunks_curated.jsonl`'s 2,452 hand-verified real quotes (false-positive side) and
   the full local corpus (catch-rate side):

   | threshold | gold false-positive rate | corpus flagged rate |
   |---|---|---|
   | 50 | 0.86% | 3.51% |
   | 60 | 1.75% | 4.42% |
   | 80 | 4.61% | 5.64% |

   Diminishing returns above ~60 — pushing to 80 nearly triples the gold false-positive rate for
   comparatively little extra catch. Landed on **60**. The confirmed hallucination that motivated this
   whole spike scores 44 — well clear of 60 either way.

**Shipped:** `QUOTE_GROUNDING_THRESHOLD = 60` added to `pipeline/parse_and_normalize.py`'s existing
per-requirement validation loop (`build_chunk_text_map()` alongside the file's existing
`build_chunk_page_map`/`build_chunk_hierarchy_map` helpers; new `"quote_not_grounded_in_chunk"`
failure reason in the same fail-list pattern as the existing `empty_source_quote`/`not_actionable`
checks). `rapidfuzz` moved from `pyproject.toml`'s `dev` extra to base `dependencies` — it's now a
genuine runtime pipeline dependency, not just an eval-only tool (incidentally resolves the
dependency-drift concern `docs/TODO_future_improvements.txt`'s dependency backlog already tracked).

**Validated against real data, not just unit tests:** nuked both Qdrant collections (backing
collections deleted directly per `docs/OPERATIONS.md`'s documented procedure) and archived
`~/documents/processed/` to `~/documents/processed.pre-wp32.1/` (not deleted — free undo at zero
cost). Re-ingested two documents fresh through the fixed pipeline:
- `afpd_17-1.pdf` — 102/105 requirements normalized, 0 grounding rejections, all real scores
  computed (min 68.5, confirmed the check is actually running, not silently passing everything).
- `CJCSI 6510.02G.pdf` — 71/72 normalized, **1 grounding rejection**: `"shall implement
  multi-factor authentication for all privileged user accounts."` (the exact same Example-2-derived
  boilerplate from the original spike), `grounding_score: 46.8`. Verified chunk 12's real text
  directly — it's a references/citation list (`source_ref: "GL-1"`), zero relation to MFA. Caught
  live, on a fresh pipeline run, not just reproduced synthetically.

**Explicitly deferred, not assumed:** re-ingesting the remaining 43 documents is a separate decision,
not folded into this WP. No change to Step C's prompt itself (the few-shot examples that get
regurgitated) — this WP catches the symptom deterministically after the fact rather than trying to
stop the model from fabricating in the first place; worth a future look if the rejection rate stays
high on further re-ingests, but out of scope here.

---

### WP-32.2 — Spike: Ligature/Text-Extraction Corruption

**Source:** Live Evidence query walkthrough, 2026-07-27 (Tyler; the saved page no longer exists, see Phase Framing above -- citations below are transcribed directly).

**Goal:** Determine whether the character-dropping pattern found in one document is isolated to
that PDF or affects other documents sharing the same problematic font/encoding.

**Rationale:** `REQ-f7dd494f5d87` (`NIST.SP.800-53Ar5.pdf`, p.268, group `IA-05(01)(b)`) has visibly
corrupted text — the "ti" digraph is missing everywhere it should appear and nowhere else:
"authentication" → "authencaon", "organizational" → "organizaonal", "composition" → "composion".
This is the textbook signature of a PDF font whose "ti" ligature glyph has no ToUnicode CMap entry,
so Step A's text extraction silently drops it. Not a chunking issue — it happens at
`pipeline/extract_pdf_to_text.py`, before chunking ever sees the text.

**Scope:**
- Confirm which extraction backend/layout mode (`pymupdf`/`pdfplumber`/`docling` —
  `--layout-mode` per `README.md`) was used to ingest `NIST.SP.800-53Ar5.pdf`.
- Check whether other requirements from the same document show the same corruption pattern (grep
  indexed records from that document for other common ligature-affected words: "definition",
  "notification", "certification", "action", etc. — anything containing "ti").
- Check whether any *other* indexed document shows the same pattern — if it's font-specific rather
  than document-specific, other PDFs using the same generator/font could be silently affected too
  and this is worth a corpus-wide check, not just this one file.
- Try re-extracting this document with a different `--layout-mode` (docling in particular, since it
  uses a different underlying extraction path) and see whether the ligature issue disappears.

**Success Criteria:** A clear answer on scope (this document only vs. a shared-font class of
documents), and whether an existing `--layout-mode` option already avoids the problem.

**Reject If / Next step:**
- If isolated to this one document and a layout-mode switch fixes it: reingest that document with
  the working mode, document the finding, no pipeline change needed.
- If it recurs across multiple documents and no existing layout mode avoids it: scope a proper fix
  (e.g. a ligature-repair post-processing step) as separate follow-up work — not attempted in this
  spike.

**Findings (2026-07-28) — isolated to one document; neither Reject-If branch cleanly fits:**

Corrected the original rationale's mechanism first: the "ti" isn't dropped, it's *replaced*. Every
occurrence is a literal Unicode Private Use Area character (`U+E000`), not a deletion — e.g. the
actual `source_quote` on `REQ-f7dd494f5d87` is `"authen<U+E000>ca<U+E000>on"`
(`for password-based authen<U+E000>ca<U+E000>on, a list of commonly used...`), confirmed by
inspecting the raw JSON bytes, not just how it renders. That distinction matters for the fix
direction: a real character is present and addressable, not information that's gone.

- **Backend confirmation — corrected twice (2026-07-28):** originally inferred from
  `_ancestry.json`'s mere presence, which Codex correctly flagged on PR #145 as unreliable
  (`run_pipeline.py` never deletes a stale `_ancestry.json` if a directory is reused, and every
  archived document happens to have one, docling or not). First re-verification checked only chunk 0
  of each document for docling's `[{breadcrumb}]\n\n` text-prefix signature and concluded "31
  docling, 14 legacy" — also wrong, because a document's first chunk is frequently title-page/cover
  content that predates any heading and legitimately lacks the breadcrumb even under docling. Fixed
  properly by checking for the `section_ref_path` *key's presence* anywhere in the file (legacy
  `chunk_text()` never writes that key at all): **all 45 archived documents were docling**, with no
  exceptions. `NIST.SP.800-53Ar5` itself is docling (confirmed the same way) — this was correct in
  both prior passes, only the corpus-wide split was wrong.
- **Corpus-wide PUA scan** (regex scan for the Unicode Private Use Area range U+E000–U+F8FF across
  all 45 archived documents' `*_chunks.jsonl`): 5 documents show hits, not 1.
  - `NIST.SP.800-53Ar5` — **53,078 hits**, five distinct codepoints (`U+E000`–`U+E004`). Inspecting
    surrounding context for each resolved the actual ligature each represents: `U+E000` = "ti",
    `U+E001` = "tt", `U+E002` = "ft", `U+E003` = "tt" (a second, distinct glyph ID for the same
    ligature — likely a separate font-weight subset), `U+E004` = "tf". This is genuine word-internal
    corruption, matching the original report.
  - `CNSSI_No1253` (312 hits, `U+F0B7`), `NIST.SP.800-125` (135 hits, `U+F06E`), `NIST.SP.800-161r1`
    (28 hits, `U+F0E0`), `dafpam90-803` (367 hits, `U+F0B7`) — checked context for each: these are
    Wingdings/Symbol-font bullet (`•`) and arrow (`→`) glyphs rendered as their raw PUA codepoint
    instead of the intended symbol, e.g. `"- <U+F0B7> NIST SP 800-30..."` and `"Moderate <U+F0E0> Low"`.
    Cosmetic — an extra stray character before a bullet or inside an arrow substitution, never
    word-internal, never corrupts a requirement's actual text. **A different bug class from
    `NIST.SP.800-53Ar5`'s, not the same font/generator issue recurring.**
  - **Qualified, per Codex feedback on PR #145:** searched for the *fully-silent-deletion* form the
    original rationale described (`informaon`, `organizaon`, `applicaon`, `noficaon`) — zero hits
    anywhere in the corpus. That only rules out silent deletion for the specific "ti"-word spellings
    checked; a different dropped ligature, or a "ti" word not on this list, wouldn't show up in this
    search and a true silent deletion leaves no marker for a broader scan to catch either. Every
    instance actually *found* by this WP is a PUA substitution, not a bare drop — but that is a
    statement about what was found, not proof nothing else exists uncaught.
- **Layout-mode test:** re-ran Step A directly against `raw_pdfs/NIST.SP.800-53Ar5.pdf` with both
  `pymupdf` and `pdfplumber` (docling was already the original backend). **Both reproduce the
  identical corruption at the identical passage**: page 268's `IA-05(01)(a)` text comes out as
  `"...authen<U+E000>ca<U+E000>on, a list of commonly used..."` under all three backends, same codepoints,
  same characters affected. Raw PUA counts differ somewhat by backend (docling 53,078 / pymupdf
  17,786 / pdfplumber 17,206) but all three are substantial — this is not a small edge case for any
  of them. **No existing `--layout-mode` avoids the problem.** This is conclusive: the defect is in
  `NIST.SP.800-53Ar5.pdf`'s own embedded font (missing `ToUnicode` CMap entries for its "ti"/"tt"/
  "ft"/"tf" ligature glyphs), not in any extraction library's behavior — every Python PDF library
  available to this pipeline reads the same broken font data the same way.
- **Scope within the document:** 1,746 of 6,899 (25.3%) of `NIST.SP.800-53Ar5`'s normalized
  requirements have at least one PUA character in `source_quote` or `description`.
- **Interaction with WP-32.1's grounding check, worth flagging explicitly:** the fuzzy
  quote-grounding fix shipped in WP-32.1 does **not** catch this. A PUA-corrupted quote and its own
  source chunk both carry the identical corruption (extraction happens once, upstream of both), so
  `fuzz.partial_ratio` correctly scores them as a strong match — it's genuinely grounded, just
  grounded in garbled text. This is a different bug class (verbatim-but-corrupted vs. fabricated)
  that WP-32.1 was never designed to catch and doesn't claim to.

**Not a download/transfer artifact:** Tyler asked whether this could simply be a corrupted local
copy rather than a real defect in the published document, given how important this one is. Checked:
`raw_pdfs/NIST.SP.800-53Ar5.pdf` is `sha256:75665570...b21be47`. The document's own embedded DOI
link (`https://doi.org/10.6028/NIST.SP.800-53Ar5`) resolves to
`https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53Ar5.pdf` — downloaded that
fresh and it hashes **byte-for-byte identical** to the local copy, same 7,469,808 bytes. The
corruption is baked into the PDF exactly as NIST currently hosts it, not something introduced in a
prior download. PDF metadata (`Creator: Acrobat PDFMaker 21 for Word`, `Producer: Acrobat Pro DC
21.11.20039`) points at *why*: this is a well-documented Word→PDF export failure mode — OpenType
ligature substitution in the source Word document paired with `PDFMaker`/Distiller not always
generating a correct `ToUnicode` CMap entry for less-common ligature glyphs (`ti`/`tt`/`ft`/`tf`,
beyond the usual `fi`/`fl`). Re-downloading won't help; a repair pass is the only path to clean text
short of NIST re-publishing the source document.

**Resolution:** Neither pre-written Reject-If branch cleanly fits the actual result — the two
branches assumed "isolated" and "fixable by switching layout mode" move together, and they don't.
Reality: isolated to one document (in the corrupting sense — the other 4 hits are a different,
cosmetic issue), *and* no layout-mode switch avoids it. Per this WP's own rule, no fix was written
during the investigation itself — scoped narrowly per this phase's existing Non-Goal against
building a general garbled-text detector: a small deterministic repair table
(`{U+E000: "ti", U+E001: "tt", U+E002: "ft", U+E003: "tt", U+E004: "tf"}`) applied as a
post-extraction pass — cheap, precise, and grounded in the exact codepoints confirmed above, not a
speculative general-purpose fix.

**Shipped (2026-07-28):** Tyler's call — `NIST.SP.800-53Ar5` is an important document (it's the
assessment-procedures companion to 800-53, used for control-assessment work specifically), and the
fix is small, so implement it now rather than leave it as a pure backlog item. Explicit constraint:
keep it out of the default ingest path, callable only when needed, rather than adding a
general-purpose repair step that runs on every document. Shipped as `pipeline/repair_ligatures.py`
— a standalone module with its own CLI, **not imported or called anywhere in `run_pipeline.py` or
`cli/reqbot.py`** (confirmed via grep, not just by omission). Operates on a `*_chunks.jsonl` file
after Step B and before Step C, repairing the `text`/`raw_text` fields (and any other string or
list-of-string field) that carry the known bad codepoints; the normal resume flow is:

```bash
python3 cli/reqbot.py ingest "raw_pdfs/NIST.SP.800-53Ar5.pdf" --layout-mode docling --no-index
python3 pipeline/repair_ligatures.py ~/documents/processed/NIST.SP.800-53Ar5_.../NIST.SP.800-53Ar5_chunks.jsonl
python3 cli/reqbot.py ingest "raw_pdfs/NIST.SP.800-53Ar5.pdf" --skip-to C --output-dir ~/documents/processed/NIST.SP.800-53Ar5_...
```

**Validated against the real archived data**, not just synthetic unit tests: ran it against a copy
of the pre-WP-32.1 archived `NIST.SP.800-53Ar5_chunks.jsonl` — repaired **53,078 characters across
2,658/3,092 chunks** (matches the corpus-wide PUA scan count above exactly, as it should — same file,
same codepoints). Spot-checked chunk_id 1131 (the original `REQ-f7dd494f5d87` source chunk) directly:
now reads `"...for password-based authentication, a list of commonly used, expected, or compromised
passwords is maintained and updated <IA-05(01)_ODP[01] frequency> and when organizational
passwords..."` — fully clean. Confirmed zero PUA characters remain anywhere in the repaired file.
10 unit tests in `tests/unit/test_repair_ligatures.py` cover the replacement logic, record-level
field handling (string and list-of-string fields, non-string fields left untouched), and the file-
level `run()` entry point (in-place and separate-output-path modes).

Tracked as `[RESOLVED — Phase 32, WP-32.2]` in `docs/TODO_future_improvements.txt` item 25.
Re-ingesting `NIST.SP.800-53Ar5.pdf` itself through this repaired flow is not done as part of this
WP — the tool is validated and ready, but actually running it against the live corpus is bundled
with the same later, separate re-ingest decision as the rest of the corpus (see Non-Goals above).

---

### WP-32.3 — Evidence Grouping Fallback Fix

**Source:** Live Evidence query walkthrough, 2026-07-27 (Tyler; the saved page no longer exists, see Phase Framing above -- citations below are transcribed directly).

**Problem:** `services/evidence_service.py`'s grouping key is `ref = p.get("source_ref") or "(no
ref)"` — every result with an empty `source_ref` collapses into one literal `"(no ref)"` group,
regardless of source document or topic. In the reproduction case this merged 14 requirements from
~10 unrelated documents (NIST 800-63B, CJCSI6510_01F, NIST 800-171, NIST 800-30, NIST 800-161, NIST
800-53r5, DODI 5200.01, NIST 800-137, NIST 800-53Ar5, NIST 800-92) into a single undifferentiated
bucket labeled "(no ref)" with no indication to the user why they're grouped together (they aren't,
meaningfully). Grouping is supposed to mean "same control/paragraph reference" — this fallback
defeats that entirely for the not-uncommon case of a requirement with no extractable reference.

Related, smaller finding folded in here since it's the same grouping-key logic: `REQ-25980e46a83b`
groups under the bare label `"(f)"` — its `source_ref` really is just `"(f)"`, a sub-item letter
with no parent control ID attached, even though the pipeline already extracts a fuller hierarchy
(`parent_section_ref`, `section_ref_path` — see `pipeline/chunk_text.py`/`parse_and_normalize.py`)
that isn't being used to disambiguate this label.

**Scope:**
- Change the "no `source_ref`" fallback so it stops silently merging unrelated documents under one
  shared key. Candidate approach: don't group at all when `source_ref` is empty — treat each such
  requirement as its own singleton group (keyed by `requirement_id`), same as if it had a unique
  ref. Decide during implementation whether that's the right default or whether grouping-by-document
  for the no-ref case is more useful; don't assume upfront.
- For the bare-sub-letter case (`"(f)"` and similar), use `parent_section_ref`/`section_ref_path`
  when present to build a fuller, disambiguating group label (e.g. combine with the nearest ancestor
  reference) instead of displaying the bare letter alone.
- Update the group header rendering in `EvidenceView.tsx` if the label composition changes.

**Non-goals:**
- No change to how grouping works for requirements that *do* have a `source_ref` — this only
  touches the empty/bare-fragment fallback paths.
- No backend reindex of existing data — this changes how `evidence_service.build()` groups at query
  time, not what's stored.

**Tests/verification:**
- Unit/service-level test reproducing the "(no ref)" and "(f)"-style cases against known payload
  shapes, confirming they no longer merge unrelated documents.
- Manual: re-run the reproduction query ("how long should my password be?") against the live corpus
  and confirm the 14-source "(no ref)" group no longer exists in that form.

**Gate:** Requirements with an empty or bare-fragment `source_ref` no longer silently merge with
unrelated requirements from other documents under one meaningless label.

**Resolution (2026-07-28):** Checked real data before deciding the empty-ref default the Scope
section deliberately left open. Across the pre-WP-32.1 archived corpus (31,725 requirements):
24% (7,621) have an empty `source_ref`; of the bare-fragment cases (1,249, e.g. `"(f)"`, `"(1)"`),
only 2.6% (32) have a `parent_section_ref`, but 33.8% (422) have a non-empty `section_ref_path` —
and every record with `parent_section_ref` also has `section_ref_path`, so the path is the more
complete signal. `section_ref_path`'s *last* element is also more specific than
`parent_section_ref` (e.g. path `["SECTION-3", "3.4"]` vs. `parent_section_ref: "SECTION-3"` for
the same record) — prefer it.

**Shipped:** `_group_key_and_label()` in `services/evidence_service.py`:
- A real, full `source_ref` groups exactly as before — same ref can legitimately span multiple
  documents (e.g. several DoD instructions citing the same NIST control), which is the point of
  grouping and explicitly out of scope to change (see Non-Goals).
- An empty `source_ref` gets a singleton key (`f"__no_ref__{requirement_id}"`) but still displays
  as `"(no ref)"` — no more silent cross-document merging, one row per requirement.
- A bare fragment (`^\(\w{1,4}\)$` — "(f)", "(a)", "(12)", etc.) with `section_ref_path` or
  `parent_section_ref` available gets a fuller label built from the closest ancestor
  (`section_ref_path[-1]` preferred over `parent_section_ref`, per the data above) — e.g.
  `"3.4" + "(a)"` → `"3.4(a)"`.
- A bare fragment with *no* hierarchy available (66% of bare-fragment cases) falls back to the
  same singleton treatment as the empty-ref case — there's no real disambiguating signal to build
  a fuller label from, so pretending otherwise would be worse than being honest about it.

Fixed three downstream leaks of the new internal singleton key format
(`__no_ref__REQ-xxxx`/`__bare_fragment__REQ-xxxx`) found while wiring this in — all now correctly
read the group's `source_ref` display field instead of the raw dict key: the LLM synthesis prompt
in `evidence_service.py` itself, `cli/reqbot.py`'s JSON and markdown evidence output, and
`EvidenceView.tsx`'s group header. Also corrected `api/routes/evidence.py`'s and
`frontend/src/api/types.ts`'s docstrings, which claimed `groups` is keyed by `source_ref` — no
longer exactly true.

**Validated against the live corpus**, not just unit tests: queried `services/evidence_service.py`
directly against the current 173-point index (`afpd_17-1.pdf` + `CJCSI 6510.02G.pdf`). Before this
fix, 8 empty-ref requirements spanning both documents would have collapsed into one `"(no ref)"`
group; confirmed they now land in 8 separate groups, still correctly labeled `"(no ref)"`. Also
confirmed 2 live bare-fragment records (`"(1)"`, `"(i)"`, both with no hierarchy metadata) stay
separate rather than merging. Confirmed via `cli/reqbot.py evidence` (the real CLI path, not just
`build()` in isolation) that no internal key ever reaches the JSON output.

13 new unit/service-level tests in `tests/unit/test_evidence_service.py`: 5 direct tests of
`_group_key_and_label()`'s branches, 4 `build()`-level integration tests (no-merge for empty ref,
no-merge for hierarchy-less bare fragment, same-full-ref-still-merges regression guard, and a test
confirming the internal key never reaches the synthesis prompt).

No frontend test added for the one-line `EvidenceView.tsx` display fix (`{ref}` →
`{group.source_ref}`) — this codebase doesn't carry view-level test scaffolding for one-line JSX
changes (see WP-31.2's `SynthesisBox.test.tsx`, added only because it was genuinely new logic), and
the backend tests already pin down that `source_ref` is always the correct display value.

---

### WP-32.4 — Context Excerpt Labeling

**Source:** Live Evidence query walkthrough, 2026-07-27 (Tyler; the saved page no longer exists, see Phase Framing above -- citations below are transcribed directly).

**Problem:** `evidence_service.py`'s "Show source context" is a deliberate ±300-character window
around the matched quote (working as designed), but the GUI gives no indication of that — a context
block that starts and ends mid-sentence with `...` reads as broken chunking, not an intentional
excerpt. This is purely a labeling/affordance gap, not a logic change.

**Scope:**
- Add a small caption/label above or alongside the context block in `EvidenceView.tsx` making clear
  it's an excerpt around the matched quote, not the full chunk (exact wording is an implementation
  choice, not fixed here).

**Non-goals:**
- No change to the ±300-character window size or truncation logic itself.

**Tests/verification:** Manual — confirm the label renders and reads clearly against a real
truncated context block.

**Gate:** A user can tell from the UI itself that a truncated context block is an intentional
excerpt, not a rendering bug.

---

### WP-32.5 — Evidence/Search Card Visual Hierarchy Rework

**Source:** Live Evidence query walkthrough, 2026-07-27 (Tyler; the saved page no longer exists, see
Phase Framing above); Tyler's repeated prior feedback that `requirement_id` is "totally useless to a
human" (noted before WP-30's UI work too).

**Problem:** In both `ResultCard.tsx` and `EvidenceView.tsx`'s inline `EvidenceCard`, the most
visually prominent element on each card is `requirement_id` — a synthetic hash with no human
meaning (`REQ-f728c681602e`) — rendered bold and blue at the top-left. The genuinely useful
identifying information (document name, page, paragraph/control reference) is small gray text
tucked in a corner or footer.

**Scope:**
- Swap the visual hierarchy in both `ResultCard.tsx` and `EvidenceView.tsx`'s `EvidenceCard`:
  promote document name + page + `source_ref` to the prominent position; demote `requirement_id` to
  small, gray, right-aligned text.
- Keep the citation number badge (WP-31.2) in its current position — this WP only reorders what's
  inside each card, not the numbering added last phase.
- Apply consistently to both components since they currently share near-identical layout.

**Non-goals:**
- No change to what data is shown, only its visual priority/ordering.
- No redesign of `TraceView.tsx`'s header (out of scope — that's a detail page, not a result list;
  revisit separately if it turns out to have the same problem).

**Tests/verification:** Manual — visual comparison against the current layout (the saved "before"
page no longer exists; compare directly against a fresh Search/Evidence query against the live GUI
instead).

**Gate:** Document name, page, and paragraph/control reference are the most visually prominent
elements on a result card; `requirement_id` is present but clearly de-emphasized.

---

### WP-32.6 — Render Generated Answer as Markdown

**Source:** Live Evidence query walkthrough, 2026-07-27 (Tyler; the saved page no longer exists, see Phase Framing above -- citations below are transcribed directly).

**Problem:** `core/ask.py`'s `SYNTHESIS_PROMPT` and `evidence_service.py`'s
`_EVIDENCE_AUDITOR_PROMPT` both produce markdown-formatted output (`**bold**`, `- ` bullet lists),
but `SynthesisBox.tsx` renders it as plain `whitespace-pre-wrap` text — the raw `**`/`-` syntax is
visible to the user instead of being rendered.

**Scope:**
- Render the Generated Answer's markdown properly in `SynthesisBox.tsx`. Evaluate a markdown
  library (e.g. `react-markdown`) against a minimal hand-rolled renderer for just the syntax these
  two prompts actually produce (bold, bullet lists) — decide based on how much the added dependency
  weighs against maintenance cost, don't assume upfront.
- Keep this WP's citation-number parsing/linking (WP-31.2's `parseCitations`/`scrollToCitation`)
  working alongside whatever markdown rendering is added — the `[N]` citation tokens still need to
  become clickable, markdown or not.
- Sanitize rendered output — this is LLM-generated text; even though `SYNTHESIS_PROMPT` doesn't ask
  for HTML, don't trust that blindly if the chosen library supports raw HTML passthrough.

**Non-goals:**
- No markdown rendering anywhere else (see Phase Non-Goals) — `source_quote`/`description`/context
  excerpts stay plain text.

**Tests/verification:**
- Unit test(s) covering bold/bullet rendering plus citation-token interop, matching the level of
  coverage WP-31.2 already established for `SynthesisBox`.
- Manual: run a real synthesized query and confirm the answer renders readably instead of showing
  raw markdown syntax.

**Gate:** Generated Answer text renders bold/bullets properly; citation links (WP-31.2) still work.

**Resolution:** Weighed hand-rolling a minimal bold/bullet parser against adding `react-markdown`
(the scope only needed CommonMark bold + bullet/numbered lists, no GFM extensions) — Tyler's call
was to add the dependency. `SynthesisBox.tsx` now overrides react-markdown's `p`/`li` renderers to
re-run WP-31.2's `parseCitations` on their text, keeping `[N]` citation buttons clickable inside
both bold text and list items. No `rehype-raw` plugin is registered, so raw HTML in
LLM-generated text stays inert rather than executing — verified by a unit test.

Manual verification against a real synthesized answer (`POST /api/ask`, CJCSI 6510.02G.pdf corpus,
"What is the process for cryptographic key extension?") caught a real bug the hand-picked unit
tests hadn't: a nested bullet list (a top-level bullet with indented sub-bullets, which the real
LLM output actually produced) caused double-processing — an ancestor list item's citation-linking
pass was re-running over a descendant list item's already-built citation button, nesting a
`<button>` inside another `<button>` (invalid DOM, double click handler). Fixed by having the
recursive linker skip back into `p`/`li`/`ul`/`ol` elements, since those are already
self-processed by react-markdown invoking the same overrides directly wherever they occur in the
tree — an ancestor never needs to re-walk a descendant's own self-processed subtree.

---

### WP-32.7 — Profile-Aware Evidence Synthesis Vocabulary

**Source:** Live Evidence query walkthrough, 2026-07-27 (Tyler; the saved page no longer exists, see Phase Framing above -- citations below are transcribed directly).

**Problem:** `services/evidence_service.py`'s `_EVIDENCE_AUDITOR_PROMPT` hardcodes cybersecurity-
specific vocabulary directly into the prompt text: *"Identify the dominant control families present
in the evidence (e.g., AC, IA, AU)."* This produces output like "Dominant Control Families: AC, IA"
— NIST/RMF-specific abbreviations that mean nothing outside cybersecurity and would be actively
wrong guidance if fed to a future non-cybersecurity profile (the profile system —
`profiles/*.json`, `core/profiles.py` — exists specifically to make ReqBot's pipeline domain-
agnostic; this prompt quietly breaks that for the one LLM-facing piece of the evidence pipeline).

**Scope:**
- Read `docs/PROFILES.md` (WP-31.3) if merged by the time this starts, or `profiles/*.json`/
  `core/profiles.py` directly otherwise — the actual profile schema is what determines what's
  available to build a domain-appropriate prompt from (`domain_tags` is the obvious candidate: it's
  already present on every profile and already attached to every requirement).
- Rework `_EVIDENCE_AUDITOR_PROMPT` to reference the active profile's actual `domain_tags` instead
  of a hardcoded cybersecurity-specific example list, so the prompt's guidance is meaningful
  regardless of which profile is active.
- Thread the active profile through to `evidence_service.build()` if it isn't already available
  there — check `domain_profile` on the retrieved requirement payloads first before adding a new
  parameter; it may already be present.
- **Mixed-profile results:** the Evidence API filters by document/domain-tag/requirement-type, not
  by profile, so a query could in principle return results spanning more than one `domain_profile`.
  Handle this simply, not cleverly: if every result's `domain_profile` agrees, use that profile's
  `domain_tags`. If they disagree, fall back to the existing hardcoded prompt text rather than
  guessing which profile's vocabulary should win or merging vocabularies from unrelated domains —
  a wrong-but-old failure mode is better than a new, confidently-wrong one. Cover this case in
  WP-32.7's tests explicitly (Codex review, PR #144).

**Non-goals:**
- No change to `core/profiles.py`'s schema/validation (see Phase Non-Goals).
- No change to `core/ask.py`'s `SYNTHESIS_PROMPT` (the Ask/Search synthesis prompt) — confirm
  whether it has the same hardcoding problem during implementation, but this WP is scoped to the
  Evidence auditor prompt specifically; if Ask's prompt needs the same fix, that's a follow-up, not
  silently expanded scope here.
- No real mixed-profile handling beyond the same-profile-or-fallback rule above — every indexed
  requirement is `cybersecurity` today (`docs/TODO_future_improvements.txt`'s Decisions and
  Guardrails #8: no second profile until Phase 32 proves the core is actually domain-neutral), so
  this scenario can't occur in practice yet. Building anything more sophisticated now would be
  designing for data that doesn't exist.

**Tests/verification:**
- Test with at least two different profiles (`cybersecurity` and `test-domain.json`) confirming the
  synthesis prompt reflects each profile's actual `domain_tags`, not a hardcoded cybersecurity list.

**Gate:** The evidence synthesis prompt's vocabulary is derived from the active profile, not
hardcoded cybersecurity/NIST terms.

---

## 5. Success Gate

Phase 32 is complete when:

1. WP-32.1 and WP-32.2's spikes have reached a documented isolated/systemic conclusion each, and any
   resulting fix work has either landed (if small enough to fit this phase) or been scoped as
   explicit follow-up (if not).
2. WP-32.3 through WP-32.7 are merged.
3. Full unit suite passes (`pytest`); `ruff check .` passes; frontend build passes; frontend test
   suite passes.
4. Re-running the reproduction query ("how long should my password be?") against the live corpus no
   longer shows: the 14-source "(no ref)" mega-group, an unlabeled truncated context block, a card
   where `requirement_id` is the most prominent element, or raw markdown syntax in the Generated
   Answer.

---

## 6. Guardrails

1. One WP at a time — each lands as its own PR, reviewed before proceeding to the next, same
   cadence as Phases 29/30/31.
2. WP-32.1 and WP-32.2 are investigation only — do not write a production fix inside either spike.
   If a fix turns out to be warranted, scope it as explicit follow-up work with its own review, not
   a rushed addition to a spike PR.
3. WP-32.3's grouping fix must not change behavior for requirements that already have a real
   `source_ref` — only the empty/bare-fragment fallback paths are in scope.
4. WP-32.6's markdown rendering stays scoped to the Generated Answer only — no change to how
   `source_quote`/`description`/context excerpts render elsewhere.
5. WP-32.7 must not touch `core/profiles.py`'s schema or validation logic — profile data is read,
   not redesigned.
6. No CLI/MCP behavior changes anywhere in this phase unless a WP's own scope explicitly says so
   (none currently do).
