# ReqBot Phase 39 — Parent-Stem Context Loss: Audit & Targeted Fix

**Status:** Locked (drafted 2026-07-31; source: WP-38.2's own Findings/Backlog, discussed directly
with Tyler in the same session that closed WP-38.2)
**Date:** 2026-07-31
**Preceded by:** Phase 38 (Extraction Precision: Failure Audit & Targeted Fixes) — both WPs complete,
`docs/PHASE38_REQUIREMENTS.md`. WP-38.2's own Backlog section named this phase's problem directly:
short enumerated child list items (e.g. `"(3) Restrain competition."`) can be genuinely incomplete
without their parent stem (`"Classification shall not be used to:"`), and no text-level Step D rule
can safely tell that shape apart from a genuinely self-contained short directive — confirmed the hard
way, across four separate review rounds narrowing and finally removing that rejection rule entirely
rather than risk silently discarding real requirements.
**Followed by:** None currently planned.

---

## Status

This table is the live source of truth for Phase 39 WP status — update it here when a WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-39.1 — Parent-Stem Context Loss Audit | Complete |
| WP-39.2 — Parent-Stem Reconstruction | Complete |

---

## 1. Phase Framing

WP-38.2 kept running into the same wall from different directions: a short enumerated list item
(`"(3) Restrain competition."`) or a subordinate clause (`"Under the authority, direction, and
control of the Chief Management Officer..."`) can be extracted as `source_quote` with its governing
context — a stem sentence, a main clause — severed, and nothing about the extracted text itself says
so. Every attempt at a Step D rule to catch this (marker + word-count, broader dangling-clause
signals) either missed real fragments or, worse, rejected genuinely complete short requirements that
happened to share the same shape. The rule was narrowed four times and ultimately removed rather than
keep guessing. That's the right call for Step D specifically — a rejection rule can only delete or
keep, and deleting a real requirement because it's short is a worse failure than leaving a fragment
in place — but it leaves the actual problem unsolved: some real requirements are genuinely retrieved
and displayed without the context that makes them mean what they mean.

Tyler's framing, which sets this phase's direction: the fix isn't a smarter rejection rule, it's
**carrying more structure forward** — reconstructing the parent-stem/main-clause relationship before
embedding and indexing, so the child item is retrieved *with* its governing context rather than
either standing alone (misleading) or being deleted (lossy). Cheap, targeted schema addition, not a
retrieval redesign:

```json
{
  "source_quote": "(1B) wear a reflective belt",
  "parent_stem": "During PT, the member shall:",
  "embedding_text": "During PT, the member shall wear a reflective belt"
}
```

Tyler also raised a direct question worth answering plainly, not assuming: this project moved to a
docling-only pipeline (WP-34.1, 2026-07-29) partly on the expectation that docling's structure-aware
parsing would help with exactly this kind of context problem. Whether it actually does, or whether
the structure exists but gets discarded somewhere downstream, is unverified — this phase's whole job
is finding out.

**A real, code-verified spot-check done before writing this doc** (not the audit itself — that's
WP-39.1's job — but enough to scope the right questions, same discipline as Phase 38's own Phase
Framing spot-check):

- Docling *does* structurally distinguish list items from other body text — confirmed by actually
  running `DocumentConverter` against a real corpus document (`raw_pdfs/afpd_17-1.pdf`, first 8
  pages), not just inferred from `pipeline/section_parser.py`'s own `_BODY_LABEL_SUBS` tuple
  recognizing the label string (which only proves ReqBot's code is written to expect it, not that
  Docling actually emits it — a real distinction, caught by Codex's review of this doc, PR #182,
  before this claim shipped as fact rather than hypothesis). Real result: 30 of 118 parsed items
  (25%) were labeled `list_item` on that sample. The raw structural signal is real and common in this
  corpus, not theoretical.
- But `section_parser.py`'s own ancestry builder (`_parse_ancestry()`, walking
  `doc.iterate_items()`) only threads **heading-level** parentage forward: every non-heading item —
  a list item exactly the same as an ordinary paragraph — gets `parent_header_text` (the enclosing
  heading) and `parent_context` (the *first* ~600 chars of body text under that heading, truncated,
  not specifically the sentence immediately preceding a given list). There is no code today that
  links a list item to the specific stem sentence that introduces its list via this ancestry map,
  only to the section heading several levels up.
- **This doesn't mean the stem is actually unrecoverable, though** (Codex's review, PR #182, caught
  the Scope below assuming it could be) — `run_pipeline.py` passes the live `DoclingDocument`
  straight from `section_parser.run()`'s `AncestryResult.doc` into `HybridChunker`
  (`chunk_text.run_structure_aware()`), independent of whatever `item_ancestry` does or doesn't
  capture. So even where the ancestry map has no stem-to-item link, the stem sentence and its list
  items may still land in the same chunk's raw text simply by being adjacent in the source document —
  a completely separate channel from the ancestry map, and one the audit has to check on its own
  terms, not assume follows from the ancestry finding above.

This is consistent with what WP-38.2's review process kept finding from the Step D side: the
information needed to resolve these fragments doesn't obviously exist *in the extracted quote text*
— the open question this phase answers is whether it exists earlier in the pipeline (docling's raw
parse, chunking) and gets dropped, or whether it needs to be reconstructed from scratch.

## 2. Goals

- Determine, with real evidence rather than assumption, exactly where parent-stem/main-clause context
  is lost for a genuinely fragmentary extraction — at Docling's raw parse, at chunking
  (`HybridChunker`), at Step C extraction (`llm_extract_requirements.py`), at Step D normalization, or
  at embedding/indexing (which field actually gets embedded).
- For each pipeline stage, produce a real, concrete example (not a hypothetical) showing whether the
  needed context is present or already gone by that point.
- Recommend the cheapest fix, at whichever stage still has (or can regain, e.g. via `chunk_id`) real
  access to the parent stem — a schema change to carry `parent_stem`/`embedding_text` forward, a Step
  C prompt change, a chunking-boundary fix, or (only if the structure is genuinely unrecoverable
  through any channel) a heavier fix at the embedding layer.
