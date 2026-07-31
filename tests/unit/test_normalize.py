import json
from pathlib import Path

from pipeline.parse_and_normalize import (
    _is_dangling_clause,
    _is_heading_echo,
    _is_orphaned_list_item,
    _is_unrepairable_fragment,
    build_chunk_text_map,
    compute_stable_id,
    run,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


SAMPLE_EXTRACTED = {
    "requirement_id": "R-1",
    "source_quote": "Systems must enforce role-based access control policies.",
    "source_ref": "1.1",
    "description": "Enforce role-based access control for all system users.",
    "requirement_type": "technical-control",
    "domain_tags": ["access-control"],
    "chunk_id": None,
    "confidence": 0.9,
}


def test_stable_id_is_deterministic():
    id1 = compute_stable_id("docabc123", "1.1", "Systems must enforce RBAC.", None, "technical-control", "Enforce RBAC.")
    id2 = compute_stable_id("docabc123", "1.1", "Systems must enforce RBAC.", None, "technical-control", "Enforce RBAC.")
    assert id1 == id2
    assert id1.startswith("REQ-")


def test_stable_id_differs_for_different_quotes():
    id1 = compute_stable_id("doc123", "1.1", "Quote A here.", None, "technical-control", "Desc A")
    id2 = compute_stable_id("doc123", "1.1", "Quote B here.", None, "technical-control", "Desc B")
    assert id1 != id2


def test_dedup_collapses_exact_quote(tmp_path):
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    _write_jsonl(req_path, [SAMPLE_EXTRACTED, SAMPLE_EXTRACTED])
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    records = _read_jsonl(out_dir / "test_requirements_normalized.jsonl")
    assert len(records) == 1


def test_source_quote_required_gate(tmp_path):
    req = dict(SAMPLE_EXTRACTED, source_quote="")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    _write_jsonl(req_path, [req])
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["error"] == "empty_source_quote"


def test_hierarchy_fields_populated(tmp_path):
    chunk = {
        "chunk_id": 42,
        "page_start": 1, "page_end": 2,
        # Must actually contain SAMPLE_EXTRACTED's source_quote (WP-32.1's grounding
        # check) -- this test verifies hierarchy metadata propagation, not grounding,
        # so the chunk text just needs to be realistic enough not to trip that check.
        "text": "1.1 Systems must enforce role-based access control policies.",
        "section_ref_path": ["1", "1.1"],
        "section_title_path": ["Access Control", "Auth Requirements"],
        "parent_header_text": "Access Control",
        "parent_context": "Section 1. Access Control. All systems must enforce RBAC.",
        "document_id": "abc123",
        "source_pdf": "TEST.pdf",
    }
    req = dict(SAMPLE_EXTRACTED, chunk_id=42)
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [chunk])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    records = _read_jsonl(out_dir / "test_requirements_normalized.jsonl")
    assert len(records) == 1
    r = records[0]
    assert r["section_ref_path"] == ["1", "1.1"]
    assert r["section_title_path"] == ["Access Control", "Auth Requirements"]
    assert r["parent_section_ref"] == "1"
    assert r["parent_context"] == "Section 1. Access Control. All systems must enforce RBAC."


def test_optional_hierarchy_defaults_to_empty(tmp_path):
    req = dict(SAMPLE_EXTRACTED, chunk_id=None)
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    _write_jsonl(req_path, [req])
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    records = _read_jsonl(out_dir / "test_requirements_normalized.jsonl")
    assert len(records) == 1
    r = records[0]
    assert r["section_ref_path"] == []
    assert r["section_title_path"] == []
    assert r["parent_section_ref"] is None
    assert r["parent_context"] is None
    assert r["child_section_refs"] == []


def test_empty_input_produces_empty_output(tmp_path):
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    req_path.write_text("")
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []


