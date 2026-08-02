# ReqBot Phase 42 — Table-Structure-Aware Serialization

**Status:** Complete (drafted 2026-08-02; source: direct conversation with Tyler after WP-41 merged)
**Date:** 2026-08-02
**Preceded by:** Phase 41 (Context Recovery Fixes & Confidence Calibration) — `docs/PHASE41_REQUIREMENTS.md`,
complete. This phase picks up the `STEM_NEVER_EXTRACTED`/table-structure-aware serialization candidate
direction from Phase 40's §5/§8 Backlog (Tyler's choice among reranker / definitional-content-decision /
table serialization). The reranker and the definitional-content-retrievability question remain deferred
— see Phase 40's §8 Backlog.
**Followed by:** Not decided. `STEM_NEVER_EXTRACTED` (Step C never extracting some verbatim chunk text at
all) is explicitly out of scope here — see Non-Goals — and remains open for a future WP.

---

## Status

| WP | Status |
|---|---|
| WP-42 — Table-Structure-Aware Serialization | Complete |

---

## 1. Phase Framing

Phase 40's Backlog (§8) carried forward two related-but-distinct deferred items under one heading,
both originally raised by WP-39.1: `STEM_NEVER_EXTRACTED` (Step C never extracts some verbatim chunk
text at all — 3 known examples, needs a Step C prompt/schema fix or raw-text stitching) and
`GARBLED_TABLE` (chunk text mangled by table serialization — originally 2 known examples, WP-40's
corpus-wide scan later confirmed 21). Tyler picked "table-structure-aware serialization" as WP-42's
direction; scoping it found the two items don't actually share a fix, so this WP takes `GARBLED_TABLE`
only — see Non-Goals.

**Re-scanning the corpus directly (`is_garbled_table_text()` against every current `*_chunks.jsonl`,
not just requirement records) found 21 chunks across 4 documents, not 5** (afi17-203: 5, afi10-2402: 7,
`DODI 5200.48`: 4, `DODI 8551.01`: 5) — Phase 40's §8 Backlog note said "5 documents"; that was an
off-by-one, corrected here.

**Tracing several examples back to the source PDFs found the 21 aren't one uniform problem:**

- **16 of 21** (afi10-2402: 7, `DODI 5200.48`: 4, `DODI 8551.01`: 5) match WP-39.1's original
  diagnosis exactly: `TableItem.export_to_dataframe()` returns clean, distinct, correct row data: the
  corruption is introduced entirely by `pipeline/chunk_text.py`'s serialization, which flattens the
  table into an unstructured `"Column = Value"` run-on paragraph. A structured-serialization fix
  cleanly resolves these.
- **5 of 21** (all in afi17-203, one table — `Table 3.2. Incident Handling and Support Activities` —
  spanning chunks 9/10/54/55/56) have an additional, worse defect that WP-39.1's own check script
  never caught: re-running Docling directly against the source PDF page shows **the table's caption
  sentence is merged into every header cell** by Docling's table-structure-recognition model itself —
  confirmed in both `export_to_dataframe()` and `export_to_markdown()` output, i.e. in Docling's own
  structured table model, not introduced by this project's serialization. WP-39.1's check script
  (`eval/audit_wp39_1/check_garbled_table_source.py`) concluded "not a Docling parsing failure" based
  on this exact table, but only verified that row *values* were distinct — it never inspected the
  header cells, which are what's actually corrupted. **This WP's fix does not clean this specific
  defect** (it's upstream of chunking, in Docling's table-structure model); it does substantially
  reduce its damage — see Scope.

**Root cause confirmed for the 16 (and the mechanism, not just the symptom, for the 5):**
`docling_core`'s `TableItem` has neither a `.text` attribute nor an `export_to_text()` method (checked
directly against the installed `docling_core==2.71.0`). `pipeline/chunk_text.py`'s `_chunk_raw_text()`
loops each chunk's body items trying `getattr(item, "text", "")` then `item.export_to_text()`; both
fail silently for a `TableItem`, so a table-only chunk falls all the way through to
`chunk.text` — Docling's own default `HybridChunker` table serializer, which renders each table cell as
a self-contained `"<row label>, <full table caption>..<column header> = <cell value>."` triplet, meant
to make each cell independently embeddable. Repeated once per cell across a real table, this produces
exactly the observed multi-hundred-word wall of repeated caption text (real example,
`afi17-203_chunks.jsonl` `chunk_id=55`, pre-fix: 2000+ characters, caption text repeated 8 times).

