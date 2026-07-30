"""Unit tests for WP-35.1's gold-dataset builder."""
import pytest

from eval.build_gold_description_grounding import build_records


def _entry(rid, quote="q", description="d", pdf="doc.pdf", chunk_id=0):
    return {
        "requirement_id": rid,
        "source_quote": quote,
        "description": description,
        "section_title_path": [],
        "parent_context": None,
        "source_pdf": pdf,
        "chunk_id": chunk_id,
        "run_dir": "doc_20260730_000000",
    }


def _harvest(citation=None, modality=None, clean=None):
    return {
        "citation_fragment_shaped": citation or [],
        "modality_shaped": modality or [],
        "clean_sample": clean or [],
    }


def test_build_records_labels_and_tags_source_correctly():
    harvest = _harvest(citation=[_entry("REQ-1")])
    labels = {"REQ-1": ("fabricated_citation", "some note")}
    records = build_records(harvest, labels, spike_overlap_ids=set(), preferred_description={})
    assert len(records) == 1
    assert records[0]["label"] == "fabricated_citation"
    assert records[0]["source"] == "wp_35_1_harvest"


def test_build_records_tags_spike_overlap_source():
    harvest = _harvest(citation=[_entry("REQ-1")])
    labels = {"REQ-1": ("fabricated_citation", "note")}
    records = build_records(
        harvest, labels, spike_overlap_ids={"REQ-1"}, preferred_description={}
    )
    assert records[0]["source"] == "wp_34_4_spike"


def test_build_records_clean_sample_always_faithful_and_new():
    harvest = _harvest(clean=[_entry("REQ-2")])
    records = build_records(harvest, labels={}, spike_overlap_ids=set(), preferred_description={})
    assert len(records) == 1
    assert records[0]["label"] == "faithful"
    assert records[0]["source"] == "wp_35_1_harvest"


def test_build_records_raises_on_label_for_missing_requirement_id():
    harvest = _harvest()
    labels = {"REQ-ghost": ("faithful", "note")}
    with pytest.raises(SystemExit, match="not found in harvest output"):
        build_records(harvest, labels, spike_overlap_ids=set(), preferred_description={})


def test_build_records_raises_on_flagged_candidate_missing_a_label():
    harvest = _harvest(citation=[_entry("REQ-1")])
    with pytest.raises(SystemExit, match="no hand-verified label"):
        build_records(harvest, labels={}, spike_overlap_ids=set(), preferred_description={})


def test_build_records_raises_on_unregistered_duplicate_with_differing_descriptions():
    harvest = _harvest(
        citation=[_entry("REQ-1", description="first"), _entry("REQ-1", description="second")]
    )
    labels = {"REQ-1": ("fabricated_citation", "note")}
    with pytest.raises(SystemExit, match="Duplicate requirement_id"):
        build_records(harvest, labels, spike_overlap_ids=set(), preferred_description={})


def test_build_records_keeps_preferred_description_on_registered_duplicate():
    harvest = _harvest(
        citation=[_entry("REQ-1", description="worse"), _entry("REQ-1", description="better")]
    )
    labels = {"REQ-1": ("fabricated_citation", "note")}
    records = build_records(
        harvest, labels, spike_overlap_ids=set(), preferred_description={"REQ-1": "better"}
    )
    assert len(records) == 1
    assert records[0]["description"] == "better"


def test_build_records_same_description_duplicate_does_not_raise():
    # A harmless exact duplicate (e.g. re-ingested identically) collapses
    # silently -- only a *differing*-description duplicate is an error.
    harvest = _harvest(
        citation=[_entry("REQ-1", description="same"), _entry("REQ-1", description="same")]
    )
    labels = {"REQ-1": ("fabricated_citation", "note")}
    records = build_records(harvest, labels, spike_overlap_ids=set(), preferred_description={})
    assert len(records) == 1