def test_all_records_missing_source_quote(tmp_path):
    reqs = [dict(SAMPLE_EXTRACTED, source_quote="") for _ in range(3)]
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    _write_jsonl(req_path, reqs)
    out_dir = tmp_path / "out"
    run(str(req_path), str(tmp_path / "no_chunks.jsonl"), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 3


# WP-32.1: build_chunk_text_map + the quote-grounding gate in run(). See
# archive/PHASE32_REQUIREMENTS.md for the corpus-wide investigation (21.55% of
# indexed requirements failed this check; confirmed genuine Step C fabrication,
# not a chunking bug) that motivated this and ruled out exact-substring matching
# in favor of fuzz.partial_ratio.

def test_build_chunk_text_map():
    chunks = [
        {"chunk_id": 1, "text": "First chunk text."},
        {"chunk_id": 2, "text": "Second chunk text."},
    ]
    assert build_chunk_text_map(chunks) == {1: "First chunk text.", 2: "Second chunk text."}


def test_build_chunk_text_map_null_text_becomes_empty_string(tmp_path):
    # An explicit "text": null (not just a missing key) must still produce "" to honor
    # this function's dict[int, str] contract -- dict.get(key, default) only substitutes
    # default when the key is absent, not when present with an explicit None (Gemini
    # review, PR #144).
    chunks = [{"chunk_id": 1, "text": None}, {"chunk_id": 2, "text": ""}]
    result = build_chunk_text_map(chunks)
    assert result == {1: "", 2: ""}
    assert all(isinstance(v, str) for v in result.values())


def _chunk(chunk_id: int, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "page_start": 1, "page_end": 1,
        "text": text,
        "section_ref_path": [], "section_title_path": [],
        "parent_header_text": None, "parent_context": None,
        "document_id": "abc123", "source_pdf": "TEST.pdf",
    }


def test_grounded_quote_passes(tmp_path):
    chunk_text = "3.2.1 All systems shall enforce role-based access control policies for every user."
    req = dict(SAMPLE_EXTRACTED, chunk_id=1, source_quote="Systems must enforce role-based access control policies.")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, chunk_text)])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert len(_read_jsonl(out_dir / "test_requirements_normalized.jsonl")) == 1
    assert _read_jsonl(out_dir / "test_normalization_failures.jsonl") == []


def test_reformatted_quote_still_passes(tmp_path):
    # Reproduces the WP-32.1 calibration finding: tabular/reflowed source text
    # (e.g. NIST.SP.800-53Ar5's assessment-procedure tables) can reformat a real
    # quote enough that exact substring matching would wrongly reject it.
    chunk_text = "AU-16(2)  Cross-Organizational Auditing.  Sharing of Audit Information."
    req = dict(SAMPLE_EXTRACTED, chunk_id=1, source_quote="Cross-Organizational Auditing | Sharing of Audit Information.")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, chunk_text)])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert len(_read_jsonl(out_dir / "test_requirements_normalized.jsonl")) == 1


def test_fabricated_quote_rejected(tmp_path):
    # Reproduces the exact confirmed WP-32.1 case: chunk text is an unrelated
    # document introduction, quote is fabricated password-policy content that
    # doesn't appear anywhere in it.
    chunk_text = (
        "An information system is a discrete set of information resources "
        "organized for the collection, processing, maintenance, use, sharing, "
        "dissemination, or disposition of information."
    )
    req = dict(
        SAMPLE_EXTRACTED, chunk_id=1,
        source_quote="shall conform to NIST SP 800-63B guidelines. Minimum password length is 12 characters.",
    )
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, chunk_text)])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["error"] == "quote_not_grounded_in_chunk"
    assert "grounding_score" in failures[0]


def test_missing_chunk_passes_through_unchecked(tmp_path):
    # chunk_id 999 doesn't exist in chunks.jsonl -- can't verify, so don't reject.
    req = dict(SAMPLE_EXTRACTED, chunk_id=999, source_quote="Completely unverifiable quote text.")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, "Some unrelated chunk text.")])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert len(_read_jsonl(out_dir / "test_requirements_normalized.jsonl")) == 1


def test_empty_chunk_text_still_rejects_fabricated_quote(tmp_path):
    # Distinct from test_missing_chunk_passes_through_unchecked above: chunk_id 1
    # DOES exist in chunks.jsonl, it's just empty -- verifiable, not the same as
    # unknown, and any non-empty quote against empty text is automatically
    # ungrounded. An earlier version of this check used `if chunk_text:` (a
    # truthiness test), which treated "chunk present but empty" the same as
    # "chunk unknown" and silently let this pass -- caught by Gemini review, PR #144.
    req = dict(SAMPLE_EXTRACTED, chunk_id=1, source_quote="Some fabricated requirement text.")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, "")])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["error"] == "quote_not_grounded_in_chunk"


