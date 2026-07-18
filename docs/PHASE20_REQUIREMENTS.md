# ReqBot — Phase 20: Domain Profile Foundation

**Status:** Planning
**Date:** 2026-05-17
**Preceded by:** Phase 19 (GUI Capability Expansion — COMPLETE 2026-05-17)
**Followed by:** Phase 21 (Checklist Generator MVP — defined in `docs/PRODUCT_PRD.md`)

---

## Framing

**Phase 20 is about externalizing existing assumptions, not inventing new domain behavior.**

The real job is narrow:

1. Find everything cybersecurity-specific that is currently hardcoded in the pipeline.
2. Move it into one profile file.
3. Prove default behavior does not regress.

If a change would require new algorithmic logic or a new capability, it belongs in Phase 21+. Phase 20 optimizes for safe refactoring, not feature ambition.

---

## Context and Motivation

ReqBot's product vision (`docs/PRODUCT_PRD.md`) is a domain-configurable requirements platform, not a cybersecurity-only tool. The Phase 16 service layer reorganization and Phase 19 GUI expansion have stabilized the architecture. Phase 20 is the right time to externalize hardcoded assumptions before checklist generation (Phase 21) lands — checklists need a profile concept to generate domain-appropriate items.

The risk is regression: the existing cybersecurity corpus (45 docs, ~32k requirements) is working well. Phase 20 must not change extraction, enrichment, or retrieval behavior for the default cybersecurity profile.

---

## Goal

Externalize hardcoded cybersecurity vocabulary and taxonomy (obligation verbs, skip-section patterns, domain tags, requirement type taxonomy) into a configurable profile system. After Phase 20:

- A `profiles/cybersecurity.json` profile captures everything the pipeline currently hard-codes.
- A `--profile <name>` flag on `reqbot ingest` selects the active profile.
- Omitting `--profile` falls back to the `cybersecurity` profile — no behavior change for existing workflows.
- New ingests record `domain_profile` in the JSONL payload. Existing JSONL is untouched until a manual reindex.
- The architecture is ready for Phase 21 (checklist generation), which will consume the profile to generate domain-appropriate checklist items.

**What goes in a profile (vocabulary/taxonomy/prompt-parameter material):**
- Obligation verbs
- Skip-section patterns
- Domain tag taxonomy
- Requirement type taxonomy
- Checklist guidance seeds

**What stays in code (algorithmic behavior):**
- Extraction control flow
- Parser logic
- Normalization rules that are structural, not domain-specific
- Confidence scoring heuristics that depend on document structure

This boundary must be respected throughout Phase 20. If something is algorithmic, it does not go in the profile.

---

## Architecture Rules

These rules are unchanged from Phases 18–19 and apply throughout Phase 20.

1. **Service layer is the source of truth.** Profile loading belongs in a new `core/profiles.py` module, callable by both CLI and API. No profile logic in route handlers.
2. **CLI and API share the same backend paths.** `reqbot ingest --profile cybersecurity` and a future `POST /api/ingest` call the same pipeline functions.
3. **No behavior change for the default profile.** Through WP-20.3, the default cybersecurity profile must produce semantically identical extraction and enrichment output to pre-Phase-20. WP-20.4 explicitly adds the new `domain_profile` field — that single addition is the only allowed JSONL difference after Phase 20.
4. **No new pip dependencies.** Profiles use JSON and stdlib `json` — no PyYAML. JSON is unambiguous, has no new dependency, and is easier to validate programmatically. TOML is not applicable here (it requires `tomllib`, which parses TOML, not YAML or JSON).
5. **Profiles are configuration, not code.** Domain-specific vocabulary lives in profile files, not scattered across pipeline scripts. Algorithmic behavior remains in code.
6. **Loader contract is strict.** The profile loader validates required fields, applies defaults for optional fields, and fails fast with a clear error on unknown or malformed fields — not a silent pass-through dict.

---

## Work Package Plan

### WP-20.1 — Hardcoding Audit

**Goal:** Locate every place cybersecurity-specific vocabulary is currently hardcoded in the pipeline. This is a read-only research WP — no code changes.

**What to look for:**

