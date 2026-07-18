# ReqBot — Phase 19.5: Test Infrastructure Foundation

**Status:** Planning
**Date:** 2026-06-25
**Preceded by:** Phase 19 (GUI Capability Expansion — COMPLETE 2026-05-17)
**Followed by:** Phase 20 (Domain Profile Foundation)

---

## Framing

Phase 19.5 is a guardrail phase, not a feature phase. It exists because the current workflow
has Claude and Codex spending review cycles on issues that automation should catch first.

The goal is a minimal, working test suite and CI pipeline that changes the review contract from:

> "Codex, inspect this diff and find everything wrong."

to:

> "Syntax, formatting, and service logic are already verified. Codex reviews architecture,
> edge cases, and maintainability."

**Scope constraint:** Test the code that exists today without requiring live Ollama or Qdrant.
Integration tests against live infra are a future concern. Phase 19.5 targets unit-testable
logic only: pure functions, JSONL I/O, service orchestration with mocked dependencies.

---

## Non-Goals

- 100% code coverage (visibility only — no threshold enforced)
- Testing pipeline Steps A–F end-to-end (requires PDF, LLM, Qdrant)
- Testing the frontend (Vite/React) — separate toolchain
- Testing the interactive shell (`cli/console.py`)
- Enforcing mypy/pyright — the codebase needs annotation work first; defer to a later phase
- Testing `core/profiles.py` here — that module doesn't exist yet; Phase 20.2 writes it
  test-first
- Fixing all historical ruff findings — we set a baseline, not a full cleanup

---

## Architecture Rules (unchanged from Phase 19)

1. Tests live in `tests/` at the repo root. No test files scattered into source packages.
2. Fixtures live in `tests/fixtures/` as static JSON/JSONL files. No generated fixtures.
3. No new production dependencies. `pytest`, `ruff`, `pytest-cov` go in `requirements-dev.txt` only.
4. Services are tested with mocked dependencies — never hit live Qdrant or Ollama in CI.
5. CI workflow must pass on a cold machine with no config file and no running services.
6. Mock at the import site, not the origin module (see WP-19.5.3).

---

## Work Package Plan

### WP-19.5.1 — Scaffolding

**Goal:** Create the test directory structure, fixture files, conftest, dev requirements,
ruff config, and a CI workflow that runs pytest and ruff. Includes one smoke test to prove
collection, imports, and CI execution all work end-to-end.

**Deliverables:**

```
requirements-dev.txt              # pinned: pytest==X.Y.Z, ruff==X.Y.Z, pytest-cov==X.Y.Z
pyproject.toml                    # ruff config section only (see below)
tests/
  __init__.py
  conftest.py                     # sys.path injection (tech debt; replace with pip install -e . later)
  test_smoke.py                   # one trivial test — proves harness works
  fixtures/
    sample_chunks.jsonl           # 3–5 realistic Step B chunk records
    sample_normalized_reqs.jsonl  # 3–5 realistic normalized requirement records (schema v2.0)
    sample_search_results.json    # 3–5 realistic ask_service result dicts
.github/workflows/ci.yml          # separate lint + test jobs; concurrency cancel; read-only perms
```

**`sys.path` injection note:** `conftest.py` will add the repo root to `sys.path` so that
`from services.ask_service import ...` works without an installed package. This is acceptable
technical debt for now. The permanent solution is a `pyproject.toml` with `pip install -e .`
— defer to a future phase when packaging is addressed.

**Ruff config (`pyproject.toml`):**

Start with correctness-only rules. Do not attempt to fix all historical findings — establish
a clean baseline for new code only.

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
exclude = [
    ".git",
    "archive",
    "Backups",
    "dist",
    "build",
    "__pycache__",
]

[tool.ruff.lint]
# E4: import errors  E7: statement errors  E9: runtime errors  F: pyflakes  I: isort
select = ["E4", "E7", "E9", "F", "I"]
```

If the initial `ruff check .` produces findings in active source directories (`cli/`, `core/`,
`services/`, `api/`, `pipeline/`):

- Fix low-risk correctness findings (undefined names, unused imports, import order) inline.
- If total remediable findings exceed **20**, do not fix them in this WP. Instead, suppress
  them with targeted per-file ignores in `pyproject.toml` and create a tracking issue:

```toml
[tool.ruff.lint.per-file-ignores]
"pipeline/some_module.py" = ["F401", "E741"]
```

- Prefer `per-file-ignores` in `pyproject.toml` over inline `# noqa` comments —
  suppressions stay centralized and visible in one place.
