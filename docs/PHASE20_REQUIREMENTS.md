# ReqBot — Phase 20: Domain Profile Foundation

**Status:** Planning
**Date:** 2026-05-17
**Preceded by:** Phase 19 (GUI Capability Expansion — COMPLETE 2026-05-17)
**Followed by:** Phase 21 (Checklist Generator MVP — defined in `docs/PRODUCT_PRD.md`)

---

## Context and Motivation

ReqBot's product vision (`docs/PRODUCT_PRD.md`) is a domain-configurable requirements platform, not a cybersecurity-only tool. The Phase 16 service layer reorganization and Phase 19 GUI expansion have stabilized the architecture. Phase 20 is the right time to generalize the pipeline before checklist generation (Phase 21) lands — checklists need a profile concept to be useful across domains.

The risk is regression: the existing cybersecurity corpus (45 docs, ~32k requirements) is working well. Phase 20 must not touch any behavior when the default profile is in use. The rule is: **extracting with `--profile cybersecurity` (explicit or default) must produce byte-for-byte identical JSONL output to extracting without the flag today.**

---

## Goal

Externalize hardcoded cybersecurity assumptions (obligation verbs, skip-section patterns, domain tags, requirement type taxonomy) into a configurable profile system. After Phase 20:

- A `profiles/cybersecurity.yaml` profile captures everything the pipeline currently hard-codes.
- A `--profile <name>` flag on `reqbot ingest` selects the active profile.
- Omitting `--profile` falls back to the `cybersecurity` profile — no behavior change for existing workflows.
- New ingests record `domain_profile` in the JSONL payload. Existing JSONL is untouched until a manual reindex.
- The architecture is ready for Phase 21 (checklist generation), which will consume the profile to generate domain-appropriate checklist items.

---

## Architecture Rules

These rules are unchanged from Phases 18–19 and apply throughout Phase 20.

1. **Service layer is the source of truth.** Profile loading belongs in a new `core/profiles.py` module, callable by both CLI and API. No profile logic in route handlers.
2. **CLI and API share the same backend paths.** `reqbot ingest --profile cybersecurity` and a future `POST /api/ingest` call the same pipeline functions.
3. **No behavior change without the flag.** Default profile must reproduce existing output exactly.
4. **No new pip dependencies without discussion.** Use stdlib `tomllib` (Python 3.11+) or `json` if YAML requires PyYAML — confirm before adding.
5. **Profiles are configuration, not code.** Domain-specific logic lives in profile files, not scattered across pipeline scripts.

---

## Work Package Plan

### WP-20.1 — Hardcoding Audit

**Goal:** Locate every place cybersecurity-specific values are currently hardcoded in the pipeline. This is a read-only research WP — no code changes.

**What to look for:**

| Category | Examples | Likely locations |
|----------|----------|-----------------|
| Obligation verbs | `shall`, `must`, `will`, `is required to` | `pipeline/llm_extract_requirements.py` (extraction prompt) |
| Skip-section patterns | `GLOSSARY`, `REFERENCES`, `ACRONYMS`, `DEFINITIONS` | `pipeline/chunk_text.py` |
| Domain tag taxonomy | `access_control`, `audit_logging`, `incident_response` | `pipeline/llm_extract_requirements.py`, `pipeline/enrich_requirements.py` |
| Requirement type taxonomy | `procedural`, `technical`, `administrative` | extraction/enrichment prompts |
| Confidence scoring signals | Any cybersecurity-specific keyword boosts | `pipeline/parse_and_normalize.py` |
| Prompt language | "cybersecurity", "DoD", "NIST" in LLM prompts | extraction and enrichment prompt strings |

**Output:** A concise written list (code locations + current hardcoded values) that drives WP-20.2 and WP-20.3 scoping. No code changes in this WP.

**Gate:**
- Audit complete; hardcoded values documented.
- Alignment on which values belong in the profile vs. which are truly universal pipeline constants.

