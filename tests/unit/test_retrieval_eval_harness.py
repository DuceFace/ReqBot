"""Unit tests for eval/retrieval_eval_harness.py's metrics math and
run_harness() orchestration (WP-37.1). retrieve() is always mocked via
monkeypatch -- no live Qdrant/Ollama calls in these tests, only the pure
recall@k/MRR computation and per-query error handling.
"""
import pytest

from eval import retrieval_eval_harness as harness


def _fake_result(ids: list[str]) -> dict:
    return {"results": [{"requirement_id": rid} for rid in ids], "total": len(ids)}


def test_compute_metrics_perfect_recall_at_rank_one():
    relevant = {"REQ-1", "REQ-2"}
    retrieved = ["REQ-1", "REQ-2", "REQ-3"]
    m = harness.compute_metrics(relevant, retrieved)
    assert m["recall@5"] == 1.0
    assert m["recall@10"] == 1.0
    assert m["recall@20"] == 1.0
    assert m["mrr"] == 1.0


def test_compute_metrics_partial_recall():
    relevant = {"REQ-1", "REQ-2", "REQ-3", "REQ-4"}
    retrieved = ["REQ-9", "REQ-1", "REQ-8"]
    m = harness.compute_metrics(relevant, retrieved)
    assert m["recall@5"] == 0.25  # only REQ-1 found, 1/4
    assert m["mrr"] == 0.5  # REQ-1 found at rank 2 -> 1/2


def test_compute_metrics_no_relevant_found():
    relevant = {"REQ-1"}
    retrieved = ["REQ-9", "REQ-8", "REQ-7"]
    m = harness.compute_metrics(relevant, retrieved)
    assert m["recall@5"] == 0.0
    assert m["mrr"] == 0.0


def test_compute_metrics_recall_at_k_boundary():
    # Relevant hit lands at rank 6 -- misses recall@5 but counts for recall@10/20.
    relevant = {"REQ-1"}
    retrieved = ["REQ-a", "REQ-b", "REQ-c", "REQ-d", "REQ-e", "REQ-1"]
    m = harness.compute_metrics(relevant, retrieved)
    assert m["recall@5"] == 0.0
    assert m["recall@10"] == 1.0
    assert m["recall@20"] == 1.0
    assert m["mrr"] == round(1 / 6, 4)


def test_compute_metrics_empty_relevant_ids_reports_returned_count_not_recall():
    m = harness.compute_metrics(set(), ["REQ-x", "REQ-y"])
    assert m == {"returned_count": 2}
    assert "recall@5" not in m
    assert "mrr" not in m


def test_run_harness_scores_non_zero_query_from_mocked_retrieve(monkeypatch):
    def fake_retrieve(query, **kwargs):
        return _fake_result(["REQ-1", "REQ-9"])

    monkeypatch.setattr(harness, "retrieve", fake_retrieve)
    queries = [{
        "query_id": "Q-1", "query": "test query", "shape": "narrow",
        "relevant_requirement_ids": ["REQ-1"],
    }]
    report = harness.run_harness(queries, qdrant_url="http://x", ollama_url="http://y")
    assert report["per_query"][0]["recall@5"] == 1.0
    assert report["aggregate"]["mean_recall@5"] == 1.0
    assert report["aggregate"]["non_zero_query_count"] == 1
    assert report["aggregate"]["zero_query_count"] == 0


def test_run_harness_zero_query_excluded_from_recall_aggregate(monkeypatch):
    def fake_retrieve(query, **kwargs):
        return _fake_result(["REQ-9", "REQ-8"])

    monkeypatch.setattr(harness, "retrieve", fake_retrieve)
    queries = [{
        "query_id": "Q-Z1", "query": "off topic", "shape": "zero",
        "relevant_requirement_ids": [],
    }]
    report = harness.run_harness(queries, qdrant_url="http://x", ollama_url="http://y")
    assert "recall@5" not in report["per_query"][0]
    assert report["per_query"][0]["returned_count"] == 2
    assert report["aggregate"]["mean_recall@5"] is None  # no non-zero queries to average
    assert report["aggregate"]["zero_query_count"] == 1
    assert report["aggregate"]["zero_query_mean_returned_count"] == 2.0