## 2. Goals

1. Serialize `TableItem`s as a clean, structured table (not a flattened run-on paragraph) in
   `pipeline/chunk_text.py`, fixing the dominant `GARBLED_TABLE` shape (16 of 21 known instances)
   at the root.
2. Re-ingest the 4 affected documents so the fix actually reaches the live corpus and index (fixing
   `chunk_text.py` alone doesn't retroactively fix already-extracted requirements — Step C runs from
   chunk text, so a real fix requires fresh Step A→D and a reindex).
3. Verify the fix with real evidence before and after reindexing live Qdrant, with a tested, cheap
   revert path if the new extraction turns out worse (Tyler's explicit condition for proceeding).

## 3. Non-Goals

- **No `STEM_NEVER_EXTRACTED` fix.** A different problem — Step C never extracting some verbatim chunk
  text at all — needs either a Step C prompt/schema change or raw-chunk-text stitching, neither of
  which this WP touches. Remains open in Phase 40's Backlog lineage for a future WP.
- **No fix for the afi17-203 header-caption-duplication defect itself.** That corruption lives in
  Docling's own table-structure-recognition model (confirmed via `export_to_dataframe()`/
  `export_to_markdown()` on a fresh parse, not in this project's code) — out of reach for a
  `chunk_text.py`-level fix. This WP reduces its blast radius (one clean table instead of a
  many-times-repeated wall of text) but does not claim to eliminate it; documented as a residual, not
  silently declared fixed.
- **No reranker, no definitional-content-retrievability decision.** Both still deferred — Phase 40's
  §8 Backlog.
- **No re-ingest of any document beyond the 4 confirmed `GARBLED_TABLE` documents.** The other ~40
  corpus documents are untouched by this WP.
- **No change to `is_garbled_table_text()`'s detection signature** — used as-is (already validated in
  WP-40) to measure before/after, not modified here.

---

## 4. Work Packages

### WP-42 — Table-Structure-Aware Serialization

**Source:** Tyler's direction, 2026-08-02, choosing among WP-40/41's 3 deferred backlog directions
(reranker / definitional-content decision / table serialization).

**Scope:**

- `pipeline/chunk_text.py`'s `_chunk_raw_text()`: when a body item is a `TableItem`, serialize it via
  `export_to_markdown(doc)` instead of falling through to `chunk.text`'s default triplet-style
  flatten. Falls back gracefully (same as any other item) if the export call itself raises. `doc`
  (the live `DoclingDocument`, already available in `run_structure_aware()`) is threaded through so
  Docling can resolve the table's caption as a heading line above the markdown grid, not just the
  grid itself.
- Re-ingest the 4 affected documents (`afi17-203.pdf`, `afi10-2402.pdf`, `DODI 5200.48.pdf`,
  `DODI 8551.01.pdf`) via `reqbot ingest --no-index` first — produces fresh, independently-timestamped
  JSONL artifacts without touching live Qdrant, so the comparison step below is fully reversible by
  construction (old run directories are untouched; `resolve_latest_requirement_files()` picks by file
  mtime, so simply not promoting/reindexing the new artifacts is itself a complete no-op revert).
- Compare old vs. new artifacts directly (JSONL-level, offline, before touching Qdrant): re-run
  `is_garbled_table_text()` against the new chunks, and spot-check extracted requirements for the
  affected tables.
- Only once satisfied: run `reqbot reindex` (full atomic rebuild from whatever
  `resolve_latest_requirement_files()` currently resolves — the documented, existing rebuild command,
  not a new mechanism) to bring the fix into the live index.
- Re-run retrieval eval (table-derived gold queries + full 45-query aggregate) post-reindex to confirm
  no regression.
