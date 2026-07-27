# Profiles

A profile is a JSON file at `profiles/<name>.json` that configures ReqBot's pipeline for a
specific compliance domain. Today only `cybersecurity` is a real profile; see
[Adding a new profile](#adding-a-new-profile) before assuming a second one is a small change.

The loader (`core/profiles.py`) validates every field's type and rejects any field it doesn't
recognize — there is no way to sneak extra data through unvalidated. `core.profiles.load_profile()`
is the only supported way to read a profile; nothing else parses `profiles/*.json` directly.

## Schema

### Required fields

| Field | Type | Consumed by |
|---|---|---|
| `name` | `string` | Must match the filename (`profiles/foo.json` must have `"name": "foo"`) — checked last, after every other validation passes. |
| `obligation_verbs` | `string[]`, non-empty | Step C (`pipeline/llm_extract_requirements.py`) — substituted into the extraction prompt's `{obligation_verbs}` placeholder, joined with `", "`. This is the literal list of words the LLM is told signal an actionable requirement. |
| `skip_sections` | `string[]`, empty allowed | Chunking (`pipeline/chunk_text.py`) — section headings to exclude from the corpus (e.g. `"GLOSSARY"`, `"REFERENCES"`). **Only takes effect on the docling structure-aware layout mode.** The default legacy pymupdf chunking path has no section hierarchy to filter on and just logs a warning and no-ops on this field. If your ingest run doesn't pass `--layout-mode docling`, `skip_sections` is silently doing nothing. |
| `domain_tags` | `string[]`, non-empty | Step C's extraction prompt and Step D.5's enrichment prompt (`pipeline/enrich_requirements.py`) — the closed vocabulary the LLM must pick from when tagging a requirement. Also used by `pipeline/parse_and_normalize.py` (Step D) to silently drop any tag the LLM returned that isn't in this list. |
| `requirement_types` | `string[]`, non-empty | Same two extraction/enrichment prompts, and the same Step D drop-if-invalid behavior, but for the requirement's type classification instead of its tags. |

### Optional fields

| Field | Type | Default | Consumed by |
|---|---|---|---|
| `description` | `string` | `""` | Not consumed by the pipeline — human-readable only. |
| `version` | `string` or `null` | `null` | Not consumed by the pipeline — informational only. |
| `checklist_guidance` | `object` | `{}` | **Currently not consumed anywhere in the pipeline.** Validated (see below) and round-tripped through `load_profile()`, but no code in `services/checklist_service.py` or `pipeline/checklist_export.py` reads it yet — populating it today has no effect on generated checklists. Its only defined sub-field is `evidence_categories` (`string[]`), which is schema-validated the same way as the other list fields but is likewise unread. Treat this as a reserved-for-future field, not live configuration. |

### Validation rules

- **Unknown fields are rejected outright** — `load_profile()` raises `ValueError` on any key not in
  the required/optional lists above. There's no forward-compatible "extra fields are ignored" mode.
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

## Adding a new profile

1. Create `profiles/<name>.json` with the five required fields above, matching `name` to the
   filename.
2. Decide `obligation_verbs` and `domain_tags`/`requirement_types` for the new domain — these
   directly shape what Step C extracts and how Step D.5 classifies it, so get them right before a
   real ingest run rather than iterating against production data.
3. Pick `skip_sections` knowing it only applies under `--layout-mode docling` (see above) — if
   you're using the default pymupdf path, this field is a no-op for now.
4. Run `python3 cli/reqbot.py ingest <doc.pdf> --profile <name>` and expect a full extraction pass
   (no cache) per the operational note above.
5. `checklist_guidance` can be included for forward-compatibility but has no effect today — don't
   spend design time on it expecting a behavior change.