def test_run_harness_unscored_query_excluded_from_scored_count_and_mean(monkeypatch):
    # Codex review, PR #189 (local re-review): a query with relevant_count == 0
    # but shape != "zero" (e.g. WP-40's unextracted_relevant_content sub-case
    # (b) -- no requirement_id ever existed to score against) must not be
    # silently counted as "scored" while contributing nothing to the mean.
    def fake_retrieve(query, **kwargs):
        return _fake_result(["REQ-1", "REQ-2"])

    monkeypatch.setattr(harness, "retrieve", fake_retrieve)
    queries = [
        {"query_id": "Q-real", "query": "a real query", "shape": "narrow",
         "relevant_requirement_ids": ["REQ-1"]},
        {"query_id": "Q-unextracted", "query": "table content never extracted",
         "shape": "table_derived", "relevant_requirement_ids": []},
    ]
    report = harness.run_harness(queries, qdrant_url="http://x", ollama_url="http://y")
    assert report["aggregate"]["non_zero_query_count"] == 1
    assert report["aggregate"]["unscored_query_count"] == 1
    assert report["aggregate"]["unscored_query_ids"] == ["Q-unextracted"]
    assert report["aggregate"]["mean_recall@5"] == 1.0  # only Q-real's perfect recall
    assert "recall@5" not in report["per_query"][1]


def test_run_harness_query_failure_does_not_crash_the_run(monkeypatch):
    def fake_retrieve(query, **kwargs):
        if query == "bad query":
            raise RuntimeError("simulated retrieve() failure")
        return _fake_result(["REQ-1"])

    monkeypatch.setattr(harness, "retrieve", fake_retrieve)
    queries = [
        {"query_id": "Q-bad", "query": "bad query", "shape": "narrow", "relevant_requirement_ids": ["REQ-1"]},
        {"query_id": "Q-good", "query": "good query", "shape": "narrow", "relevant_requirement_ids": ["REQ-1"]},
    ]
    report = harness.run_harness(queries, qdrant_url="http://x", ollama_url="http://y")
    assert "error" in report["per_query"][0]
    assert report["per_query"][0]["query_id"] == "Q-bad"
    assert "error" not in report["per_query"][1]
    assert report["aggregate"]["failed_query_count"] == 1
    assert report["aggregate"]["non_zero_query_count"] == 1  # only the good one counted


def test_load_gold_queries_reads_jsonl(tmp_path):
    path = tmp_path / "queries.jsonl"
    path.write_text(
        '{"query_id": "Q-1", "query": "a", "shape": "narrow", "relevant_requirement_ids": ["REQ-1"]}\n'
        "\n"  # blank line must be skipped
        '{"query_id": "Q-2", "query": "b", "shape": "zero", "relevant_requirement_ids": []}\n',
        encoding="utf-8",
    )
    queries = harness.load_gold_queries(str(path))
    assert len(queries) == 2
    assert queries[0]["query_id"] == "Q-1"
    assert queries[1]["shape"] == "zero"


def _write_gold(tmp_path):
    path = tmp_path / "queries.jsonl"
    path.write_text(
        '{"query_id": "Q-1", "query": "a query", "shape": "narrow", "relevant_requirement_ids": ["REQ-1"]}\n',
        encoding="utf-8",
    )
    return path


def test_main_rejects_top_k_below_max_k_values(tmp_path, monkeypatch, capsys):
    # Gemini + Codex review, PR #177: a lower --top-k silently truncates the
    # candidate set that recall@10/@20 are computed against.
    gold = _write_gold(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["retrieval_eval_harness.py", "--gold", str(gold), "--top-k", "5",
         "--qdrant-url", "http://x", "--ollama-url", "http://y",
         "--output-dir", str(tmp_path / "out")],
    )
    with pytest.raises(SystemExit) as exc_info:
        harness.main()
    assert exc_info.value.code != 0
    assert "--top-k must be at least 20" in capsys.readouterr().err


def test_main_exits_nonzero_when_a_query_fails(tmp_path, monkeypatch):
    # Codex review, PR #177: a transient retrieve() failure must not produce
    # a silently "successful" exit code on an incomplete report.
    gold = _write_gold(tmp_path)

    def failing_retrieve(query, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(harness, "retrieve", failing_retrieve)
    monkeypatch.setattr(
        "sys.argv",
        ["retrieval_eval_harness.py", "--gold", str(gold),
         "--qdrant-url", "http://x", "--ollama-url", "http://y",
         "--output-dir", str(tmp_path / "out")],
    )
    with pytest.raises(SystemExit) as exc_info:
        harness.main()
    assert exc_info.value.code == 1
    # Report is still written -- partial results remain useful for debugging.
    assert (tmp_path / "out" / "results.json").exists()


def test_main_exits_zero_when_all_queries_succeed(tmp_path, monkeypatch):
    gold = _write_gold(tmp_path)

    def fake_retrieve(query, **kwargs):
        return _fake_result(["REQ-1"])

    monkeypatch.setattr(harness, "retrieve", fake_retrieve)
    monkeypatch.setattr(
        "sys.argv",
        ["retrieval_eval_harness.py", "--gold", str(gold),
         "--qdrant-url", "http://x", "--ollama-url", "http://y",
         "--output-dir", str(tmp_path / "out")],
    )
    harness.main()  # must not raise/exit nonzero
    assert (tmp_path / "out" / "results.json").exists()
