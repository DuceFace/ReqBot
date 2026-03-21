# Qdrant Integration Plan — Code-Level Review

> Analysis by Claude after reading all pipeline scripts and test output.
> Evaluated against actual code, not just the abstract plan.

---

## Issues That Will Break Things If Not Addressed

### 1. `--source-pdf` arg for Step D needs the actual PDF file path, not a filename

The plan says "Add `--source-pdf` arg → compute document_id as SHA-256 of PDF
bytes." But Step D (`parse_and_normalize.py`) currently only receives:
- `requirements_jsonl` (the extracted reqs)
- `--chunks-jsonl` (chunk metadata)

It has **no access to the original PDF file**. To hash the PDF bytes, it needs
the full file path, not just a name string.

**Complication:** Step E (`aggregate_and_export.py`) already has a `--source-pdf`
arg, but it's just the filename string for metadata display (line 74). The
pipeline orchestrator passes `pdf_path.name` to it (run_pipeline.py:216).

**Fix:** Step D should receive `--source-pdf-path <path>` (the full PDF path for
hashing). Compute `document_id` (short hash), `document_hash_full` (full SHA-256),
and `source_pdf` (basename) all from that single path arg. This avoids the naming
collision with Step E.

### 2. `chunk_id` is consumed but not preserved in Step D output

Current Step D reads `chunk_id` from each raw requirement (line 170) and uses it
for page reference lookup (line 217). But the normalized output dict (lines
232-241) **does not include `chunk_id`**.

This matters because:
- The last-resort stable ID hash uses `chunk_id`
- It's useful for traceability in Qdrant payload
- Debugging provenance chains require it

**Fix:** Add `chunk_id` to the normalized output schema.

### 3. Dropping `confidence` will break Step E

ChatGPT said to drop `confidence` from the payload. But Step D already computes
it (lines 222-230) as a deterministic heuristic:
- -0.2 if no domain tags
- -0.2 if no source quote
- -0.1 if description < 20 chars
- -0.1 if no source ref

Step E reads `confidence` from the normalized JSONL and computes
`average_confidence` for the stats output (line 113-117).

**ChatGPT's own guidance was:** "If you want confidence, make it a simple,
explainable heuristic like has_source_ref (bool), has_domain_tags (bool),
quote_length." That is literally what the existing code already does.

**Recommendation:** Keep `confidence` in Step D output AND in the Qdrant payload.
It's already implemented, deterministic, and useful for filtering low-quality
results during retrieval. Removing working code for no functional benefit is
unnecessary churn.

### 4. `page_refs` → `page_start`/`page_end` change ripples into Step E

The plan changes the normalized schema from `page_refs: [47, 48]` to
`page_start: 47, page_end: 48`. Step E doesn't directly use `page_refs` for
computation (it just passes requirements through to final_output.json), so it
won't *break*, but the schema change should be documented and the downstream
consumers (Qdrant payload, ask.py citations) need to expect the new field names.

**This is actually simpler than it sounds.** Step D already has
`(page_start, page_end)` from `chunk_page_map` (line 218) and then expands it
to a list. Just stop expanding and store the two fields directly.

---

## Issues That Need Clarification

### 5. `ollama.embed()` vs `ollama.embeddings()` API

The plan says to use `ollama.embed()` from the `ollama` Python package. But the
API method name depends on the installed version:
- Older versions: `ollama.embeddings(model=..., prompt=...)`
- Newer versions: `ollama.embed(model=..., input=...)`

Also: the rest of the codebase uses raw `requests.post()` to call Ollama (Step C,
line 126-138). Using the `ollama` package for embeddings creates an inconsistency.

**Options:**
1. Use the `ollama` package for embed_and_index.py (cleaner API for embeddings)
2. Use raw `requests` for consistency with the rest of the codebase

Either works. Just verify the installed `ollama` package version before coding.
The raw API endpoint for embeddings is `POST /api/embed` (or `/api/embeddings`
in older Ollama versions).

### 6. The 70b model exact tag needs verification

The plan defaults ask.py to `llama3.3:70b`. But the extraction model uses a very
specific tag: `llama3.1:8b-instruct-q4_K_M`. The 70b model may have a similarly
specific tag. Verify with `ollama list` at implementation time.

### 7. Qdrant client may support string point IDs

The plan uses uuid5 conversion from requirement_id to get UUID point IDs. Modern
qdrant-client versions support string point IDs directly via `models.PointId`.
If supported, skip the uuid5 layer — just use requirement_id as the point ID.
Simpler, no namespace constant to maintain.

Verify with the installed qdrant-client version.

### 8. Stable ID: dedupe ordering must be explicit

Current code flow: validate/filter → deduplicate → assign sequential IDs.
New flow should be: validate/filter → deduplicate → assign stable hash IDs.

The plan implies this order but should state it explicitly. The dedupe key
(`source_ref::normalized_description`) is different from the stable ID input
(`document_id + source_ref + normalized_source_quote`), which is correct — they
serve different purposes. Dedupe removes semantic duplicates, stable IDs provide
deterministic identifiers for survivors.

---

## Things ChatGPT Got Wrong or Imprecise

### 9. "Remove confidence" was bad advice for this codebase

See issue #3 above. The existing confidence is exactly the kind of deterministic
heuristic ChatGPT recommended as acceptable. Removing it creates work (update
Step D + Step E) for negative value (lose a useful filter dimension).

### 10. "subprocess dispatch is fine for now" undersells the error handling need

ChatGPT and the plan both say subprocess dispatch in grcai.py is fine. It is,
but with one caveat: each subprocess needs proper returncode checking and error
reporting. If `run_pipeline.py` fails at Step C (LLM timeout), grcai.py needs
to surface that clearly, not just silently exit.

The current `run_pipeline.py` already handles this well (checks returncode per
step, calls sys.exit(1) on failure). grcai.py should follow the same pattern.

---

## Things the Plan Gets Right

- **JSONL as system of record, Qdrant as rebuildable index** — correct architecture
- **Stable IDs anchored to source_quote** — much more stable than description
- **nomic-embed-text (768-dim)** — appropriate for this use case
- **Deterministic embedding text format** with `\n\nEvidence:` separator — good
- **Retrieve-only default** for ask.py — smart for validation
- **Lean payload** — correct fields chosen
- **Filter normalization at query time** — prevents silent empty results
- **Phase ordering** (Step D first) — correct dependency chain
- **Single CLI with subcommands** — matches the user's packaging goal
- **Cosine distance** for Qdrant collection — standard for nomic-embed-text

---

## Revised Phase 1 Spec (incorporating fixes)

For reference, here's what Phase 1 should actually do given the code:

```
Step D modifications (parse_and_normalize.py):

1. New arg: --source-pdf-path <path_to_pdf>
   - Read PDF bytes → SHA-256
   - document_id = first 16 hex chars
   - document_hash_full = full SHA-256 hex
   - source_pdf = Path(path).name

2. Replace page_refs list with page_start/page_end integers
   - Already computed at line 218, just stop expanding to range()

3. Preserve chunk_id in normalized output

4. Replace sequential REQ-0001 IDs with stable hash IDs:
   - Normalize source_quote: lowercase, collapse whitespace, strip
   - Primary: SHA-256(document_id + source_ref + norm_quote)[:12]
   - Fallback: SHA-256(document_id + norm_quote)[:12]
   - Last resort: SHA-256(document_id + str(chunk_id) + req_type + norm_desc)[:12]
   - Prefix with "REQ-" for readability: REQ-a1b2c3d4e5f6

5. Keep confidence (already deterministic heuristic)

6. Keep deduplication as-is (runs before ID assignment)
```