---

### WP-20.2 — Profile Schema and Cybersecurity Profile

**Goal:** Define the profile file format and create the initial `profiles/cybersecurity.yaml` profile containing everything the audit surfaces.

**Profile format (YAML — pending dependency decision):**

```yaml
name: cybersecurity
description: Cybersecurity, RMF, and compliance requirements (DoD/NIST/CNSSI/AFI)

obligation_verbs:
  - shall
  - must
  - will
  - is required to
  - is responsible for

skip_sections:
  - GLOSSARY
  - REFERENCES
  - ACRONYMS
  - DEFINITIONS
  - ABBREVIATIONS
  - TABLE OF CONTENTS

domain_tags:
  - access_control
  - audit_logging
  - configuration_management
  - identification_authentication
  - incident_response
  - media_protection
  - personnel_security
  - physical_protection
  - risk_assessment
  - system_communications_protection
  - system_information_integrity

requirement_types:
  - procedural
  - technical
  - administrative
  - policy

checklist_guidance:
  evidence_categories:
    - policy
    - procedure
    - system_configuration
    - logs
    - tickets
    - interviews
    - training_records
```

**`core/profiles.py` — new module:**

```python
def load_profile(name: str) -> dict:
    """Load a named profile from profiles/<name>.yaml. Falls back to cybersecurity."""

def default_profile() -> dict:
    """Returns the cybersecurity profile. Used when --profile is not specified."""
```

**Dependency decision:** Determine whether PyYAML is acceptable or whether profiles should be JSON (no new dep). Record the decision in this WP before writing any profile files.

**Gate:**
- `profiles/cybersecurity.yaml` exists and passes a load round-trip.
- `core/profiles.py` loads it cleanly.
- Profile fields match the PRD `PR-12` spec.

---

### WP-20.3 — Profile-Aware Pipeline Integration

**Goal:** Thread the active profile through the pipeline steps that currently hardcode cybersecurity values, and expose `--profile` on `reqbot ingest`.

**Scope — pipeline steps to update:**

| Step | What changes |
|------|-------------|
| Step B (`chunk_text.py`) | Load skip-section patterns from profile instead of hardcoded list |
| Step C (`llm_extract_requirements.py`) | Inject obligation verbs and domain tags from profile into extraction prompt |
| Step D.5 (`enrich_requirements.py`) | Inject domain tags and requirement type taxonomy into enrichment prompt |
| `pipeline/run_pipeline.py` | Accept `profile` parameter; pass to each step |
| `cli/reqbot.py` | Add `--profile` flag to `ingest` subcommand; default to `cybersecurity` |

**Threading pattern:**

```python
# run_pipeline.py
from core.profiles import load_profile

def run(pdf_path, ..., profile_name='cybersecurity'):
    profile = load_profile(profile_name)
    run_step_b(..., profile=profile)
    run_step_c(..., profile=profile)
    run_step_d5(..., profile=profile)
```

**Rules:**
- Profile object is passed through, never re-loaded mid-pipeline.
- All existing tests and smoke tests must pass with no `--profile` flag (default path).
- LLM prompt content must be semantically identical to today's prompts when the cybersecurity profile is active — do not rephrase prompts during this WP.

**Gate:**
- `reqbot ingest doc.pdf` (no flag) → identical output to pre-Phase-20 behavior.
- `reqbot ingest doc.pdf --profile cybersecurity` → identical output to above.
- A second (non-cybersecurity) profile YAML can be created for test purposes and load without errors (even if it produces meaningless extraction results).

---

### WP-20.4 — Schema Field Addition (`domain_profile`)

**Goal:** Add `domain_profile` to the normalized requirement JSONL and Qdrant payload so requirements are tagged with the profile used to extract them.

