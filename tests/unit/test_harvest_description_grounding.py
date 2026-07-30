"""Unit tests for WP-35.1's candidate-harvesting heuristics."""
import argparse
import json

import pytest

from eval.harvest_description_grounding_candidates import (
    _is_citation_fragment_shaped,
    _is_modality_shaped,
    _non_negative_int,
    _obligation_words_in,
    harvest,
)


def _write_enriched(run_dir, filename, records_text):
    run_dir.mkdir()
    (run_dir / filename).write_text(records_text)

# ---------------------------------------------------------------------------
# _is_citation_fragment_shaped
# ---------------------------------------------------------------------------

def test_citation_fragment_shaped_true_for_real_fabricated_citation():
    # WP-34.4 known-bad (afpd_dodi_8500_citation), hand-verified fabricated.
    quote = "DoDI 8500.01, Cybersecurity, March 14, 2014"
    description = (
        "Establishes policies and procedures for implementing cybersecurity "
        "measures in accordance with NIST SP 800-53 Rev. 4."
    )
    assert _is_citation_fragment_shaped(quote, description) is True


def test_citation_fragment_shaped_true_for_colon_terminated_fragment():
    # WP-34.4 known-bad (cjcsi_po_service_principal_fragment).
    quote = "The PO, in conjunction with Service Principal/CIO and AO will:"
    description = (
        "The PO, in conjunction with Service Principal/CIO and AO will: Address "
        "the operational readiness of cybersecurity solutions and cryptographic "
        "products employed to provide continuous protection to national security "
        "information."
    )
    assert _is_citation_fragment_shaped(quote, description) is True


def test_citation_fragment_shaped_false_for_faithful_paraphrase():
    # WP-34.4 known-good (cjcsi_ker_reordered) -- real paraphrase, not fabricated.
    quote = (
        "In the event a decertified product would be required to be used beyond "
        "the published cease key dates, then a key extension request (KER) for "
        "decertified product must be submitted."
    )
    description = (
        "A key extension request (KER) for decertified product must be submitted "
        "if a decertified product is required to be used beyond the published "
        "cease key dates."
    )
    assert _is_citation_fragment_shaped(quote, description) is False


def test_citation_fragment_shaped_false_when_description_not_much_longer():
    # Short quote, but description is roughly the same length -- not fragment-shaped.
    quote = "Immediate removal from operational mission areas is required."
    description = "Immediate removal from operational mission areas is required."
    assert _is_citation_fragment_shaped(quote, description) is False


def test_citation_fragment_shaped_false_for_long_quote_even_if_dissimilar():
    # A quote longer than FRAGMENT_MAX_WORDS and not colon-terminated never
    # qualifies as "short or colon", regardless of the description.
    quote = (
        "This is a long, complete sentence with plenty of its own content that "
        "exceeds the fragment word-count threshold on its own and does not end "
        "in a colon at all."
    )
    description = "Something completely unrelated invented from nothing."
    assert _is_citation_fragment_shaped(quote, description) is False


# ---------------------------------------------------------------------------
# _obligation_words_in
# ---------------------------------------------------------------------------

def test_obligation_words_in_finds_single_word_verb():
    assert "must" in _obligation_words_in("DoD Components must use only approved products.")


def test_obligation_words_in_finds_multi_word_phrase():
    words = _obligation_words_in("The agency is responsible for this program.")
    assert "is responsible for" in words


def test_obligation_words_in_respects_word_boundaries():
    # "will" should not match inside "willing" or "willingly".
    words = _obligation_words_in("AO willingly accepts all risk associated with the outage.")
    assert "will" not in words


def test_obligation_words_in_empty_for_no_matches():
    assert _obligation_words_in("The sky is blue today.") == set()


# ---------------------------------------------------------------------------
# _is_modality_shaped
# ---------------------------------------------------------------------------

def test_modality_shaped_true_for_real_fabricated_obligation():
    # WP-34.4 known-bad (afpd_definition_reframed_as_imperative) -- a glossary
    # definition reframed as an imperative; "Implement" is invented.
    quote = (
        "Cybersecurity - Prevention of damage to, protection of, and restoration "
        "of computers, electronic communications systems, to ensure its "
        "availability, integrity, authentication, confidentiality, and "
        "nonrepudiation."
    )
    description = (
        "Implement cybersecurity measures to prevent damage, protect, and "
        "restore computers, electronic communications systems, to ensure "
        "availability, integrity, authentication, confidentiality, and "
        "nonrepudiation."
    )
    assert _is_modality_shaped(quote, description) is True


def test_modality_shaped_false_when_obligation_words_match_on_both_sides():
    quote = "DoD Components will use only NSA-approved cryptographic products."
    description = "DoD Components will use only NSA-approved cryptographic products."
    assert _is_modality_shaped(quote, description) is False


