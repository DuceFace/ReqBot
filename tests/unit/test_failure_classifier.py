"""WP-40: unit tests for eval/failure_classifier.py's 8-category classification
logic, against synthetic examples of each category -- proving the classification
logic is correct independent of any specific real miss (same discipline as
WP-37.1's harness-math unit tests, docs/PHASE40_REQUIREMENTS.md's Tests/
verification bullet).
"""
from unittest.mock import patch

import eval.failure_classifier as fc

_LONG_SENTENCE = (
    "Systems shall implement multi-factor authentication for all privileged "
    "accounts accessing sensitive information systems in accordance with "
    "applicable Department of Defense cybersecurity directives and guidance "
    "issued by the appropriate authority."
)


def _corpus(records: dict, doc_key: str = "docA", chunks: dict | None = None, run_dir=None) -> fc.CorpusIndex:
    doc_key_by_id = {rid: doc_key for rid in records}
    return fc.CorpusIndex(
        records_by_id=records,
        doc_key_by_id=doc_key_by_id,
        chunk_text_by_doc={doc_key: chunks or {}},
        run_dir_by_doc_key={doc_key: run_dir} if run_dir is not None else {},
    )


# --- is_garbled_table_text -------------------------------------------------

def test_garbled_table_signature_matches_real_shape():
    text = (
        "Reporting& Notification = Update of actions taken. Preliminary Response "
        "Action, This table presents the relationship...Documentation = "
        "Documentation of any actions taken."
    )
    assert fc.is_garbled_table_text(text) is True


def test_garbled_table_signature_does_not_false_positive_on_single_equals():
    assert fc.is_garbled_table_text("Set MaxLoginAttempts = 3 for all accounts.") is False


def test_garbled_table_signature_ignores_plain_text():
    assert fc.is_garbled_table_text("Systems shall restrict access to authorized users.") is False


# --- Category 1a: extraction_failure (absent from corpus) ------------------

def test_classify_miss_extraction_failure_unconfirmed_when_no_expected_quote_recorded():
    corpus = _corpus({})
    result = fc.classify_miss(
        {"query_id": "Q-1", "query": "irrelevant"}, "REQ-nonexistent", corpus, [],
        qdrant_url="http://x", ollama_url="http://y",
    )
    assert result["category"] == "extraction_failure"
    assert result["sub_case"] == "a_absent_from_corpus"
    assert "UNCONFIRMED" in result["evidence"]


def test_classify_miss_extraction_failure_confirmed_via_normalization_failures(tmp_path):
    fail_file = tmp_path / "docA_normalization_failures.jsonl"
    fail_file.write_text(
        '{"requirement_id": "R-6-3", "error": "unrepairable_fragment_quote", '
        '"raw": {"source_quote": "A rejected fragment quote."}}\n',
        encoding="utf-8",
    )
    corpus = _corpus({}, run_dir=tmp_path)
    query = {
        "query_id": "Q-1", "query": "irrelevant",
        "expected_quotes": {"REQ-gone": {"doc_key": "docA", "quote": "A rejected fragment quote."}},
    }
    result = fc.classify_miss(query, "REQ-gone", corpus, [], qdrant_url="http://x", ollama_url="http://y")
    assert result["category"] == "extraction_failure"
    assert "unrepairable_fragment_quote" in result["evidence"]


def test_classify_miss_not_extraction_failure_when_content_survived_under_different_id(tmp_path):
    corpus = _corpus(
        {"REQ-newid": {"chunk_id": 1, "source_quote": "A relabeled but still-present quote."}},
        run_dir=tmp_path,
    )
    query = {
        "query_id": "Q-1", "query": "irrelevant",
        "expected_quotes": {"REQ-oldid": {"doc_key": "docA", "quote": "A relabeled but still-present quote."}},
    }
    result = fc.classify_miss(query, "REQ-oldid", corpus, [], qdrant_url="http://x", ollama_url="http://y")
    assert result["category"] is None
    assert "REQ-newid" in result["evidence"]


# --- Category 3: table_serialization ----------------------------------------

