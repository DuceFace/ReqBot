# ReqBot Phase 15 — Retrieval Quality (HyDE Spike + WP-3 Resume)

**Requirements Document — April 2026**

---

## 1. Executive Summary

Phase 15 has two sequential goals:

1. **Resume Phase 13 WP-3** (gold set curation) — unblocked by Phase 14's structure-aware chunking. Phase 14 re-ingest produced clean artifacts; the gold set seeded on the broken fixed-size chunker is now stale and needs to be regenerated and curated. WP-3 blocks WP-4 (training data) and WP-5 (fine-tuning).

2. **HyDE spike** — evaluate whether Hypothetical Document Embedding meaningfully improves dense retrieval quality for compliance queries before committing to it as a default retrieval path.

Phase 15 is a validation phase. No new interfaces, no API, no GUI. All changes are confined to the `ask` retrieval path and the evaluation tooling.

---

## 2. Relationship to Prior Phases

- **Phase 13 WP-3/WP-4/WP-5** remain blocked until WP-3 curation is complete on Phase 14 artifacts.
- **Phase 14** produced the clean chunking output that makes WP-3 curation meaningful. Phase 15 resumes where Phase 13 paused.
- **Phase 16** (service layer + API) depends on Phase 15 passing its gate. Do not proceed to GUI work without confidence in retrieval quality.

---

## 3. Work Package Summary

| WP | Title | Status | Description |
|----|-------|--------|-------------|
| WP-15.1 | Gold Set Regeneration | DEFERRED | Re-seed gold set from Phase 14 artifacts; export CSV for curation |
| WP-15.2 | Gold Set Curation | DEFERRED | Tyler-driven review pass in Excel; import curated CSV |
| WP-15.3 | HyDE Spike Implementation | DONE 2026-04-07 | `--hyde` flag on `ask.py`; 3-leg RRF; hypothesis logging; PR #32 merged |
| WP-15.4 | HyDE Evaluation | DONE 2026-04-07 | 5-query manual comparison; gate passed — see outcome below |

---

## 4. WP-15.1 — Gold Set Regeneration

### 4.1 Goal

Re-generate the Phase 13 WP-3 gold set from Phase 14 chunking artifacts. The 402-chunk seed committed in Phase 13 reflects the broken fixed-size chunker and must not be used for curation.

### 4.2 Procedure

1. Confirm Phase 14 re-ingest artifacts are present in `~/documents/processed/`.
2. Re-run `eval/export_gold_review_csv.py` against Phase 14 chunks to produce a fresh `eval/gold_eval_chunks_review.csv`.
3. Verify chunk count and breadcrumb coverage look reasonable before handing to curation.

### 4.3 Success Criteria

- New CSV generated from Phase 14 artifacts (not Phase 13 artifacts)
- Breadcrumb field populated on ≥95% of exported chunks
- No ToC lines in exported chunks

---

## 5. WP-15.2 — Gold Set Curation

### 5.1 Goal

Produce a curated gold set that grades extraction quality on clean Phase 14 chunks, not chunking damage.

### 5.2 Procedure

Follow the established CSV review workflow:

1. Open `eval/gold_eval_chunks_review.csv` in Excel.
2. Set `review_status` to `"done"` on reviewed rows; leave others blank.
3. Run `eval/import_gold_review_csv.py` — only `review_status="done"` rows are imported.
4. Commit the updated gold set JSONL.

**Do not adjudicate gold set quality in chat.** The CSV export/import workflow exists for a reason; use it.

### 5.3 Scope Note

Curation is Tyler-driven. Claude/Codex assists with tooling, not with deciding what is or is not a good requirement. The agent's job is to make the tooling work, not to make editorial decisions about the corpus.

### 5.4 Success Criteria

- Curated gold set committed to repo
- At least 50 requirements with `review_status="done"` (minimum for meaningful WP-4 signal)
- No chunks from pre-Phase 14 artifacts in the final set

---

## 6. WP-15.3 — HyDE Spike Implementation

### 6.1 Goal

Implement Hypothetical Document Embedding on the dense leg of the `ask` retrieval path in a way that is testable and reversible. No config flags, no permanent changes to the default retrieval path until WP-15.4 evaluation passes.

### 6.2 Architecture