- Confirm whether one reconstruction shape (`parent_stem` + `child_item`) covers both known fragment
  patterns — enumerated list items missing a stem, and subordinate clauses missing a main clause — or
  whether they need distinct handling.

## 3. Non-Goals

- **Not implementing reconstruction yet.** This phase is audit-first, same shape as WP-38.1 →
  WP-38.2. A WP-39.2 (or later), scoped from this audit's actual findings, does the fix.
- **Small instrumentation only, if needed to answer an audit question** (e.g. a one-off script that
  dumps a chunk's raw text for a known fragment's `chunk_id`) — not production pipeline changes.
- **Not "smarter embeddings" as a first move.** Only in scope if the audit shows the needed context is
  genuinely unrecoverable earlier in the pipeline, or reconstruction alone doesn't fix retrieval for
  the affected examples. `docs/PHASE37_REQUIREMENTS.md`'s WP-37.2 (contextual chunk embeddings,
  reverted) is the standing caution here — don't reach for that lever again without first
  understanding why it didn't work last time.
- **Not re-auditing over-grab precision** — that's WP-38's own still-open backlog item, unrelated to
  this phase's fragment/context-loss problem.
- **Not touching `_is_orphaned_list_item()`/`_is_dangling_clause()` (Step D) again.** Those rules are
  settled as of WP-38.2 — this phase is about giving fragments real context, not further tuning
  whether they get rejected.

---

## 4. Work Packages

### WP-39.1 — Parent-Stem Context Loss Audit

**Source:** WP-38.2's Backlog entry (`docs/PHASE38_REQUIREMENTS.md`); this doc's Phase Framing above.

**Problem:** No pipeline-stage-by-stage evidence exists for where parent-stem/main-clause context
gets lost between Docling's raw parse and what actually gets embedded/indexed. Every fix option's
cost and shape depends on the answer, and guessing has already cost four review rounds of narrowing
and reverting a Step D rule that was never going to solve this from that side.

**Scope:**
- **Start from known examples, not a fresh trawl.** WP-38.1's audit fixture
  (`eval/audit_wp38_1/`) already has hand-labeled, real examples of both target shapes: 12
  `orphaned_list_item` records and 6 `dangling_clause` records, several with the missing context
  already identified in prose during WP-38.2's own Findings (e.g. `REQ-c6aeb8df528b`, `"(3) Restrain
  competition."`, stem `"Classification shall not be used to:"`). **Note (Codex local review, PR
  #182): `labeled_failures.jsonl` is only the label sheet** —
  `category`/`subtype`/`quote`/`doc_key` and a few derived flags, no `chunk_id`, `source_pdf`,
  `document_id`, or artifact path (verified directly: it genuinely has none of these fields). Tracing
  needs the full record — join back to `unbiased_sample.jsonl` by `requirement_id` first (that file
  has `chunk_id`, `source_pdf`, `_source_file`, `document_id`, and `document_hash_full`). Trace these
  ~18 real cases through the pipeline first; only broaden to a fresh sample if that's not enough
  signal to answer the Goals.