# WP-34.2: heading-echo and unrepairable-fragment rejection. Fixtures are the 5
# real examples confirmed in docs/PHASE34_REQUIREMENTS.md (afpd_17-1.pdf and
# CJCSI 6510.02G.pdf docling re-ingests), plus the original WP-33.3 fixture.

def test_is_heading_echo_exact_match():
    assert _is_heading_echo(
        "COMPLIANCE WITH THIS PUBLICATION IS MANDATORY",
        ["Purpose", "COMPLIANCE WITH THIS PUBLICATION IS MANDATORY"],
    )


def test_is_heading_echo_second_real_fixture():
    assert _is_heading_echo(
        "All HAF Functionals, MAJCOMs, DRUs, and FOAs will:",
        ["All HAF Functionals, MAJCOMs, DRUs, and FOAs will:"],
    )


def test_is_heading_echo_trailing_punctuation_still_matches():
    # Minor punctuation difference from the heading shouldn't let a real echo
    # slip through -- fuzz.ratio's tolerance covers this without needing exact
    # string equality.
    assert _is_heading_echo(
        "COMPLIANCE WITH THIS PUBLICATION IS MANDATORY.",
        ["COMPLIANCE WITH THIS PUBLICATION IS MANDATORY"],
    )


def test_is_heading_echo_false_for_unrelated_quote():
    assert not _is_heading_echo("KERs shall be approved by the MC4EB.", ["KER Approval Process"])


def test_is_heading_echo_false_when_heading_word_appears_incidentally():
    # A short, generic heading (e.g. "Purpose") merely appearing as a substring
    # inside a much longer, unrelated real requirement must NOT be flagged --
    # this is why the check uses whole-string fuzz.ratio rather than literal
    # substring containment.
    assert not _is_heading_echo(
        "Access badges shall be issued for the sole purpose of controlling entry to restricted areas.",
        ["Purpose"],
    )


def test_is_heading_echo_false_with_no_hierarchy():
    assert not _is_heading_echo("Any quote text.", [])


def test_is_unrepairable_fragment_short_colon_lead_in():
    assert _is_unrepairable_fragment("The process will be as follows:")


def test_is_unrepairable_fragment_longer_colon_lead_in():
    assert _is_unrepairable_fragment(
        "The KER may be sent either by scanned soft copy via SIPRNET or by mail to the address listed below:"
    )


def test_is_unrepairable_fragment_original_wp_33_3_fixture():
    assert _is_unrepairable_fragment("The MC4EB will:")


def test_is_unrepairable_fragment_false_for_complete_terse_quote():
    # Must not over-reject a genuinely terse-but-real requirement just because
    # it's short -- the trigger is the trailing bare colon, not brevity alone.
    assert not _is_unrepairable_fragment("KERs shall be approved by the MC4EB.")


def test_is_unrepairable_fragment_false_for_colon_with_content_after():
    assert not _is_unrepairable_fragment("Passwords must be at least 12 characters: no exceptions.")


def test_heading_echo_rejected_in_full_pipeline(tmp_path):
    chunk_text = "COMPLIANCE WITH THIS PUBLICATION IS MANDATORY"
    req = dict(SAMPLE_EXTRACTED, chunk_id=1, source_quote=chunk_text)
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    chunk = _chunk(1, chunk_text)
    chunk["section_title_path"] = ["Purpose", chunk_text]
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [chunk])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["error"] == "heading_echo_quote"


def test_unrepairable_fragment_rejected_in_full_pipeline(tmp_path):
    chunk_text = "3.2 The process will be as follows: step one, step two, step three."
    req = dict(SAMPLE_EXTRACTED, chunk_id=1, source_quote="The process will be as follows:")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, chunk_text)])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["error"] == "unrepairable_fragment_quote"


def test_negative_fixture_survives_full_pipeline(tmp_path):
    # "KERs shall be approved by the MC4EB." -- terse and real, must survive
    # both the heading-echo and unrepairable-fragment checks.
    chunk_text = "4.1 KER Approval Process. KERs shall be approved by the MC4EB."
    req = dict(SAMPLE_EXTRACTED, chunk_id=1, source_quote="KERs shall be approved by the MC4EB.")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    chunk = _chunk(1, chunk_text)
    chunk["section_title_path"] = ["KER Approval Process"]
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [chunk])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert len(_read_jsonl(out_dir / "test_requirements_normalized.jsonl")) == 1
    assert _read_jsonl(out_dir / "test_normalization_failures.jsonl") == []


