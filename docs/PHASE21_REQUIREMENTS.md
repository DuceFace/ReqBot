# ReqBot - Phase 21: Checklist Generator MVP

**Status:** In Progress
**Date:** 2026-07-18
**Preceded by:** Phase 20 (Domain Profile Foundation)
**Followed by:** Phase 22 (Evidence Request and Test Step Refinement)

---

## Framing

**Phase 21 turns validated requirements into source-backed audit checklist items.**

The job is narrow:

1. Consume existing normalized requirement records.
2. Generate checklist items that preserve requirement provenance.
3. Export the checklist in formats people can actually use for assessment work.

Phase 21 does not perform audits, determine compliance, ingest new document types, or create requirements outside the extraction pipeline.

---

## Context and Motivation

ReqBot now has domain profiles and a `domain_profile` metadata field from Phase 20. That gives checklist generation enough context to produce domain-appropriate checklist language without hardcoding cybersecurity assumptions into the checklist feature.

The first checklist version should be useful to a human assessor, but conservative. Every checklist item must map back to one or more extracted requirements. If ReqBot cannot trace an item to source text, it must not create the item.

---

## Goal

Add a `reqbot checklist` command that generates a usable audit checklist from existing validated requirements.

After Phase 21:

- A user can generate a checklist for a document or requirement set.
- Checklist output is available in CSV, JSON, and Markdown.
- Every checklist item includes source provenance.
- Checklist items include clear audit questions.
- Low-confidence or incomplete source records are marked for human review.
- Checklist generation consumes existing normalized requirements instead of bypassing the pipeline.

---

## Architecture Rules

1. **Validated requirements are the source of truth.** Checklist generation consumes normalized requirement records. It must not parse PDFs directly or re-extract obligations from raw chunks.
2. **No orphan checklist items.** Every checklist item must reference at least one `requirement_id`. A record missing `requirement_id` or `source_quote` must not produce a checklist item — these are the hard provenance anchors. A record missing weaker provenance (`source_ref`, `section_title_path`, `page_refs`, `domain_tags`) produces an item flagged with `requires_human_review`.
3. **No invented obligations.** The generator may rephrase a requirement as an audit question, but it must not add new duties, controls, or evidence claims that are not grounded in the source requirement. If it cannot produce a grounded rephrase, it must leave the generated field blank.
4. **Profile-aware, not profile-hardcoded.** Checklist logic may consume `profile["checklist_guidance"]`, `domain_profile`, and requirement metadata. It must not hardcode cybersecurity-only evidence categories or assumptions.
5. **Service layer first.** Core checklist logic belongs in a reusable service/module callable by CLI now and API/GUI later.
6. **CLI is a thin wrapper.** `reqbot checklist` handles arguments, calls the service, and writes output.
7. **No new pip dependencies unless explicitly approved.** Prefer stdlib CSV, JSON, and Markdown generation.

---

## Checklist JSON Schema

Checklist JSON uses a document envelope with a flat, document-ordered `items` array.

Minimum JSON envelope:

```json
{
  "format": "reqbot-checklist",
  "format_version": "1.0",
  "generated_at": "",
  "generator": {
    "tool": "reqbot",
    "command": ""
  },
  "document": {
    "document_id": "",
    "source_pdf": ""
  },
  "profile": "",
  "summary": {
    "total_items": 0,
    "items_requiring_review": 0
  },
  "items": []
}
```

Minimum JSON checklist item:

```json
{
  "checklist_item_id": "",
  "requirement_ids": [],
  "domain_tags": [],
  "source_ref": "",
  "page_refs": [],
  "section_title_path": [],
  "source_quote": "",
  "audit_question": "",
  "evidence_to_request": [],
  "generation_notes": "",
  "assessor_notes": "",
  "status": "not-started",
  "confidence": 0.0,
  "requires_human_review": true,
  "review_reasons": []
}
```

Field rules:

- `checklist_item_id`: stable deterministic ID derived from source requirement ID(s).
- `requirement_ids`: one or more normalized requirement IDs.
- `domain_tags`: copied from source requirement metadata.
- `source_ref`: copied from source requirement metadata when present.
- `page_refs`: derived from `page_start`/`page_end` in source requirement; e.g. `[3]` or `[3, 4]` for cross-page items.
- `section_title_path`: copied from source requirement metadata when present.
- `source_quote`: copied from source requirement text or quote field when present.
- `audit_question`: generated from the requirement text; blank if a grounded rephrase cannot be produced.
- `evidence_to_request`: optional in Phase 21 MVP; blank/empty unless the requirement directly supports a conservative value.
- `generation_notes`: generator-owned notes or caveats; blank by default.
- `assessor_notes`: human-owned notes; always blank at generation time and never overwritten by regeneration.
- `status`: human-owned assessment status; defaults to `not-started` and is never overwritten by regeneration.
- `confidence`: copied from source requirement; heuristic score (0.0–1.0) computed by `parse_and_normalize` based on field completeness (missing domain_tags, source_quote, description, source_ref each deduct).
- `requires_human_review`: true when confidence is below threshold, provenance is incomplete, or grounded wording cannot be produced.
- `review_reasons`: controlled list explaining why review is required.