- Only use inline `# noqa` for a single isolated finding where a per-file rule would
  be overly broad.
- Do not touch `archive/` or `Backups/`.

**Smoke test (`tests/test_smoke.py`):**

```python
def test_test_harness_runs() -> None:
    assert True
```

**Fixture content rules:**
- Records must be structurally valid (all required fields present) but content is synthetic.
- `sample_normalized_reqs.jsonl` must include the full schema v2.0 field set:
  `req_id`, `source_quote`, `source_ref`, `source_pdf`, `document_id`,
  `section_ref_path`, `section_title_path`, `parent_section_ref`, `parent_context`,
  `child_section_refs`, `description`, `domain_tags`, `requirement_type`.
- No real document content — use obviously synthetic placeholder text.

**CI workflow (`.github/workflows/ci.yml`):**

```yaml
on: [push, pull_request]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements-dev.txt
      - run: ruff check .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest tests/ -v --cov=core --cov=services --cov=pipeline --cov-report=term-missing
```

**Gate:**
- `pytest tests/` collects and passes the smoke test.
- `ruff check .` passes with the baseline config.
- CI workflow runs green on a push to the branch (both lint and test jobs).

---

### WP-19.5.2 — Easy-Win Unit Tests

**Goal:** Tests for the three modules with no external dependencies: `core/config.py`,
`services/docs_service.py`, and the normalization/dedup logic in
`pipeline/parse_and_normalize.py`.

**Test targets:**

**`core/config.py`:**
- Default values load when no config file is present
- Config file values override defaults
- Environment variables override config file values
- Unknown env vars are ignored (no crash)
- Missing `processed_dir` resolves to the documented default

**`services/docs_service.py`:**
- Empty directory returns empty list
- Valid JSONL files are scanned and requirement counts returned
- "Most recent" file selection is by **file modification time** (mtime) — this is the
  documented contract; note that mtime can be affected by file copies and git checkouts,
  which is acceptable for now
- Multiple JSONL files for the same document stem: the one with the latest mtime is kept
- Missing `processed_dir` path raises a clear error (not a silent empty list)

**Negative / failure-path cases for `docs_service` (required):**
- Empty file (0 bytes) — handled without crash
- File containing blank lines — skipped gracefully
- Malformed JSON line — line skipped, rest of file processed; **filename and line number
  logged**; parse-error count returned or recorded so callers can detect partial corruption
- Partially written final line (simulate interrupted write) — treated as malformed per above
- File with missing required fields — document counted with 0 requirements, not a crash
- **Observable corruption contract:** a JSONL file with N valid lines and M malformed lines
  must never appear to be a clean N+M-record document. The parse-error count must be
  non-zero and accessible to the caller or visible in logs.

**`pipeline/parse_and_normalize.py`:**
- `source_quote` required gate: record without `source_quote` is rejected
- Dedup: exact-duplicate `source_quote` values produce a single output record
- `req_id` stability: same `source_quote` + `source_pdf` input always produces the same ID
- Schema v2.0 hierarchy fields populated correctly from the chunk hierarchy map
- Record missing optional hierarchy fields normalizes without crash (fields default to empty)

**Negative cases for normalize (required):**
- Empty input JSONL → empty output, no crash
- Input with all records failing validation → zero output records, failures logged

**File layout:**
```
tests/
  unit/
    test_config.py
    test_docs_service.py
    test_normalize.py
```

**Gate:**
- All tests pass.
- `ruff check .` still passes.
- CI green.

---

### WP-19.5.3 — Service Tests with Mocks

**Goal:** Tests for `services/ask_service.py` and `services/trace_service.py` using
`unittest.mock` to stand in for Qdrant and Ollama calls. These services are touched by
almost every feature and currently have no test coverage.

**Mock patching rule (critical):** Always patch the symbol as it is imported in the module
under test, not where it originates. For example:

```python
# Correct — patches the name as ask_service sees it
with patch("services.ask_service.QdrantClient") as mock_qdrant:
    ...

# Wrong — does not intercept the already-imported name
with patch("qdrant_client.QdrantClient") as mock_qdrant:
    ...
```

Verify the correct patch target by inspecting the `import` statements at the top of each
service file before writing the test.

**Prove no live service is called (required):** In each service test module, add a
session-scoped autouse fixture that makes the un-patched constructors raise immediately:

```python
import pytest
import qdrant_client
import ollama

@pytest.fixture(autouse=True, scope="session")
def block_live_services(monkeypatch):
    monkeypatch.setattr(qdrant_client, "QdrantClient",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Live Qdrant called in tests")))
    monkeypatch.setattr(ollama, "Client",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Live Ollama called in tests")))
```

If a test patches at the wrong path, the live constructor fires, the fixture raises, and
the mistake is immediately visible. Tests that correctly patch at the service import site
are unaffected because the service module's local name is replaced before it is called.

**`services/ask_service.py` tests:**
- Returns canonical shape: `{query, filters, results, metadata}` with all documented keys
- `metadata.retrieval_ms` is present and numeric
- `metadata.result_count` matches the length of the results list
- Filters are passed through to the retrieval call (assert mock called with correct args)
- `top_k` limit is passed to retrieval (assert mock called with correct value)
- `synthesis` key absent in metadata when synthesis not requested
- Qdrant exception propagates as a `RuntimeError` (per API contract)
- Empty results list is a valid successful response (not a crash)
- Result ordering is preserved (output order matches mock return order)

**`services/trace_service.py` tests:**
- Returns full detail dict for a known `req_id` (mock Qdrant scroll with fixture data)
- `ValueError` raised for unknown `req_id` (mock returns empty result)
- `cross_matches` key present in response (may be empty list)
- `domain_profile` field returns `"cybersecurity"` when absent from Qdrant payload
  (forward-compat for Phase 20 — `payload.get("domain_profile", "cybersecurity")`)
- `domain_profile` field returns the stored value when present in Qdrant payload

**File layout:**
```
tests/
  unit/
    test_ask_service.py
    test_trace_service.py
```

**Gate:**
- All tests pass without Qdrant or Ollama running.
- `ruff check .` passes.
- CI green.

---

### WP-19.5.4 — CI Enforcement

**Goal:** Require both CI jobs (lint and test) to pass before a PR can merge.

**Steps:**
1. Confirm both job names in `.github/workflows/ci.yml` (`lint`, `test`).
2. Add both as required status checks in the `branch_basic` ruleset (Settings →
   Rules → branch_basic → Required status checks).
3. Verify: push a branch with a ruff lint error — merge blocked.
4. Fix the error — merge unblocked.
5. Verify: push a branch with a failing test — merge blocked.
6. Fix the test — merge unblocked.

Tyler can still self-merge (no additional reviewer requirement added).

**Gate:**
- A PR with failing CI cannot be merged.
- A PR with passing CI can be merged normally by Tyler.

---

## Success Gate (Phase 19.5)

1. `pytest tests/ -v` passes with no live services.
2. `ruff check .` passes with the baseline config.
3. CI triggers on every push and PR; both `lint` and `test` jobs run.
4. At least 20 test cases covering config, docs_service (including negative paths),
   normalize (including negative paths), ask_service, and trace_service.
5. `domain_profile` fallback to `"cybersecurity"` verified in trace_service tests.
6. Both CI jobs are required checks — PRs cannot merge with either failing.
7. Coverage report visible in CI output (no threshold enforced).

---

## Sequencing

| WP | Description | Gate before next |
|----|-------------|-----------------|
| 19.5.1 | Scaffolding — harness, fixtures, ruff config, CI workflow, smoke test | CI green; lint + test jobs both pass |
| 19.5.2 | Easy-win unit tests (config, docs, normalize — including negative paths) | All pass; ruff clean |
| 19.5.3 | Service tests with mocks (ask_service, trace_service) | All pass without live infra |
| 19.5.4 | CI enforcement (required status checks for both jobs) | Broken PR blocked; clean PR unblocked |

**Do one WP at a time. Codex review after each before proceeding.**

---

## Notes for Phase 20 Integration

- WP-20.2 creates `core/profiles.py`. Write its tests in the same PR, not after.
  The loader contract is simple and fully unit-testable (no external deps). Follow the
  same mock-at-import-site rule for any dependencies it introduces.
- WP-20.3 threads profiles through the pipeline. Add at least one regression test asserting
  that `parse_and_normalize` with the default profile produces the same normalized field
  values as pre-Phase-20.
- After Phase 19.5, the Phase 20 gate conditions in `PHASE20_REQUIREMENTS.md` should be
  interpreted as: *passing CI + the named behavior*, not just manual verification.
- When coverage numbers become visible, use them to prioritize which Phase 20 paths
  need tests — don't chase the number, use it as a signal.
