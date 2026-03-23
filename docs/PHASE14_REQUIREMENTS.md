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

Decide whether the pipeline should:

- standardize on `pdfplumber` for all document classes, or
- keep a per-class extraction split and normalize both outputs into a common structure layer

Required check:

- compare `pymupdf` vs `pdfplumber` output on a high-risk multi-column NIST document such as `NIST.SP.800-53r5.pdf`
- confirm whether `pdfplumber` output is coherent enough to be a universal default

### 5.2 Decision B - Paragraph Boundary Rule

Choose one primary paragraph-boundary strategy:

- blank-line based
- layout-gap based
- hybrid

This decision must be explicit because the chunker behavior depends on it.

### 5.3 Decision C - Parent Context Scope

Lock the definition of parent context before implementation. It should not drift package by package.

Recommended default:

- `parent_context` = the full immediate parent clause text when available, not just the numeric header

If the parent clause body cannot be isolated cleanly, fall back to the immediate parent header text and log the degradation.

---

## 6. Work Packages

### 6.1 WP-14.1: Section Parser

**Goal:** deterministically parse structural hierarchy from Step A page text.

**Primary output:** a structured section map for each document.

#### Requirements

1. Parse document-class-specific section patterns for:
   - NIST SP
   - AFI/DAFI/DAFPAM/DAFMAN
   - DODI/DoDM

2. Maintain a header stack while scanning text.

3. Emit two distinct ancestry fields:
   - `section_ref_path`: canonical structural identifiers used for joins and derivations
   - `section_title_path`: human-readable section titles or full header labels for display

4. Handle resets such as:
   - appendices
   - enclosures
   - glossary/definition sections
   - page headers/footers
   - table of contents pages

5. Fail cleanly:
   - if parsing fails, emit empty ancestry fields
   - preserve raw text
   - log the unparseable pattern with document and page context

6. Produce an inspectable artifact before the chunker consumes it.

#### Validation Gate

Run the parser on one representative document per major class and confirm:

- hierarchy is correct for at least 80 percent of tested sections
- reset events do not corrupt later stack state
- failure mode emits empty ancestry rather than a wrong breadcrumb

---

### 6.2 WP-14.2: Structure-Aware Chunker

**Goal:** replace the fixed-size chunker with paragraph-aware chunking that preserves structure metadata.

**Primary output:** improved `*_chunks.jsonl`.

#### Requirements

1. Paragraphs are the atomic unit. Never split mid-paragraph.

2. Character budget is a maximum, not a target.

3. Each chunk record must preserve raw source body separately from prompt-visible breadcrumb context.

Recommended schema split:

- `raw_text`: original chunk body used for source verification
- `breadcrumb`: formatted hierarchy context block
- `text`: full prompt-facing text passed to Step C, composed as `breadcrumb + raw_text`

If the current schema requires `text` to remain the main field, `raw_text` must still be added explicitly so verbatim review can anchor against unmodified body text.

4. Each chunk must carry:
   - `section_ref_path`
   - `section_title_path`
   - `parent_header_text`
   - `parent_context`

5. Table-aware chunking must continue to work. Tables must not be split mid-table.

6. Overlap should remain configurable, but its semantics must be re-evaluated after paragraph-aware chunking lands. Do not assume the current overlap behavior is still desirable.

#### Validation Gate

For representative documents:

- zero mid-paragraph splits
- breadcrumb/context present where parser succeeded
- raw body remains recoverable
- chunk-count inflation is explained if material

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