Profile rules:

- The JSON envelope `profile` field records the selected checklist generation profile. It is set from the `--profile` CLI argument (or `profile_name` service parameter) — it is not read from individual source records.
- Each source record's `domain_profile` is read at the item level (with `"cybersecurity"` fallback for pre-Phase-20 records that lack the field). If `domain_profile` conflicts with the selected `profile_name`, the item is flagged `requires_human_review: True` with `"profile-mismatch"` in `review_reasons`. This check runs in the service layer (WP-21.2), not deferred to CLI.
- Checklist item `domain_tags` record topical tags from the source requirement.
- Do not collapse `domain_tags` into `domain_profile`.

Assessor-owned fields:

- `status`
- `assessor_notes`

Regenerating a checklist must not overwrite assessor-owned fields in any future round-trip workflow.

Deterministic ID rule:

- For one-to-one checklist items, derive `checklist_item_id` from the source requirement ID/hash.
- For multi-requirement checklist items, hash the sorted source requirement IDs.
- ID generation must be deterministic across re-runs.

Deferred fields for Phase 22:

- `test_steps`
- `pass_criteria`
- `failure_indicators`

---

## Content Rules

Checklist generation shall follow these rules:

- Checklist items must map directly to extracted requirements.
- The system shall not create a checklist item if `requirement_id` or `source_quote` is missing.
- The system shall create a checklist item but flag it `requires_human_review` if weaker provenance fields (`source_ref`, `section_title_path`, `page_refs`, `domain_tags`) are missing.
- The system shall not invent new obligations.
- The system shall leave generated fields blank when source-grounded wording is uncertain.
- The system shall preserve source references in every checklist item when available.
- The system shall preserve section title paths when available.
- Requirements with incomplete provenance shall produce checklist items marked for review with a reason.
- Generated checklist language shall be clear enough for a human assessor to use.
- Checklist output shall not claim that an organization is compliant or noncompliant.


---

## Command Scope

Initial command:

```bash
reqbot checklist --doc <doc_key> --format csv
```

Initial options:

```bash
reqbot checklist --doc <doc_key> --format md
reqbot checklist --doc <doc_key> --format json
reqbot checklist --doc <doc_key> --format csv --output checklist.csv
reqbot checklist --doc <doc_key> --profile cybersecurity
```

Optional if low-risk:

```bash
reqbot checklist --doc <doc_key> --group-by section
```

Out of scope for Phase 21:

- GUI checklist view
- API endpoint
- XLSX/HTML export
- Autonomous compliance scoring
- Evidence collection workflow
- Policy gap analysis
- Editing checklist items in ReqBot

---

## Data Source Decision

Phase 21 should start from normalized requirement records, not Qdrant search results.

Reason:

- Checklist generation is document-scoped and needs complete coverage.
- Qdrant retrieval is query-scoped and may omit requirements.
- Normalized JSONL preserves the extraction pipeline contract and avoids retrieval-ranking side effects.

Qdrant may be used later for interactive or query-scoped checklist generation, but it is not the Phase 21 MVP source of truth.

---

## WP-21.1 Findings — Field Mapping

**Status:** COMPLETE 2026-07-19

### Source field map (production-confirmed against 45-doc corpus)

| JSONL field | Checklist item field | Notes |
|---|---|---|
| `requirement_id` | `requirement_ids[0]` | Source of `CHK-` ID derivation |
| `source_ref` | `source_ref` | Often empty in non-enriched records |
| `source_quote` | `source_quote` | Never empty — pipeline requires it |
| `section_title_path` | `section_title_path` | Array; empty `[]` for legacy fixed-size chunker records |
| `domain_tags` | `domain_tags` | Often empty in non-enriched records |
| `confidence` | `confidence` | Heuristic 0.0–1.0; penalties: missing `domain_tags` −0.2, missing `source_quote` −0.2, short `description` −0.1, missing `source_ref` −0.1; corpus values: 0.6, 0.7 |
| `page_start` / `page_end` | `page_refs` | Present in all records; carry through to answer the page provenance gap |
| `document_id` | envelope `document.document_id` | Hash, e.g. `b25aadb2b57dd930` |
| `source_pdf` | envelope `document.source_pdf` | Filename only, e.g. `afi17-101.pdf` |
| `domain_profile` | envelope `profile` (with fallback) | **Absent from all 45 existing corpus records** — apply `req.get("domain_profile", "cybersecurity")` fallback |
| `description` | omitted | Paraphrase competing with `source_quote` — not carried into checklist |
| `requirement_type` | omitted (Phase 22) | Useful for grouping; deferred |