def test_classify_miss_table_serialization_from_own_quote():
    records = {"REQ-t1": {"chunk_id": 1, "source_quote": "Column A = Value 1. Column B = Value 2."}}
    corpus = _corpus(records)
    result = fc.classify_miss(
        {"query_id": "Q-1", "query": "irrelevant"}, "REQ-t1", corpus, [],
        qdrant_url="http://x", ollama_url="http://y",
    )
    assert result["category"] == "table_serialization"


def test_classify_miss_table_serialization_from_chunk_text_when_own_quote_is_clean():
    # Mirrors the real corpus shape (afi17-203 REQ-5c349cdc3656): Step C extracted
    # a clean short value, but the chunk it came from is a garbled table.
    records = {"REQ-t2": {"chunk_id": 55, "source_quote": "Documentation of analysis results."}}
    chunks = {55: "Reporting& Notification = Update. Documentation = Documentation of results."}
    corpus = _corpus(records, chunks=chunks)
    result = fc.classify_miss(
        {"query_id": "Q-1", "query": "irrelevant"}, "REQ-t2", corpus, [],
        qdrant_url="http://x", ollama_url="http://y",
    )
    assert result["category"] == "table_serialization"


# --- Category 2: missing_context --------------------------------------------

def test_classify_miss_missing_context_fragment_with_no_parent_stem():
    records = {"REQ-m1": {"chunk_id": 2, "source_quote": "(3) Restrain competition.", "parent_stem": ""}}
    corpus = _corpus(records)
    result = fc.classify_miss(
        {"query_id": "Q-1", "query": "irrelevant"}, "REQ-m1", corpus, [],
        qdrant_url="http://x", ollama_url="http://y",
    )
    assert result["category"] == "missing_context"


def test_classify_miss_not_missing_context_when_parent_stem_present():
    # Has parent_stem -- WP-39.2 already reconstructed context for it, so a miss
    # here must fall through to embedding/ranking classification, not missing_context.
    records = {
        "REQ-m2": {
            "chunk_id": 2, "source_quote": "(3) Restrain competition.",
            "parent_stem": "Information will not be classified in order to:",
        }
    }
    corpus = _corpus(records)
    pool_hits = [{"requirement_id": "REQ-other", "score": 0.5}]
    result = fc.classify_miss(
        {"query_id": "Q-1", "query": "irrelevant"}, "REQ-m2", corpus, pool_hits,
        qdrant_url="http://x", ollama_url="http://y",
    )
    assert result["category"] == "embedding_miss"


# --- Category 4: embedding_miss ---------------------------------------------

def test_classify_miss_embedding_miss_when_absent_from_pool():
    records = {"REQ-e1": {"chunk_id": 9, "source_quote": _LONG_SENTENCE}}
    corpus = _corpus(records)
    pool_hits = [{"requirement_id": "REQ-other", "score": 0.5}]
    result = fc.classify_miss(
        {"query_id": "Q-1", "query": "some query"}, "REQ-e1", corpus, pool_hits,
        qdrant_url="http://x", ollama_url="http://y",
    )
    assert result["category"] == "embedding_miss"


def test_fetch_classification_pool_uses_min_score_zero_and_large_topk():
    with patch.object(fc, "retrieve", return_value={"results": []}) as mock_retrieve:
        fc.fetch_classification_pool(
            {"query_id": "Q-1", "query": "some query"}, fc.CorpusIndex(),
            qdrant_url="http://x", ollama_url="http://y",
        )
    _, kwargs = mock_retrieve.call_args
    # min_score=0 must be passed alongside the raised top_k (Codex review, PR #186) --
    # not top_k alone, since retrieve() filters min_score before trimming to top_k.
    assert kwargs["min_score"] == 0
    assert kwargs["top_k"] == fc.LARGE_POOL_TOP_K


# --- Category 8b: zero_truth_confidence_failure (sub-threshold record) -----

def test_classify_miss_sub_threshold_record_is_confidence_failure_not_embedding_miss():
    records = {"REQ-z1": {"chunk_id": 9, "source_quote": _LONG_SENTENCE}}
    corpus = _corpus(records)
    pool_hits = [{"requirement_id": "REQ-z1", "score": 0.008}]  # below production floor of 0.02
    result = fc.classify_miss(
        {"query_id": "Q-1", "query": "some query"}, "REQ-z1", corpus, pool_hits,
        qdrant_url="http://x", ollama_url="http://y",
    )
    assert result["category"] == "zero_truth_confidence_failure"
    assert result["sub_case"] == "b_sub_threshold_record"