- **Verify the local corpus before trusting any `chunk_id` lookup against it** (Codex local review,
  PR #182) — the processed corpus this fixture was built from lives outside the repo, in
  `~/documents/processed`, and isn't guaranteed to still match on whatever machine WP-39.1 actually
  runs on. First step: check `eval/audit_wp38_1/source_manifest.json`'s per-document sha256 against
  the current files `core.artifact_resolver.resolve_latest_requirement_files()` resolves. (Checked
  directly while writing this doc, 2026-07-31: all 13 documents match exactly, 0 drift — but that's
  today's state on this machine, not a standing guarantee, so the audit re-checks this itself rather
  than trusting this note.) If any document is missing or its hash has changed (a re-ingest happened
  since WP-38.1's audit ran, which can reassign `chunk_id`s), don't trust that document's `chunk_id`
  values as-is — re-match its affected records by `document_hash_full` + exact `source_quote` text
  instead, and note which examples needed the fallback.
- **For each traced example, check every representation independently — do not stop at the first
  stage where a specific field or record lacks the link** (Codex review, PR #182: a stem missing from
  one representation doesn't mean it's gone — it may still be recoverable through a different channel
  at a later stage, e.g. `chunk_id` pointing back to raw chunk text even after Step C's own output
  record drops it; stopping early risks recommending a fix at the wrong stage entirely):
  1. Does Docling's raw parsed document contain the parent stem for this item at all, and does
     Docling's own document model (not ReqBot's ancestry code) expose a direct link between the list
     item and its stem/list-group — separately from whatever `section_parser.py` currently computes?
  2. Does `section_parser.py`'s ancestry map (`parent_header_text`/`parent_context`) happen to carry
     the stem for this example, even though it's only designed for heading-level parentage?
  3. Is the parent stem in the *same chunk* as the child item after `HybridChunker` runs, checked
     directly against the chunk's raw text (`build_chunk_text_map`-style lookup by `chunk_id`, same
     pattern WP-32.1's grounding check uses) — **independently of what #1/#2 found**, since chunking
     works from the live `DoclingDocument` directly, not from the ancestry map (confirmed in Phase
     Framing above).
  4. Does Step C's extraction output (`llm_extract_requirements.py`) see or preserve the stem
     anywhere, even if not in `source_quote` itself?
  5. Does Step D normalization drop it anywhere in the current record schema, for whichever of
     #1-#4 it had going in?
  6. What exact text actually gets embedded today (`pipeline/embed_and_index.py` /
     `embed_context_index.py`) — the `source_quote` alone, or something already richer? And
     separately: could `chunk_id` still be used to reconstruct `parent_stem` at embedding time even if
     every earlier stage's own output record dropped it — i.e. is the *cheapest* fix actually the
     latest stage that still has (or can regain, via `chunk_id`) access to the raw material, not
     necessarily the earliest stage where a field first goes missing?
- **Retrieval check, not just presence/absence.** For at least a handful of the traced examples,
  check directly whether prepending the recovered `parent_stem` to the embedding input would plausibly
  improve retrieval for a realistic query about that requirement — informed by, but not re-litigating,
  WP-37.2's finding that *heading*-level context regressed retrieval on this corpus. A stem sentence
  immediately governing a list item is a different kind of context than a section heading several
  levels up (WP-37.2's finding was specifically about heading-chain context) — don't assume WP-37.2's
  result transfers here without checking.
- End with an explicit, evidenced recommendation: which single pipeline stage (or stages) should
  carry `parent_stem`/`embedding_text` forward, and the cheapest concrete schema/prompt/chunking
  change that does it — or, if the audit finds the two fragment shapes need genuinely different
  fixes, say so plainly rather than force one shape onto both.

**Non-goals:**
- Not fixing anything found yet — same as WP-38.1, audit and recommend only.
- Not building the `parent_stem` reconstruction itself, even if the audit makes the fix obvious —
  that's a subsequent WP once the exact stage and shape of the fix is known.

**Tests/verification:**
- Investigation/measurement WP, same shape as WP-38.1 — committed audit findings (real traced
  examples, per-stage evidence, a grounded recommendation) are the deliverable, not new production
  code.
- Any instrumentation script written to answer an audit question gets committed under
  `eval/audit_wp39_1/` (mirroring `eval/audit_wp38_1/`'s pattern) so the findings are reproducible,
  not just asserted in prose.
- `ruff check .` clean if any code is added.

**Gate:** A real, per-stage traced account of where parent-stem/main-clause context is lost for both
known fragment shapes, backed by the traced examples and their evidence, with a grounded
recommendation for what WP-39.2 (or later) should build — including whether one schema covers both
shapes.

**Findings (2026-07-31):**

*Method.* Joined `eval/audit_wp38_1/labeled_failures.jsonl` (category/subtype labels) with
`unbiased_sample.jsonl` (`chunk_id`, `source_pdf`, `document_id`, `document_hash_full`) by
`requirement_id`, per this WP's revised Scope. Re-verified the local corpus against
`source_manifest.json` first — still 0/13 documents drifted. Traced all 18 real FRAGMENT examples
(12 `orphaned_list_item`, 6 `dangling_clause`) against their actual on-disk pipeline artifacts —
`*_chunks.jsonl` (Step B raw text + ancestry), `*_extracted_requirements.jsonl` (Step C raw output)
— and hand-classified each into a loss category, same discipline as WP-38.1's own hand-audit.
Script and full classification (with per-example notes) committed at
`eval/audit_wp39_1/trace_examples.py` and `eval/audit_wp39_1/classify_examples.py`.

*Headline result: chunking is almost never the problem, and Step C's flat extraction schema is where
context actually gets lost — but through three genuinely different mechanisms, not one.*

| Category | Count | What it means |
|---|---:|---|
| `SAME_CHUNK_STEM_EXTRACTED` | 7 | The stem/main clause is already a *separate* Step C record in the same chunk — just not linked to the fragment. Cheapest possible fix: pure proximity reconstruction against data already extracted, no LLM or chunking change needed. |
| `STEM_NEVER_EXTRACTED` | 3 | The needed text is verbatim in the chunk's raw text, but Step C never extracted it as *any* record — truncated mid-sentence or skipped entirely. Needs either a Step C prompt/schema fix, or reconstruction straight from raw chunk text (bypassing Step C's output). |
| `CROSS_CHUNK_SPLIT` | 2 | The stem is in a *different*, earlier chunk — confirmed directly for both examples by loading the preceding chunk, not inferred from absence: `REQ-cf527f39c8d7` (stem in `chunk_id=12`, item in `chunk_id=13`, `DODI 8551.01`) and `REQ-48f549669bb2` (stem in `chunk_id=32`, item in `chunk_id=33`, `DODI 8410.03` — this second one was originally asserted without checking the preceding chunk at all; Codex's review of PR #183 caught that gap, and checking it directly confirmed the stem really is one hop back). Exactly the failure mode Codex's PR #182 review warned the original "stop at first stage" methodology would miss. |
| `CITATION_ONLY_NOT_A_TARGET` | 2 | A `"<term>, as defined in <citation>"` pointer — WP-38.2's `_is_definitional_citation_only()` already correctly rejects these. Not fragments needing reconstruction at all. |
| `GARBLED_TABLE` | 2 | Chunk text is mangled, flattened tabular content — but confirmed via directly re-running Docling on the source page (`eval/audit_wp39_1/check_garbled_table_source.py`, added after Codex's review of PR #183 pointed out the original audit never actually loaded the raw `DoclingDocument` for these) that **the mangling is not a Docling parsing failure**: Docling correctly labels this a `table` item, and `table.export_to_dataframe()` returns real, distinct row values (`"Detection of Events"`, `"Preliminary Analysis & Identification"`, ...). The corruption is introduced by `chunk_text.py`'s handling of body-label items, which serializes tables the same generic way as flowing prose instead of using Docling's own structured table export. Still a genuinely different problem from the other categories (needs table-aware serialization, not a `parent_stem` field) — but a more tractable one than "Docling parsed this badly" would have implied, since the real structure already exists one function call away. |
| `HEADING_IS_SUBJECT` | 1 | The missing "stem" is really the section heading itself (`REQ-1b1071c8d317`: `parent_header_text` = `"2.2. Directorate of Security, Special Access Program Oversight and Information Protection (SAF/AAZ)."`) — the source document never states a separate subject sentence at all; the office name *is* the subject for every item under it. Already computed, already flows through every chunk record today — zero new engineering to *access* it, just needs to be recognized as a `parent_stem` candidate. |
| `AMBIGUOUS_MAY_NOT_BE_REQ` | 1 | `REQ-364e0be72ebb`, `"Overview of programmatic and policy updates or changes."` — a bare noun-phrase item in a training-program topic list. Unclear a `parent_stem` even makes this an actionable requirement; closer to descriptive/topic content than a requirement missing context. Flagging rather than force-classifying. |

*What this rules out, concretely (corrected after Codex's review, PR #183, caught the original count
here — this table's own 7 + 3 + 1 was written up as "15," not 11):*
- **Chunking is not the primary bottleneck.** 10 of 18 examples (`SAME_CHUNK_STEM_EXTRACTED`'s 7 +
  `STEM_NEVER_EXTRACTED`'s 3) have their needed context in the *same* chunk as the fragment —
  confirmed by reading `HybridChunker`'s actual output, not assumed from the Phase Framing's
  architectural note above. `HEADING_IS_SUBJECT`'s 1 example needs no chunk lookup at all (the context
  is `parent_header_text`, already on the record regardless of chunking). 11 of 18 total need no
  chunking fix of any kind. Only 2/18 are genuine cross-chunk splits — and both were confirmed by
  directly checking the adjacent chunk, not inferred from absence alone: the first version of this
  audit asserted `REQ-48f549669bb2` was cross-chunk without actually loading the preceding chunk to
  check (also caught by Codex's review). It's since been verified directly — the stem really is there,
  one hop back, same as the other confirmed case.
- **Step C's own LLM input already contains the answer in the large majority of cases** — the model
  had the full stem sentence in front of it (it's in the same chunk `raw_text` that gets sent as its
  prompt input) and either extracted it as a separate, unlinked candidate (7 cases) or dropped it
  outright (3 cases). Either way, **no chunking change is needed for 10 of these 18 examples** — the
  fix is entirely about what Step C's *output schema* keeps, not what it *sees*.
- **`_is_definitional_citation_only()` and the `_is_orphaned_list_item()`/`_is_dangling_clause()`
  removal from WP-38.2 are both already doing the right thing** — the 2 `CITATION_ONLY_NOT_A_TARGET`
  examples confirm those aren't reconstruction candidates, and the 3 examples WP-38.2 explicitly chose
  *not* to reject (per Tyler's product call) are exactly the ones this audit shows have recoverable
  context sitting one hop away.

*Step D and embedding, confirmed directly from code, not assumed:*
- Step D (`pipeline/parse_and_normalize.py`) doesn't currently *reject* anything based on this — but
  it also would **not** pass a hypothetical `parent_stem` field through: `run()` builds its
  `normalized` output dict from an explicit field literal, not a passthrough of the incoming record,
  so any field not named in that literal is silently dropped (corrected after Codex's review of PR
  #183 — the original version of this bullet claimed the opposite; see the WP-39.2 recommendation
  below for what this means for where reconstruction should live).
- Embedding (`pipeline/embed_and_index.py`'s `build_embedding_text()`) confirmed by reading the code
  directly: embeds `source_quote` plus an optional `\nRef: {source_ref}` suffix — **nothing else,
  today.** Matches Codex's own independent verification during PR #182's review.

*Retrieval check — real embeddings, not simulated (`nomic-embed-text` via the project's configured
Ollama host), for one example per major category:*

| Example | Category | Bare-quote similarity | With parent-stem | Delta |
|---|---|---:|---:|---:|
| `REQ-9700722b04cd` (`"shall be coordinated with the customer"`) | `SAME_CHUNK_STEM_EXTRACTED` | 0.5051 | 0.7690 | **+0.264** |
| `REQ-c6aeb8df528b` (`"(3) Restrain competition."`) | `SAME_CHUNK_STEM_EXTRACTED` | 0.6727 | 0.7100 | +0.037 |
| `REQ-1b1071c8d317` (CNDSP CA item) | `HEADING_IS_SUBJECT` | 0.7033 | 0.7061 | +0.003 |

Each tested against a realistic query about that specific requirement (see
`eval/audit_wp39_1/classify_examples.py` for exact text). The gain scales with how semantically empty
the bare quote is on its own — largest where the fragment alone carries almost no domain content
(`"shall be coordinated with the customer"` could be about anything), smallest where the bare quote
already contains enough identifying detail that the missing subject barely matters for retrieval.
This is a different intervention than WP-37.2's reverted contextual-embedding attempt — that
prepended a heading chain to *every* record regardless of need and measurably regressed retrieval;
this is a targeted, per-record addition only for records that are already known to be
context-starved, and it doesn't touch the embedding text for the other 95%+ of the corpus that isn't
fragmentary. No evidence found that WP-37.2's regression applies here — different mechanism, opposite
scope (universal vs. targeted).

*Recommendation for WP-39.2 (not built here, per this WP's Non-Goals):*
1. **Don't touch Step C's LLM prompt.** Consistent with this project's standing preference for
   deterministic fixes over LLM-reliability risk — 10 of the 15 real reconstruction candidates (all
   of `SAME_CHUNK_STEM_EXTRACTED` + `HEADING_IS_SUBJECT`, plus both `CROSS_CHUNK_SPLIT` cases) are
   solvable with **purely deterministic reconstruction against data already on disk today**: no model
   call, no prompt engineering.
2. **Placement matters and needs to be decided explicitly, not left implicit** (Codex review, PR
   #183: the original draft here said "Step D or a new step between C and D" as if those were
   interchangeable — they aren't. `parse_and_normalize.py`'s `run()` builds its `normalized` output
   from an explicit field literal, not a passthrough of the incoming record — a new
   `parent_stem`/`embedding_text` field placed *before* Step D would be silently dropped unless Step
   D's own schema is also updated to carry it through). Two real options, not one:
   a. Add the reconstruction logic *inside* Step D, with `parent_stem`/`embedding_text` added to
      `run()`'s `normalized` field literal directly; or
   b. Run reconstruction as a separate step *after* Step D, reading `*_requirements_normalized.jsonl`
      (which already has `chunk_id` on every record) and writing the new fields onto its own output
      — no changes to `parse_and_normalize.py` at all.
      (b) is probably cleaner (zero risk to Step D's existing, already-tested rejection logic) and is
   this WP's recommendation, but WP-39.2 should make the call explicitly rather than assume either.
3. **The trigger condition needs its own new selector — not the existing Step D rejection
   predicates** (Codex local review of PR #183: caught that the original draft here said "only for
   records already flagged by the existing `_is_orphaned_list_item()`/`_is_dangling_clause()`
   detectors" — checked directly against the current code and this is wrong. WP-38.2 deliberately
   removed `_is_orphaned_list_item()`'s marker/list-item branch entirely and kept
   `_is_dangling_clause()` narrowed to bare-copula-openers only, precisely so these fragile-but-real
   requirements would *survive* un-rejected rather than risk a false rejection. Checked all 10 cheap-win
   candidates (`SAME_CHUNK_STEM_EXTRACTED`'s 7 + `CROSS_CHUNK_SPLIT`'s 2 + `HEADING_IS_SUBJECT`'s 1)
   against both current detectors (corrected after Codex's local review of PR #183 caught the first
   version of this only summing to 7 and misdescribing which categories that 7 covered — it was
   actually a 7-example subset spanning all three categories, not an exhaustive check of any one of
   them; now all 10 are checked): only `REQ-1b1071c8d317` (`HEADING_IS_SUBJECT`, the bare-copula
   case) is flagged by either one — every other example, across all three categories, returns `False`
   for both. Gating reconstruction on these predicates would miss 9 of the 10 cheap wins this
   recommendation is built on — the two jobs are opposites: Step D's predicates decide "is this
   unsafe enough to delete," precision-first; reconstruction candidacy needs to decide "is this short
   enough to plausibly benefit from more context," which is a different, likely broader question).
   **WP-39.2 needs to define this selector itself as part of its own scope** — not assumed solved
   here. A plausible starting point (not a commitment): reuse the *structural* signals already proven
   safe in this file (list-marker prefix via a regex like the deleted `_LIST_MARKER_RE`, a short word
   count, a colon-terminated preceding record) as a *candidacy* heuristic rather than a *rejection*
   heuristic — false positives here are far cheaper than in Step D (attaching an unhelpful
   `parent_stem` to an already-complete quote is a minor embedding-quality cost, not a silently
   deleted requirement), so the precision bar can reasonably be lower than Step D's.
4. Whichever placement and trigger condition are chosen, the reconstruction step attempts, in order,
   falling through to "leave empty" rather than guessing:
   a. the nearest preceding same-chunk Step C record that looks like a stem (ends in `:`, or
      similar structural signal already established in `_is_unrepairable_fragment()`);
   b. if not found, the same check against the *immediately preceding chunk* (same `document_id`,
      sequential `chunk_id`) — covers the confirmed `CROSS_CHUNK_SPLIT` cases;
   c. if still not found, fall back to `parent_header_text` directly — covers `HEADING_IS_SUBJECT`
      at zero additional engineering cost, since that field already exists on every chunk record.
   Then update `build_embedding_text()` to prefer `embedding_text` when present, falling back to
   `source_quote` — backward compatible, no reindex forced.
5. **Leave `STEM_NEVER_EXTRACTED` (3 examples) and `GARBLED_TABLE` (2 examples) out of WP-39.2's
   scope.** The former needs either a Step C fix (out of step with recommendation #1) or raw-chunk-text
   stitching (a meaningfully different, riskier mechanism than steps 2a-2c); the latter needs
   table-structure-aware handling, a different problem entirely. Both are real, but scoping them into
   the same WP as the 10 cheap wins risks the whole WP stalling on the hard 30% instead of shipping
   the easy, well-evidenced 70%. Worth their own future WP if the rate justifies it after WP-39.2
   ships and the corpus is re-measured.
6. `AMBIGUOUS_MAY_NOT_BE_REQ` (1 example): don't force a `parent_stem` guess onto it. If it stays
   unrejected and unreconstructed after WP-39.2, that's the same "honest gap over false confidence"
   discipline already established for `_is_orphaned_list_item()`'s bare-noun-phrase case in WP-38.2.

*Not done, by design (per this WP's own Non-Goals):* no `parent_stem` reconstruction was
implemented, no schema changed, no reindex run. This is audit output only.

---

### WP-39.2 — Parent-Stem Reconstruction

**Source:** WP-39.1's Findings and Recommendation above (`docs/PHASE39_REQUIREMENTS.md`), scoped
directly from its evidence rather than assumed — same relationship as WP-38.1 → WP-38.2.

**Problem:** 10 of the 18 known real fragment examples (7 `SAME_CHUNK_STEM_EXTRACTED`, 2
`CROSS_CHUNK_SPLIT`, 1 `HEADING_IS_SUBJECT`) have their governing context sitting one deterministic
lookup away — already extracted as a separate Step C record in the same or an adjacent chunk, or
already computed as `parent_header_text` — but nothing in the pipeline captures it or uses it today.
`build_embedding_text()` embeds `source_quote` alone. A real (not simulated) embedding-similarity
check confirmed this measurably hurts retrieval, worst exactly where the bare quote carries the least
content on its own (+0.264 similarity recovered for `"shall be coordinated with the customer"`
against a realistic query).

**Scope:**
- **Define the reconstruction-candidate selector — this is new work, not a reuse of Step D's rejection
  predicates.** WP-39.1 confirmed directly that `_is_orphaned_list_item()`/`_is_dangling_clause()`
  flag only 1 of the 10 cheap-win examples (WP-38.2 deliberately narrowed/removed those predicates so
  fragile-but-real requirements would *survive*, not so they'd be identifiable later). Candidacy is a
  different, likely broader question than rejection-safety — false positives here just mean an
  unhelpful `parent_stem` gets attached to an already-complete quote (a minor embedding-quality cost),
  not a silently deleted requirement, so the precision bar can reasonably be lower than Step D's.
  Starting point per WP-39.1: reuse structural signals already proven safe in this codebase (a
  list-marker prefix, the deleted `_LIST_MARKER_RE` pattern; a short word count; the record's own
  preceding same-chunk neighbor ending in `:`) as a *candidacy* heuristic. Calibrate against the same
  18 known examples WP-39.1 traced (validate the selector actually catches the 10 intended cheap wins
  and doesn't fire on the 8 that shouldn't get a `parent_stem` — the 2 `CITATION_ONLY_NOT_A_TARGET`
  examples especially, since those are correctly non-actionable already).
- **Reconstruction lookup, in order, falling through to "leave empty" rather than guessing** (per
  WP-39.1's Recommendation; step 1's exact matching signal corrected below after Codex's local review
  of PR #184 found a real counter-example):
  1. the nearest preceding same-chunk record (from Step C's raw output, matched by `chunk_id`) that
     contains an introductory colon — **not necessarily as the record's last character.** Checked
     directly: `REQ-48f549669bb2`'s actual preceding stem in `DODI 8410.03`'s chunk 32 is Step C's own
     record `"This section will define for all parties: The characteristics of the NM information to
     be exchanged..."` — Step C already merged the stem with its first sibling `(a)` item into one
     combined quote ending in a period, not a colon. A strict "record *ends in* `:`" match (the
     original draft here, and the same shape as `_is_unrepairable_fragment()`'s own trigger) misses
     this case entirely. The reconstruction logic needs to extract the text *up to and including* the
     first colon within a matching record, not require the colon to be the record's own ending —
     calibrate this against all 18 known examples during implementation, the same way every text
     signal in this file has been calibrated rather than assumed correct on the first pass;
  2. if not found, the same check against the *immediately preceding chunk* (same `document_id`,
     sequential `chunk_id`) — covers the confirmed `CROSS_CHUNK_SPLIT` cases;
  3. if still not found, fall back to `parent_header_text` directly — covers `HEADING_IS_SUBJECT` at
     zero additional engineering cost, since that field already exists on every chunk record today.
- **Placement: extend the enrichment stage (Step D.5, `pipeline/enrich_requirements.py`), not a new
  untracked output file** (corrected after Codex's local review of PR #184 — the original draft here
  said "a new step after Step D, writing to its own output," but checked directly against
  `core/artifact_resolver.py`: `resolve_latest_requirement_files()` only discovers the three
  hardcoded suffixes `_requirements_gated`/`_requirements_enriched`/`_requirements_normalized`. A
  reconstruction step writing to any other file name would be invisible to that resolver — `reindex`
  and every other caller of it would keep silently selecting an existing tier without `parent_stem`/
  `embedding_text`, and the fix would do nothing on any run after the one that happened to explicitly
  target the new file). `enrich_requirements.py`'s own docstring already describes exactly the right
  shape: `"Input: requirements_normalized.jsonl (from Step D). Output: requirements_enriched.jsonl —
  same schema, with enrichment fields populated."` Adding `parent_stem`/`embedding_text` as two more
  fields this stage populates keeps output landing in the `_requirements_enriched` tier the resolver
  already recognizes and already prefers over `normalized` — no resolver changes needed, and still no
  changes to `parse_and_normalize.py`'s Step D rejection logic (this is Step D.5, not Step D).
  **One more constraint this placement needs, not yet handled by "just add fields to
  `enrich_requirements.py`" alone** (Codex local review of PR #184, second pass — a real gap in the
  fix above, not the same one already resolved): checked `run_pipeline.py` directly — Step D.5 is
  wrapped in a single `try`/`except Exception` that catches *any* failure (including Ollama being
  unreachable, per the LLM-dependent description/domain_tags/requirement_type generation
  `enrich_requirements.py` already does) and silently falls back to `index_path = norm_path`, and the
  whole step is skipped outright when `--skip-enrichment` is passed. Reconstruction is supposed to be
  deterministic and model-independent — if it's simply folded into the same function body as the
  LLM-calling enrichment logic, it inherits both failure modes for free: an Ollama outage or
  `--skip-enrichment` would silently lose the free, no-model-call context recovery too, even though
  neither has anything to do with it. **WP-39.2 must keep reconstruction structurally independent of
  the LLM-dependent portion of Step D.5** — either as its own code path inside
  `enrich_requirements.py` with its own (or no) error handling, not sharing the LLM call's
  `try`/`except`, and running regardless of whether `--skip-enrichment` is set; or, if that coupling
  turns out to be awkward in practice, as a distinct small step in `run_pipeline.py` that always runs
  on whatever `index_path` is once Step D has run, independent of D.5's own success/skip state. Which
  of these two shapes is used is an implementation decision for WP-39.2 itself — but the outcome must
  be tested (see Tests/verification below): reconstruction survives both `--skip-enrichment` and a
  simulated enrichment failure.
- Add `parent_stem` and `embedding_text` fields to the schema (Tyler's original example: `source_quote`
  + `parent_stem` + a combined `embedding_text`). Update `pipeline/embed_and_index.py`'s
  `build_embedding_text()` to prefer `embedding_text` when present, falling back to `source_quote` when
  absent — backward compatible, no forced reindex.
- **Also add both new fields to the indexed Qdrant *payload*, not just the embedding computation**
  (Codex local review of PR #184, real gap: `build_payload()` builds the stored payload from its own
  explicit field literal — same pattern as `parse_and_normalize.py`'s `normalized` dict — and doesn't
  include either new field today. Improving `build_embedding_text()` alone only makes a fragment
  easier to *find*; the record a user actually gets back still renders bare `source_quote`/
  `description`, since that's literally all `core/ask.py` has access to
  (`hit.get("description") or hit.get("source_quote", "")` — confirmed by reading the code). Without
  this, the phase's own stated goal — "the child item is retrieved *with* its governing context
  rather than standing alone" — isn't actually met even after everything else in this WP ships;
  ranking would improve but the displayed result would still be the same dangling fragment). Scope
  includes updating whichever of `core/ask.py`/the API/the UI render results to actually surface
  `parent_stem` when present, not just storing it unused in the payload.
- Validate against the 10 known cheap-win examples specifically: did each recover the *correct* stem
  (matching what WP-39.1 already hand-verified), not just *some* non-empty value.
- Re-run WP-39.1's own retrieval-similarity methodology (real `nomic-embed-text` embeddings via
  `core.config.load()`, not simulated) across a broader sample post-fix — WP-39.1 only spot-checked 3
  examples; confirm the improvement generalizes before calling this done.

**Non-goals:**
- **Not touching Step C's LLM prompt.** Per WP-39.1's recommendation — this WP is a deterministic,
  no-model-call fix.
- **Not attempting `STEM_NEVER_EXTRACTED` (3 examples) or `GARBLED_TABLE` (2 examples).** The former
  needs either a Step C fix or raw-chunk-text stitching (a different mechanism from the lookup above);
  the latter needs table-structure-aware serialization in `chunk_text.py` (WP-39.1 confirmed the real
  table structure exists via Docling's `export_to_dataframe()` — a genuinely different, separately
  scoped fix, not this WP's job). Both explicitly deferred so this WP isn't blocked shipping the
  well-evidenced 10/18.
- **Not forcing a `parent_stem` guess onto `AMBIGUOUS_MAY_NOT_BE_REQ`** (1 example) — same "honest gap
  over false confidence" discipline as `_is_orphaned_list_item()`'s bare-noun-phrase case in WP-38.2.
- **Not re-ingesting or reindexing the full production corpus as part of this WP** — schema/code
  changes only affect future runs, matching WP-38.2's own precedent; re-ingesting the rest of the
  corpus is a separate, explicit decision. (Distinct from the `reindex` *sanity check* in
  Tests/verification below, which only needs a small local run to confirm the resolver picks up the
  new fields correctly — not a full corpus reindex.)
- **Not building a general contextual-embedding system.** Targeted, per-record, only for records the
  candidate selector actually flags — not the universal per-record approach WP-37.2 tried and reverted.

**Tests/verification:**
- New unit tests for the candidate-selector heuristic and each of the three lookup steps, using real
  corpus examples (same discipline as WP-38.2's rule tests — cite real `requirement_id`s, not
  hypotheticals).
- Regression check against all 18 WP-39.1 examples: the 10 cheap wins recover the correct stem, the 8
  others (`STEM_NEVER_EXTRACTED`, `GARBLED_TABLE`, `CITATION_ONLY_NOT_A_TARGET`, `AMBIGUOUS_MAY_NOT_BE_REQ`)
  correctly get no `parent_stem` attached.
- `build_embedding_text()` tests confirming `embedding_text` is preferred when present and the fallback
  to `source_quote` still works when absent.
- **`build_payload()` tests confirming `parent_stem`/`embedding_text` are actually indexed into
  Qdrant, not just used at embedding time** — and an end-to-end check that `core/ask.py` (or whichever
  consumer is updated) surfaces `parent_stem` in what a query actually returns for one of the 10 known
  examples, not just that the field exists unused in the payload.
- **`reindex` sanity check**: confirm `core.artifact_resolver.resolve_latest_requirement_files()`
  picks up the enrichment-stage output with the new fields on a real run, not a different tier missing
  them — the specific failure mode this WP's Placement section above was rewritten to avoid.
- **`--skip-enrichment` / enrichment-failure survival check**: run the pipeline with
  `--skip-enrichment` and separately with a simulated Step D.5 LLM failure (e.g. point
  `enrichment_model`/`ollama_url` at something unreachable), and confirm `parent_stem`/
  `embedding_text` are still populated in both cases — the specific coupling risk the Placement
  section's second constraint above exists to prevent.
- Retrieval-similarity re-check (real embeddings) across a broader sample, not just the 3 WP-39.1
  spot-checked.
- Full `pytest` suite and `ruff check .` clean throughout.

**Gate:** `parent_stem`/`embedding_text` reconstruction implemented and placed per the recommendation
above; validated against all 18 known examples with *correct* (not just non-empty) results —
including `REQ-48f549669bb2`'s merged-stem case, not just the 9 that fit the simpler pattern; both
fields present in the indexed Qdrant payload *and* actually surfaced by at least one result-rendering
consumer, not just computed and left unused; `reindex` confirmed to pick up the new fields on a real
run; reconstruction confirmed to survive both `--skip-enrichment` and a simulated Step D.5 LLM
failure, not silently coupled to Ollama availability; retrieval improvement re-confirmed on a broader
sample; Step D's existing rejection logic untouched; full test suite and `ruff check .` clean.

**Findings:**

*Implementation, per the Placement recommendation above:* `pipeline/enrich_requirements.py`
gained a fully separate, deterministic code path (`apply_parent_stem_reconstruction()` and its
helpers) that writes `parent_stem`/`embedding_text` directly onto `*_requirements_normalized.jsonl`
— the resolver's lowest, always-present tier, not just the enriched one — and is called
unconditionally from `run_pipeline.py` immediately after Step D, before the `--skip-enrichment`
check and in its own `try`/`except`, separate from Step D.5's. `enrich_requirements.run()` also
calls it at its own top for anyone invoking that module standalone. `pipeline/embed_and_index.py`'s
`build_embedding_text()` now prefers a record's `embedding_text` field over bare `source_quote`, and
`build_payload()` indexes both new fields. `core/ask.py`'s `format_evidence()`/`print_results_table()`
now render a `Governing clause:` line when `parent_stem` is present.

*Calibration against the 18 known examples surfaced 6 real gaps beyond what PR #184's review
caught* — the scope above was written before any code existed against it; every one of these was
found by actually running the lookup against real corpus text, not by re-reading the spec:

1. **The scope's step-1 signal ("preceding record contains a colon") misses 2 of the 10 cheap
   wins.** `REQ-c62e41aaf181` and `REQ-9700722b04cd`'s real antecedent records have no colon at
   all — one is an unfinished clause Step C split from its own continuation
   (`"establish, direct, and administer...SCI security programs"`, no terminal punctuation at
   all); the other is a case where the fragment's text is already a verbatim tail of the
   preceding record (`"...shall be coordinated with the customer."`). Fixed by adding two more
   antecedent-validity conditions: no terminal sentence punctuation at all (used as-is), or the
   target quote is a substring of the candidate (candidate used as-is).
2. **A step-3 fallback that fires whenever steps 1-2 fail also fires for `STEM_NEVER_EXTRACTED`,**
   which must get no `parent_stem` at all. Confirmed `REQ-4aeeff50f15b`'s own `parent_header_text`
   doesn't even match its chunk's real section (an unrelated upstream ancestry-tracking mismatch,
   not fixable here) — an ungated fallback would have attached it anyway. Fixed by gating step 3 on
   `_is_dangling_clause()`, the existing WP-38.2 predicate already confirmed (by its own docstring)
   to uniquely flag `REQ-1b1071c8d317` among all 18 with zero false positives against 284 real
   corpus records — reused rather than reinvented.
3. **Checking only the immediate preceding record misses deep list items.** `REQ-626b98fef9aa`
   (`"(4) Prevent or delay..."`) sits 4 items after its real colon-terminated stem
   (`R-2-3`); every sibling in between (`"(1)..."`, `"(2)..."`, `"(3)..."`) ends in an ordinary
   period, not a colon, so checking only `records[idx-1]` finds nothing. Fixed by walking backward
   through all preceding same-chunk (and, for step 2, previous-chunk) records until one qualifies,
   not just the nearest one.
4. **The step-2 gate didn't account for raw_text's dash-prefixed lines** (`"- (7)  Communicate..."`),
   so the "does this chunk open mid-enumeration" marker check never matched anything and step 2
   never fired at all until the dash was stripped first.
5. **"Opens with *some* list marker" is too loose a step-2 gate.** `DODI 5200.48` chunk 64 opens
   with `"a."` — its own fresh list, item one — which matches a bare marker check exactly as well
   as a genuine continuation like `"(7)"` does. Without narrowing further, this produced a real
   false positive: `REQ-1cc75ab1ae84` (a `STEM_NEVER_EXTRACTED` example that must stay excluded)
   picked up an unrelated colon-terminated line (`"...the OCA will:"`) from three chunks back.
   Fixed by excluding markers that are themselves a sequence's first value (`"1"`/`"a"`/`"i"`).
6. **A URL's own colon isn't a list-intro colon.** `REQ-cf527f39c8d7`'s true stem
   (`"b. Oversee their respective Component's PPSM program to:"`) was never extracted as a Step C
   record at all — only present in the previous chunk's raw_text, reachable by the step-2 raw_text
   fallback added for gap 4 above — but a sibling list item's own body text contains
   `"https://pnp.cert.smil.mil/pnp"` and `"https://pnp.cert.mil/pnp"`, and the naive first-colon
   scan matched those instead, landing on the wrong (and truncated) line. Fixed with a
   URL-scheme-aware colon finder that skips `"://"`.

*Validation:* all 18 known examples now produce the exact expected result (10 cheap wins recover
the correct stem verbatim, including `REQ-48f549669bb2`'s merged-stem case; the 8 others correctly
get no `parent_stem`) — codified as `tests/unit/test_parent_stem_reconstruction.py`, 25 tests,
using the real text as literal fixtures rather than a live corpus dependency. Ran the actual pipeline
(Step D onward, `run_pipeline.run(skip_to="D", ...)`) against a real document (`DODI 8551.01`, a
WP-39.1 calibration source) three times against a scratch copy of its processed artifacts: normal
run, `--skip-enrichment`, and enrichment pointed at an unreachable Ollama host (genuine
`ConnectionRefusedError`, confirmed in the logs, not assumed) — `parent_stem` was correctly populated
on 18/57 real requirements in all three cases, including `REQ-cf527f39c8d7`'s exact calibrated stem,
confirming survival end to end rather than just at the unit level. `core.artifact_resolver.
resolve_requirement_file()` picked up the gated tier with both new fields intact; `build_payload()`
and `build_embedding_text()` confirmed against that real, reconstructed data.

*Retrieval re-check, broadened to all 10 cheap wins (real `nomic-embed-text` embeddings, not
simulated) — an honest, mixed result, not uniformly positive:* mean delta **+0.0745** (net
improvement), but 3 of 10 individually regressed (`REQ-1b1071c8d317` −0.005, `REQ-3097aa5d306c`
−0.015, `REQ-626b98fef9aa` −0.113). All three regressions share a pattern WP-39.1's own 3-example
spot-check didn't surface: they start from an already-high bare-quote similarity (0.70–0.88) —
long, self-contained quotes where the added stem text dilutes rather than sharpens the match against
a query that already targets the fragment's own specific phrasing. This refines, rather than
contradicts, WP-39.1's finding that gain scales with how context-starved the bare quote is: gain can
go slightly *negative*, not just toward zero, when the bare quote is already information-dense. Net
effect remains positive and the largest gains are still on the most context-starved fragments
(`REQ-9700722b04cd` +0.260, `REQ-c62e41aaf181` +0.205) — consistent with WP-39.1's mechanism, not a
different one.

Full `pytest` (818 tests) and `ruff check .` clean throughout.

---

## 5. Backlog (deferred, not WP-39.1 or WP-39.2)

- **`STEM_NEVER_EXTRACTED` (3 examples) and `GARBLED_TABLE` (2 examples)** — explicitly out of
  WP-39.2's scope (see its Non-Goals above). The former needs either a Step C prompt fix or
  raw-chunk-text stitching; the latter needs table-structure-aware serialization in `chunk_text.py`
  (WP-39.1 confirmed real table structure exists via Docling's `export_to_dataframe()` — a separately
  scoped fix, not a `parent_stem` field). Worth their own WP if the rate justifies it after WP-39.2
  ships and the corpus is re-measured.
- **Over-Grab Precision** — still open from Phase 38, unrelated to this phase's problem; see
  `docs/PHASE38_REQUIREMENTS.md`'s Backlog.

---

## 6. Success Gate

- [x] WP-39.1's audit is complete: real per-stage evidence for both fragment shapes across at least
      the known WP-38.1-fixture examples, with a grounded recommendation — not assumed from Tyler's
      framing alone. (All 18 examples traced against real on-disk pipeline artifacts, hand-classified
      into 7 loss categories, committed at `eval/audit_wp39_1/`. Real retrieval-similarity check via
      `nomic-embed-text`, not simulated.)
- [x] The recommendation is either acted on as a properly-scoped follow-up WP, or, if the audit finds
      the context is already unrecoverable or the fix doesn't move retrieval, a documented conclusion
      to that effect — an equally valid, equally evidenced outcome, not a failure to close the phase.
      (WP-39.2 implemented parent-stem reconstruction per the recommendation; validated against all
      18 known examples with correct results; retrieval improvement re-confirmed, net positive, on a
      broadened 10-example sample.)
- [x] Full `pytest` suite and `ruff check .` clean throughout. (818 tests passed; `ruff check .`
      clean.)

---

## 7. Guardrails

- No reconstruction gets built on an assumption of *where* context is lost — WP-39.1's real, traced
  evidence decides that, not the framing in this doc alone.
- Every traced example uses real `chunk_id`/`requirement_id` data, not a hypothetical — same
  discipline WP-38.1 and WP-38.2 both held to throughout.
- Don't reach for "smarter embeddings" (redesigned retrieval, contextual chunk embeddings) as a first
  move — WP-37.2 already tried something in that direction and it regressed retrieval on this corpus.
  Cheapest fix wins: a schema addition that carries more structure forward is preferred over anything
  that touches how retrieval itself works, unless the audit shows that's not enough.