# WP-38.2: real fixtures below are drawn from eval/audit_wp38_1/'s hand-labeled
# audit (docs/PHASE38_REQUIREMENTS.md's WP-38.1/WP-38.2 Findings), not invented
# examples -- both the positive and negative cases are real quotes this
# project's own corpus produced.

def test_is_heading_echo_matches_ancestor_heading_not_just_immediate():
    # REQ-955ab005b394 (afi10-2402): a real quote that echoes an *ancestor*
    # heading two levels up, not the chunk's own immediate heading -- the
    # exact case WP-34.2's original section_title_path[-1]-only check
    # structurally couldn't catch.
    assert _is_heading_echo(
        "COMPLIANCE WITH THIS PUBLICATION IS MANDATORY",
        ["COMPLIANCE WITH THIS PUBLICATION IS MANDATORY", "1.1. Executive Summary"],
    )


def test_is_heading_echo_false_when_no_heading_in_path_matches():
    assert not _is_heading_echo(
        "KERs shall be approved by the MC4EB.",
        ["Purpose", "KER Approval Process", "1.1. Executive Summary"],
    )


def test_is_heading_echo_false_for_none_section_title_path():
    # Gemini review, PR #181: removing the immediate-heading-only check also
    # dropped the guard against section_title_path being None (not just an
    # empty list) -- a bare `for heading in None:` raises TypeError. Must not
    # crash, same as the pre-existing empty-list case.
    assert not _is_heading_echo("Any quote text.", None)


def test_is_unrepairable_fragment_no_longer_capped_by_length():
    # REQ-97e6e5483093 (DODI 5200.44): a real 41-word colon-terminated
    # fragment that WP-34.2's original 25-word cap let through -- WP-38.2
    # removed the cap since a colon-ending quote carries no content of its
    # own regardless of length.
    assert _is_unrepairable_fragment(
        "Designate a focal point and resources to represent the acquisition "
        "executive; risk management executive; and counterintelligence, "
        "security, and operational communities with access to the DoD "
        "Component's research, development, acquisition, sustainment "
        "activities, and ICT supply chain risk analyses for applicable "
        "systems to:"
    )


def test_is_orphaned_list_item_numbered_marker_short_remainder():
    # REQ-c6aeb8df528b (DODI 5200.01): item 3 of a "shall not be used to:"
    # prohibition list, meaningless standalone.
    assert _is_orphaned_list_item("(3) Restrain competition.")


def test_is_orphaned_list_item_bare_marker_zero_words():
    # Gemini review round 3, PR #181: a bare marker with nothing after it at
    # all is the most degenerate case of this shape, not an exemption --
    # `remainder` is "" (falsy), and an earlier `if remainder and ...` guard
    # let that slip through unrejected.
    assert _is_orphaned_list_item("(1)")


def test_is_orphaned_list_item_false_for_three_word_marker_directives():
    # Gemini review round 6, PR #181: raised the same list-marker/word-count
    # tension a third time with three new hypothetical short, complete,
    # marker-prefixed directives, all 3-word remainders -- one word longer
    # than ORPHANED_LIST_ITEM_MAX_REMAINDER_WORDS was lowered to (3 -> 2) in
    # response, specifically to exclude examples exactly this shape while
    # still catching the one real, verified 2-word target. See
    # ORPHANED_LIST_ITEM_MAX_REMAINDER_WORDS's own comment for the full
    # weighing of "narrow further" vs. "remove the signal entirely."
    assert not _is_orphaned_list_item("(1) Encrypt stored CUI.")
    assert not _is_orphaned_list_item("(2) Restrict root access.")
    assert not _is_orphaned_list_item("(3) Conduct annual audits.")


def test_is_orphaned_list_item_defined_in_citation():
    # REQ-4523443092b8 (afi10-2402): the whole quote is just a term plus a
    # citation, no independent obligation content.
    assert _is_orphaned_list_item(
        "Suspicious activity reporting, as defined in DoDI 2000.26, "
        "Suspicious Activity Reporting."
    )


