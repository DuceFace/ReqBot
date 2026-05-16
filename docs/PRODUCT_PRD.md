# ReqBot Product Requirements Document
## General Requirements + Audit Checklist Capability

**Status:** Draft  
**Purpose:** Define ReqBot’s longer-term product direction as a domain-configurable requirements extraction, retrieval, traceability, and audit-planning platform.

---

## 1. Product Vision

ReqBot shall evolve from a cybersecurity-focused compliance retrieval tool into a general-purpose requirements analysis platform.

ReqBot’s core purpose is to:

1. Extract atomic requirements from authoritative documents.
2. Preserve traceability to source text, page, section, and document identity.
3. Make requirements searchable through reliable retrieval.
4. Support multiple domains through configurable domain profiles.
5. Generate audit checklists and evidence request plans from extracted requirements.

Cybersecurity is the first supported domain, not the only supported domain.

---

## 2. Product Scope

### In Scope

ReqBot shall support:

- Cybersecurity and compliance documents as the initial domain.
- Generalized requirement extraction.
- Domain-specific profiles.
- Requirement search and traceability.
- Checklist generation from extracted requirements.
- Evidence request generation.
- Markdown and JSON checklist export initially.
- Human review workflows.

### Out of Scope

ReqBot shall not:

- Automatically certify compliance.
- Replace human assessors.
- Perform autonomous audits.
- Invent new obligations not present in source material.
- Make legal, regulatory, or accreditation determinations.

ReqBot provides assessment support, not final compliance judgment.

---

## 3. Core Product Requirements

### PR-1: Domain-Neutral Core

The system shall maintain a domain-neutral core requirement model.

Cybersecurity-specific logic shall not be hardcoded into the core pipeline unless unavoidable. Domain-specific behavior shall live in profiles.

---

### PR-2: Domain Profiles

The system shall support configurable domain profiles.

A domain profile may define:

- Domain name
- Requirement extraction guidance
- Obligation verbs
- Skip-section patterns
- Domain tags
- Requirement categories
- Checklist generation guidance
- Evidence categories
- Confidence scoring adjustments

Example profiles:

- `cybersecurity`
- `hr_policy`
- `safety`
- `maintenance`
- `finance`
- `acquisition`

Initial implementation shall support `cybersecurity` only, but the architecture shall allow additional profiles.

---

### PR-3: Generalized Requirement Schema

The system shall represent extracted requirements using a generalized schema.

Minimum fields:

```json
{
  "requirement_id": "",
  "document_id": "",
  "domain_profile": "",
  "source_document": "",
  "source_ref": "",
  "source_quote": "",
  "normalized_description": "",
  "section_title_path": "",
  "parent_context": "",
  "page_refs": [],
  "requirement_type": "",
  "domain_tags": [],
  "confidence": 0.0,
  "validation_status": ""
}
```

The schema shall support cybersecurity requirements but shall not assume all requirements are cybersecurity controls.

---

### PR-4: Source Traceability

Every extracted requirement shall preserve provenance.

At minimum, each requirement shall trace back to:

- Source document
- Document ID/hash
- Source quote
- Page reference
- Section path
- Extraction run metadata

No requirement shall be considered valid unless it can be traced back to source material.

---

### PR-5: Requirement Validation

The system shall validate extracted requirements before indexing.

Validation shall include:

- Source quote verification against chunk text
- Non-requirement section filtering
- Confidence scoring based on deterministic signals
- Hallucination rejection
- Low-confidence flagging

Requirements that fail validation shall be discarded or marked for review.

---

## 4. Audit Checklist Generation

### PR-6: Checklist Generation Command

The system shall provide a command to generate an audit checklist from extracted requirements.

Example:

```bash
reqbot checklist --doc AFI-17-101 --format md
```

Future examples:

```bash
reqbot checklist --doc AFI-17-101 --format json
reqbot checklist --doc AFI-17-101 --group-by section
reqbot checklist --doc AFI-17-101 --profile cybersecurity
```

---

### PR-7: Checklist Item Schema

For each requirement, the system shall generate a checklist item.

Minimum checklist item fields:

```json
{
  "checklist_item_id": "",
  "requirement_id": "",
  "source_ref": "",
  "source_quote": "",
  "audit_question": "",
  "evidence_to_request": [],
  "test_steps": [],
  "pass_criteria": [],
  "failure_indicators": [],
  "assessor_notes": "",
  "confidence": 0.0,
  "requires_human_review": true
}
```

---

### PR-8: Checklist Content Rules

Checklist generation shall follow these rules:

- Checklist items must map directly to extracted requirements.
- The system shall not create checklist items without a source requirement.
- The system shall not invent new obligations.
- The system shall preserve source references in every checklist item.
- Low-confidence requirements shall produce checklist items marked for review.
- Generated checklist language shall be clear enough for a human assessor to use.

---

### PR-9: Checklist Output Formats

Initial checklist export formats:

- Markdown
- JSON

Future formats:

- CSV
- XLSX
- HTML
- GUI-rendered checklist view

Markdown output shall be human-readable. JSON output shall be machine-readable and suitable for later GUI use.

---

## 5. Evidence Request Generation

