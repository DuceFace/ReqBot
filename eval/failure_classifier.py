#!/usr/bin/env python3
"""WP-40: Failure-classification layer for retrieval misses/over-grabs.

Built on top of eval/retrieval_eval_harness.py (WP-37.1) -- not a separate
eval. Every classification cites the specific artifact/check that justified
it (docs/PHASE40_REQUIREMENTS.md's Guardrails), grounded in real pipeline
artifacts rather than intuition about which category a miss "feels like".

Categories (operational definitions: docs/PHASE40_REQUIREMENTS.md Section 4):
  1. extraction_failure             -- (a) requirement_id confirmed absent
                                        from the current, reprocessed corpus,
                                        or (b) a query-level
                                        unextracted_relevant_content note
                                        (content Step C never extracted at
                                        all, so no requirement_id exists to
                                        even place in the gold set).
  2. missing_context                -- fragment-shaped (looks like a WP-39.2
                                        reconstruction candidate) but has no
                                        parent_stem.
  3. table_serialization            -- source_quote or the record's own
                                        chunk raw_text matches WP-39.1's
                                        confirmed GARBLED_TABLE "Column =
                                        Value" run-on signature.
  4. embedding_miss                 -- absent even from a generously-sized,
                                        floor-disabled candidate pool
                                        (top_k=100, min_score=0).
  5. ranking_miss                   -- present in that pool, above the
                                        production min_score floor, but
                                        outside the evaluated top-k.
  6. over_grab                      -- an irrelevant result ranks in top-k,
                                        evidenced by same-chunk co-location
                                        with a relevant record or an
                                        explicit hand-verified label.
  7. query_filter_issue             -- present in a raw (no rewrite/no HyDE)
                                        query's top-k but not production's --
                                        the rewrite/HyDE transformation is
                                        what pushed it out.
  8. zero_truth_confidence_failure  -- (a) a zero-truth query never reports
                                        "no relevant results", or (b) a
                                        relevant record's score is below the
                                        production min_score floor even in
                                        the larger pool -- a threshold-
                                        calibration symptom, not a ranking one
                                        (Codex review, PR #186: min_score
                                        filtering happens *before* the top_k
                                        trim in core.ask.retrieve(), so a
                                        sub-threshold record found only at
                                        min_score=0 must not be mislabeled
                                        embedding_miss or ranking_miss).

No retrieval code changes happen here -- measurement/diagnosis only
(WP-40 Non-Goals).
"""
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.artifact_resolver import resolve_latest_requirement_files  # noqa: E402
from core.ask import retrieve  # noqa: E402
from pipeline.enrich_requirements import _is_reconstruction_candidate  # noqa: E402

CATEGORIES = (
    "extraction_failure",
    "missing_context",
    "table_serialization",
    "embedding_miss",
    "ranking_miss",
    "over_grab",
    "query_filter_issue",
    "zero_truth_confidence_failure",
)

PRODUCTION_MIN_SCORE = 0.02
PRODUCTION_TOP_K = 20
LARGE_POOL_TOP_K = 100

# WP-39.1's confirmed GARBLED_TABLE signature: a Docling table serialized as
# run-on "Column = Value" segments with no real row/column structure (e.g.
# afi17-203 chunk_id=55: "Reporting& Notification = Update of actions
# taken.[...]Documentation = Documentation of any actions taken.[...]").
# >=2 occurrences distinguishes real garbling from an ordinary sentence that
# happens to contain a single " = " -- verified empirically against every
# source_quote in the currently-indexed corpus (2268 records): zero matches
# at this threshold outside the 2 known GARBLED_TABLE records.
_GARBLED_TABLE_SIG = re.compile(r"[A-Za-z][A-Za-z0-9 &/\-]{2,40}\s=\s")


def is_garbled_table_text(text: str) -> bool:
    return len(_GARBLED_TABLE_SIG.findall(text or "")) >= 2