def test_is_orphaned_list_item_false_for_marker_with_real_content():
    # REQ-01a7421e8e0a (DODI 8551.01): a real, self-contained directive that
    # happens to start with a list marker -- must NOT be caught just because
    # of the marker.
    assert not _is_orphaned_list_item(
        "(6) Directs the PPSM PMO to document the assurance category for "
        "all PPS in the CAL."
    )


def test_is_orphaned_list_item_false_for_real_quote_no_marker():
    assert not _is_orphaned_list_item("KERs shall be approved by the MC4EB.")


def test_is_orphaned_list_item_false_for_marker_short_but_self_contained():
    # Codex review, PR #181 (both a hypothetical and a real live-corpus
    # example, REQ-63cdc8363326: "(1) Identify individual responsibilities
    # for protecting CUI.") -- a short marker-prefixed remainder isn't
    # automatically a fragment; a genuinely complete short directive must
    # survive. This is why ORPHANED_LIST_ITEM_MAX_REMAINDER_WORDS was
    # tightened from 6 to 3 words during calibration.
    assert not _is_orphaned_list_item("(a) Encrypt all stored CUI.")
    assert not _is_orphaned_list_item(
        "(1) Identify individual responsibilities for protecting CUI."
    )


def test_is_orphaned_list_item_true_for_short_directive_known_accepted_risk():
    # Codex local review, PR #181 (fourth round of this exact tension --
    # see ORPHANED_LIST_ITEM_MAX_REMAINDER_WORDS's comment in
    # pipeline/parse_and_normalize.py): these are genuinely complete 2-word
    # imperative directives, confirmed via execution to be wrongly rejected
    # by the marker+word-count branch at threshold=2 -- structurally
    # identical in shape to the one real, verified catch in this corpus
    # ("(3) Restrain competition.", which needs a missing governing clause
    # to be correctly understood). No text-level signal distinguishes the
    # two shapes. Tyler's explicit call: keep the threshold as-is and accept
    # this documented risk, on the strength of zero real false positives
    # found across two full-corpus sweeps (1,872 records) -- only
    # constructed counter-examples so far, never one found in real ingested
    # documents. This test pins that accepted trade-off so it reads as a
    # deliberate decision, not an unnoticed regression, if it's ever
    # revisited.
    assert _is_orphaned_list_item("(1) Encrypt CUI.")
    assert _is_orphaned_list_item("(2) Patch systems.")
    assert _is_orphaned_list_item("(a) Report incidents.")


def test_is_orphaned_list_item_false_for_citation_with_real_clause_after():
    # Gemini + Codex review, PR #181: _DEFINED_IN_CITATION_RE only anchors
    # the start of the quote, so a real requirement that opens with a
    # definitional qualifier but continues with a real governing clause must
    # not be swallowed just because it starts the same way as a genuine
    # citation-only fragment.
    assert not _is_orphaned_list_item(
        "Cybersecurity incidents, as defined in CNSSI 4009, shall be "
        "reported immediately to the ISSO."
    )
    assert not _is_orphaned_list_item(
        "Covered data, as defined in DoDI X, must be encrypted."
    )


def test_is_orphaned_list_item_false_for_citation_with_obligation_verb_outside_narrow_list():
    # Gemini review round 2, PR #181: the first fix checked for a small
    # obligation-verb whitelist (shall/must/will/...) -- any real verb
    # outside that list (e.g. "requires") still false-positived, because a
    # verb whitelist can never be exhaustive enough to make that failure
    # direction safe. Replaced with a structural check (does the remainder
    # look like ordinary lowercase prose vs. citation-shaped tokens) that
    # doesn't depend on naming every possible verb.
    assert not _is_orphaned_list_item(
        "Controlled Unclassified Information, as defined in Executive Order "
        "13556, requires safeguarding controls."
    )


def test_is_orphaned_list_item_false_for_citation_with_quoted_prose():
    # Gemini review round 4, PR #181: the structural check strips a fixed
    # punctuation set to find each word's real first character -- a lowercase
    # prose word wrapped in quotes or brackets (e.g. "'applies'") wasn't in
    # that set, so its leading quote mark was tested instead of the real
    # first letter, misclassifying it as citation-shaped. Fixed by stripping
    # *any* non-alphanumeric character from both ends instead of an
    # enumerated set, closing the whole class of gap rather than the one
    # example found this round.
    assert not _is_orphaned_list_item(
        "Some term, as defined in CNSSI 4009, 'applies within the DoD'."
    )