### PR-10: Evidence Mapping

For each checklist item, the system shall generate suggested evidence to request.

Evidence examples may include:

- Policies
- Procedures
- SOPs
- Configuration screenshots
- System exports
- Logs
- Tickets
- Training records
- Approval records
- Interview prompts

Evidence requests shall be suggestions, not proof of compliance.

---

### PR-11: Test Steps

For each checklist item, the system shall generate suggested test steps.

Test steps should answer:

- What should the assessor inspect?
- What records should be sampled?
- What questions should be asked?
- What would indicate implementation?
- What would indicate noncompliance?

---

## 6. Architecture Requirements

### AR-1: Core Pipeline Protection

The existing extraction, validation, indexing, retrieval, and trace pipeline shall remain the product core.

New checklist features shall consume validated requirement objects. They shall not bypass or duplicate the extraction pipeline.

---

### AR-2: Service Layer Integration

Checklist generation shall eventually live behind a service function.

Example:

```python
generate_checklist(document_id, profile, output_format)
```

The CLI and future API shall call the same service function.

---

### AR-3: API Compatibility

When the API layer exists, checklist functionality may be exposed through a future endpoint.

Possible future endpoint:

```http
POST /checklist
```

This endpoint is not part of the Phase 16 read-only API MVP unless explicitly added later.

---

### AR-4: GUI Compatibility

Checklist output shall be structured so it can later be displayed in the GUI without reworking the generation logic.

The GUI shall consume checklist JSON rather than triggering custom frontend logic.

---

## 7. Domain Profile Framework

### PR-12: Profile File Format

Domain profiles should be stored as configuration files.

Example:

```yaml
name: cybersecurity
description: Cybersecurity, RMF, and compliance requirements

obligation_verbs:
  - shall
  - must
  - will
  - is responsible for
  - is required to

skip_sections:
  - GLOSSARY
  - REFERENCES
  - ACRONYMS
  - DEFINITIONS

domain_tags:
  - access_control
  - audit_logging
  - incident_response
  - configuration_management
  - identification_authentication

checklist_guidance:
  evidence_categories:
    - policy
    - procedure
    - system_configuration
    - logs
    - tickets
    - interviews
```

---

### PR-13: Profile Selection

The user shall be able to select a profile during ingest or checklist generation.

Examples:

```bash
reqbot ingest document.pdf --profile cybersecurity
reqbot checklist --doc document_id --profile cybersecurity
```

If no profile is specified, the system shall use the configured default profile.

---

## 8. Quality and Safety Requirements

### QR-1: No Unsupported Claims

The system shall not claim that an organization is compliant or noncompliant based only on generated checklist output.

Allowed language:

- “Suggested audit checklist”
- “Potential evidence to request”
- “Assessment support”
- “Human review required”

Disallowed language:

- “Certified compliant”
- “This organization complies”
- “This satisfies the regulation”

---

### QR-2: Human Review Required

All generated checklist outputs shall include a human review disclaimer.

Example:

> This checklist is generated from extracted requirements and is intended to support human assessment. It does not constitute a compliance determination.

---

### QR-3: Low-Confidence Handling

If a requirement has low confidence, the generated checklist item shall be marked as requiring review.

Low-confidence requirements should not be silently included as authoritative checklist items.

---

## 9. Suggested Implementation Phases

### Phase 19 — Domain Profile Foundation

Goal: Generalize ReqBot beyond cybersecurity hardcoding.

Deliverables:

- Domain profile config format
- Cybersecurity profile
- Profile-aware extraction settings
- Profile-aware skip sections
- Generalized requirement schema review

Gate:

- Existing cybersecurity workflow still works
- No regression in current corpus extraction

---

### Phase 20 — Checklist Generator MVP

Goal: Generate a usable audit checklist from extracted requirements.

Deliverables:

- `reqbot checklist` command
- Checklist item schema
- Markdown export
- JSON export
- Source references included in every item

Gate:

- Checklist items map one-to-one or many-to-one back to extracted requirements
- No checklist item lacks provenance
- Human reviewer can use the output as an assessment starting point

---

### Phase 21 — Evidence Request and Test Step Refinement

Goal: Improve checklist usefulness.

Deliverables:

- Evidence request generation
- Test procedure generation
- Pass/fail indicators
- Group-by-section output
- Low-confidence review flags

Gate:

- Checklist output is useful for a real assessment workflow
- Generated evidence requests are specific and tied to requirements

---

### Phase 22 — Policy Alignment / Gap Analysis

Goal: Compare an organization policy or SSP against an authoritative requirement corpus.

Deliverables:

- Upload policy/procedure
- Extract policy requirements
- Map policy requirements to authoritative corpus
- Identify aligned, partially aligned, missing, and extra items

Gate:

- Output supports human review
- System does not claim final compliance status

---

## 10. Immediate Next Step

Before implementation, Codex should review the current codebase and identify:

1. Where cybersecurity assumptions are hardcoded.
2. Where requirement schema fields need to be generalized.
3. Where profile loading should occur.
4. Whether checklist generation should use existing extracted JSON files or query indexed requirements from Qdrant.
5. Minimum viable implementation path for `reqbot checklist`.