@dataclass
class CorpusIndex:
    """Real, current corpus artifacts needed to classify a miss -- loaded
    once and reused across every query in a classification run. Built from
    the same resolve_latest_requirement_files() winning tier that reindex/
    production retrieval actually uses, not an arbitrary file glob."""

    records_by_id: dict = field(default_factory=dict)
    doc_key_by_id: dict = field(default_factory=dict)
    chunk_text_by_doc: dict = field(default_factory=dict)

    @classmethod
    def load(cls, processed_dir: Path) -> "CorpusIndex":
        files = resolve_latest_requirement_files(processed_dir)
        records_by_id: dict = {}
        doc_key_by_id: dict = {}
        chunk_text_by_doc: dict = {}
        for doc_key, path in files.items():
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    records_by_id[rec["requirement_id"]] = rec
                    doc_key_by_id[rec["requirement_id"]] = doc_key

            chunk_map: dict = {}
            chunks_path = path.parent / f"{doc_key}_chunks.jsonl"
            if chunks_path.exists():
                with open(chunks_path, encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        c = json.loads(line)
                        chunk_map[c["chunk_id"]] = c.get("raw_text") or c.get("text", "")
            chunk_text_by_doc[doc_key] = chunk_map
        return cls(records_by_id=records_by_id, doc_key_by_id=doc_key_by_id, chunk_text_by_doc=chunk_text_by_doc)


def classify_miss(
    query: dict,
    missing_id: str,
    corpus: CorpusIndex,
    *,
    qdrant_url: str,
    ollama_url: str,
    hyde: bool = True,
    pool_cache: dict | None = None,
) -> dict:
    """Classify one labeled-relevant requirement_id that didn't make a
    query's evaluated top-k. Returns {"category", "evidence", ...}.

    pool_cache (optional): {query_id: {"pool": [...], "raw": [...]}} --
    every missed id for the same query shares the same large-pool/raw-query
    retrieve() calls, so callers processing a whole query's misses in one
    pass should share a cache dict across those calls to avoid redundant
    network round trips against live Qdrant/Ollama.
    """
    rec = corpus.records_by_id.get(missing_id)

    # Category 1a: the requirement_id is confirmed absent from the current,
    # reprocessed corpus -- Step D no longer produces it at all (checked
    # directly against the same resolve_latest_requirement_files() winning
    # tier reindex/production retrieval use).
    if rec is None:
        return {
            "category": "extraction_failure",
            "sub_case": "a_absent_from_corpus",
            "evidence": f"{missing_id} not present in any current *_requirements_normalized.jsonl "
                        f"winning-tier file (post-Step-D-reprocess corpus).",
        }

    doc_key = corpus.doc_key_by_id.get(missing_id, "")
    chunk_id = rec.get("chunk_id")
    chunk_text = corpus.chunk_text_by_doc.get(doc_key, {}).get(chunk_id, "")

    # Category 3: table-serialization signature, checked before missing_context
    # since a garbled-table fragment can also look list-marker-short/dangling.
    if is_garbled_table_text(rec.get("source_quote", "")) or is_garbled_table_text(chunk_text):
        return {
            "category": "table_serialization",
            "evidence": f"{missing_id} (chunk_id={chunk_id}, doc={doc_key}): source_quote or its "
                        f"chunk's raw_text matches the GARBLED_TABLE 'Column = Value' run-on signature.",
        }

    # Category 2: missing context -- fragment-shaped (same candidacy check
    # WP-39.2's own reconstruction uses) but parent_stem is empty, i.e.
    # either STEM_NEVER_EXTRACTED or reconstruction genuinely found no
    # governing clause for it.
    if not rec.get("parent_stem") and _is_reconstruction_candidate(rec.get("source_quote", "")):
        return {
            "category": "missing_context",
            "evidence": f"{missing_id}: fragment-shaped (_is_reconstruction_candidate=True) but "
                        f"parent_stem is empty -- source_quote={rec.get('source_quote', '')[:100]!r}",
        }

    # Categories 4/5/7/8b need a live retrieve() call against a generously
    # sized, floor-disabled candidate pool -- min_score must be disabled too,
    # not just top_k raised (Codex review, PR #186: core.ask.retrieve()
    # filters min_score *before* trimming to top_k, so a relevant record
    # scoring just under the production floor would still be silently
    # absent from a "top-100" call that didn't also disable the floor).
    cache_entry = (pool_cache or {}).get(query["query_id"])
    if cache_entry is None or "pool" not in cache_entry:
        try:
            pool_result = retrieve(
                query["query"], top_k=LARGE_POOL_TOP_K, min_score=0, hyde=hyde,
                qdrant_url=qdrant_url, ollama_url=ollama_url,
            )
        except Exception as e:
            return {"category": None, "evidence": f"retrieve() failed during classification: {e}"}
        if pool_cache is not None:
            pool_cache.setdefault(query["query_id"], {})["pool"] = pool_result
    else:
        pool_result = cache_entry["pool"]

    pool_hits = pool_result["results"]
    pool_ids = [r["requirement_id"] for r in pool_hits]
    if missing_id not in pool_ids:
        return {
            "category": "embedding_miss",
            "evidence": f"{missing_id} absent even from top_k={LARGE_POOL_TOP_K}/min_score=0 pool "
                        f"({len(pool_ids)} candidates) -- genuine semantic/vocabulary mismatch.",
        }

    rank = pool_ids.index(missing_id) + 1
    score = next(r["score"] for r in pool_hits if r["requirement_id"] == missing_id)

    if score < PRODUCTION_MIN_SCORE:
        return {
            "category": "zero_truth_confidence_failure",
            "sub_case": "b_sub_threshold_record",
            "evidence": f"{missing_id} only found once min_score=0 (score={score:.4f} < production "
                        f"floor {PRODUCTION_MIN_SCORE}) -- threshold-calibration symptom, not ordering.",
        }

    # Present, above the floor, but outside production top-k: disambiguate
    # query/filter drift (rewrite/HyDE) from a genuine ranking problem via a
    # raw-query (no rewrite, no HyDE), production-min_score call.
    if cache_entry is None or "raw" not in (pool_cache or {}).get(query["query_id"], {}):
        try:
            raw_result = retrieve(
                query["query"], top_k=PRODUCTION_TOP_K, min_score=PRODUCTION_MIN_SCORE,
                hyde=False, no_rewrite=True, qdrant_url=qdrant_url, ollama_url=ollama_url,
            )
            raw_ids = [r["requirement_id"] for r in raw_result["results"]]
        except Exception:
            raw_ids = []
        if pool_cache is not None:
            pool_cache.setdefault(query["query_id"], {})["raw"] = raw_ids
    else:
        raw_ids = pool_cache[query["query_id"]]["raw"]

    if missing_id in raw_ids and rank > PRODUCTION_TOP_K:
        return {
            "category": "query_filter_issue",
            "evidence": f"{missing_id} appears in a raw-query (no rewrite/HyDE) top-{PRODUCTION_TOP_K} "
                        f"but not production's -- the rewrite/HyDE transformation pushed it out.",
        }

    return {
        "category": "ranking_miss",
        "evidence": f"{missing_id}: present in the top_k={LARGE_POOL_TOP_K}/min_score=0 pool at rank "
                    f"{rank} (score={score:.4f} >= floor) but outside production top-{PRODUCTION_TOP_K}.",
    }


def classify_over_grabs(query: dict, retrieved_ids: list, corpus: CorpusIndex, *, top_k: int = 5) -> list:
    """Flag irrelevant results ranking inside top_k as over-grab candidates.

    A conservative, artifact-grounded subset of true over-grabs -- not a
    full per-result manual review. Two evidence sources only:
      - same-chunk co-location with a relevant record (a real, structural
        Phase 38 Over-Grab Precision pattern: duplicate/near-duplicate
        fragments of the same source clause), or
      - the query's own hand-verified expected_over_grab_ids (the
        messy-PDF/over-grab gold bucket).
    """
    relevant = set(query.get("relevant_requirement_ids", []))
    expected_over_grabs = set(query.get("expected_over_grab_ids", []))
    relevant_chunks = {
        (corpus.doc_key_by_id.get(rid, ""), corpus.records_by_id[rid].get("chunk_id"))
        for rid in relevant if rid in corpus.records_by_id
    }
    findings = []
    for rank, rid in enumerate(retrieved_ids[:top_k], start=1):
        if rid in relevant:
            continue
        rec = corpus.records_by_id.get(rid)
        if rec is None:
            continue
        key = (corpus.doc_key_by_id.get(rid, ""), rec.get("chunk_id"))
        if rid in expected_over_grabs:
            findings.append({
                "requirement_id": rid, "rank": rank, "category": "over_grab",
                "evidence": f"{rid} hand-labeled as a known over-broad/duplicate extraction for "
                            f"query {query['query_id']}.",
            })
        elif key in relevant_chunks:
            findings.append({
                "requirement_id": rid, "rank": rank, "category": "over_grab",
                "evidence": f"{rid} shares chunk {key} with a relevant record for query "
                            f"{query['query_id']} -- likely duplicate/near-duplicate fragment of "
                            f"the same source clause.",
            })
    return findings


def build_prevalence_report(
    queries: list,
    corpus: CorpusIndex,
    *,
    qdrant_url: str,
    ollama_url: str,
    harness_report: dict | None = None,
) -> dict:
    """Run (or reuse) the WP-37.1 harness, classify every miss/over-grab, and
    report category prevalence. harness_report can be passed in to reuse an
    already-computed baseline run instead of re-querying retrieve() for the
    aggregate numbers too."""
    if harness_report is None:
        from eval.retrieval_eval_harness import run_harness
        harness_report = run_harness(queries, qdrant_url=qdrant_url, ollama_url=ollama_url)

    queries_by_id = {q["query_id"]: q for q in queries}
    miss_classifications = []
    over_grab_classifications = []
    zero_truth_query_level = []
    pool_cache: dict = {}

    for pq in harness_report["per_query"]:
        if "error" in pq:
            continue
        query = queries_by_id[pq["query_id"]]

        if pq["shape"] == "zero":
            zero_truth_query_level.append({
                "query_id": pq["query_id"],
                "returned_count": pq["returned_count"],
                "correctly_empty": pq["returned_count"] == 0,
            })
            continue

        relevant = set(query["relevant_requirement_ids"])
        retrieved_top_k = set(pq["retrieved_ids"][:PRODUCTION_TOP_K])
        missed = relevant - retrieved_top_k
        for missing_id in sorted(missed):
            result = classify_miss(
                query, missing_id, corpus,
                qdrant_url=qdrant_url, ollama_url=ollama_url, pool_cache=pool_cache,
            )
            result.update({"query_id": query["query_id"], "requirement_id": missing_id})
            miss_classifications.append(result)

        for note in query.get("unextracted_relevant_content", []):
            miss_classifications.append({
                "query_id": query["query_id"], "requirement_id": None,
                "category": "extraction_failure", "sub_case": "b_never_extracted",
                "evidence": note if isinstance(note, str) else json.dumps(note),
            })

        for og in classify_over_grabs(query, pq["retrieved_ids"], corpus):
            og["query_id"] = query["query_id"]
            over_grab_classifications.append(og)

    prevalence = {c: 0 for c in CATEGORIES}
    extraction_sub_counts = {"a_absent_from_corpus": 0, "b_never_extracted": 0}
    for m in miss_classifications:
        cat = m.get("category")
        if cat:
            prevalence[cat] = prevalence.get(cat, 0) + 1
        if cat == "extraction_failure":
            extraction_sub_counts[m.get("sub_case", "a_absent_from_corpus")] += 1
    prevalence["over_grab"] += len(over_grab_classifications)

    if zero_truth_query_level:
        never_reports_empty = all(not z["correctly_empty"] for z in zero_truth_query_level)
    else:
        never_reports_empty = None

    return {
        "harness_report": harness_report,
        "miss_classifications": miss_classifications,
        "over_grab_classifications": over_grab_classifications,
        "zero_truth_query_level": zero_truth_query_level,
        "zero_truth_never_reports_empty": never_reports_empty,
        "category_prevalence": prevalence,
        "extraction_failure_sub_counts": extraction_sub_counts,
    }