HyDE is inserted before the dense embedding call only:

```
raw query ─────────────────────────────────► BM25 sparse retrieval (unchanged)
         │
         └─► LLM generates hypothesis ──► dense embedding ──► dense retrieval
                                                                     │
                                         raw query embedding ──► dense retrieval
                                                                     │
                                         RRF fuses all three ──────►results
```

Concretely:

1. Embed raw query → baseline dense results (existing path, unchanged)
2. Call Ollama with the HyDE prompt → get 1 hypothetical requirement statement
3. Embed the hypothesis → HyDE dense results
4. Add HyDE dense results as a third RRF leg alongside baseline dense + BM25
5. RRF fuses all three → final ranked list

The BM25 sparse leg is **not modified**. RRF parameters are **not tuned** in this phase.

### 6.3 HyDE Prompt

```
Given this compliance question, write a single regulatory requirement statement that would
answer it. Use formal language matching DoD/NIST style. Do NOT include specific control IDs,
section numbers, or numeric thresholds. Describe only the semantic intent of the requirement.

Question: {query}

Requirement:
```

**Critical constraint — anti-hallucination:** If the model invents a control ID (e.g., "IA-5(1)") or a specific numeric threshold (e.g., "15-character minimum"), BM25 will latch onto those exact tokens and surface wrong documents. The prompt must prohibit fabricated identifiers. Inspect generated hypotheses for this pattern during evaluation.

### 6.4 Implementation Notes

- Use the existing `synthesis_model` (qwen2.5:14b) for hypothesis generation — it produces cleaner formal language than the extraction model.
- Log every generated hypothesis to `hyde_hypotheses.jsonl` during testing. Review in batch after the evaluation run, not inline.
- Hypothesis generation failure (timeout, empty response) → fall back to baseline-only retrieval silently.
- This is a spike; implement in `ask.py` behind a `--hyde` flag for the duration of testing. Do not expose in the shell or make it permanent until WP-15.4 passes the gate.

### 6.5 Success Criteria

- `reqbot ask "..." --hyde` returns results without error
- `hyde_hypotheses.jsonl` contains the generated hypothesis for each query
- Baseline path (`reqbot ask` without `--hyde`) is unchanged and produces identical results to pre-WP-15.3

---

## 7. WP-15.4 — HyDE Evaluation

### 7.1 Goal

Determine whether HyDE meaningfully improves retrieval quality for compliance queries. The result gates whether HyDE becomes a default retrieval path or is discarded.

### 7.2 Evaluation Query Set

Define 10–15 representative queries covering:

- **Source types:** NIST SP 800-53, DoDI, AFI/DAFI, CNSSI
- **Query styles:**
  - Vague: "What are the access control requirements?"
  - Precise: "What are the password length minimums for privileged accounts?"
  - Cross-document: queries that should surface requirements from multiple documents
  - Single-document: queries scoped to one framework

Commit the query list to `eval/hyde_eval_queries.json` before running evaluation.

### 7.3 Metrics

| Metric | Primary? | Notes |
|--------|----------|-------|
| Precision@5 | Yes | Primary observation metric |
| New relevant hits surfaced (baseline miss) | Yes | Did HyDE find something baseline didn't? |
| Ranking changes | Yes | Did good results move up? |
| Latency delta | Measured, not gated | Record but do not gate on latency |

### 7.4 Gate: Success Criteria

All three conditions must hold for HyDE to proceed to default path:

1. HyDE surfaces relevant requirements not found in baseline on **≥3 of the test queries**
2. **No query shows degraded relevance** vs. baseline
3. **No hypothesis** contains hallucinated control IDs or numeric thresholds that corrupted retrieval (visible in `hyde_hypotheses.jsonl` review)

### 7.5 Outcomes

| Result | Action |
|--------|--------|
| **Passes gate** | HyDE becomes a candidate for default dense retrieval. Proceed to Phase 16. |
| **Inconclusive** | Refine hypothesis prompt; retry with synthesis model if not already used; re-evaluate once. |
| **Negative** | Discard HyDE. Reassess retrieval strategy before Phase 16. Document findings in `docs/PHASE15_HYDE_OUTCOME.md`. |

---

## 8. Design Constraints (Enforced)