- Enforce Tyler's verbatim-only `source_quote` principle: before reindexing, identify any new
  non-verbatim surviving records genuinely attributable to this fix (not pre-existing corpus-wide Step
  C variance) and quarantine them from the tier that `reindex` actually indexes
  (`eval/audit_wp42/quarantine_corrupted_header_table.py`).
- Correct any gold-set ids that no longer exist post-reingest, following WP-41's documented-correction
  discipline — including recording an honest zero-answer state where the quarantine removes the only
  candidate records for a query, rather than silently dropping the query or leaving a stale id.

**Revert plan (Tyler's explicit condition before approving the live re-ingest):**

1. `ingest --no-index` writes to a new timestamped run directory per document; it never modifies or
   deletes the prior run directory, and never touches Qdrant. Fully inert until reindexed.
2. `core/artifact_resolver.py`'s `resolve_latest_requirement_files()` picks the freshest tier purely by
   file `mtime` — if the new artifacts look worse at the JSONL-comparison step, simply don't reindex;
   the old (untouched, still on disk) run directory remains authoritative with zero further action.
3. If a problem is only discovered *after* reindexing: move the new run directory's JSONL aside (e.g.
   append `.superseded`) so `resolve_latest_requirement_files()` falls back to the old run directory,
   then run `reqbot reindex` again — this rebuilds Qdrant from the old data, since `reindex` always
   does a full atomic rebuild from whatever is currently "latest," not an incremental upsert.

**Tests/verification:**

- New unit tests (`tests/unit/test_chunk_raw_text.py`) for `_chunk_raw_text()`'s `TableItem` handling:
  markdown-grid output, no fallback to a triplet-style `chunk.text`, graceful failure handling, mixed
  table/text items, non-table items unaffected, `doc` threaded through correctly. Built against a
  real, minimally-constructed `docling_core.types.doc.TableItem` (not a bare mock), so
  `isinstance(item, TableItem)` inside the function under test is genuinely exercised.
- Live verification against the real source PDFs (page-range-limited Docling convert) confirming the
  fix eliminates the wall-of-repeated-caption-text shape on the known afi17-203 example.
- Full `pytest` suite and `ruff check .` clean.
- Live re-ingest + before/after comparison + reindex + retrieval eval, per Scope above.

**Gate:** Fix implemented and unit-tested; 4 affected documents re-ingested and compared against their
prior artifacts before any live index change; `is_garbled_table_text()` count materially reduced
(residual afi17-203 header-duplication documented, not hidden); live reindex only performed after
comparison is satisfactory; retrieval eval shows no regression; full test suite and `ruff check .`
clean; revert path documented and (if needed) exercised.

**Findings:**

**Serialization fix — 21 → 4 `GARBLED_TABLE` chunks (81% reduction), root cause confirmed for both
the fixed and residual cases.** Re-ingested all 4 documents, re-ran `is_garbled_table_text()`:
afi17-203 5→0, afi10-2402 7→2, `DODI 5200.48` 4→1, `DODI 8551.01` 5→1. The 4 residual chunks were
confirmed byte-identical to their pre-fix text (no regression) and traced to a different root cause
than the 17 fixed ones: Docling's table-structure model failed to recognize these specific regions as
a table at all (generic `DocItem` with `label="table"` but no `TableData` grid, not a `TableItem`),
so there is no structured export available to use — genuinely out of reach for this WP, not a gap in
the fix.

**Extraction quality — clear, large improvement for the 16 tables where Docling's structure
recognition worked cleanly.** Spot-check example: afi10-2402 chunk_id=111 (Table A2.1, AF Critical
Asset Identification Process) went from 3–10 low-quality fragments per re-run to 9 clean, verbatim,
correctly-grounded process-step records, e.g. `"Mission owners decompose assigned missions to
identify capabilities required to implement each mission."` — a direct, real quote now present
because the table's own row values were already correct (WP-39.1's original finding); only the
serialization was broken.

