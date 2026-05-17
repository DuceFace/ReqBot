# Phase 8: The Compliance Research Workbench

> Goal: Transform the GRC AI system from a retrieval engine into a compliance research
> workstation that supports traceability, evidence generation, and cross-framework analysis.
>
> Status tracking: Update each task checkbox as work completes.

Phase 7 delivered the interactive shell (`grcai >`).
Phase 8 builds analyst workflows on top of that shell.

This phase focuses on **defensible compliance research** — not expanding the ingestion pipeline.
Pipeline steps (A–F2) remain unchanged.

**Phase 8 Status: COMPLETE — All subphases implemented and Gemini code-reviewed.**

---

## Architecture Principles

**Provenance First** — Every result must preserve: requirement text, document ID, page number,
surrounding context, and extraction source. The system must never produce an answer without
traceable evidence.

**No Hidden Deduplication** — Cross-document duplicates are valuable signal. NIST AC-2 + CNSSI AC-2
+ DoDI AC-2 returning together demonstrates cross-framework alignment. Phase 8 introduces result
grouping instead of suppression.

**Grouping by source_ref, not content hash** — ChatGPT proposed content hashing to identify
duplicate requirements. Rejected. DoDI and NIST will word the same control differently — hashes
won't match. The correct grouping key is the explicit control ID (`source_ref` like `"AC-2"`),
which already exists in the data model. For documents without structured control IDs, fall back
to cosine similarity thresholding at query time.

**Local by default** — All pipeline steps (PDF extraction, embeddings, retrieval) remain 100%
local. Remote synthesis is an opt-in capability, never enabled by default.

---

## Phase 8.1 — `trace` Command [x]

**Goal:** Trace the full provenance of a specific requirement — where it came from, what document,
what page, and which other frameworks say the same thing.

**Shell command:**
```
grcai > trace <requirement_id>
```

**Behavior:**
- Look up the requirement by `requirement_id` in Qdrant
- Display full provenance: document, page, source_ref, source_quote, extraction_model, run_timestamp
- Run a second query: find all requirements with the same `source_ref` across other documents
- Display related cross-framework matches

**UX example:**
```
grcai > trace REQ-a3f2c1d4e5b6

Requirement Trace
=================
ID:              REQ-a3f2c1d4e5b6
Description:     Accounts must be reviewed at least annually by the designated
                 account manager to verify they remain necessary and appropriate.

Provenance
----------
  Document:      NIST.SP.800-53r5
  Source ref:    AC-2(j)
  Page:          244
  Extracted by:  llama3.1:8b-instruct-q4_K_M
  Run date:      2026-03-07T14:32:01Z
  Authority:     3/5  (NIST)        ← shown when authority registry is loaded

Source Quote
------------
  "The organization reviews accounts for compliance with account management
   requirements at the organization-defined frequency."

Cross-Framework Matches (same source_ref: AC-2)
------------------------------------------------
  CNSSI.1253             AC-2       Page 187  [auth:4/5]
  DODI.8500.01           AC-2       Page 92   [auth:5/5]
```

**Deliverables:**
- [x] Add `do_trace` to `console.py`
- [x] Add `cmd_trace` to `grcai.py` (for single-command mode: `grcai.py trace <id>`)
- [x] Add `trace` subparser to argparse in `grcai.py`
- [x] Qdrant lookup by `requirement_id` payload field (scroll with filter, not vector search)
- [x] Second query: filter by same `source_ref` across all documents
- [x] Display formats: terminal (default), `--json`
- [x] Graceful handling if ID not found
- [x] `--context` flag for surrounding chunk text from grc_context (added during Gemini review)
- [x] Authority weight displayed in provenance and cross-framework matches (Phase 8.4 integration)

**Gemini code review: APPROVED** (2 bugs found and fixed — self-match trap, missing context flag)

---

## Phase 8.2 — `compare` Command [x]

**Goal:** Pull a control ID across all indexed documents and display the implementations
side-by-side. Exposes subtle differences in requirement language between frameworks.

**Shell command:**
```
grcai > compare <control_id_or_query>
```