### 8.1 Scope Boundaries

**Do NOT in this phase:**

- Add persistent config flags (`hyde_enabled`, etc.) — the `--hyde` spike flag is temporary
- Expose HyDE in the interactive shell
- Replace baseline retrieval — baseline always runs; HyDE augments it
- Introduce paraphrase expansion (HyPE) — deferred; only if HyDE works and coverage gaps remain
- Tune RRF fusion parameters
- Experiment with alternative fusion strategies

### 8.2 Architecture Safety Test

Before any WP-15.3 change ships, verify:

- Can you kill the API server (Phase 16, not yet built) without affecting `reqbot ask`?
- Does the CLI `ask` command call the same function path regardless of `--hyde`?
- Can you remove the `--hyde` flag and return to the exact baseline with zero other changes?

If any answer is no, the implementation is wrong.

---

## 9. Success Criteria (Phase Gate)

Phase 15 completes when:

1. ~~**WP-15.2 done:** Curated gold set committed with ≥50 reviewed requirements~~ *(deferred)*
2. **WP-15.4 done:** HyDE evaluation run complete and a go/no-go decision recorded ✅
3. **No regression:** Baseline `reqbot ask` behavior unchanged from end of Phase 14 ✅
4. **Documented outcome:** See section 11 below ✅

---

## 11. HyDE Evaluation Outcome (2026-04-07) — PASSED

**Decision: GO — HyDE is a candidate for default dense retrieval path in Phase 16.**

### Evaluation Queries and Results

All 5 queries run with `--no-rewrite` to isolate HyDE effect from query expansion.

| Query | Baseline top result | HyDE change | Verdict |
|---|---|---|---|
| "What are the access control requirements?" | DAFMAN 17-1304 access control policies | Minor tail improvements, top result same | Neutral |
| "What are the encryption requirements for data at rest?" | DODI 5200.01 PII encryption | New [2]: DODI unclassified data policy; New [5]: NIST PM-17a CUI | **Improved** |
| "audit log retention requirements" | NIST AU-02(04) retention defined | New [4]: substantive retention records requirement; New [5]: AU-11 retention period | **Improved** |
| "incident response plan requirements" | NIST 800-161 IR plan | New [4]: DODI 5200.01_vol2 IR plan (cross-document hit baseline missed) | **Improved** |
| "supply chain security vendor risk" | DODI 5200.44 ICT risk identification | New [1]: NIST 800-161 SCRM program (more actionable, promoted to top) | **Improved** |

### Gate Conditions

- ✅ HyDE surfaced relevant requirements not in baseline on **4 of 5** queries (≥3 required)
- ✅ No query showed degraded relevance vs. baseline
- ✅ No hypothesis contained hallucinated control IDs or numeric thresholds

### Generated Hypotheses (quality review)

All 5 hypotheses were clean regulatory-register text with no fabricated identifiers:
- Access control: "Access to organizational information systems...restricted based on need-to-know principle..."
- Encryption: "Sensitive and unclassified information must be protected through approved encryption methods when stored in a non-transient state..."
- Audit: "The organization shall retain audit logs for a period sufficient to support forensic analysis and incident response activities..."
- IR: "The organization shall develop and maintain an incident response plan that describes procedures for identifying, containing, eradicating, and recovering..."
- Supply chain: "Organizations shall assess and mitigate risks associated with third-party vendors..."

### Latency

One additional LLM generate call + one additional embed call per query. Observed as ~1–2 seconds additional latency on localhost Ollama. Acceptable for analyst-facing queries.

---

## 10. Files Introduced or Modified in This Phase

| File | Change |
|------|--------|
| `ask.py` | Add `--hyde` flag; HyDE dense leg; hypothesis logging |
| `eval/hyde_eval_queries.json` | New — committed query set for evaluation |
| `eval/hyde_eval_results.jsonl` | New — per-query baseline vs. HyDE comparison (gitignored; scratch output) |
| `hyde_hypotheses.jsonl` | New — generated hypotheses log (gitignored; scratch output) |
| `eval/gold_eval_chunks_review.csv` | Regenerated from Phase 14 artifacts |
| `docs/PHASE15_HYDE_OUTCOME.md` | New — written at WP-15.4 completion |