**A real complication, investigated and corrected in real time.** Initial spot-checking (sampling
only the fixed table chunks, not the full documents) found the fix's cleaner input occasionally
caused Step C to synthesize non-verbatim paraphrases, including one case — `"All DoD information
systems shall implement multi-factor authentication for all privileged user accounts."` — that
appeared identically across 3 unrelated chunks in different documents, matching
`pipeline/llm_extract_requirements.py`'s own Pass-1 few-shot example almost verbatim (Step C echoing
its prompt rather than extracting real content). **First framing of this to Tyler overstated it**:
comparing only the sampled table chunks against nothing made 12/50 new records in that sample look
non-verbatim. A full scan of all 4 documents' surviving records, old run vs. new run, found the
non-verbatim rate is **a pre-existing, corpus-wide Step C characteristic (5.4% in the old runs, 5.9%
in the new — within normal run-to-run LLM variance)**, already governed by the existing WP-32.1
grounding gate (`fuzz.partial_ratio >= 60`) and already present throughout the corpus long before
this WP. Diffing old vs. new precisely, **this fix is responsible for exactly 3 new non-verbatim
surviving records**, all from afi17-203's `Table 3.2` (`Incident Handling and Support Activities`,
chunk_id 54 ×2, 55 ×1) — the same table already flagged as having Docling's own header-caption-
duplication defect (Phase Framing above). A second table in the same document, `Table 1.1`
(`Categories of Events and Incidents`, chunks 9/10), produced worse hallucinations post-fix
(including the MFA/password few-shot echo) but **every one of them already scored below the existing
grounding threshold (42–50 vs. 60) and was rejected by the pipeline itself** — no manual action
needed there.

**Quarantine applied per Tyler's explicit principle (2026-08-02): "source quotes should be verbatim
source text… a paraphrase may be useful as a description, but not as source_quote."** Not a case-by-
case judgment call — `eval/audit_wp42/quarantine_corrupted_header_table.py` removes the 3 specific
non-verbatim `requirement_id`s from afi17-203's `*_requirements_gated.jsonl` (the tier
`resolve_latest_requirement_files()` actually resolves and `reindex` actually indexes) before the
live reindex. Verified live in Qdrant post-reindex: all 3 quarantined ids absent, a genuine clean
CAIP-table record present and correct.

**Net consequence of the quarantine, documented rather than hidden:** afi17-203's `Table 3.2` (chunks
54/55/56) and `Table 1.1` (chunks 9/10) now have **zero surviving verbatim records** between them —
both tables' real content is currently unretrievable via the requirements index. This is the accepted
cost of enforcing verbatim-only `source_quote`, not a bug to chase further in this WP. Reflected in
gold-set corrections below.