# --- Category 7: query_filter_issue -----------------------------------------

def test_classify_miss_query_filter_issue_when_raw_query_finds_it_but_production_doesnt():
    records = {"REQ-q1": {"chunk_id": 9, "source_quote": _LONG_SENTENCE}}
    corpus = _corpus(records)
    pool_hits = [{"requirement_id": f"REQ-filler-{i}", "score": 0.5} for i in range(24)]
    pool_hits.append({"requirement_id": "REQ-q1", "score": 0.3})

    with patch.object(fc, "retrieve", return_value={"results": [{"requirement_id": "REQ-q1", "score": 0.3}]}):
        result = fc.classify_miss(
            {"query_id": "Q-1", "query": "some query"}, "REQ-q1", corpus, pool_hits,
            qdrant_url="http://x", ollama_url="http://y",
        )
    assert result["category"] == "query_filter_issue"


def test_classify_miss_raw_query_failure_is_inconclusive_not_ranking_miss():
    records = {"REQ-fail1": {"chunk_id": 9, "source_quote": _LONG_SENTENCE}}
    corpus = _corpus(records)
    pool_hits = [{"requirement_id": f"REQ-filler-{i}", "score": 0.5} for i in range(24)]
    pool_hits.append({"requirement_id": "REQ-fail1", "score": 0.3})

    with patch.object(fc, "retrieve", side_effect=RuntimeError("Ollama unreachable")):
        result = fc.classify_miss(
            {"query_id": "Q-1", "query": "some query"}, "REQ-fail1", corpus, pool_hits,
            qdrant_url="http://x", ollama_url="http://y",
        )
    # A transient failure in the disambiguation call must not silently count as
    # evidence for ranking_miss (Codex review, PR #187).
    assert result["category"] is None
    assert "failed" in result["evidence"]


# --- Category 5: ranking_miss ------------------------------------------------

def test_classify_miss_ranking_miss_when_present_above_floor_but_outside_topk_both_ways():
    records = {"REQ-r1": {"chunk_id": 9, "source_quote": _LONG_SENTENCE}}
    corpus = _corpus(records)
    pool_hits = [{"requirement_id": f"REQ-filler-{i}", "score": 0.5} for i in range(24)]
    pool_hits.append({"requirement_id": "REQ-r1", "score": 0.3})

    with patch.object(fc, "retrieve", return_value={"results": []}):
        result = fc.classify_miss(
            {"query_id": "Q-1", "query": "some query"}, "REQ-r1", corpus, pool_hits,
            qdrant_url="http://x", ollama_url="http://y",
        )
    assert result["category"] == "ranking_miss"


def test_classify_miss_raw_query_cache_avoids_duplicate_retrieve_calls_for_same_query():
    records = {
        "REQ-a": {"chunk_id": 1, "source_quote": "Systems shall implement the first complete, well-formed requirement sentence used to verify the raw-query cache is shared correctly across two separate missed records for one query."},
        "REQ-b": {"chunk_id": 1, "source_quote": "Systems shall implement the second complete, well-formed requirement sentence used to verify the raw-query cache is shared correctly across two separate missed records for one query."},
    }
    corpus = _corpus(records)
    query = {"query_id": "Q-shared", "query": "some query"}
    pool_hits = [{"requirement_id": f"REQ-filler-{i}", "score": 0.5} for i in range(24)]
    pool_hits += [{"requirement_id": "REQ-a", "score": 0.3}, {"requirement_id": "REQ-b", "score": 0.3}]
    cache: dict = {}
    with patch.object(fc, "retrieve", return_value={"results": []}) as mock_retrieve:
        r1 = fc.classify_miss(query, "REQ-a", corpus, pool_hits, qdrant_url="http://x", ollama_url="http://y", raw_query_cache=cache)
        r2 = fc.classify_miss(query, "REQ-b", corpus, pool_hits, qdrant_url="http://x", ollama_url="http://y", raw_query_cache=cache)
    assert r1["category"] == r2["category"] == "ranking_miss"
    assert mock_retrieve.call_count == 1


