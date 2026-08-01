#!/usr/bin/env python3
"""WP-40: Failure-classification layer for retrieval misses/over-grabs.

Built on top of eval/retrieval_eval_harness.py (WP-37.1) -- not a separate
eval. Every classification cites the specific artifact/check that justified
it (docs/PHASE40_REQUIREMENTS.md's Guardrails), grounded in real pipeline
artifacts rather than intuition about which category a miss "feels like".

Categories (operational definitions: docs/PHASE40_REQUIREMENTS.md Section 4):
  1. extraction_failure             -- (a) requirement_id confirmed absent
                                        from the current, reprocessed corpus
                                        AND independently confirmed rejected
                                        in *_normalization_failures.jsonl (not
                                        just relabeled to a different id), or
                                        (b) a query-level
                                        unextracted_relevant_content note.
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

Every query's embedding/ranking/query-filter classification is driven by a
SINGLE retrieve() call per query (top_k=100, min_score=0), not a separate
draw per check. HyDE is unseeded and stochastic (eval/retrieval_eval_harness.py's
own docstring), so two independently-issued calls for the same query can
disagree with each other about a borderline record's rank -- using one call
as the sole source of truth for that query's whole classification avoids
self-contradictory results (Codex review, PR #187: a record the harness
counted as a miss showing up "at rank 20" in a *different* stochastic draw
used for classification). The official baseline-refresh numbers reported
elsewhere still come from eval/retrieval_eval_harness.py's own unmodified,
separately-run production-default call -- this module's pool call is a
second, deliberately different measurement used only for classification, not
a substitute for the official recall/MRR baseline.

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
from pipeline.parse_and_normalize import normalize_text  # noqa: E402

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
    run_dir_by_doc_key: dict = field(default_factory=dict)

    @classmethod
    def load(cls, processed_dir: Path) -> "CorpusIndex":
        files = resolve_latest_requirement_files(processed_dir)
        records_by_id: dict = {}
        doc_key_by_id: dict = {}
        chunk_text_by_doc: dict = {}
        run_dir_by_doc_key: dict = {}
        for doc_key, path in files.items():
            run_dir_by_doc_key[doc_key] = path.parent
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
        return cls(
            records_by_id=records_by_id, doc_key_by_id=doc_key_by_id,
            chunk_text_by_doc=chunk_text_by_doc, run_dir_by_doc_key=run_dir_by_doc_key,
        )


def fetch_classification_pool(query: dict, corpus: CorpusIndex, *, qdrant_url: str, ollama_url: str, hyde: bool = True) -> list:
    """Single retrieve() call for one query (top_k=100, min_score=0), used as
    the sole source of truth for that query's whole classification pass --
    both which relevant ids are missed at the production floor/top-k AND
    which category each miss falls into (Codex review, PR #187: using a
    second, separately-drawn HyDE call per check let the same record get
    inconsistent verdicts across calls)."""
    del corpus  # unused, kept for a consistent call signature with classify_miss
    return retrieve(
        query["query"], top_k=LARGE_POOL_TOP_K, min_score=0, hyde=hyde,
        qdrant_url=qdrant_url, ollama_url=ollama_url,
    )["results"]


def _confirm_extraction_loss(doc_key: str, expected_quote: str, corpus: CorpusIndex) -> dict:
    """Given a requirement_id absent from the current corpus, confirm whether
    its original content was genuinely rejected by Step D or merely survived
    under a different id (a content-hash id can change if normalize_for_hash's
    inputs shift even slightly -- absence of the OLD id alone doesn't prove
    the content is gone). Checked directly against the current corpus's
    records (relabeling) and *_normalization_failures.jsonl (confirmed
    rejection), per the operational definition's own citation requirement
    (Codex review, PR #187)."""
    norm_expected = normalize_text(expected_quote)

    for rid, rec in corpus.records_by_id.items():
        if corpus.doc_key_by_id.get(rid) == doc_key and normalize_text(rec.get("source_quote", "")) == norm_expected:
            return {
                "confirmed": False,
                "evidence": f"content survived under a different id ({rid}) -- not actually lost, "
                            f"the gold label's id is stale.",
            }

    run_dir = corpus.run_dir_by_doc_key.get(doc_key)
    if run_dir is not None:
        fail_file = run_dir / f"{doc_key}_normalization_failures.jsonl"
        if fail_file.exists():
            with open(fail_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    fr = json.loads(line)
                    raw_quote = (fr.get("raw") or {}).get("source_quote", "")
                    if normalize_text(raw_quote) == norm_expected:
                        return {
                            "confirmed": True,
                            "evidence": f"Step D rejected this content directly (error="
                                        f"{fr.get('error')!r}), confirmed via {fail_file.name}.",
                        }

    return {
        "confirmed": None,
        "evidence": "not found under any current id for this doc, nor in its "
                     "*_normalization_failures.jsonl -- absence noted but not independently confirmed.",
    }


def classify_miss(
    query: dict,
    missing_id: str,
    corpus: CorpusIndex,
    pool_hits: list,
    *,
    qdrant_url: str,
    ollama_url: str,
    raw_query_cache: dict | None = None,
) -> dict:
    """Classify one labeled-relevant requirement_id that didn't make a
    query's production-equivalent top-k in pool_hits. Returns
    {"category", "evidence", ...}.

    pool_hits: this query's single fetch_classification_pool() result,
    shared across every missing id for the same query -- see module
    docstring for why this must be one call, not one per check.

    raw_query_cache (optional): {query_id: raw_ids} -- the no-rewrite/no-HyDE
    diagnostic call (category 7) is deliberately a *different* retrieval
    config from the classification pool, but still only needs issuing once
    per query; share a cache dict across missing ids of the same query to
    avoid redundant round trips.
    """
    rec = corpus.records_by_id.get(missing_id)

    # Category 1a: the requirement_id is confirmed absent from the current,
    # reprocessed corpus. Absence alone doesn't prove the content is gone
    # (a content-hash id can shift under normalization changes) -- when the
    # gold query recorded expected_quotes for this id, independently confirm
    # via _confirm_extraction_loss(); otherwise report honestly as unconfirmed
    # rather than silently asserting loss (Codex review, PR #187).
    if rec is None:
        expected = (query.get("expected_quotes") or {}).get(missing_id)
        if expected:
            confirmation = _confirm_extraction_loss(expected["doc_key"], expected["quote"], corpus)
            if confirmation["confirmed"] is False:
                return {"category": None, "evidence": f"{missing_id}: {confirmation['evidence']}"}
            return {
                "category": "extraction_failure",
                "sub_case": "a_absent_from_corpus",
                "evidence": f"{missing_id}: {confirmation['evidence']}",
            }
        return {
            "category": "extraction_failure",
            "sub_case": "a_absent_from_corpus",
            "evidence": f"{missing_id} not present in any current *_requirements_normalized.jsonl "
                        f"winning-tier file -- UNCONFIRMED (no expected_quotes entry recorded for this "
                        f"id, so content-loss vs. id-relabeling could not be independently checked).",
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

    # Categories 4/5/7/8b are read directly from pool_hits -- no new call
    # here (see module docstring: one draw per query, not one per check).
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
    # raw-query (no rewrite, no HyDE), production-min_score call. A transient
    # failure here must not silently count as evidence for ranking_miss
    # (Codex review, PR #187) -- report it as its own inconclusive result.
    query_id = query["query_id"]
    cache = raw_query_cache if raw_query_cache is not None else {}
    if query_id not in cache:
        try:
            raw_result = retrieve(
                query["query"], top_k=PRODUCTION_TOP_K, min_score=PRODUCTION_MIN_SCORE,
                hyde=False, no_rewrite=True, qdrant_url=qdrant_url, ollama_url=ollama_url,
            )
            cache[query_id] = [r["requirement_id"] for r in raw_result["results"]]
        except Exception as e:
            return {
                "category": None,
                "evidence": f"{missing_id}: present in the top_k={LARGE_POOL_TOP_K}/min_score=0 pool at "
                            f"rank {rank} (score={score:.4f}) but the raw-query disambiguation call "
                            f"failed ({e}) -- inconclusive, not counted as ranking_miss or "
                            f"query_filter_issue.",
            }
    raw_ids = cache[query_id]

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


def classify_over_grabs(query: dict, retrieved_ids: list, corpus: CorpusIndex, *, top_k: int = PRODUCTION_TOP_K) -> list:
    """Flag irrelevant results ranking inside top_k as over-grab candidates.

    A conservative, artifact-grounded subset of true over-grabs -- not a
    full per-result manual review. Two evidence sources, both scanned across
    the full evaluated top_k (default: production top-20, not an arbitrary
    smaller window -- Codex review, PR #187: a top-5 default silently missed
    hand-labeled over-grabs the gold set itself recorded at ranks 6-8):
      - same-chunk co-location with a relevant record (a real, structural
        Phase 38 Over-Grab Precision pattern: duplicate/near-duplicate
        fragments of the same source clause), or
      - the query's own hand-verified expected_over_grab_ids (the
        messy-PDF/over-grab gold bucket) -- checked against the FULL
        retrieved_ids list regardless of top_k, since a hand-labeled
        over-grab is worth reporting (with its real rank) even if it lands
        outside the evaluated window.
    """
    relevant = set(query.get("relevant_requirement_ids", []))
    expected_over_grabs = set(query.get("expected_over_grab_ids", []))
    relevant_chunks = {
        (corpus.doc_key_by_id.get(rid, ""), corpus.records_by_id[rid].get("chunk_id"))
        for rid in relevant if rid in corpus.records_by_id
    }
    findings = []
    seen_ids = set()
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant or rid in seen_ids:
            continue
        rec = corpus.records_by_id.get(rid)
        if rec is None:
            continue
        within_window = rank <= top_k
        key = (corpus.doc_key_by_id.get(rid, ""), rec.get("chunk_id"))
        if rid in expected_over_grabs:
            seen_ids.add(rid)
            suffix = "" if within_window else f" (outside evaluated top-{top_k}, reported for completeness)"
            findings.append({
                "requirement_id": rid, "rank": rank, "category": "over_grab",
                "evidence": f"{rid} hand-labeled as a known over-broad/duplicate extraction for "
                            f"query {query['query_id']}{suffix}.",
            })
        elif within_window and key in relevant_chunks:
            seen_ids.add(rid)
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
    """Run (or reuse) the WP-37.1 harness for the official baseline numbers,
    then classify every miss/over-grab using ONE additional retrieve() call
    per non-zero query (see module docstring) and report category
    prevalence. harness_report can be passed in to reuse an already-computed
    baseline run instead of re-querying retrieve() for the aggregate numbers
    too."""
    if harness_report is None:
        from eval.retrieval_eval_harness import run_harness
        harness_report = run_harness(queries, qdrant_url=qdrant_url, ollama_url=ollama_url)

    queries_by_id = {q["query_id"]: q for q in queries}
    miss_classifications = []
    over_grab_classifications = []
    zero_truth_query_level = []
    raw_query_cache: dict = {}

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
        pool_hits = fetch_classification_pool(query, corpus, qdrant_url=qdrant_url, ollama_url=ollama_url)
        production_ids = [
            r["requirement_id"] for r in pool_hits if r["score"] >= PRODUCTION_MIN_SCORE
        ][:PRODUCTION_TOP_K]
        missed = relevant - set(production_ids)
        for missing_id in sorted(missed):
            result = classify_miss(
                query, missing_id, corpus, pool_hits,
                qdrant_url=qdrant_url, ollama_url=ollama_url, raw_query_cache=raw_query_cache,
            )
            result.update({"query_id": query["query_id"], "requirement_id": missing_id})
            miss_classifications.append(result)

        for note in query.get("unextracted_relevant_content", []):
            miss_classifications.append({
                "query_id": query["query_id"], "requirement_id": None,
                "category": "extraction_failure", "sub_case": "b_never_extracted",
                "evidence": note if isinstance(note, str) else json.dumps(note),
            })

        # Pass the full pool (not just the top_k-truncated production_ids) so a
        # hand-labeled expected_over_grab_id can be found and its real rank
        # reported even when this particular draw pushed it past the evaluated
        # window -- classify_over_grabs' own top_k still gates which findings
        # count as "in the user-visible top-k" (Codex review, PR #187).
        pool_ordered_ids = [r["requirement_id"] for r in pool_hits]
        for og in classify_over_grabs(query, pool_ordered_ids, corpus):
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
