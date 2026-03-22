# ReqBot Phase 13 — Extraction Model Optimization

**Requirements Document — March 2026**

> **Current Phase.** Plan document authored by Tyler + Codex + Claude (March 2026).
> See CLAUDE.md for current WP status.

## Current Status

| Work Package | Status | Notes |
|---|---|---|
| WP-1: Structured Output Decoding | NOT STARTED | `format: "json"` + few-shot examples in Step C |
| WP-2: Model Configuration Split | NOT STARTED | `extraction_model` / `enrichment_model` in config; parallel with WP-1 |
| WP-3: Gold Evaluation Set | NOT STARTED | Prerequisite: WP-1 complete (eval baseline must reflect structured output) |
| WP-4: Training Data Curation | NOT STARTED | Only if WP-3 gate says precision/recall gap remains |
| WP-5: Fine-Tuning and Integration | NOT STARTED | Only if WP-4 gate passed |

**Rule:** WP-1 and WP-2 may run in parallel. All others are sequential with gates.
**Corpus re-ingest:** Deferred. Do not reindex corpus until WP-1 is complete and accepted.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Assessment](#2-current-state-assessment)
3. [Work Packages](#3-work-packages)
4. [Implementation Sequence](#4-implementation-sequence)
5. [Decision Tree](#5-decision-tree)
6. [Hardware and Tooling Requirements](#6-hardware-and-tooling-requirements)
7. [Risks and Mitigations](#7-risks-and-mitigations)
8. [Source Attribution](#8-source-attribution)
9. [Glossary](#9-glossary)

---

## 1. Executive Summary

Phase 13 addresses the reliability and precision of Step C (LLM requirement extraction), which is the highest-value and least-constrained stage of the ReqBot pipeline. A code review of the current pipeline confirmed that Step C is not using Ollama's structured output capabilities, despite the query layer (ask.py) already doing so. This is the single largest untapped reliability lever in the codebase.

This phase is sequenced as a decision tree, not a linear march. Each work package has a validation gate that determines whether the next package is necessary. The terminal goal — fine-tuning a custom extraction model — is only reached if cheaper interventions fail to close the quality gap.

**Decision logic:** Constrain output format → measure → build eval set → measure → fine-tune only if a ceiling remains.

---

## 2. Current State Assessment

The following findings are based on a full codebase review (Codex, March 2026) of the Phase 12.2 branch.

### 2.1 What Works

- Step C's parse failure recovery (bracket salvage, truncated-array repair) is operationally solid.
- Raw responses are always persisted to `*_raw_responses.jsonl` — full auditability.
- Step D normalization catches some semantic issues (bad tags, missing source_quote, dedup).
- `ask.py` already uses Ollama `format="json"` for query rewriting — proving the pattern works in this codebase.

### 2.2 What Doesn't

- Step C calls `/api/generate` with no `format` field — output is free-text that must be repaired after the fact.
- No few-shot input/output demonstrations in the extraction prompt — only prose GOOD/BAD descriptions.
- `run_pipeline.py` uses a single `model` argument for both Step C extraction and Step D.5 enrichment — no way to swap one without changing the other.
- No human-verified gold dataset exists — the 32k requirements are all pipeline-generated labels.
- Table-heavy DoD documents remain the hardest class (evidenced by pdfplumber reruns in INDEXED_DOCUMENTS.md).

### 2.3 Failure Modes Still Present

- Valid JSON with wrong semantics (syntactically correct but factually wrong extractions).
- Missed requirements in structurally complex chunks.
- Bad `source_ref` extraction in messy DoD layouts.
- Over-extraction and under-extraction at the chunk level.
- Noisy labels that survive because they are syntactically valid JSON.

---

## 3. Work Packages

Phase 13 is organized as five work packages (WP). Each has a validation gate. Packages are sequential — do not start WP-N+1 until WP-N's gate is evaluated. The sequence is designed so you can stop at any gate where the measured improvement is sufficient.

---

### 3.1 WP-1: Structured Output Decoding

**Goal:** Eliminate parse failures caused by free-text LLM output by enabling Ollama's native JSON constraint.

**Affected component:** `llm_extract_requirements.py` (Step C)

**Estimated effort:** 2–4 hours

#### Requirements

1. **R-1.1:** Add `format: "json"` to the Ollama `/api/generate` call in Step C. Validate that the model produces parseable JSON on first attempt without bracket salvage.

2. **R-1.2:** Evaluate whether a full JSON schema (Ollama structured outputs) is feasible for the Pass 1 extraction target. If the schema is too rigid for variable-length requirement arrays, fall back to `format: "json"` without a schema.

3. **R-1.3:** Add 2–3 few-shot input/output examples to the Step C system prompt. Examples should include: (a) a prose-heavy NIST chunk, (b) a table-heavy DODI chunk, and (c) a chunk with no extractable requirements (expected output: empty array).

4. **R-1.4:** Retain the existing bracket salvage and truncated-array recovery logic as a fallback — do not remove it. Log when fallback is triggered so degradation is visible.

**Validation gate:** Re-ingest the 3 worst-performing documents (highest parse failure rate from current `stats.json`). Compare parse failure rate before and after. Target: <2% parse failures on these documents.

**Stop condition:** If parse failure rate drops below 2% and spot-check of extraction quality shows no regression, WP-1 may be sufficient. Proceed to WP-2 only to address extraction precision, not formatting.

---

### 3.2 WP-2: Model Configuration Split

**Goal:** Decouple extraction and enrichment model references so each pipeline stage can be independently configured and experimented with.

**Affected components:** `config.py`, `config.json` schema, `run_pipeline.py`, `reqbot.py` CLI

**Estimated effort:** 1–2 hours

#### Requirements

1. **R-2.1:** Add `extraction_model` and `enrichment_model` fields to `config.json` schema. Both default to the current `default_model` value for backward compatibility.

2. **R-2.2:** Update `run_pipeline.py` to accept separate model arguments for Step C and Step D.5. The existing `--model` flag should continue to work as a convenience alias that sets both.

3. **R-2.3:** Update `reqbot init` wizard to prompt for `extraction_model` and `enrichment_model` separately, with the current `default_model` as the default for both.

4. **R-2.4:** Ensure `reqbot ingest` and `reqbot batch` surface the model split in their `--help` output and log which model is used at each stage.

**Validation gate:** Run `reqbot ingest` on a single test PDF with `extraction_model` and `enrichment_model` set to different values. Verify logs show the correct model at each stage. Verify backward compat: a config with only `default_model` still works.

---

### 3.3 WP-3: Gold Evaluation Set

**Goal:** Build a human-verified ground truth dataset that enables quantitative measurement of extraction quality — precision, recall, and semantic accuracy.

**Affected components:** New artifacts (eval set JSONL, eval harness script)

**Estimated effort:** 3–5 days (manual curation is the bottleneck)

#### Requirements

1. **R-3.1:** Select 300–500 chunks stratified across three document classes: NIST SP prose, DODI/DoDM tables, and AFI/DAF prose. Selection should include chunks with high, medium, and zero requirement density.

2. **R-3.2:** For each selected chunk, produce a hand-corrected extraction target: the JSON array of requirements that a perfect extractor would produce. Start from existing Step C output and correct errors — do not extract from scratch.

3. **R-3.3:** Store the gold set as a standalone JSONL file with schema: `{chunk_id, chunk_text, page_start, page_end, source_pdf, document_class, gold_requirements: [...], corrector_notes}`.

4. **R-3.4:** Build an eval harness script that takes a gold JSONL and a Step C output JSONL, joins on `chunk_id`, and reports: (a) requirement-level precision and recall (fuzzy match on `source_quote`), (b) `source_ref` accuracy, (c) false positive rate, (d) per-document-class breakdown.

5. **R-3.5:** Run the eval harness against the current pipeline (post WP-1) to establish a quantitative baseline. Record baseline metrics in a results file committed to the repo.

**Validation gate:** Baseline eval metrics exist and are reproducible. The eval harness runs end-to-end on the gold set. Metrics inform the decision: if precision >90% and recall >85%, fine-tuning may not be justified. If either metric is significantly lower, proceed to WP-4/WP-5.

---

### 3.4 WP-4: Training Data Curation

**Goal:** Prepare a clean supervised fine-tuning dataset from existing pipeline artifacts, augmented by the gold eval set, suitable for QLoRA training.

**Prerequisite:** WP-3 gate indicates fine-tuning is warranted.

**Estimated effort:** 2–3 days

#### Requirements

1. **R-4.1:** Build a training data assembly script that: (a) reads `*_chunks.jsonl` and matching `*_extracted_requirements.jsonl`, (b) groups requirements by `chunk_id`, (c) excludes `chunk_ids` present in `*_parse_failures.jsonl`, (d) formats each pair as a chat-style SFT example (system prompt + user: chunk text + assistant: JSON array).

2. **R-4.2:** Do NOT build training targets from `*_requirements_normalized.jsonl`. Step D's global dedup alters per-chunk output. Use Step C extracted output directly, joined to chunks.

3. **R-4.3:** Overlay gold set corrections: for `chunk_ids` present in the gold eval set, replace the pipeline-generated target with the hand-corrected target.

4. **R-4.4:** Apply quality filters: exclude training pairs where the pipeline confidence score is below 0.3, or where the chunk text is <200 characters (likely fragment noise).

5. **R-4.5:** Output in Alpaca/ShareGPT JSON format compatible with Unsloth and axolotl. Include a held-out 10% validation split (stratified by document class).

6. **R-4.6:** Document the training data provenance: total examples, per-document-class counts, gold-corrected count, filtered count, and known label noise caveats.

**Validation gate:** Training dataset exists, loads cleanly in Unsloth's data loader, and the provenance doc is complete. Spot-check 50 random examples for obvious errors.

---

### 3.5 WP-5: Fine-Tuning and Integration

**Goal:** Train a QLoRA adapter for Llama 3.1 8B on the curated extraction task, evaluate against the gold set, and integrate into the pipeline via Ollama.

**Prerequisite:** WP-4 gate passed. WP-2 model config split is in place.

**Estimated effort:** 1–2 weeks (includes learning curve)

#### Requirements

1. **R-5.1:** Use Unsloth for QLoRA fine-tuning of Llama 3.1 8B (confirmed compatible with RTX 4070 Ti S, ~12GB VRAM for 8B QLoRA). If Unsloth proves insufficient, axolotl is the fallback.

2. **R-5.2:** Training hyperparameters: start with rank 16, alpha 32, learning rate 2e-4, 3 epochs. Document all hyperparameters and results per run.

3. **R-5.3:** After training, merge adapter weights into full model weights (do not attempt to import raw QLoRA adapters into Ollama — quantization incompatibilities are a known risk). Export as GGUF.

4. **R-5.4:** Create an Ollama Modelfile that loads the merged GGUF. Register as a custom model name (e.g., `reqbot-extract:v1`). Update `extraction_model` in `config.json` to point to this model.

5. **R-5.5:** Run the WP-3 eval harness against the fine-tuned model. Compare precision, recall, and `source_ref` accuracy against the WP-3 baseline. Target: >5 percentage point improvement in recall OR >10 point improvement in precision on the weakest document class.

6. **R-5.6:** If the fine-tuned 8B model meets targets, optionally test whether a fine-tuned 3B model (e.g., Llama 3.2 3B) achieves comparable quality — this would significantly reduce Step C inference time on batch runs.

7. **R-5.7:** Full corpus re-ingestion with the fine-tuned model is a separate decision. Do not re-ingest until the eval results are reviewed and the model is accepted.

**Validation gate:** Eval harness metrics show measurable improvement over prompted baseline on the gold set. The custom model loads and runs correctly in Ollama. Pipeline integration is confirmed with `reqbot ingest` on a test PDF.

---

## 4. Implementation Sequence

Execution order with dependency chain and decision gates between packages.

| WP | Action | Gate Criteria | Effort | Depends On |
|----|--------|---------------|--------|------------|
| 1 | Structured output decoding + few-shot prompt | Parse failure <2% on worst docs | 2–4 hrs | None |
| 2 | Split `extraction_model` / `enrichment_model` config | Both models independently configurable | 1–2 hrs | None (parallel OK) |
| 3 | Build gold eval set + eval harness | Baseline metrics recorded | 3–5 days | WP-1 (run eval post-fix) |
| 4 | Curate SFT training dataset | Dataset loads in Unsloth, spot-checked | 2–3 days | WP-3 gate says tune |
| 5 | QLoRA fine-tune + Ollama integration | Eval improvement over baseline | 1–2 weeks | WP-2, WP-4 |

WP-1 and WP-2 can run in parallel. WP-3 should follow WP-1 so the eval baseline reflects the structured output fix. WP-4 and WP-5 are only executed if WP-3's gate indicates a measurable quality ceiling remains after prompt-level fixes.

---

## 5. Decision Tree

| After WP... | If Result Is... | Then... |
|---|---|---|
| WP-1: Structured decoding | Parse failures <2%, extraction quality acceptable on spot-check | Stop. Ship WP-1 + WP-2. Build eval set (WP-3) at leisure for future regression testing. |
| WP-1: Structured decoding | Parse failures fixed, but extraction precision/recall still has visible gaps | Proceed to WP-3 to quantify the gap. |
| WP-3: Gold eval baseline | Precision >90%, recall >85% across all document classes | Stop. Current prompted approach is sufficient. Revisit when corpus grows or new doc types are added. |
| WP-3: Gold eval baseline | Precision or recall significantly below target on one or more doc classes | Proceed to WP-4 and WP-5. |
| WP-5: Fine-tuned model eval | Improvement meets targets (>5pt recall OR >10pt precision on weakest class) | Accept model. Plan full corpus re-ingestion as a separate phase. |
| WP-5: Fine-tuned model eval | Improvement is marginal or inconsistent | Investigate: training data quality, document class imbalance, or model size. Do not re-ingest corpus. |

---

## 6. Hardware and Tooling Requirements

| Component | Requirement | Notes |
|---|---|---|
| Training GPU | RTX 4070 Ti Super (16GB VRAM) | QLoRA 8B fits in ~12GB. Confirmed sufficient. |
| Training framework | Unsloth (primary), axolotl (fallback) | Unsloth has native Llama 3.1 support and fastest single-GPU QLoRA. |
| Adapter strategy | QLoRA → merge to full weights → GGUF export | Do not import raw QLoRA adapters into Ollama — quantization mismatch risk. |
| Serving | Ollama with custom Modelfile | FROM base model, weights replaced by merged GGUF. |
| Eval tooling | Custom Python script (WP-3, R-3.4) | Fuzzy match on `source_quote`, exact match on `source_ref`. |
| Training data format | Alpaca or ShareGPT JSON | Compatible with both Unsloth and axolotl. |

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Training on noisy labels distills current model's errors | High | Medium | Overlay gold corrections (R-4.3). Quality filters (R-4.4). Measure against gold set, not pipeline output. |
| Ollama adapter import fails due to quantization mismatch | Medium | High | Always merge to full weights before GGUF export (R-5.3). Never import raw QLoRA. |
| Fine-tuned model overfits to current doc corpus | Medium | Medium | Held-out validation split (R-4.5). Test on a new PDF not in training data. |
| Gold eval set curation takes longer than estimated | High | Low | Start with 150 chunks (minimum viable). Expand later. Prioritize table-heavy DODI class. |
| Structured output (WP-1) solves the whole problem | Medium | Positive | This is the best outcome. WP-3 eval set still has long-term value for regression testing. |
| Model config split introduces regressions | Low | Medium | Backward compat requirement (R-2.1 defaults). Explicit test case (WP-2 gate). |

---

## 8. Source Attribution

This document synthesizes findings from two sources:

- **Codex code review (March 2026)** — full analysis of Phase 12.2 branch including `llm_extract_requirements.py`, `parse_and_normalize.py`, `config.py`, `run_pipeline.py`, and `ask.py`. Provided current state assessment, integration path analysis, and sequencing recommendation.
- **Claude analysis (March 2026)** — extraction model optimization strategy, fine-tuning tool selection (Unsloth/QLoRA over nanoGPT), training data quality assessment, and decision tree structure.

Where both sources agreed (structured decoding first, gold eval before training, merge weights before Ollama import), the recommendation was adopted directly. The decision tree structure and stop conditions are original to this document.

---

## 9. Glossary

| Term | Definition |
|---|---|
| **QLoRA** | Quantized Low-Rank Adaptation. Fine-tuning method that trains small adapter weights on top of a quantized base model, reducing VRAM requirements by ~75%. |
| **LoRA adapter** | The small set of trained weights produced by LoRA/QLoRA. Can be loaded on top of a base model or merged into full weights. |
| **Unsloth** | Open-source library for fast single-GPU LoRA/QLoRA training. Supports Llama 3.x natively. |
| **axolotl** | Config-driven fine-tuning framework. Broader model support than Unsloth, slightly more complex setup. |
| **GGUF** | File format for quantized LLM weights used by llama.cpp and Ollama. |
| **Ollama Modelfile** | Configuration file that defines how Ollama loads and serves a model. Specifies base weights, system prompt, and parameters. |
| **SFT** | Supervised Fine-Tuning. Training a model on input/output pairs where the correct output is provided. |
| **Gold eval set** | Human-verified ground truth dataset used to measure extraction quality objectively. |
| **Structured outputs** | Ollama capability that constrains LLM generation to valid JSON matching a specified schema. |
| **Pass 1 / Pass 2** | Phase 12.2 extraction architecture: Pass 1 extracts `source_quote` + `source_ref`, Pass 2 enriches with metadata. Phase 13 focuses on Pass 1. |