# ReqBot Phase 14 - Structure-Aware Chunking and Hierarchy Preservation

**Requirements Document - March 2026 - Codex revision draft**

---

## 1. Executive Summary

Phase 14 addresses an upstream representation defect in the ReqBot pipeline: hierarchical source documents are being flattened into chunk text that loses governing structure before extraction begins. This is not primarily a prompt-quality or model-quality problem. It is a preprocessing and schema problem.

The goals of this phase are:

1. Stop splitting text at semantically wrong boundaries.
2. Preserve deterministic section hierarchy from Step A through Step E.
3. Carry enough parent context forward that extracted requirements remain meaningful at retrieval time.

This phase is intentionally narrower than the earlier critical-issues writeup. It does **not** introduce retrieval-time family expansion, adaptive map-reduce, or model fine-tuning. Those are follow-on decisions after the structural fixes land and are measured.

---

## 2. Relationship to Phase 13

Phase 13 remains the extraction-evaluation and fine-tuning phase.

Current relationship:

- Phase 13 WP-1: shipped
- Phase 13 WP-2: shipped
- Phase 13 WP-3: paused
- Phase 13 WP-4/WP-5: blocked

Phase 14 exists to repair the input representation so that Phase 13 WP-3 can resume on regenerated artifacts. Do not collapse Phase 14 back into Phase 13. The phase boundary is useful because the premise changed: the current baseline is not only measuring extraction quality, it is also measuring chunking damage.

---

## 3. Problem Statement

### 3.1 Core Defects

The current pipeline has three coupled structural problems:

1. **Hierarchy loss.**
   Child sub-paragraphs are extracted without enough parent context to preserve their governing meaning.

2. **Mid-paragraph chunk splits.**
   The current chunker is character-window based and can separate a governing clause from its subordinate bullets, exceptions, or conditions.

3. **Semantically isolated quotes.**
   Step F currently embeds `source_quote`, which is better than embedding `description`, but orphaned child quotes still lack the parent terms needed for strong retrieval.

### 3.2 Operational Consequences

These defects produce:

- syntactically valid but semantically incomplete requirements
- false negatives during retrieval because key governing terms are absent
- misleading parent-only retrieval when child exceptions are structurally detached
- gold-set review effort spent diagnosing broken inputs instead of only grading Step C

### 3.3 What This Phase Does Not Do

This phase does not include:

- retrieval-time family expansion in `ask` or `evidence`
- map-reduce or context compaction logic
- model fine-tuning
- broad eval-set curation restart

Those are deferred until Phase 14 artifacts exist and are measured.

---

## 4. Design Principles

Phase 14 implementation should follow these rules:

1. **Deterministic structure beats LLM inference.**
   Header parsing, ancestry, and parent-child linkage should come from deterministic preprocessing, not from asking the model to infer structure.

2. **Canonical IDs and display text must be separated.**
   The parser should produce canonical structural identifiers for joins and derivations, and separate human-readable header text for display and prompts.

3. **Raw source text must remain recoverable.**
   Do not lose the original chunk body by mixing breadcrumbs into the only text field.

4. **Graceful degradation is better than silent corruption.**
   If structure cannot be parsed for a region, emit empty hierarchy metadata and preserve raw text rather than inventing a wrong breadcrumb.

---

## 5. Pre-Implementation Decisions

These decisions should be locked before WP-14.1 or WP-14.2 code is written.

### 5.1 Decision A - Layout Mode Strategy

**RESOLVED — MOOT 2026-04-04**

Docling replaces `extract_pdf_to_text.py` as the primary parsing backend for structure-aware chunking. The pymupdf vs pdfplumber comparison is no longer required. Docling handles layout detection internally across all document classes.

### 5.2 Decision B - Paragraph Boundary Rule

**RESOLVED — MOOT 2026-04-04**

Docling `HybridChunker` handles paragraph boundary detection internally. The blank-line vs layout-gap decision is no longer required. Custom boundary logic was the fallback plan; it is not needed under Outcome B.

### 5.3 Decision C - Parent Context Scope

**STILL REQUIRED before WP-14.1/14.2 implementation begins.**

Lock the definition of parent context before implementation. It should not drift package by package.

Recommended default:

- `parent_context` = the full immediate parent clause text when available, not just the numeric header

