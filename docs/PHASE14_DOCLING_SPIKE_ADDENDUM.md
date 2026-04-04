# ReqBot Phase 14 - Docling Evaluation Addendum

**Status:** Proposed pre-implementation addendum to Phase 14  
**Purpose:** Decide whether Docling should replace the planned custom Step A / Step B structural parsing work before WP-14.1 begins

---

## 1. Plain-English Summary

This addendum does **not** replace Phase 14.

It adds a short, time-boxed test before Phase 14 implementation starts.

That test is called a **spike**.

In plain terms, a spike means:

- create a small experimental branch
- try one idea quickly
- measure whether it is actually better
- then decide whether to adopt it or discard it

For ReqBot, the idea is:

**Before we build our own regex-based section parser and structure-aware chunker, test whether Docling already solves enough of that problem to justify using it as the primary backend.**

---

## 2. What Stays the Same

The core goals of Phase 14 do not change:

1. Preserve section hierarchy.
2. Stop splitting text at semantically wrong boundaries.
3. Carry enough parent context forward that extracted requirements remain meaningful.
4. Keep canonical structure deterministic.
5. Preserve raw source text separately from added context.

This means:

- Phase 14 remains the right next phase.
- Phase 13 WP-3 remains paused.
- Fine-tuning remains blocked.

The only question is **implementation approach**, not direction.

---

## 3. What the Docling Spike Is Evaluating

The spike is evaluating whether Docling can replace most or all of the planned work in:

- WP-14.1: custom section parser
- WP-14.2: custom structure-aware chunker

The spike is **not** evaluating:

- retrieval-time family expansion
- map-reduce context assembly
- fine-tuning
- major changes to Step C logic

---

## 4. Recommended Branch

Recommended experimental branch name:

`phase14-docling-spike`

This is not a production branch. It is an evaluation branch.

Its job is to answer:

**Should ReqBot adopt Docling as the primary structural parsing backend for Phase 14?**

---

## 5. Spike Scope

The spike should be limited to one representative document per class:

1. **NIST SP**
   - Example: `NIST.SP.800-53r5.pdf`

2. **AFI / DAF**
   - One document with numbered paragraph hierarchy

3. **DODI / DoDM**
   - One table-heavy or enclosure-heavy document

For each document, the spike should:

1. Run Docling and inspect raw structural output.
2. Inspect Docling heading hierarchy.
3. Inspect table extraction behavior.
4. Inspect Docling chunk output using its chunker.
5. Compare the result against the current Step A + Step B output.

The spike should also test whether ReqBot can map Docling output into the Phase 14 schema shape.

For at least one document, identify a specific parent-child clause hierarchy (parent governing clause with subordinate sub-paragraphs). Verify that Docling's structural output and chunking preserve enough information to reconstruct the parent-child relationship — either by keeping them in the same chunk or by providing heading ancestry metadata that links them.

---

## 6. Required Deliverables

The spike should produce:

1. A short evaluation report in Markdown.
2. Example outputs for the three representative documents.
3. A judgment for each document class:
   - pass
   - partial pass
   - fail
4. A recommendation:
   - adopt Docling
   - adopt Docling + deterministic post-processing
   - reject Docling and proceed with the current regex plan

Optional but strongly recommended:

5. A thin prototype bridge script that maps Docling output into a ReqBot-like intermediate structure for inspection.

---

## 7. Success Criteria

Docling should only be adopted if the spike shows **material improvement** over the current planned custom path.

The spike should evaluate these criteria:

### 7.1 Structure Quality

- Headings are detected correctly across all three document classes.
- Section nesting is materially better than the current raw text approach.
- Page headers, footers, and table-of-contents noise do not dominate the hierarchy.

### 7.2 Chunk Quality

- Chunks align to real structural boundaries.
- Mid-paragraph splits are eliminated or clearly improved.
- Tables remain intact as coherent structural units.

### 7.3 Parent Context Preservation

- Docling output provides enough information to derive:
  - `section_ref_path`
  - `section_title_path`
  - `parent_context`
  - `raw_text`
  - `text`

### 7.4 Bridge Complexity

- Mapping Docling output into ReqBot artifacts is still cheaper than building and maintaining the custom regex parser + chunker stack.
- Canonical section ID derivation remains tractable after Docling extraction.

### 7.5 Operational Fit

- Runtime is acceptable for corpus regeneration.
- Dependency burden is acceptable for the local/offline ReqBot environment.

---

## 8. Explicit Failure Conditions

Docling should **not** be adopted as the primary backend if any of these are true:

1. It performs well on pretty layout structure but still leaves canonical section reference derivation almost as hard as the current regex plan.
2. It fails materially on DoD document structure, especially tables, enclosures, or mixed numbering.
3. It produces hierarchy that looks clean visually but cannot be mapped reliably into deterministic ReqBot schema fields.
4. The bridge code and post-processing burden are large enough that the custom parser/chunker path is no longer clearly more expensive.

---

## 9. Decision Outcomes

### Outcome A - Adopt Docling

Use Docling as the primary backend for Step A / Step B structural parsing.

Implications:

- WP-14.1 becomes Docling integration + deterministic section ID derivation
- WP-14.2 becomes Docling chunk mapping + raw text / breadcrumb handling
- Phase 14 goals remain unchanged

### Outcome B - Hybrid Approach

Use Docling for layout and chunk structure, then add deterministic post-processing for:

- canonical section IDs
- parent context shaping
- schema normalization

This is probably the most realistic “good” outcome if Docling performs well but not perfectly.

### Outcome C - Reject Docling

Proceed with the current Phase 14 plan:

- custom regex section parser
- custom structure-aware chunker

If this happens, the spike still has value because it reduced uncertainty before implementation.

---

## 10. Phase 14 Requirements Impact

If the spike is approved, the current Phase 14 plan should be interpreted as follows:

1. **WP-14.1 and WP-14.2 implementation are paused pending spike results.**
2. **WP-14.3 and WP-14.4 remain valid regardless of outcome.**
3. **Decision A and Decision B from Phase 14 may become moot if Docling is adopted.**
4. **Decision C remains relevant either way.**

This means the next practical step is not “start coding the regex parser.”

The next step is:

**run the Docling spike first, then choose the implementation path.**

---

## 11. Recommended Instruction to Claude Code

Use this as the operating instruction:

1. Do not begin full WP-14.1 or WP-14.2 implementation yet.
2. Create a small evaluation branch for a Docling spike.
3. Time-box it to a short experiment.
4. Test one representative document per class.
5. Compare Docling output against current Step A / Step B artifacts.
6. Produce a decision memo with:
   - what worked
   - what failed
   - what bridge code is still needed
   - whether Docling should replace, augment, or be rejected relative to the current plan

---

## 12. Final Recommendation

The right move is:

- keep Phase 14
- do not rewrite its goals
- insert a Docling spike before WP-14.1 starts
- decide from evidence, not optimism

This is a good candidate for evaluation, but it is not yet proven enough to become the new plan by default.
