# Profiles

A profile is a JSON file at `profiles/<name>.json` that configures ReqBot's pipeline for a
specific compliance domain. Today only `cybersecurity` is a real profile; see
[Adding a new profile](#adding-a-new-profile) before assuming a second one is a small change.

The loader (`core/profiles.py`) validates every top-level field's type and rejects any top-level
key it doesn't recognize. That guarantee doesn't extend below the top level, though: nested content
inside `checklist_guidance` other than its one defined sub-field (`evidence_categories`) is neither
type-checked nor rejected — see that field's row below. `core.profiles.load_profile()` is the only
supported way to read a profile; nothing else parses `profiles/*.json` directly.

## Schema

### Required fields

| Field | Type | Consumed by |
|---|---|---|
| `name` | `string` | Must match the filename (`profiles/foo.json` must have `"name": "foo"`) — checked last, after every other validation passes. |
| `obligation_verbs` | `string[]`, non-empty | Step C (`pipeline/llm_extract_requirements.py`) — substituted into the extraction prompt's `{obligation_verbs}` placeholder, joined with `", "`. This is the literal list of words the LLM is told signal an actionable requirement. |
| `skip_sections` | `string[]`, empty allowed | Chunking (`pipeline/chunk_text.py`) — section headings to exclude from the corpus (e.g. `"GLOSSARY"`, `"REFERENCES"`). **Only takes effect on the docling structure-aware layout mode.** The default legacy pymupdf chunking path has no section hierarchy to filter on and just logs a warning and no-ops on this field. If your ingest run doesn't pass `--layout-mode docling`, `skip_sections` is silently doing nothing. |
| `domain_tags` | `string[]`, non-empty | **Not Step C** — `PASS1_PROMPT_TEMPLATE` only asks the LLM for `source_quote`/`source_ref`, it never references tags. The real prompting happens in Step D.5's enrichment prompt (`pipeline/enrich_requirements.py`'s `{valid_tags}` placeholder) — that's where the LLM is actually told to pick from this vocabulary. `pipeline/parse_and_normalize.py` (Step D) then silently drops any tag Step D.5 returned that isn't in this list. (Step C's `validate_requirement()`/`process_chunk()` do accept a `valid_domain_tags` parameter, but since Pass-1's prompt never asks the LLM for a `domain_tags` field, that filter always runs against empty input today — effectively inert, not a live consumer.) |
| `requirement_types` | `string[]`, non-empty | Same story as `domain_tags`: Step D.5's enrichment prompt (`{valid_types}`) is the real consumer, Step D enforces it afterward, and Step C's equivalent parameter is inert for the same reason. |

### Optional fields

| Field | Type | Default | Consumed by |
|---|---|---|---|
| `description` | `string` | `""` | Not consumed by the pipeline — human-readable only. |
| `version` | `string` or `null` | `null` | Not consumed by the pipeline — informational only. |
| `checklist_guidance` | `object` | `{}` | **Currently not consumed anywhere in the pipeline.** Validated (see below) and round-tripped through `load_profile()`, but no code in `services/checklist_service.py` or `pipeline/checklist_export.py` reads it yet — populating it today has no effect on generated checklists. Its only defined sub-field is `evidence_categories` (`string[]`), which is schema-validated the same way as the other list fields but is likewise unread. Treat this as a reserved-for-future field, not live configuration. |

### Validation rules

- **Unknown top-level fields are rejected outright** — `load_profile()` raises `ValueError` on any
  top-level key not in the required/optional lists above. This does not apply recursively:
  `checklist_guidance` accepts arbitrary unvalidated nested keys other than `evidence_categories`
  (e.g. `{"checklist_guidance": {"typo": 123}}` loads without error).
- `obligation_verbs`, `domain_tags`, and `requirement_types` must be **non-empty** lists of strings —
  an empty list here would produce either a broken prompt or validation that silently
  accepts/rejects everything. `skip_sections` is the one list field allowed to be empty.
- Every list item must be a string; a non-string item anywhere raises `ValueError` naming the exact
  index.
- `name` in the file must match the filename stem exactly (`profiles/cybersecurity.json`'s `name`
  field must be `"cybersecurity"`) — checked only after every other check passes.
- Profile names can't contain path separators (`/` or `\`) — `load_profile()` rejects those before
  even trying to open a file.

## `profiles/test-domain.json` is not a second real domain

It exists purely as a minimal fixture for pipeline plumbing tests (`"Minimal test profile for
pipeline plumbing validation only. Not a real domain."` — its own `description` field says as
much). Don't treat it as precedent for what a second real profile should look like; it deliberately
has the bare minimum required fields and nothing else.

## Operational note: non-default profiles bypass Step C's cache

`pipeline/llm_extract_requirements.py`'s `run()` defaults to the `cybersecurity` profile when none
is passed. If you run with any other profile, Step C **always re-extracts from scratch** — the
prompt-hash cache that normally lets you resume an interrupted run without re-calling the LLM is
bypassed entirely for non-default profiles, because cached records don't yet track which profile
produced them (a known gap, not yet fixed). Budget for a full re-extraction, not a resumed one,
whenever testing a profile other than `cybersecurity`.

## Should you add a second profile right now?

Probably not yet (decision recorded 2026-07-27, see `docs/TODO_future_improvements.txt`'s
Decisions and Guardrails #8). Cybersecurity is meant to be the first domain, not the only one
(`docs/PRODUCT_PRD.md`'s PR-2 names `hr_policy`/`safety`/`finance`/`acquisition` as future
candidates) — but three things make now a bad time to actually build one: no source documents exist
yet for any candidate domain, testing a new profile is expensive (see the cache-bypass note above),
and the one existing profile still leaks cybersecurity-specific assumptions into supposedly generic
code (e.g. `evidence_service.py`'s synthesis prompt hardcodes NIST control-family vocabulary —
tracked as Phase 32's WP-32.7). Revisit once that's actually fixed, not before.

## Adding a new profile

1. Create `profiles/<name>.json` with the five required fields above, matching `name` to the
   filename.
2. Decide `obligation_verbs` (shapes what Step C's extraction prompt asks for) and
   `domain_tags`/`requirement_types` (shapes what Step D.5's enrichment prompt classifies into) for
   the new domain — get them right before a real ingest run rather than iterating against
   production data.
3. Pick `skip_sections` knowing it only applies under `--layout-mode docling` (see above) — if
   you're using the default pymupdf path, this field is a no-op for now.
4. Run `python3 cli/reqbot.py ingest <doc.pdf> --profile <name>` and expect a full extraction pass
   (no cache) per the operational note above.
5. `checklist_guidance` can be included for forward-compatibility but has no effect today — don't
   spend design time on it expecting a behavior change.