**Changes:**
- Step D (`parse_and_normalize.py`): write `domain_profile` field to normalized output.
- Step F (`embed_and_index.py`): include `domain_profile` in Qdrant payload.
- **Soft addition:** existing JSONL files are not rewritten. Existing Qdrant payloads are not updated. The field appears in new ingests going forward. A manual `reqbot reindex` (which reads from JSONL) will populate the field for any documents that have been re-normalized since WP-20.3 landed.

**Backward compatibility:**
- Any code that reads `domain_profile` from a payload must handle its absence gracefully (`payload.get('domain_profile', 'cybersecurity')`).
- API responses that include `domain_profile` should return `null` or `"cybersecurity"` (not crash) for requirements indexed before Phase 20.

**Gate:**
- A freshly ingested test document has `domain_profile: cybersecurity` in its JSONL and Qdrant payload.
- `reqbot trace <id>` for a pre-Phase-20 requirement does not error on missing `domain_profile`.
- `reqbot ask` results are unaffected (field is payload metadata, not a retrieval signal).

---

### WP-20.5 — Integration Gate

**Goal:** Confirm zero regression across all existing CLI commands and the GUI with the default cybersecurity profile active.

**Test matrix:**

| Command | Expected behavior |
|---------|------------------|
| `reqbot ask "multi-factor authentication"` | Same results as pre-Phase-20 |
| `reqbot trace <existing-req-id>` | Full detail, no crash on `domain_profile` field |
| `reqbot compare --doc1 ... --doc2 ... --topic ...` | Identical compare output |
| `reqbot evidence --topic ...` | Identical evidence groups |
| `reqbot docs` | Same doc list; new ingests show `domain_profile` |
| GUI demo walkthrough (7 steps from Phase 19 gate) | All steps clean |
| `reqbot ingest test.pdf --profile cybersecurity` | Same output as without flag |

**Gate:**
- All commands above pass without errors.
- No stale-state bugs introduced by profile loading.
- Phase 19 GUI demo walkthrough still completes cleanly (spot-check, not full re-run).

---

## Explicit Non-Goals for Phase 20

- **No non-cybersecurity profile actually working end-to-end.** The architecture supports it; a real second profile is Phase 21+ scope (if needed for checklist generation).
- **No GUI profile selector.** Profiles are an ingest-time concern. The GUI has no ingest capability yet.
- **No checklist generation.** That is Phase 21.
- **No reindex of the existing corpus.** The 45-doc corpus remains as-is. New ingests get `domain_profile`; old payloads fall back gracefully.
- **No changes to retrieval logic.** `domain_profile` is a payload field, not a retrieval filter (yet).
- **No API endpoint for profile management.** Profiles are config files on disk; no CRUD API needed in Phase 20.

---

## Success Gate (Phase 20)

1. `profiles/cybersecurity.yaml` exists and captures all values currently hardcoded in the pipeline.
2. `--profile` flag works on `reqbot ingest`; omitting it produces byte-for-byte identical JSONL to pre-Phase-20.
3. New ingests include `domain_profile: cybersecurity` in JSONL and Qdrant payload.
4. All existing CLI commands and the Phase 19 GUI demo walkthrough pass with zero regression.
5. The architecture is ready for Phase 21 to consume the profile for checklist item generation.

---

## Sequencing

| WP | Description | Gate before next |
|----|-------------|-----------------|
| 20.1 | Hardcoding audit (read-only) | Written list of hardcoded locations and values; alignment on profile vs. constant |
| 20.2 | Profile schema + cybersecurity profile + loader | Profile loads cleanly; fields match PRD spec |
| 20.3 | Profile-aware pipeline + `--profile` flag | Default path produces identical output; `--profile cybersecurity` explicit is also identical |
| 20.4 | `domain_profile` schema field (soft addition) | New ingests tagged; old payloads handled gracefully |
| 20.5 | Integration gate | Full CLI + GUI regression check passes |

**Do one WP at a time. Codex/Gemini review after each before proceeding.**