**Input modes:**
- **Control ID** (e.g., `compare AC-2`) — exact `source_ref` match across all documents
- **Free text** (e.g., `compare "account management"`) — semantic search, then group results
  by `source_ref`

**UX example:**
```
grcai > compare AC-2

Cross-Framework Comparison: AC-2
=================================

NIST SP 800-53r5 (Page 244)  [auth:3/5]
-----------------------------
  Account managers must review accounts for compliance with account
  management requirements at an organization-defined frequency.

CNSSI 1253 (Page 187)  [auth:4/5]
----------------------
  Accounts must be reviewed annually by designated personnel to ensure
  continued business need and appropriate access levels.

DoDI 8500.01 (Page 92)  [auth:5/5]
-----------------------
  DoD information system accounts must undergo periodic review and
  revalidation per the applicable STIG requirements.

3 frameworks — 1 control ID
```

**Deliverables:**
- [x] Add `do_compare` to `console.py`
- [x] Add `cmd_compare` to `grcai.py`
- [x] Add `compare` subparser to argparse in `grcai.py`
- [x] Detect input mode: alphanumeric control ID pattern (e.g., `AC-2`, `IA-5(1)`) → exact match;
      otherwise → semantic search
- [x] Exact match path: scroll Qdrant with `source_ref` filter, no vector search needed
- [x] Semantic path: vector search, group results by `source_ref`, deduplicate within each source
- [x] `--top-k` applies to semantic search path only
- [x] Display formats: terminal (default), `--json`, `--markdown`
- [x] Session `document_id` filter respected (compare within a single doc)
- [x] Authority weight shown in document headers (Phase 8.4 integration)

**Gemini code review: APPROVED** (2 bugs found and fixed — case-sensitivity trap for control IDs,
Ollama API drift trap replaced with `ollama.Client().embed()`)

---

## Phase 8.3 — `evidence` Command [x]

**Goal:** Export a defensible evidence pack for SSPs, POA&Ms, and audit artifacts.
Takes a query, retrieves requirements, groups them by control ID, runs a compliance auditor
LLM synthesis for an executive summary, and exports a structured bundle an analyst can paste
directly into a compliance document.

**Shell command:**
```
grcai > evidence "query" [--format markdown|json] [--output FILE]
```

**UX example:**
```
grcai > evidence "password complexity requirements" --format markdown

Evidence Pack: password complexity requirements
===============================================
Generated: 2026-03-08T19:41:00Z
Query:     password complexity requirements
Results:   2 requirement groups, 5 sources

## Executive Summary

- IA-5(1) controls dominate the evidence (3 frameworks). All require minimum
  complexity including uppercase, lowercase, numeric, and special characters.
- IA-5(1)(h) (password history) appears only in NIST SP 800-53r5 — gap in
  CNSSI 1253 and DoDI 8500.01.
- No conflicting language identified across frameworks for core complexity rules.

---

## Requirement Group 1 — IA-5(1): Authenticator Management
...
```

**Deliverables:**
- [x] Add `do_evidence` to `console.py`
- [x] Add `cmd_evidence` to `grcai.py`
- [x] Add `evidence` subparser to argparse in `grcai.py`
- [x] Retrieve top-N results (session `top_k`, default 20)
- [x] Group by `source_ref` — requirements with same control ID form one group
- [x] Within each group, aggregate all sources (document + page)
- [x] Representative description: use the result with highest `confidence` score as the
      group's canonical description
- [x] `--format markdown` (default) or `--format json`
- [x] `--output FILE` — write to file; default prints to terminal
- [x] `--context` flag — include surrounding chunk text in each group (from grc_context)
- [x] Session filters (document_id, domain_tag, requirement_type) respected
- [x] Header block: query, timestamp, group count, source count
- [x] LLM Executive Summary via `_EVIDENCE_AUDITOR_PROMPT` — compliance auditor persona,
      flags control family gaps and cross-framework conflicts (added after Gemini review)
- [x] Authority column in sources table when registry is loaded (Phase 8.4 integration)
- [x] Remote synthesis warning banner in `do_evidence` (fires once per session)

