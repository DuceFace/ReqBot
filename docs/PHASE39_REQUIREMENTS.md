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
| WP-39.1 — Parent-Stem Context Loss Audit | Not started |

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

**Findings:** _(pending — filled in once WP-39.1 runs)_

---

## 5. Backlog (deferred, not WP-39.1)

- **The reconstruction fix itself** (WP-39.2 or later, scoped from WP-39.1's actual findings) —
  whatever shape the audit recommends: a schema addition threaded through Step C/D, a chunking-boundary
  fix, or (only if warranted) embedding-layer work.
- **Over-Grab Precision** — still open from Phase 38, unrelated to this phase's problem; see
  `docs/PHASE38_REQUIREMENTS.md`'s Backlog.

---

## 6. Success Gate

- [ ] WP-39.1's audit is complete: real per-stage evidence for both fragment shapes across at least
      the known WP-38.1-fixture examples, with a grounded recommendation — not assumed from Tyler's
      framing alone.
- [ ] The recommendation is either acted on as a properly-scoped follow-up WP, or, if the audit finds
      the context is already unrecoverable or the fix doesn't move retrieval, a documented conclusion
      to that effect — an equally valid, equally evidenced outcome, not a failure to close the phase.
- [ ] Full `pytest` suite and `ruff check .` clean throughout.

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