If the parent clause body cannot be isolated cleanly, fall back to the immediate parent header text and log the degradation.

---

## 6. Work Packages

### 6.1 WP-14.1: Docling Integration + Ancestry Traversal

**Goal:** replace `extract_pdf_to_text.py` + regex section parser with Docling as the primary structural parsing backend, and build a deterministic ancestry map from the Docling document model.

**Implementation approach:** Outcome B (hybrid) confirmed by Docling spike 2026-04-04.

**Primary output:** a structured section ancestry map per document, consumable by WP-14.2.

#### Requirements

1. Use `docling.document_converter.DocumentConverter` to parse each PDF. Replace the current Step A text extraction for the structure-aware path.

2. Traverse `doc.body` (the Docling document model) to build full heading ancestry per item. Do NOT rely solely on `chunk.meta.headings` — the HybridChunker provides only the immediate heading per chunk, not the full path from document root.

3. Emit two distinct ancestry fields per structural section:
   - `section_ref_path`: canonical structural identifiers used for joins and derivations. Derive from numbered heading prefixes (e.g. `1.1.` → `"1.1"`). For prose-titled sections without a numbering prefix, derive a slug or leave empty and log.
   - `section_title_path`: human-readable section titles or full header labels for display.

4. Handle noise:
   - Table of Contents pages: filter chunks where >40% of lines are dotted-line or bare page-number entries.
   - Page headers/footers: rely on Docling's layout detection to exclude running headers.
   - Appendices, enclosures, glossaries: treat as structural resets; log section boundary.

5. Fail cleanly:
   - if ancestry traversal fails for a region, emit empty `section_ref_path` and `section_title_path`
   - preserve raw text
   - do not emit a partial breadcrumb — partial is silent corruption

6. Produce an inspectable ancestry artifact before WP-14.2 consumes it.

#### Validation Gate

Run on one representative document per major class and confirm:

- heading hierarchy depth matches expected document structure
- numbered sections produce non-empty `section_ref_path`
- ToC chunks are filtered before sampling
- failure mode emits empty ancestry rather than a wrong breadcrumb

---

### 6.2 WP-14.2: Docling-Based Structure-Aware Chunker

**Goal:** replace the fixed-size chunker (`chunk_text.py`) with Docling `HybridChunker` as the chunking backend, augmented with ToC filtering and breadcrumb injection from the WP-14.1 ancestry map.

**Primary output:** improved `*_chunks.jsonl`.

#### Requirements

1. Use `docling.chunking.HybridChunker` as the primary chunking backend. It respects paragraph boundaries and keeps tables intact.

2. Apply the ToC chunk filter from WP-14.1 before emitting chunks. ToC chunks must not enter `*_chunks.jsonl`.

3. Each chunk record must preserve raw source body separately from prompt-visible breadcrumb context:

   - `raw_text`: original chunk body used for source verification
   - `breadcrumb`: formatted hierarchy context block derived from WP-14.1 ancestry traversal
   - `text`: full prompt-facing text passed to Step C, composed as `breadcrumb + raw_text`

4. Each chunk must carry:
   - `section_ref_path`
   - `section_title_path`
   - `parent_header_text`
   - `parent_context` (per Decision C definition — lock before implementation)

5. Tables must not be split mid-table. Docling HybridChunker handles this; verify it holds in practice.

6. Overlap: re-evaluate after paragraph-aware chunking lands. Do not carry over the current fixed-size overlap behavior without validating it is still useful.

#### Validation Gate

For representative documents:

- zero mid-paragraph splits
- breadcrumb present where ancestry traversal succeeded
- raw body remains recoverable from `raw_text`
- ToC chunks absent from output JSONL
- chunk-count inflation documented and explained

---

### 6.3 WP-14.3: Schema and Pipeline Propagation

**Goal:** propagate deterministic hierarchy metadata through extraction, normalization, enrichment, and export.

#### Requirements

1. Step C receives structure metadata as pass-through context. It does not infer hierarchy.

2. Step D adds to normalized records:
   - `section_ref_path`
   - `section_title_path`
   - `parent_section_ref`
   - `parent_context`

3. Parent/child linkage must be based on deterministic parser output, not LLM-extracted `source_ref`.

4. Store canonical child linkage using deterministic IDs, for example:
   - `child_section_refs`