**Gold-set corrections** (`eval/gold_retrieval_queries.jsonl`): `Q-T01` and `Q-T03`'s old ids no
longer exist post-reingest (they were WP-39.1/WP-40's own pre-fix garbled-content examples).
**First attempt blanked `relevant_requirement_ids` to `[]` — Codex review, PR #189 (P1), caught that
this was wrong**: `retrieval_eval_harness.py`'s `compute_metrics()` returns no `recall@k`/`mrr` keys
for empty ground truth, and since these queries' `shape` is `table_derived` (not `zero`), they're
counted in `non_zero_query_count` but contribute nothing to the mean — silently vanishing from every
aggregate instead of registering as the real misses they are, while `"Queries scored: 37"` implied
otherwise. Fixed by restoring the original (still-nonexistent) ids and adding `expected_quotes`,
matching the existing `Q-N04`/`Q-C04`/`Q-C06` convention exactly — this correction should have
followed that precedent the first time. `Q-T02`'s old ids were replaced with 3 of the 9 new clean
CAIP records.

**A second, more serious bug found by the same Codex review round: `_chunk_raw_text()`'s
`export_to_markdown()` call ignored chunk boundaries entirely.** Verified directly: `HybridChunker`
splits every oversized table across multiple chunks that all reference the *same* `TableItem` object
(checked all 4 documents by re-parsing and tracking `TableItem.self_ref` across chunks — every table
in every document is split this way; afi10-2402's largest spans 11 chunks). The first fix called
`export_to_markdown()` unconditionally per chunk, re-exporting the *entire* table on each one — live
Qdrant confirmed exact byte-identical duplicate chunk text (afi10-2402 chunk_ids 111/112/113, all
4739 chars) and Step C's raw output showed the same 9 quotes extracted 3 times (27 raw records,
collapsing to 9 only via `compute_stable_id()` producing the same id for identical content — so the
live index itself wasn't left with duplicate garbage, but Step C's LLM cost was being multiplied by
however many chunks a table spanned, up to 11x for the largest table, with a latent correctness risk
too: nothing guaranteed N non-deterministic extraction calls over identical input would agree).
Confirmed this was a genuine regression from this fix, not pre-existing: the old `chunk.text`
fallback was already correctly chunk-bounded (old afi10-2402 chunks 111/112/113 were 1005/973/469
chars — all different), since it never had cross-chunk table logic to break.

Fixed by threading a `seen_table_refs` set through the whole per-document chunking loop
(`pipeline/chunk_text.py`'s `run_structure_aware()`): a table's full markdown is emitted exactly once,
on the first chunk referencing it; later chunks referencing the same table contribute nothing and
correctly end up empty (dropped by the existing empty-chunk filter, not resurrected via the old
garbled `chunk.text` fallback). 4 new unit tests. Re-ingested and reindexed all 4 documents a second
time; re-ran the `is_garbled_table_text()` scan (still 4/21 residual, same known cases, confirming the
core fix is unaffected) and the full non-verbatim scan (37/672 = 5.5% — consistent with the
already-established ~5% baseline). The corrupted-header table (`Table 3.2`) now appears in exactly one
chunk (was 3 duplicates) and still produces 2 non-verbatim records from the same known defect (was 3
before dedup — normal LLM-call variance, same underlying cause) — quarantined again with updated ids,
verified absent from live Qdrant post-reindex.

**One more real finding while re-verifying `Q-T02` post-correction: it still scores 0 recall@20, but
this is a pre-existing, already-tracked `ranking_miss`, not something this WP caused or should fix.**
Checked directly with `core.ask.retrieve(top_k=100, min_score=0)`: the correct records are present,
correctly grounded, and verbatim — just ranked 33rd, 51st, 69th, and 87th of 100, well outside
production's `top_k=20`. This is WP-40's own dominant, already-deferred-to-the-reranker finding
surfacing again on a query this WP's fix made *possible* to answer correctly for the first time
(before the fix, chunk 111 had almost nothing worth ranking) — real, but explicitly out of scope here
(Non-Goals: no reranker work in this WP).

**A third Codex review round found two more real issues in the dedup fix itself, both fixed without
requiring another re-ingest.** (1) `seen_table_refs` was being marked *before* attempting the table's
export, not after — if a table's export genuinely failed both ways, every later chunk referencing that
same table would be wrongly suppressed as a "duplicate" even though nothing had actually been emitted,
silently discarding their own `chunk.text` fallback. Fixed by only marking a table "seen" on a
successful, non-empty export. (2) A table's full markdown is now emitted in a single chunk rather than
bounded by `HybridChunker`'s own token-based splitting — raising a real question of whether an
oversized table could overflow Step C's context window. Investigated empirically rather than assumed:
`curl .../api/ps` confirmed Ollama is currently running the model at `context_length=8192` as its own
server default (nothing in this codebase had ever set it explicitly). Reproduced the actual Step C
prompt for the corpus's largest known table (afi10-2402 chunk 119, 10746 chars) and confirmed an
explicit `num_ctx=8192` produces byte-identical output to the unset default — ruling out context
truncation for that specific case. (Its own extraction output — the same instructional template
sentence repeated 3 times — turned out to be a separate, pre-existing LLM repetition-loop issue on a
mostly-blank instructional table, unrelated to size.) Current largest table uses ~43% of that budget.
Not a live risk today, but pinning `num_ctx=8192` explicitly (`pipeline/llm_extract_requirements.py`)
rather than depending on whatever the Ollama server happens to default to, plus a size-guard warning
log for any future table approaching the budget, is a proportionate response — building full
token-bounded table rechunking isn't justified by current evidence. Neither fix changes output for the
already-reindexed corpus (verified: the seen-after-success fix only fires on export failure, which
didn't occur for any of the 4 documents' tables; `num_ctx=8192` matches the already-active server
default) — confirmed no third re-ingest was needed.

**Final full-corpus retrieval eval** (not a clean pre/post-WP-42 baseline — the gold set and the
underlying documents both changed mid-WP across two fix rounds):
`eval/spike_results/wp_42_table_fix_eval/report.md`. With the corrected gold labels (`Q-T01`/`Q-T03`
scored as real 0.0 misses, not silently excluded) against the final, deduplicated, quarantined corpus:
mean recall@5 0.638, recall@10 0.672, recall@20 0.714, MRR 0.762, across 37 honestly-scored queries,
8/8 zero-truth queries still returning results (unchanged — zero-truth calibration is WP-41's
already-closed, conclusive-negative finding, not reopened here). No other bucket regressed.

---

## 5. Success Gate

- [x] `TableItem`s serialized via structured markdown instead of falling through to `chunk.text`'s
      triplet-style flatten; unit-tested against a real `TableItem`, not a bare mock.
- [x] A table split by `HybridChunker` across multiple chunks (confirmed: every table in all 4
      documents) is emitted exactly once, not re-exported in full on every chunk that references it
      (Codex review, PR #189, P1 — a real regression from the first version of this fix, verified live
      via byte-identical duplicate chunk text before the correction).
- [x] 4 affected documents re-ingested twice (`--no-index`) — once for the core fix, once more after
      the duplication fix — and compared against prior artifacts before any live index change each
      time.
- [x] `is_garbled_table_text()` re-scan shows a material reduction in flagged chunks (21→4, 81%),
      stable across both re-ingests; residual cases documented (Docling structure-recognition failure,
      not a serialization gap).
- [x] Non-verbatim `source_quote` risk investigated corpus-wide (not just the sampled table chunks),
      correcting an initial overstated claim; the records genuinely attributable to this fix
      quarantined per Tyler's explicit verbatim-only principle before each reindex; verified absent
      from live Qdrant post-reindex both times.
- [x] Live `reqbot reindex` performed only after each comparison was satisfactory (twice).
- [x] Retrieval eval (table-derived + full aggregate) shows no regression post-reindex; the one
      remaining `Q-T02` shortfall identified as a pre-existing, already-tracked `ranking_miss`
      (content present, correctly grounded, ranked outside top-20), not caused by this WP.
- [x] Gold-set corrections documented and self-corrected: `Q-T01`/`Q-T03`'s stale ids kept (not
      blanked to `[]`) with `expected_quotes`, so the harness scores them as real misses instead of
      silently excluding them from every aggregate (Codex review, PR #189, P1); `Q-T02` → corrected
      ids.
- [x] Revert path documented; not needed (no step required reverting).
- [x] `seen_table_refs` only marks a table after a successful export, not before — a table whose
      export genuinely fails no longer wrongly suppresses later chunks' own fallback content (Codex
      review, PR #189, third round).
- [x] Context-window risk for single-chunk table markdown investigated empirically (not assumed): live
      Ollama server confirmed at `context_length=8192`; the corpus's largest table uses ~43% of that
      budget; `num_ctx` now pinned explicitly; a size-guard warning log added for future oversized
      tables (Codex review, PR #189, third round).
- [x] Full `pytest` suite and `ruff check .` clean throughout (871 tests after three fix rounds).

---

## 6. Guardrails

- The fix is scoped to `TableItem` serialization only — no change to non-table chunking/breadcrumb/
  skip-section logic.
- No claim of a complete fix for the afi17-203 header-duplication defect — that's a Docling-side table-
  structure-recognition artifact, out of reach for a `chunk_text.py` change; documented as a residual.
- The live re-ingest only touches the 4 confirmed `GARBLED_TABLE` documents — no broader corpus
  re-ingest is implied or attempted.
- Every step that touches live Qdrant is preceded by an offline, reversible comparison step, per
  Tyler's explicit condition for approving this WP's live-infrastructure work.
