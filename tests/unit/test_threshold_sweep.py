"""Unit tests for WP-35.2's threshold sweep and selection logic."""
from eval.threshold_sweep import margin_analysis, regression_check, select_threshold, sweep


def _record(rid, label, support_prob, source="wp_35_1_harvest"):
    return {"requirement_id": rid, "label": label, "support_prob": support_prob, "source": source}


def test_sweep_computes_rates_at_a_single_threshold():
    scored = [
        _record("REQ-1", "faithful", 0.9),
        _record("REQ-2", "faithful", 0.4),  # below threshold -> false positive
        _record("REQ-3", "fabricated_citation", 0.1),  # below threshold -> caught
        _record("REQ-4", "fabricated_fragment", 0.8),  # above threshold -> missed
    ]
    table = sweep(scored, thresholds=[0.5])
    row = table[0]
    assert row["faithful_n"] == 2
    assert row["false_positive_count"] == 1
    assert row["false_positive_rate"] == 0.5
    assert row["fabricated_n"] == 2
    assert row["catch_count"] == 1
    assert row["catch_rate"] == 0.5


def test_sweep_excludes_wp_34_4_spike_records():
    scored = [
        _record("REQ-1", "faithful", 0.9, source="wp_35_1_harvest"),
        _record("REQ-2", "fabricated_citation", 0.1, source="wp_34_4_spike"),
    ]
    table = sweep(scored, thresholds=[0.5])
    row = table[0]
    # Only the wp_35_1_harvest record counts -- 1 faithful, 0 fabricated.
    assert row["faithful_n"] == 1
    assert row["fabricated_n"] == 0
    assert row["catch_rate"] is None


def test_sweep_per_subtype_breakdown():
    scored = [
        _record("REQ-1", "fabricated_citation", 0.1),
        _record("REQ-2", "fabricated_citation", 0.9),
        _record("REQ-3", "fabricated_modality", 0.1),
    ]
    table = sweep(scored, thresholds=[0.5])
    by_subtype = table[0]["by_subtype"]
    assert by_subtype["fabricated_citation"] == {"n": 2, "caught": 1}
    assert by_subtype["fabricated_modality"] == {"n": 1, "caught": 1}
    assert by_subtype["fabricated_fragment"] == {"n": 0, "caught": 0}


def test_sweep_is_monotonic_as_threshold_rises():
    scored = [
        _record("REQ-1", "faithful", 0.3),
        _record("REQ-2", "faithful", 0.7),
        _record("REQ-3", "fabricated_citation", 0.2),
        _record("REQ-4", "fabricated_citation", 0.6),
    ]
    table = sweep(scored, thresholds=[0.1, 0.5, 0.9])
    fp_counts = [row["false_positive_count"] for row in table]
    catch_counts = [row["catch_count"] for row in table]
    assert fp_counts == sorted(fp_counts)
    assert catch_counts == sorted(catch_counts)


def test_regression_check_flags_incorrect_classification():
    scored = [
        _record("REQ-1", "fabricated_citation", 0.1, source="wp_34_4_spike"),  # correctly rejected
        _record("REQ-2", "faithful", 0.9, source="wp_34_4_spike"),  # correctly accepted
        _record("REQ-3", "fabricated_modality", 0.92, source="wp_34_4_spike"),  # missed
    ]
    result = regression_check(scored, threshold=0.85)
    assert result["all_correct"] is False
    by_id = {r["requirement_id"]: r for r in result["records"]}
    assert by_id["REQ-1"]["correct"] is True
    assert by_id["REQ-2"]["correct"] is True
    assert by_id["REQ-3"]["correct"] is False
    assert by_id["REQ-3"]["predicted_reject"] is False
    assert by_id["REQ-3"]["should_reject"] is True


def test_regression_check_all_correct_true_when_all_classified_correctly():
    scored = [
        _record("REQ-1", "fabricated_citation", 0.1, source="wp_34_4_spike"),
        _record("REQ-2", "faithful", 0.9, source="wp_34_4_spike"),
    ]
    result = regression_check(scored, threshold=0.5)
    assert result["all_correct"] is True


# ---------------------------------------------------------------------------
# select_threshold
# ---------------------------------------------------------------------------

def test_select_threshold_picks_highest_catch_rate_within_fp_cap():
    table = [
        {"threshold": 0.5, "false_positive_rate": 0.05, "catch_rate": 0.5},
        {"threshold": 0.85, "false_positive_rate": 0.05, "catch_rate": 0.875},
        {"threshold": 0.9, "false_positive_rate": 0.13, "catch_rate": 0.875},  # over the cap
        {"threshold": 0.95, "false_positive_rate": 0.587, "catch_rate": 1.0},  # over the cap
    ]
    chosen = select_threshold(table, fp_rate_cap=0.10)
    assert chosen["threshold"] == 0.85


def test_select_threshold_falls_back_to_full_table_when_nothing_within_cap():
    table = [
        {"threshold": 0.5, "false_positive_rate": 0.5, "catch_rate": 0.5},
        {"threshold": 0.9, "false_positive_rate": 0.9, "catch_rate": 1.0},
    ]
    chosen = select_threshold(table, fp_rate_cap=0.10)
    assert chosen["threshold"] == 0.9


def test_select_threshold_does_not_crash_on_empty_faithful_partition():
    # false_positive_rate is None when the faithful partition is empty
    # (sweep()'s own convention) -- must not raise a TypeError comparing None.
    table = [
        {"threshold": 0.5, "false_positive_rate": None, "catch_rate": 1.0},
    ]
    chosen = select_threshold(table)
    assert chosen["threshold"] == 0.5


def test_select_threshold_does_not_crash_on_empty_fabricated_partition():
    # catch_rate is None when the fabricated partition is empty.
    table = [
        {"threshold": 0.5, "false_positive_rate": 0.0, "catch_rate": None},
    ]
    chosen = select_threshold(table)
    assert chosen["threshold"] == 0.5


# ---------------------------------------------------------------------------
# margin_analysis
# ---------------------------------------------------------------------------

def test_margin_analysis_finds_narrowest_catch_and_accept():
    # Real regression case: REQ-c6d23854cd0b at 0.8421 vs threshold 0.85 --
    # found by Codex review, PR #167.
    scored = [
        _record("REQ-1", "fabricated_citation", 0.1),
        _record("REQ-2", "fabricated_fragment", 0.8421),
        _record("REQ-3", "faithful", 0.9),
    ]
    result = margin_analysis(scored, threshold=0.85)
    assert result["narrowest_catch"]["requirement_id"] == "REQ-2"
    assert result["narrowest_catch"]["margin"] == 0.0079
    assert result["narrowest_accept"]["requirement_id"] == "REQ-3"
    assert result["narrowest_accept"]["margin"] == 0.05
    assert result["missed_fabricated_n"] == 0


def test_margin_analysis_excludes_wp_34_4_spike_records():
    scored = [
        _record("REQ-1", "fabricated_citation", 0.84, source="wp_34_4_spike"),
    ]
    result = margin_analysis(scored, threshold=0.85)
    assert result["narrowest_catch"] is None


def test_margin_analysis_counts_missed_fabricated():
    scored = [
        _record("REQ-1", "fabricated_citation", 0.9),  # above threshold -> missed
    ]
    result = margin_analysis(scored, threshold=0.85)
    assert result["missed_fabricated_n"] == 1
    assert result["narrowest_catch"] is None


def test_margin_analysis_handles_no_faithful_records():
    scored = [_record("REQ-1", "fabricated_citation", 0.1)]
    result = margin_analysis(scored, threshold=0.85)
    assert result["narrowest_accept"] is None