# --- Category 6: over_grab ---------------------------------------------------

def test_classify_over_grabs_flags_same_chunk_co_location():
    records = {
        "REQ-good": {"chunk_id": 5, "source_quote": "The correct, relevant clause."},
        "REQ-dup": {"chunk_id": 5, "source_quote": "A near-duplicate fragment of the same clause."},
    }
    corpus = _corpus(records)
    query = {"query_id": "Q-og1", "query": "x", "relevant_requirement_ids": ["REQ-good"]}
    findings = fc.classify_over_grabs(query, ["REQ-dup", "REQ-good"], corpus, top_k=5)
    assert len(findings) == 1
    assert findings[0]["requirement_id"] == "REQ-dup"
    assert findings[0]["category"] == "over_grab"


def test_classify_over_grabs_flags_hand_labeled_expected_over_grab():
    records = {
        "REQ-good": {"chunk_id": 5, "source_quote": "The correct clause."},
        "REQ-wrong": {"chunk_id": 9, "source_quote": "An unrelated, over-broad extraction."},
    }
    corpus = _corpus(records)
    query = {
        "query_id": "Q-og2", "query": "x",
        "relevant_requirement_ids": ["REQ-good"],
        "expected_over_grab_ids": ["REQ-wrong"],
    }
    findings = fc.classify_over_grabs(query, ["REQ-wrong", "REQ-good"], corpus, top_k=5)
    assert len(findings) == 1
    assert findings[0]["requirement_id"] == "REQ-wrong"


def test_classify_over_grabs_does_not_flag_unrelated_irrelevant_results():
    # An irrelevant result in a different chunk, not hand-labeled, is NOT flagged --
    # over-grab detection here is deliberately conservative/artifact-grounded, not a
    # catch-all for every non-relevant top-k result.
    records = {
        "REQ-good": {"chunk_id": 5, "source_quote": "The correct clause."},
        "REQ-unrelated": {"chunk_id": 40, "source_quote": "Something else entirely."},
    }
    corpus = _corpus(records)
    query = {"query_id": "Q-og3", "query": "x", "relevant_requirement_ids": ["REQ-good"]}
    findings = fc.classify_over_grabs(query, ["REQ-unrelated", "REQ-good"], corpus, top_k=5)
    assert findings == []


def test_classify_over_grabs_does_not_match_two_records_both_missing_chunk_id():
    # (Gemini review, PR #187): a relevant record and an irrelevant candidate
    # both lacking chunk_id would otherwise share the key (doc_key, None),
    # falsely matching as "same chunk" duplicates. chunk_id=None must be
    # excluded from the same-chunk-co-location check entirely.
    records = {
        "REQ-good": {"chunk_id": None, "source_quote": "The correct clause."},
        "REQ-unrelated": {"chunk_id": None, "source_quote": "Something else entirely, same missing metadata."},
    }
    corpus = _corpus(records)
    query = {"query_id": "Q-og6", "query": "x", "relevant_requirement_ids": ["REQ-good"]}
    findings = fc.classify_over_grabs(query, ["REQ-unrelated", "REQ-good"], corpus, top_k=5)
    assert findings == []


def test_classify_over_grabs_same_chunk_respects_top_k_cutoff():
    records = {
        "REQ-good": {"chunk_id": 5, "source_quote": "The correct clause."},
        "REQ-dup": {"chunk_id": 5, "source_quote": "Duplicate fragment."},
    }
    corpus = _corpus(records)
    query = {"query_id": "Q-og4", "query": "x", "relevant_requirement_ids": ["REQ-good"]}
    retrieved = ["REQ-filler-1", "REQ-filler-2", "REQ-filler-3", "REQ-filler-4", "REQ-filler-5", "REQ-dup"]
    findings = fc.classify_over_grabs(query, retrieved, corpus, top_k=5)
    assert findings == []  # REQ-dup is at rank 6, outside top_k=5