def test_is_orphaned_list_item_false_for_all_caps_citation_with_real_clause():
    # Gemini review round 6, PR #181 (guard scope corrected round 8): the
    # structural citation check tells a citation token from real prose by
    # checking whether a word's first letter is lowercase -- meaningless
    # when the whole quote is ALL CAPS, since every word "looks like" a
    # citation token regardless of what it actually is. Bails out (not
    # citation-only) whenever the *whole quote* is all-uppercase.
    assert not _is_orphaned_list_item(
        "COMPLIANCE DATA, AS DEFINED IN DODI 2000.26, SHALL BE REPORTED "
        "IMMEDIATELY TO THE ISSO."
    )


def test_is_orphaned_list_item_true_for_short_acronym_only_citation():
    # Gemini review round 8, PR #181: round 6's first fix checked
    # `remainder.isupper()` (just the text after "as defined in") instead of
    # the whole quote -- wrong scope. A short, genuine citation-only
    # remainder made purely of acronym/document-ID tokens (e.g. "CNSSI
    # 4009.") is *also* all-uppercase on its own even though the rest of the
    # quote ("Term,") isn't, which made that version wrongly preserve real
    # citation-only fragments as if they were real requirements. Checking
    # the whole quote's casing instead fixes both this and round 6's
    # original case.
    assert _is_orphaned_list_item("Term, as defined in CNSSI 4009.")
    assert _is_orphaned_list_item("Data, as defined in DODI 5200.01.")
    assert _is_orphaned_list_item("Control, as defined in NIST SP 800-53.")


def test_is_orphaned_list_item_false_for_mixed_case_citation_with_all_caps_clause():
    # Codex local review, PR #181: round 8's guard checked
    # `source_quote.isupper()` -- true only when the *entire* quote is
    # uppercase. A real quote whose citation opener is normal/title case
    # while only its governing clause is rendered in caps has neither the
    # whole quote nor even the whole remainder all-uppercase, so round 8's
    # guard didn't fire and a real obligation clause got misclassified as
    # citation-shaped word by word. Confirmed via direct execution against
    # all three of these (the third mixes a title-case citation, "Executive
    # Order 13556", with an all-caps clause in the very same remainder --
    # the specific shape that motivated replacing the whole-string check
    # with a consecutive-all-caps-run check).
    assert not _is_orphaned_list_item(
        "Compliance data, as defined in DODI 2000.26, SHALL BE REPORTED "
        "IMMEDIATELY TO THE ISSO."
    )
    assert not _is_orphaned_list_item(
        "Cybersecurity incidents, as defined in CNSSI 4009, SHALL BE "
        "REPORTED IMMEDIATELY TO THE ISSO."
    )
    assert not _is_orphaned_list_item(
        "Controlled Unclassified Information, as defined in Executive "
        "Order 13556, REQUIRES SAFEGUARDING CONTROLS."
    )


def test_is_orphaned_list_item_defined_in_citation_with_multiple_references():
    # Live-corpus generalization check (not in the original 12-example set):
    # a citation-only quote referencing two documents joined by "and" is
    # still correctly caught.
    assert _is_orphaned_list_item(
        "Readiness Reporting, as defined in DoDD 7730.65, DoD Readiness "
        "Reporting System, and AFI 10-201, Force Readiness Reporting."
    )


def test_is_dangling_clause_bare_copula_first_word():
    # REQ-1b1071c8d317 (afi17-203): missing its real subject before "Is".
    assert _is_dangling_clause(
        "Is designated Computer Network Defense Service Provider (CNDSP) "
        "Certification Authority (CA) for Special Access Program (SAP) "
        "networks and is responsible for coordinating and directing SAP "
        "enclave-wide CNDSP activities."
    )


def test_is_dangling_clause_false_for_lowercase_start_real_list_item():
    # REQ-474f99ed3b50 (DODI 5200.01): a real, correctly-kept requirement
    # extracted starting mid-sentence on a shared governing clause -- this
    # corpus's DoD/AF-style responsibility lists do this legitimately, which
    # is why WP-38.2 calibrated away from a blanket "starts lowercase" rule.
    assert not _is_dangling_clause(
        "establish, direct, and administer all aspects of their respective "
        "organization's SCI security programs"
    )


