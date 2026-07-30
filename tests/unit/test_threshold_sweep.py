"""Unit tests for WP-35.2's threshold sweep and selection logic."""
from eval.threshold_sweep import regression_check, sweep


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