def test_classify_over_grabs_finds_hand_labeled_over_grab_beyond_default_topk():
    # Codex review, PR #187: a top-5 default silently missed hand-labeled
    # over-grabs recorded at ranks 6-8 in the real gold set (Q-O01). Hand-labeled
    # expected_over_grab_ids must be found regardless of the scan window.
    records = {
        "REQ-good": {"chunk_id": 5, "source_quote": "The correct clause."},
        "REQ-wrong": {"chunk_id": 9, "source_quote": "An over-broad extraction."},
    }
    corpus = _corpus(records)
    query = {
        "query_id": "Q-og5", "query": "x",
        "relevant_requirement_ids": ["REQ-good"],
        "expected_over_grab_ids": ["REQ-wrong"],
    }
    retrieved = ["REQ-filler-1", "REQ-filler-2", "REQ-filler-3", "REQ-filler-4", "REQ-filler-5", "REQ-good", "REQ-wrong"]
    findings = fc.classify_over_grabs(query, retrieved, corpus, top_k=5)
    assert len(findings) == 1
    assert findings[0]["requirement_id"] == "REQ-wrong"
    assert findings[0]["rank"] == 7
    assert findings[0]["evidence"].endswith("(outside evaluated top-5, reported for completeness).")


def test_classify_over_grabs_default_topk_is_production_topk():
    import inspect
    sig = inspect.signature(fc.classify_over_grabs)
    assert sig.parameters["top_k"].default == fc.PRODUCTION_TOP_K


# --- build_prevalence_report wiring (zero-truth query-level + unextracted note) --

def test_build_prevalence_report_flags_zero_truth_never_reporting_empty():
    queries = [
        {"query_id": "Q-Z1", "query": "off topic", "shape": "zero", "relevant_requirement_ids": []},
    ]
    harness_report = {
        "per_query": [
            {"query_id": "Q-Z1", "query": "off topic", "shape": "zero", "relevant_count": 0, "returned_count": 20},
        ],
        "aggregate": {},
    }
    corpus = _corpus({})
    report = fc.build_prevalence_report(
        queries, corpus, qdrant_url="http://x", ollama_url="http://y", harness_report=harness_report,
    )
    assert report["zero_truth_never_reports_empty"] is True
    assert report["zero_truth_query_level"][0]["correctly_empty"] is False


def test_build_prevalence_report_counts_unextracted_relevant_content_as_extraction_failure_b():
    queries = [
        {
            "query_id": "Q-N1", "query": "narrow query", "shape": "narrow",
            "relevant_requirement_ids": ["REQ-known"],
            "unextracted_relevant_content": ["docX p.4: real obligation sentence Step C never extracted."],
        },
    ]
    harness_report = {
        "per_query": [
            {"query_id": "Q-N1", "query": "narrow query", "shape": "narrow", "relevant_count": 1,
             "retrieved_ids": ["REQ-known"], "recall@5": 1.0, "recall@10": 1.0, "recall@20": 1.0, "mrr": 1.0},
        ],
        "aggregate": {},
    }
    corpus = _corpus({"REQ-known": {"chunk_id": 1, "source_quote": "A complete sentence.", "parent_stem": ""}})
    with patch.object(fc, "retrieve", return_value={"results": [{"requirement_id": "REQ-known", "score": 0.5}]}):
        report = fc.build_prevalence_report(
            queries, corpus, qdrant_url="http://x", ollama_url="http://y", harness_report=harness_report,
        )
    assert report["extraction_failure_sub_counts"]["b_never_extracted"] == 1
    assert report["category_prevalence"]["extraction_failure"] == 1


def test_build_prevalence_report_attaches_query_id_to_over_grab_findings():
    queries = [
        {"query_id": "Q-N1", "query": "narrow query", "shape": "narrow", "relevant_requirement_ids": ["REQ-good"]},
    ]
    harness_report = {
        "per_query": [
            {"query_id": "Q-N1", "query": "narrow query", "shape": "narrow", "relevant_count": 1,
             "retrieved_ids": ["REQ-dup", "REQ-good"], "recall@5": 1.0, "recall@10": 1.0, "recall@20": 1.0, "mrr": 0.5},
        ],
        "aggregate": {},
    }
    corpus = _corpus({
        "REQ-good": {"chunk_id": 5, "source_quote": "The correct clause.", "parent_stem": ""},
        "REQ-dup": {"chunk_id": 5, "source_quote": "A near-duplicate fragment.", "parent_stem": ""},
    })
    with patch.object(fc, "retrieve", return_value={"results": [
        {"requirement_id": "REQ-dup", "score": 0.5}, {"requirement_id": "REQ-good", "score": 0.4},
    ]}):
        report = fc.build_prevalence_report(
            queries, corpus, qdrant_url="http://x", ollama_url="http://y", harness_report=harness_report,
        )
    assert len(report["over_grab_classifications"]) == 1
    assert report["over_grab_classifications"][0]["query_id"] == "Q-N1"