**Gemini code review: APPROVED** after 3 rounds:
1. Silent filter failure fixed (`domain_tag` → `domain_tags` list, `action="append"`)
2. Subprocess amnesia fixed (warning banner moved to `console.py`, `self._remote_synthesis_warned`)
3. Missing AI synthesis added (`_EVIDENCE_AUDITOR_PROMPT`, `raw_prompt` bypass in `synthesis.py`)
4. Warning banner also added to `do_evidence` (missed on first pass — evidence always synthesizes)

---

## Phase 8.4 — Authority Metadata Registry [x]

**Goal:** Give analysts visibility into document precedence. Helps answer "which framework
is authoritative for this control?" without changing the fundamental retrieval behavior.

**Design decision:** Authority is a light ranking modifier, not a hard filter. It never
hides results — it nudges scoring when multiple equivalent results compete.

**Registry file:** `~/.grcai/authority.json` — manually maintained, loaded by config.py

**Schema:**
```json
{
  "documents": [
    {
      "source_pdf": "NIST.SP.800-53r5.pdf",
      "document_type": "framework",
      "framework": "NIST",
      "revision": "Rev 5",
      "publication_date": "2020-09",
      "authority_weight": 3
    },
    {
      "source_pdf": "DODI_8500.01.pdf",
      "document_type": "policy-directive",
      "framework": "DoD",
      "revision": "2014-03-14",
      "publication_date": "2014-03",
      "authority_weight": 5
    }
  ]
}
```

**Authority weight guidance:**
```
5 — Mandatory DoD policy directive (DoDI, DoDD)
4 — CNSSI overlay / DoD instruction supplement
3 — NIST SP framework
2 — Guidance / best practice (STIG, CIS)
1 — Informational reference
```

**Deliverables:**
- [x] Add `authority_registry` key to `~/.grcai/config.json` (path to authority.json)
- [x] Load authority registry in `config.py` — optional, graceful if missing
- [x] `AuthorityEntry` dataclass in `config.py`; `authority_weight()` / `authority_framework()` helpers on `GrcaiConfig`
- [x] `do_authority` in `console.py` — display the current registry (or example JSON if missing)
- [x] `analyze` enhanced: when authority registry is loaded, show requirements by framework
      group (NIST, DoD, CNSSI, etc.) and by document_type
- [x] Authority weight exposed in `trace`, `compare`, and `evidence` output
- [x] Authority weight NOT wired into retrieval scoring in Phase 8 — display only for now;
      scoring integration is Phase 8+ / backlog

**Gemini code review: APPROVED**

---

## Phase 8.5 — Remote Synthesis Backend [x]

**Goal:** Allow the synthesis step to optionally use a hosted LLM (Claude, GPT-4o) for
higher-quality answers, while keeping all retrieval, indexing, and embedding 100% local.

**Security model:**
- Local Ollama is the default and never changes without explicit configuration
- Remote backend requires an explicit config change — it cannot be enabled accidentally
- First-use warning banner per shell session if remote is configured (lives in `console.py`,
  not `synthesis.py` — subprocess amnesia would break a global in synthesis.py)
- The system never sends raw documents to an external API — only the retrieved evidence
  snippets and the user's query (the same text visible on screen) are sent
- Data handling decision rests entirely with the operator

**Config additions to `~/.grcai/config.json`:**
```json
{
  "synthesis_backend": "local",
  "remote_provider": "anthropic",
  "remote_model": "claude-sonnet-4-6",
  "api_key_env": "ANTHROPIC_API_KEY"
}
```

**Supported remote providers:** `anthropic`, `openai`

**Deliverables:**
- [x] Add `synthesis_backend`, `remote_provider`, `remote_model`, `api_key_env` to `config.py`
- [x] Create `synthesis.py` — pluggable backend module:
  - `synthesize_local(prompt, model, ollama_url, *, raw_prompt)` — existing Ollama flow extracted here
  - `synthesize_remote(prompt, provider, model, api_key, *, raw_prompt)` — Anthropic / OpenAI
  - `synthesize()` — router; `raw_prompt` param allows specialist callers (e.g., evidence auditor prompt) to bypass standard SYNTHESIS_PROMPT template