### Decided

- **`--doc` argument** accepts the `doc_key` (PDF stem, e.g. `afi17-101`) — the same identifier `reqbot docs` displays. The checklist service resolves it to a JSONL path via `docs_service.list_docs()`. Not the hash `document_id` (that is a Qdrant concern).
- **`domain_profile` fallback** — all 45 existing corpus JSONL records lack the field. Service must apply `req.get("domain_profile", "cybersecurity")`, consistent with the Phase 20 Qdrant payload fallback.
- **Confidence threshold** — `< 0.8` triggers `requires_human_review: true` with `review_reasons: ["low-confidence"]`. Flags any record missing at least one provenance field. Define as a named constant in the service.
- **Service location** — new file `services/checklist_service.py`. Pure Python, no framework dependencies, same pattern as `docs_service.py`. Signature: `generate(processed_dir: Path, doc_key: str, profile_name: str) -> dict`.
- **Page provenance** — `page_start`/`page_end` are already in normalized records. Add `page_refs` to the checklist item schema (e.g. `[1]` or `[3, 4]` for cross-page items) so assessors can locate the source without opening a 200-page PDF.

---

## Work Package Plan

### WP-21.1 - Checklist Design Audit

**Status:** COMPLETE 2026-07-19 — see findings section above.

**Gate:** ✅ Field mapping documented. Open questions resolved. WP-21.2 may proceed.

---

### WP-21.2 - Checklist Service and Schema

**Status:** COMPLETE 2026-07-19 — PR open (`feature/wp-21.2-checklist-service`); 48 unit tests; 148 total.

**Goal:** Implement core checklist item creation from normalized requirement records.

**Tasks:**

- Add a reusable checklist module/service. ✅
- Define checklist item dict schema. ✅
- Generate deterministic `checklist_item_id` values. ✅
- Copy provenance fields from source requirements. ✅
- Mark low-confidence or incomplete provenance items with `requires_human_review`. ✅
- Flag items where source record `domain_profile` conflicts with selected `profile_name`. ✅
- Add unit tests for schema, provenance, low-confidence handling, review reasons, assessor-owned fields, no-orphan behavior, and profile mismatch. ✅

**Key implementation facts:**

- Service: `services/checklist_service.py`; signature `generate(processed_dir: Path, doc_key: str, profile_name: str) -> dict`
- Source resolution: prefers `*_requirements_enriched.jsonl` (Step D.5) over `*_requirements_normalized.jsonl` (Step D) within the latest run directory; older enriched from a prior run never beats newer normalized from a later run
- `CONFIDENCE_REVIEW_THRESHOLD = 0.8`; confidence < threshold → `review_reasons: ["low-confidence"]`
- Deterministic ID: `CHK-` + sha256(`requirement_id`)[:16]; multi-req: sha256(sorted IDs joined by `|`)
- `page_refs` derived from `page_start`/`page_end`; `[]` if `page_start` missing
- `assessor_notes`, `status` initialized to `""` / `"not-started"`; never overwritten by regeneration
- `domain_profile` fallback: `req.get("domain_profile", "cybersecurity")` for pre-Phase-20 records; mismatch with `profile_name` → `review_reasons: ["profile-mismatch"]`
- Profile loaded via `load_profile(profile_name)` for validation; content use reserved for WP-21.3

**Gate:**

- ✅ Service creates valid checklist JSON from fixture requirements.
- ✅ Every item has at least one `requirement_id`.
- ✅ Records missing `requirement_id` or `source_quote` are skipped entirely, not flagged.
- ✅ Records missing weaker provenance (`source_ref`, `section_title_path`, `page_refs`, `domain_tags`) produce a flagged item, not a skipped one.
- ✅ Low confidence (below threshold) triggers `requires_human_review: true` with a reason.
- ✅ `status` and `assessor_notes` are initialized for assessor use and treated as human-owned fields.
- ✅ Source record `domain_profile` mismatch with selected profile flags the item with `"profile-mismatch"`; missing `domain_profile` falls back to `"cybersecurity"` with no flag when running `--profile cybersecurity`.