| Category | Examples | Likely locations |
|----------|----------|-----------------|
| Obligation verbs | `shall`, `must`, `will`, `is required to` | `pipeline/llm_extract_requirements.py` (extraction prompt) |
| Skip-section patterns | `GLOSSARY`, `REFERENCES`, `ACRONYMS`, `DEFINITIONS` | `pipeline/chunk_text.py` |
| Domain tag taxonomy | `access_control`, `audit_logging`, `incident_response` | `pipeline/llm_extract_requirements.py`, `pipeline/enrich_requirements.py` |
| Requirement type taxonomy | `procedural`, `technical`, `administrative` | extraction/enrichment prompts |
| Prompt language | "cybersecurity", "DoD", "NIST" in LLM prompts | extraction and enrichment prompt strings |

**Explicitly out of scope for the audit:** Confidence scoring heuristics and normalization rules that depend on document structure — these are algorithmic behavior that stays in code regardless of what the audit finds.

**Output:** A concise written list (code locations + current hardcoded values) that drives WP-20.2 and WP-20.3 scoping. No code changes in this WP.

**Gate:**
- Audit complete; hardcoded vocabulary documented.
- Alignment on which values are vocabulary/taxonomy (→ profile) vs. universal pipeline constants or algorithmic behavior (→ stays in code).

---

### WP-20.2 — Profile Schema and Cybersecurity Profile

**Goal:** Define the profile file format, create `profiles/cybersecurity.json`, and implement a strict loader in `core/profiles.py`.

**Format decision:** JSON, stdlib `json`. No new dependencies.

**Profile schema (`profiles/cybersecurity.json`):**

```json
{
  "name": "cybersecurity",
  "description": "Cybersecurity, RMF, and compliance requirements (DoD/NIST/CNSSI/AFI)",
  "obligation_verbs": [
    "shall", "must", "will", "is required to", "is responsible for"
  ],
  "skip_sections": [
    "GLOSSARY", "REFERENCES", "ACRONYMS", "DEFINITIONS",
    "ABBREVIATIONS", "TABLE OF CONTENTS"
  ],
  "domain_tags": [
    "access_control", "audit_logging", "configuration_management",
    "identification_authentication", "incident_response",
    "media_protection", "personnel_security", "physical_protection",
    "risk_assessment", "system_communications_protection",
    "system_information_integrity"
  ],
  "requirement_types": [
    "procedural", "technical", "administrative", "policy"
  ],
  "checklist_guidance": {
    "evidence_categories": [
      "policy", "procedure", "system_configuration",
      "logs", "tickets", "interviews", "training_records"
    ]
  }
}
```

**`skip_sections` note:** This field is present in the schema and validated by the loader, but **not consumed by any pipeline step in Phase 20**. No skip-section filtering currently exists in `chunk_text.py` — wiring it would be new behavior, not externalization. The field is reserved config; see Post-Phase-20 Backlog below.

**Loader contract (`core/profiles.py`):**

```python
REQUIRED_FIELDS = {"name", "obligation_verbs", "skip_sections", "domain_tags", "requirement_types"}
OPTIONAL_FIELDS = {"description", "checklist_guidance", "version"}

def load_profile(name: str) -> dict:
    """
    Load a named profile from profiles/<name>.json.
    Raises ValueError on missing required fields or unknown fields.
    Returns a validated profile dict.
    """

def default_profile() -> dict:
    """Returns the cybersecurity profile. Used when --profile is not specified."""
```