- [x] Update `ask.py` to call `synthesis.py` instead of Ollama directly
- [x] Warning banner in `console.py` `do_ask` (once per session, not once per query)
- [x] Warning banner also in `console.py` `do_evidence` (evidence always synthesizes)
- [x] `grcai init` adds optional remote configuration prompts (skippable with Enter)
- [x] No remote provider libraries installed by default — import guarded with helpful error:
  `[-] Remote synthesis requires 'anthropic' package: pip3 install anthropic`
- [x] API key missing at runtime falls back to local with printed warning

**Gemini code review: APPROVED**

---

## Technical Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Grouping key | `source_ref` (control ID) | Content hashes fail on paraphrased identical requirements |
| Grouping fallback | Cosine similarity threshold | For docs without structured control IDs |
| Authority weight use | Display only in Phase 8 | Ranking integration needs careful calibration |
| Authority registry | Manual JSON file | LLM inference of precedence risks false positives |
| Remote synthesis default | Local (Ollama) | Security by default; remote is explicit opt-in |
| Remote synthesis scope | Synthesis step only | Retrieval, embeddings, indexing always local |
| Remote warning banner | Lives in `console.py` | `synthesis.py` is re-imported fresh per subprocess; globals there are ephemeral |
| Subprocess refactor | Stays in Phase 9.1 | Phase 8 is pure query work — no pipeline changes needed |
| New modules | `synthesis.py` | Everything else lives in `console.py` / `grcai.py` |
| Evidence auditor prompt | `raw_prompt` bypass | Specialist prompts shouldn't fight the standard SYNTHESIS_PROMPT grounding rules |

---

## Files Changed

| File | Action |
|------|--------|
| `console.py` | Add `do_trace`, `do_compare`, `do_evidence`, `do_authority`; `_remote_synthesis_warned` session flag; `analyze` framework breakdown |
| `grcai.py` | Add `cmd_trace`, `cmd_compare`, `cmd_evidence`; extend `cmd_init` for remote synthesis; `_EVIDENCE_AUDITOR_PROMPT` |
| `config.py` | Add `AuthorityEntry` dataclass; authority registry loading; remote synthesis fields; `authority_weight()` / `authority_framework()` helpers |
| `ask.py` | Route synthesis through `synthesis.py`; load remote config at runtime |
| `synthesis.py` | New — pluggable synthesis backend (local Ollama + remote providers); `raw_prompt` bypass |

Pipeline scripts (A–F2) are **not touched** in Phase 8.

---

## Success Criteria

- [x] `trace <requirement_id>` displays full provenance and cross-framework matches
- [x] `compare AC-2` pulls AC-2 from all indexed documents side-by-side
- [x] `compare "account management"` runs semantic search and groups by source_ref
- [x] `evidence "query"` produces a Markdown evidence pack with grouped sources and LLM executive summary
- [x] `evidence "query" --output report.md` writes to file
- [x] `evidence "query" --context` includes surrounding chunk text
- [x] `analyze` shows framework-level breakdowns when authority registry is present
- [x] `synthesis_backend: remote` with `anthropic` provider synthesizes via Claude API
- [x] Warning banner appears when remote synthesis is active (once per session, in shell only)
- [x] `synthesis_backend: local` (default) behavior is 100% unchanged
- [x] All new shell commands survive bad flags (argparse death trap respected)
- [x] Session filters (document_id, domain_tag, requirement_type) respected by all new commands
- [x] Pipeline scripts (A–F2) unmodified

---

## Backlog / Post-Phase 8

**Knowledge Graph Relationships** (`derived_from`, `superseded_by`, `broader_than`):
Deferred — LLM-based inference risks false positives. Requires curated crosswalk datasets.

**Revision Diffing** (`grcai diff NIST.SP.800-53r4 NIST.SP.800-53r5`):
Deferred — reliable diffing requires matching controls by explicit IDs, not vector similarity.

**Authority weight scoring integration** (use weight as retrieval ranking modifier):
Deferred — needs calibration against real analyst queries to avoid perturbing good results.

**PDF evidence report export** (`evidence "query" --format pdf`):
Deferred — requires reportlab or weasyprint dependency.