def test_modality_shaped_true_is_a_broad_heuristic_not_a_final_verdict():
    # Documented, known over-catch: a real "will" -> "must" paraphrase (WP-34.4
    # known-good, dodi_nsa_approved_crypto) still flags here -- this heuristic
    # is a haystack net for hand review, not a production classifier (see this
    # module's own docstring). Hand-verification is what assigns the real label.
    quote = (
        "DoD Components will use only NSA-approved cryptographic products to "
        "protect classified and/or sensitive national security information."
    )
    description = (
        "DoD Components must use only NSA-approved cryptographic products to "
        "protect classified and/or sensitive national security information."
    )
    assert _is_modality_shaped(quote, description) is True


# ---------------------------------------------------------------------------
# _non_negative_int
# ---------------------------------------------------------------------------

def test_non_negative_int_accepts_zero_and_positive():
    assert _non_negative_int("0") == 0
    assert _non_negative_int("42") == 42


def test_non_negative_int_rejects_negative():
    with pytest.raises(argparse.ArgumentTypeError):
        _non_negative_int("-1")


def test_non_negative_int_rejects_non_numeric():
    with pytest.raises(argparse.ArgumentTypeError):
        _non_negative_int("abc")


# ---------------------------------------------------------------------------
# harvest() -- run scanning, dedup, and robustness against in-progress runs
# ---------------------------------------------------------------------------

def test_harvest_against_missing_processed_dir(tmp_path):
    result = harvest(clean_sample_size=5, processed_dir=tmp_path / "does-not-exist")
    assert result["totals"]["run_dirs_found"] == 0
    assert result["totals"]["runs_scanned"] == 0
    assert result["totals"]["records_scanned"] == 0


def test_harvest_excludes_empty_enriched_file_from_runs_scanned(tmp_path):
    # A run directory whose enriched file exists but has zero records (e.g. a
    # Step D.5 run that just created the file and hasn't written anything yet)
    # must not count toward runs_scanned -- it contributed nothing.
    _write_enriched(tmp_path / "doc1_20260101_000000", "doc1_requirements_enriched.jsonl", "")
    result = harvest(clean_sample_size=5, processed_dir=tmp_path)
    assert result["totals"]["run_dirs_found"] == 1
    assert result["totals"]["runs_scanned"] == 0


def test_harvest_skips_truncated_trailing_line_without_crashing(tmp_path):
    # Step D.5 appends incrementally -- reading mid-write can catch a
    # partially-written last line. Must skip it, not raise.
    rec = {
        "requirement_id": "REQ-1", "source_quote": "q", "description": "d",
        "source_pdf": "doc2.pdf", "chunk_id": 0,
    }
    text = json.dumps(rec) + "\n" + '{"incomplete json'
    _write_enriched(tmp_path / "doc2_20260730_150000", "doc2_requirements_enriched.jsonl", text)
    result = harvest(clean_sample_size=5, processed_dir=tmp_path)
    assert result["totals"]["runs_scanned"] == 1
    assert result["totals"]["records_scanned"] == 1


def test_harvest_dedups_identical_records_across_runs(tmp_path):
    rec = {
        "requirement_id": "REQ-1", "source_quote": "same quote", "description": "same description",
        "source_pdf": "doc.pdf", "chunk_id": 0,
    }
    text = json.dumps(rec) + "\n"
    _write_enriched(tmp_path / "doc_20260101_000000", "doc_requirements_enriched.jsonl", text)
    _write_enriched(tmp_path / "doc_20260102_000000", "doc_requirements_enriched.jsonl", text)
    result = harvest(clean_sample_size=5, processed_dir=tmp_path)
    assert result["totals"]["records_scanned"] == 1
    assert result["totals"]["runs_scanned"] == 2


def test_harvest_survives_invalid_timestamp_in_dir_name(tmp_path):
    # "doc_20260231_120000" matches the regex shape but Feb 31 isn't a real
    # date -- _run_timestamp must return None (fix_status "unknown"), not raise.
    rec = {
        "requirement_id": "REQ-1", "source_quote": "q", "description": "d",
        "source_pdf": "doc.pdf", "chunk_id": 0,
    }
    _write_enriched(
        tmp_path / "doc_20260231_120000", "doc_requirements_enriched.jsonl", json.dumps(rec) + "\n"
    )
    result = harvest(clean_sample_size=5, processed_dir=tmp_path)
    assert result["totals"]["records_scanned"] == 1


def test_harvest_skips_non_dict_json_lines_without_crashing(tmp_path):
    # Syntactically valid JSON that isn't an object (null, a bare number/
    # string, an array) must be skipped, not crash on rec.get(...).
    text = "null\n123\n\"a string\"\n[]\n"
    _write_enriched(tmp_path / "doc_20260101_000000", "doc_requirements_enriched.jsonl", text)
    result = harvest(clean_sample_size=5, processed_dir=tmp_path)
    assert result["totals"]["records_scanned"] == 0
    assert result["totals"]["runs_scanned"] == 0