- Unknown fields → `ValueError` (fail fast, don't silently accept)
- Missing required fields → `ValueError` with field name
- Missing optional fields → filled with documented defaults (e.g. empty `checklist_guidance`)
- Profile name must match file stem — validate on load

**Profile versioning note:** Reserve room in the schema for a future `domain_profile_version` field (optional, ignored in Phase 20). Do not implement versioning logic now, but do not make the schema hostile to adding it later. Adding `"version": "1.0"` to `cybersecurity.json` is acceptable if it makes the forward-compat story cleaner.

**Gate:**
- `profiles/cybersecurity.json` exists and round-trips through the loader without errors.
- `load_profile("cybersecurity")` returns a validated dict.
- `load_profile("nonexistent")` raises a clear `FileNotFoundError`.
- `load_profile` with a profile missing a required field raises `ValueError`.
- Profile fields match the PRD `PR-12` spec.

---

### WP-20.3 — Profile-Aware Pipeline Integration

**Goal:** Thread the active profile through pipeline steps that currently hardcode cybersecurity vocabulary, and expose `--profile` on `reqbot ingest`.

**Scope — pipeline steps to update:**

| Step | What changes |
|------|-------------|
| Step B (`chunk_text.py`) | No behavior change in Phase 20. `skip_sections` is loaded and validated as reserved profile configuration — no existing skip-section filter exists in `chunk_text.py` to externalize. |
| Step C (`llm_extract_requirements.py`) | Inject `obligation_verbs` and `domain_tags` from profile into extraction prompt |
| Step D.5 (`enrich_requirements.py`) | Inject `domain_tags` and `requirement_types` from profile into enrichment prompt |
| `pipeline/run_pipeline.py` | Accept `profile_name` parameter; call `load_profile()`; pass dict to each step |
| `cli/reqbot.py` | Add `--profile` flag to `ingest` subcommand; default `"cybersecurity"` |

**Threading pattern:**

```python
# run_pipeline.py
from core.profiles import load_profile

def run(pdf_path, ..., profile_name='cybersecurity'):
    profile = load_profile(profile_name)   # load once, pass through
    run_step_b(..., profile=profile)
    run_step_c(..., profile=profile)
    run_step_d5(..., profile=profile)
```

**Rules:**
- Profile object is loaded once and passed through — never re-loaded mid-pipeline.
- LLM prompt content must be semantically identical to today's prompts when the cybersecurity profile is active. Do not rephrase prompts in this WP — thread the values, don't redesign the prompts.
- A second non-cybersecurity profile JSON may be created for loader and plumbing validation only. It does not need to produce meaningful extraction results. Do not use it to claim a second domain "works."

**Parity target through WP-20.3:** Same extracted requirements, same normalized content, same enrichment behavior, same retrieval behavior as pre-Phase-20. The only allowed delta is the single `domain_profile` field added in WP-20.4.

**Gate:**
- `reqbot ingest doc.pdf` (no flag) → semantically identical output to pre-Phase-20 (same requirements, same fields, same values — `domain_profile` field not yet present at this WP).
- `reqbot ingest doc.pdf --profile cybersecurity` → identical to above.
- A second test profile JSON loads without error (loader and plumbing validation only).

---

### WP-20.4 — Schema Field Addition (`domain_profile`)

**Goal:** Add `domain_profile` to normalized requirement JSONL and Qdrant payload so requirements are tagged with the profile used to extract them. This WP introduces the only intentional JSONL difference from pre-Phase-20.

**Changes:**
- Step D (`parse_and_normalize.py`): write `domain_profile` field (string) to normalized output, sourced from the active profile's `name` field.
- Step F (`embed_and_index.py`): include `domain_profile` in Qdrant payload.
- **Soft addition:** existing JSONL files are not rewritten. Existing Qdrant payloads are not updated. The field appears in new ingests going forward. A manual `reqbot reindex` will populate it for any previously-normalized documents.

**API contract for missing `domain_profile` (locked):**

Any API response field that surfaces `domain_profile` must return the string `"cybersecurity"` — not `null`, not omit the field — for requirements indexed before Phase 20. Use `payload.get("domain_profile", "cybersecurity")` everywhere this field is read. This default is chosen because all pre-Phase-20 requirements were extracted using cybersecurity assumptions.

**Gate:**
- A freshly ingested test document has `"domain_profile": "cybersecurity"` in its JSONL and Qdrant payload.
- `reqbot trace <id>` for a pre-Phase-20 requirement returns `"domain_profile": "cybersecurity"` (fallback, not a crash or null).
- `reqbot ask` results are unaffected (field is payload metadata, not a retrieval signal).

---

### WP-20.5 — Integration Gate

**Goal:** Confirm zero regression across all existing CLI commands and the GUI with the default cybersecurity profile active.

**Test matrix:**

| Command | Expected behavior |
|---------|------------------|
| `reqbot ask "multi-factor authentication"` | Same results as pre-Phase-20 |
| `reqbot trace <existing-req-id>` | Full detail; `domain_profile` returns `"cybersecurity"` |
| `reqbot compare --doc1 ... --doc2 ... --topic ...` | Identical compare output |
| `reqbot evidence --topic ...` | Identical evidence groups |
| `reqbot docs` | Same doc list; new ingests show `domain_profile` |
| GUI demo walkthrough (spot-check, not full re-run) | No errors or regressions |
| `reqbot ingest test.pdf --profile cybersecurity` | Same output as without flag (plus `domain_profile` field) |

**Gate:**
- All commands above pass without errors.
- `domain_profile` appears in new ingest output and falls back cleanly for old payloads.
- Phase 19 GUI spot-check passes.

---

## Explicit Non-Goals for Phase 20

- **No working second domain profile.** The architecture supports it; a real second domain is Phase 21+ scope. The Phase 20 test profile is a loader/plumbing check only.
- **No GUI profile selector.** Profiles are an ingest-time concern. The GUI has no ingest capability.
- **No checklist generation.** That is Phase 21.
- **No corpus reindex.** The 45-doc corpus remains as-is. New ingests get `domain_profile`; old payloads fall back to `"cybersecurity"`.
- **No retrieval filtering by `domain_profile`.** The field is payload metadata only in Phase 20.
- **No API endpoint for profile management.** Profiles are config files on disk.
- **No profile versioning logic.** Reserve the schema field; do not implement it.
- **No skip-section filtering.** `skip_sections` is reserved config in the profile schema but no corresponding filter exists in `chunk_text.py` to externalize. Adding one would be new behavior. Deferred to Phase 21+.

---

## Success Gate (Phase 20)

1. `profiles/cybersecurity.json` exists and captures all vocabulary currently hardcoded in the pipeline.
2. `core/profiles.py` loader is strict: validates required fields, rejects unknown fields, fails fast.
3. `--profile` flag works on `reqbot ingest`; omitting it produces semantically identical output to pre-Phase-20 (only addition: `domain_profile` field from WP-20.4).
4. New ingests include `"domain_profile": "cybersecurity"` in JSONL and Qdrant payload; pre-Phase-20 payloads return `"cybersecurity"` via fallback — never `null`.
5. All existing CLI commands and a spot-check GUI run pass with zero regression.
6. The architecture is ready for Phase 21 to consume the profile for checklist item generation.

---

## Sequencing

| WP | Description | Gate before next |
|----|-------------|-----------------|
| 20.1 | Hardcoding audit (read-only) | Written list of vocabulary locations; vocabulary vs. algorithmic boundary agreed |
| 20.2 | Profile schema + `cybersecurity.json` + strict loader | Loader validates correctly; required/optional/unknown fields all handled |
| 20.3 | Profile-aware pipeline + `--profile` flag | Default path produces semantically identical output; loader/plumbing test profile loads cleanly |
| 20.4 | `domain_profile` schema field (soft addition) | New ingests tagged; old payloads return `"cybersecurity"` fallback |
| 20.5 | Integration gate | Full CLI regression + GUI spot-check pass |

**Do one WP at a time. Codex/Gemini review after each before proceeding.**

---

## Post-Phase-20 Backlog

### Skip-Section Filtering (Phase 21+)

Implement profile-based skip-section filtering after Phase 20 parity is complete. Filtering
should be section-title based, profile-driven, logged, tested against glossary/references/
acronyms/table-of-contents cases, and documented as behavior-changing because it may alter
extraction counts.

The `skip_sections` field in `profiles/cybersecurity.json` (populated in WP-20.2) serves as
the configuration source. Implementation belongs in Step B (`chunk_text.py`) for the
structure-aware path and may require a separate handling decision for the legacy fixed-size
chunker (which has no section-title awareness).

### `REQBOT_PROFILE` Environment Variable (Phase 21+)

Add `REQBOT_PROFILE` to the `REQBOT_*` env var layer in `core/config.py` so the active
profile can be set without a CLI flag (useful for CI, scripted ingestion, and future API
calls). Default remains `"cybersecurity"`. Natural follow-on once WP-20.3 wires the `--profile`
CLI flag — the config layer precedence would be: hardcoded default → config.json → env var →
CLI flag.
