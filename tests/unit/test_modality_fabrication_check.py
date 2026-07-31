"""Unit tests for WP-35.3's obligation/modality-fabrication check."""

from eval.modality_fabrication_check import (
    _governing_action_verbs_in,
    _has_governing_obligation,
    _has_modal_marker,
    _is_infinitive_purpose_clause,
    is_fabricated_obligation,
)

# ---------------------------------------------------------------------------
# is_fabricated_obligation — real fixtures (docs/PHASE35_REQUIREMENTS.md
# WP-35.3 Gate: the known WP-34.4/Codex miss must be caught, real modal
# paraphrases must not be falsely rejected, and the "ensure"-as-purpose-clause
# case specifically must not cause a false negative on the original miss).
# ---------------------------------------------------------------------------

def test_catches_known_wp34_4_codex_miss():
    # eval/entailment_spike.py's afpd_definition_reframed_as_imperative —
    # a glossary definition (quote's "ensure" is a purpose clause) reframed
    # as an imperative ("Implement..."). MiniCheck alone scored this 0.9197
    # (confidently supported); this check exists specifically to catch it.
    quote = (
        "Cybersecurity - Prevention of damage to, protection of, and restoration of "
        "computers, electronic communications systems, electronic communications "
        "services, wire communication, and electronic communication, including "
        "information contained therein, to ensure its availability, integrity, "
        "authentication, confidentiality, and nonrepudiation."
    )
    description = (
        "Implement cybersecurity measures to prevent damage, protect, and restore "
        "computers, electronic communications systems, services, wire communication, "
        "and electronic communication to ensure availability, integrity, "
        "authentication, confidentiality, and nonrepudiation."
    )
    assert is_fabricated_obligation(quote, description) is True


def test_does_not_flag_will_must_paraphrase():
    # eval/entailment_spike.py's dodi_nsa_approved_crypto — a real, faithful
    # modal-verb substitution (will -> must), same facts.
    quote = (
        "DoD Components will use only NSA-approved cryptographic products to "
        "protect classified and/or sensitive national security information "
        "processed and transmitted over National Security Systems (NSS)."
    )
    description = (
        "DoD Components must use only NSA-approved cryptographic products to "
        "protect classified and/or sensitive national security information "
        "processed and transmitted over National Security Systems (NSS)."
    )
    assert is_fabricated_obligation(quote, description) is False


def test_does_not_flag_required_adjective_to_must_paraphrase():
    # eval/gold_description_grounding.jsonl REQ-efc38d9d853d — "required"
    # (adjective) in the quote already asserts the same necessity "must"
    # (modal) restates in the description; not new content.
    quote = "meet all required background checks, training, and certification requirements prior to assuming their duties"
    description = "All required background checks, training, and certification requirements must be met prior to assuming duties."
    assert is_fabricated_obligation(quote, description) is False


def test_does_not_flag_support_maintain_paraphrase_when_quote_already_obligatory():
    # eval/gold_description_grounding.jsonl REQ-35dfe9353e60 — quote already
    # has "must"; description's "maintain" is a synonym for quote's "support",
    # not a fabricated new command.
    quote = (
        "The agency must support the EA with a complete inventory of agency "
        "information resources, including personnel, equipment, and funds "
        "devoted to information resources management and information "
        "technology, at an appropriate level of detail."
    )
    description = (
        "Agency must maintain a complete inventory of information resources, "
        "including personnel, equipment, and funds, at an appropriate level "
        "of detail."
    )
    assert is_fabricated_obligation(quote, description) is False


def test_catches_fabricated_action_verb_on_a_bare_fragment():
    # eval/gold_description_grounding.jsonl REQ-cbc6374a655f — quote is a
    # bare term + citation cross-reference, no obligation of any kind;
    # description invents "Implement X" wholesale.
    quote = (
        "Insider Threat, as defined in DoDD 5205.16, The DoD Insider Threat "
        "Program, and AFI 16-1402, Insider Threat Program Management."
    )
    description = "Implement Insider Threat Program as defined in DoDD 5205.16 and AFI 16-1402."
    assert is_fabricated_obligation(quote, description) is True


# ---------------------------------------------------------------------------
# _is_infinitive_purpose_clause
# ---------------------------------------------------------------------------

def test_purpose_clause_detects_bare_infinitive():
    text = "better control of systems to ensure compliance"
    idx = text.index("ensure")
    assert _is_infinitive_purpose_clause(text, idx) is True


def test_purpose_clause_false_for_governing_verb():
    text = "the administrator must ensure compliance"
    idx = text.index("ensure")
    assert _is_infinitive_purpose_clause(text, idx) is False


def test_purpose_clause_false_for_sentence_initial_verb():
    text = "implement the control immediately"
    idx = text.index("implement")
    assert _is_infinitive_purpose_clause(text, idx) is False


# ---------------------------------------------------------------------------
# _governing_action_verbs_in
# ---------------------------------------------------------------------------

def test_governing_action_verbs_excludes_purpose_clause_ensure():
    assert _governing_action_verbs_in("systems configured to ensure availability") == set()


def test_governing_action_verbs_includes_finite_ensure():
    assert "ensure" in _governing_action_verbs_in("the administrator must ensure availability")


def test_governing_action_verbs_finds_multiple():
    found = _governing_action_verbs_in("implement and maintain the access control policy")
    assert found == {"implement", "maintain"}


def test_governing_action_verbs_empty_for_no_match():
    assert _governing_action_verbs_in("the system processes login requests") == set()


def test_governing_action_verbs_matches_third_person_singular_inflection():
    # Gemini review, PR #168: exact-match regex missed inflected forms like
    # "maintains"/"enforces", which are the normal way regulatory quotes
    # state a governing action in third-person-singular present tense.
    assert _governing_action_verbs_in("The ISSO maintains access logs.") == {"maintain"}
    assert _governing_action_verbs_in("The system enforces multi-factor authentication.") == {"enforce"}


def test_governing_action_verbs_matches_past_and_gerund_inflections():
    assert "establish" in _governing_action_verbs_in("Controls were established by the ISSM.")
    assert "implement" in _governing_action_verbs_in("The team is implementing the new policy.")


def test_does_not_flag_third_person_to_imperative_normalization():
    # A faithful tense/person normalization (quote states the action in
    # third-person-singular; description restates it as an imperative) is
    # not a new fabricated action -- both sides resolve to the same base verb.
    quote = "The ISSO maintains access logs."
    description = "Maintain access logs."
    assert is_fabricated_obligation(quote, description) is False


# ---------------------------------------------------------------------------
# _has_modal_marker / _has_governing_obligation
# ---------------------------------------------------------------------------

def test_has_modal_marker_true_for_will():
    assert _has_modal_marker("Officers will meet the requirement.") is True


def test_has_modal_marker_false_for_no_marker():
    assert _has_modal_marker("A bare noun phrase with no verb.") is False


def test_has_governing_obligation_true_via_modal_only():
    assert _has_governing_obligation("The agency shall comply.") is True


def test_has_governing_obligation_false_for_purpose_clause_only():
    assert _has_governing_obligation("configured to ensure availability") is False


# ---------------------------------------------------------------------------
# is_fabricated_obligation — edge cases
# ---------------------------------------------------------------------------

def test_no_action_verb_in_description_never_flags():
    assert is_fabricated_obligation("A bare fragment.", "A slightly longer bare fragment.") is False


def test_empty_strings_do_not_flag():
    assert is_fabricated_obligation("", "") is False