def test_is_dangling_clause_false_for_bare_modal_first_word_real_requirement():
    # REQ-580c9ef77b37 (DODI 5200.48): a real requirement starting directly
    # with a bare modal, same shape as a real dangling-clause fragment
    # ("shall be coordinated with the customer") -- not safely distinguishable
    # by a modal-first-word check alone, so WP-38.2 doesn't use one.
    assert not _is_dangling_clause("must have a lawful governmental purpose for such access")


def test_is_dangling_clause_false_for_trailing_comma_real_requirement():
    # REQ-abf7f0a2a776 (DODI 5200.48): a real, complete requirement whose
    # trailing comma is a punctuation artifact of a longer source list, not a
    # sign of incomplete content -- why WP-38.2 doesn't use a trailing-comma
    # rule.
    assert not _is_dangling_clause(
        "Reporting or accounting for UD of CUI shall be done in accordance "
        "with Paragraph 3.5.a(4),"
    )


def test_is_dangling_clause_bare_copula_with_non_space_whitespace_after():
    # Gemini review, PR #181: splitting only on a literal " " missed a bare
    # copula followed by a newline/tab instead of a space.
    assert _is_dangling_clause("Is\nresponsible for coordinating enclave-wide activities.")


def test_is_dangling_clause_bare_copula_wrapped_in_quote_marks():
    assert _is_dangling_clause('"Is designated the CNDSP Certification Authority."')


def test_is_dangling_clause_false_for_real_question():
    # Gemini review round 5, PR #181: a copula-first quote ending in "?" is a
    # real interrogative requirement (the style NIST SP 800-53A-type
    # assessment-procedure documents use) -- subject-auxiliary inversion
    # puts the subject after the copula, which is grammatically complete,
    # not the same missing-subject problem as the declarative case.
    assert not _is_dangling_clause(
        "Is multi-factor authentication enforced for all administrative access?"
    )
    assert not _is_dangling_clause("Are security audit logs reviewed at least weekly?")


def test_is_dangling_clause_false_for_question_wrapped_in_quotes():
    assert not _is_dangling_clause(
        '"Is multi-factor authentication enforced for all administrative access?"'
    )


def test_is_dangling_clause_false_for_question_with_trailing_parenthetical():
    # Gemini review round 7, PR #181: the round-5 fix only checked the
    # quote's trailing non-alphanumeric run for "?", which misses a question
    # mark followed by more content (a trailing parenthetical or control-ID
    # note). Checking the whole quote is safe here since this function only
    # ever fires on an already-narrow bare-copula-first-word trigger.
    assert not _is_dangling_clause(
        "Is multi-factor authentication enforced? (see NIST SP 800-53)"
    )
    assert not _is_dangling_clause("Is audit logging enabled? [Control AC-2]")


def test_orphaned_list_item_rejected_in_full_pipeline(tmp_path):
    chunk_text = "Classification shall not be used to: (1) ... (2) ... (3) Restrain competition."
    req = dict(SAMPLE_EXTRACTED, chunk_id=1, source_quote="(3) Restrain competition.")
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, chunk_text)])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["error"] == "orphaned_list_item_quote"


def test_dangling_clause_rejected_in_full_pipeline(tmp_path):
    chunk_text = (
        "The 624 OC is designated Computer Network Defense Service Provider "
        "Certification Authority for Special Access Program networks."
    )
    req = dict(
        SAMPLE_EXTRACTED, chunk_id=1,
        source_quote="Is designated Computer Network Defense Service Provider Certification Authority.",
    )
    req_path = tmp_path / "test_extracted_requirements.jsonl"
    chunks_path = tmp_path / "test_chunks.jsonl"
    _write_jsonl(req_path, [req])
    _write_jsonl(chunks_path, [_chunk(1, chunk_text)])
    out_dir = tmp_path / "out"
    run(str(req_path), str(chunks_path), "", str(out_dir))
    assert _read_jsonl(out_dir / "test_requirements_normalized.jsonl") == []
    failures = _read_jsonl(out_dir / "test_normalization_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["error"] == "dangling_clause_quote"