Optional display-oriented fields may also exist, but canonical linkage must remain deterministic.

5. If enrichment runs, it may use `parent_context` in the prompt, but hierarchy metadata passes through unchanged.

6. Bump schema version to `2.0` and keep backward-compatible loading behavior for `1.0`.

#### Validation Gate

Verify on representative documents:

- normalized artifacts carry hierarchy fields end to end
- parent/child links are internally consistent
- mixed schema loading does not break reindexing or export

---

### 6.4 WP-14.4: Corpus Regeneration

**Goal:** rebuild artifacts on the improved structural foundation.

#### Requirements

1. Record baseline artifact directories before regeneration.

2. Re-run ingestion on the full corpus using the same extraction and enrichment models as the current baseline.

3. Rebuild indexes from the regenerated artifacts.

4. Compare old vs new:
   - requirement counts
   - parse failure rates
   - hierarchy coverage
   - representative retrieval outcomes

5. Preserve a small diagnostic subset from the paused Phase 13 CSV to use as before/after evidence.

#### Validation Gate

Proceed only if:

- regeneration completes cleanly
- hierarchy coverage is meaningful
- requirement count does not collapse unexpectedly
- representative retrieval looks better on known weak cases

---

## 7. Schema Changes

### 7.1 Step B chunk schema

Recommended new fields:

| Field | Type | Purpose |
|---|---|---|
| `raw_text` | `string` | Original chunk body without breadcrumb injection |
| `text` | `string` | Prompt-facing chunk text used by Step C |
| `breadcrumb` | `string` | Formatted hierarchy context block |
| `section_ref_path` | `string[]` | Canonical structural identifiers |
| `section_title_path` | `string[]` | Human-readable section labels |
| `parent_header_text` | `string \| null` | Immediate parent header label |
| `parent_context` | `string \| null` | Immediate parent clause text when available |

### 7.2 Step D / D.5 requirement schema

Recommended new fields:

| Field | Type | Purpose |
|---|---|---|
| `section_ref_path` | `string[]` | Canonical ancestry for joins |
| `section_title_path` | `string[]` | Human-readable ancestry |
| `parent_section_ref` | `string \| null` | Canonical immediate parent identifier |
| `parent_context` | `string \| null` | Governing parent clause text |
| `child_section_refs` | `string[]` | Canonical immediate child identifiers |

`source_ref` remains useful for user-facing output, but it should not be the canonical join key for structural derivation.

---

## 8. Validation Strategy

### 8.1 Diagnostic Subset

Do not discard the paused Phase 13 review work.

Preserve `25-50` rows covering:

- hierarchy loss
- chunk-boundary truncation
- glossary/definition false positives
- quote-not-in-chunk misalignment

Use these as regression evidence after Phase 14 lands.

### 8.2 Resume Rule for Phase 13

Phase 13 WP-3 should resume only after:

1. Phase 14 artifacts exist
2. hierarchy coverage is demonstrated
3. representative weak retrieval cases improve
4. reseeded eval inputs are generated from the new artifacts

Do not resume broad gold-set curation before that point.

---

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Regex parser is brittle on DODI edge cases | Medium | Target 80 percent coverage first; log and iterate |
| Breadcrumb text pollutes verbatim extraction | High | Preserve `raw_text` separately and keep prompt instructions explicit |
| Parent context is defined too vaguely | High | Lock the definition before implementation |
| Overlap duplicates content unnecessarily after paragraph-aware chunking | Medium | Re-evaluate overlap after validation rather than preserving blindly |
| Schema fields mix canonical IDs and display labels | High | Separate deterministic refs from human-readable titles |

---

## 10. Recommended Sequence

1. Lock Decisions A-C.
2. Build WP-14.1 parser artifact.
3. Build WP-14.2 chunker with raw-text preservation.
4. Propagate hierarchy through WP-14.3.
5. Regenerate artifacts in WP-14.4.
6. Resume Phase 13 WP-3 on regenerated inputs.

---

## 11. Summary Judgment

Phase 14 is the right next phase.

The key implementation caution is this:

- preserve deterministic structure
- preserve raw source text
- do not let breadcrumb injection blur the distinction between source evidence and added context

If that boundary is kept clean, Phase 14 should give Phase 13 a much better foundation.