def test_build_prevalence_report_uses_self_consistent_pool_for_miss_detection_and_classification():
    # Codex review, PR #187: miss detection and category assignment must come from
    # the SAME retrieve() call per query, not the harness's separately-drawn one plus
    # a second independent draw for classification.
    queries = [
        {"query_id": "Q-N1", "query": "narrow query", "shape": "narrow", "relevant_requirement_ids": ["REQ-missed"]},
    ]
    # Harness itself reports REQ-missed as retrieved (not a miss by its own numbers) --
    # but the classification pool call (mocked below) disagrees. The self-consistent
    # design must trust the pool call it actually issued for classification purposes,
    # not silently mix in the harness's separate retrieved_ids.
    harness_report = {
        "per_query": [
            {"query_id": "Q-N1", "query": "narrow query", "shape": "narrow", "relevant_count": 1,
             "retrieved_ids": ["REQ-missed"], "recall@5": 1.0, "recall@10": 1.0, "recall@20": 1.0, "mrr": 1.0},
        ],
        "aggregate": {},
    }
    corpus = _corpus({"REQ-missed": {"chunk_id": 1, "source_quote": _LONG_SENTENCE, "parent_stem": ""}})
    with patch.object(fc, "retrieve", return_value={"results": []}):  # pool call finds nothing
        report = fc.build_prevalence_report(
            queries, corpus, qdrant_url="http://x", ollama_url="http://y", harness_report=harness_report,
        )
    # Classified as a miss (embedding_miss) based on the pool call actually issued,
    # regardless of what the harness's own separate retrieved_ids said.
    assert len(report["miss_classifications"]) == 1
    assert report["miss_classifications"][0]["category"] == "embedding_miss"


def test_build_prevalence_report_finds_expected_over_grab_beyond_production_topk():
    # A hand-labeled expected_over_grab_id that lands past rank 20 in this
    # particular pool draw must still be found and reported (Codex review,
    # PR #187) -- classify_over_grabs must see the full pool, not just the
    # top_k-truncated production_ids passed for miss detection.
    queries = [
        {
            "query_id": "Q-O1", "query": "narrow query", "shape": "messy_pdf_overgrab",
            "relevant_requirement_ids": ["REQ-good"],
            "expected_over_grab_ids": ["REQ-buried"],
        },
    ]
    harness_report = {
        "per_query": [
            {"query_id": "Q-O1", "query": "narrow query", "shape": "messy_pdf_overgrab", "relevant_count": 1,
             "retrieved_ids": ["REQ-good"], "recall@5": 1.0, "recall@10": 1.0, "recall@20": 1.0, "mrr": 1.0},
        ],
        "aggregate": {},
    }
    corpus = _corpus({
        "REQ-good": {"chunk_id": 1, "source_quote": "The correct clause.", "parent_stem": ""},
        "REQ-buried": {"chunk_id": 9, "source_quote": "An over-broad extraction.", "parent_stem": ""},
    })
    pool_hits = [{"requirement_id": "REQ-good", "score": 0.9}]
    pool_hits += [{"requirement_id": f"REQ-filler-{i}", "score": 0.5} for i in range(24)]
    pool_hits.append({"requirement_id": "REQ-buried", "score": 0.1})  # rank 26, past top_k=20
    with patch.object(fc, "retrieve", return_value={"results": pool_hits}):
        report = fc.build_prevalence_report(
            queries, corpus, qdrant_url="http://x", ollama_url="http://y", harness_report=harness_report,
        )
    over_grabs = [og for og in report["over_grab_classifications"] if og["requirement_id"] == "REQ-buried"]
    assert len(over_grabs) == 1
    assert over_grabs[0]["rank"] == 26