---

### WP-21.3 - Audit Question Generation

**Goal:** Convert requirement text into clear audit questions.

**Tasks:**

- Implement conservative question generation.
- Prefer deterministic transformation first where possible.
- Use LLM generation only if an existing project LLM helper pattern supports it cleanly.
- Ensure the generated question remains grounded in the source requirement.
- Add tests for representative obligation types.

**Gate:**

- Every generated question maps back to source requirement text.
- The generator does not introduce obligations absent from the source.
- Low-confidence or ungrounded generation is marked for human review with a reason.

---

### WP-21.4 - CSV, JSON, and Markdown Export

**Goal:** Export checklist output for spreadsheet, machine, and plain-text use.

**Tasks:**

- Add CSV export as the primary human-usable MVP format.
- Add JSON export.
- Add Markdown export.
- Include requirement IDs, source references, section title paths, review reasons, and assessor-owned fields in all formats.
- Add tests or golden fixtures for all formats.

**Gate:**

- CSV output opens cleanly in spreadsheet tools.
- JSON output is parseable.
- Markdown output is readable and source-backed.
- No checklist item lacks provenance.
- CSV columns follow locate -> ask -> record -> verify -> trace order.

---

### WP-21.5 - CLI Integration

**Goal:** Add `reqbot checklist` command.

**Tasks:**

- Add CLI command and options.
- Support `--doc`, `--format`, `--output`, and `--profile`.
- Load normalized requirements for the requested document.
- Call the checklist service.
- Write output to stdout or file.

**Gate:**

- `reqbot checklist --doc <doc_key> --format csv` works.
- `reqbot checklist --doc <doc_key> --format json` works.
- `reqbot checklist --doc <doc_key> --format md` works.
- Invalid document IDs produce clear errors.
- Profile mismatch handling is explicit and tested.
- Generated output records the selected profile in the JSON envelope and keeps item-level `domain_tags` separate.

---

### WP-21.6 - Integration Gate

**Goal:** Confirm checklist generation works without regressing existing ReqBot commands.

**Test matrix:**

| Command | Expected behavior |
|---------|------------------|
| `reqbot checklist --doc <doc_key> --format csv` | Produces spreadsheet-friendly CSV with locate -> ask -> record -> verify -> trace columns |
| `reqbot checklist --doc <doc_key> --format md` | Produces readable Markdown with provenance |
| `reqbot checklist --doc <doc_key> --format json` | Produces parseable checklist JSON |
| `reqbot ask "multi-factor authentication"` | Existing retrieval behavior unchanged |
| `reqbot trace <existing-req-id>` | Existing trace behavior unchanged |
| `reqbot docs` | Existing document listing unchanged |

**Gate:**

- Checklist output is usable as a human assessment starting point.
- All checklist items have source provenance.
- Existing CLI commands still pass.

---

## Explicit Non-Goals for Phase 21

- No autonomous audit execution.
- No compliance pass/fail determination.
- No policy alignment or gap analysis.
- No GUI checklist editor.
- No checklist persistence database.
- No profile management UI.
- No new domain profile beyond existing/test profiles unless separately planned.
- No retrieval filtering by `domain_profile` unless separately planned.
- No reindex of the existing corpus unless separately requested.

---

## Success Gate

1. `reqbot checklist` exists and generates checklist output from normalized requirements.
2. CSV, Markdown, and JSON output formats work.
3. Every checklist item references one or more source requirements.
4. Source references, source quotes, and section title paths are preserved when available.
5. Low-confidence or incomplete items are marked `requires_human_review` with `review_reasons`.
6. Generated fields are blank when grounded wording cannot be produced.
7. `status` and `assessor_notes` are assessor-owned fields and are not generated as findings.
8. Existing CLI behavior is not regressed.
9. The architecture is ready for Phase 22 evidence request and test step refinement.

---

## Sequencing

| WP | Description | Gate before next |
|----|-------------|-----------------|
| 21.1 | Checklist design audit | Field mapping and source-of-truth decisions documented |
| 21.2 | Checklist service and schema | Valid source-backed checklist JSON from fixtures |
| 21.3 | Audit question generation | Questions are grounded and tested |
| 21.4 | CSV, JSON, and Markdown export | Outputs are spreadsheet-friendly/readable/parseable |
| 21.5 | CLI integration | `reqbot checklist` works for document-scoped generation |
| 21.6 | Integration gate | Checklist MVP passes without CLI regressions |

**Do one WP at a time. Codex/Gemini review after each before proceeding.**
