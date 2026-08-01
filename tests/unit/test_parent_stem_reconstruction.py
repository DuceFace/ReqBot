"""WP-39.2: parent-stem reconstruction tests.

Regression fixtures are real text from eval/audit_wp39_1/'s 18 known FRAGMENT
examples (docs/PHASE39_REQUIREMENTS.md's WP-39.1 Findings), not hypotheticals --
same discipline as WP-38.2's own rule tests. Encoded as literal dicts here (not a
live dependency on ~/documents/processed, which is gitignored and won't exist in a
fresh checkout or CI) rather than read from disk, but the text and structure below
were copied verbatim from the real corpus during WP-39.2 calibration.
"""
import json

import pipeline.embed_and_index as embed_mod
from pipeline.enrich_requirements import (
    _extract_stem_from_record_text,
    _find_cross_chunk_stem,
    _is_reconstruction_candidate,
    apply_parent_stem_reconstruction,
    reconstruct_parent_stem,
)
from pipeline.parse_and_normalize import run as normalize_run

# ---------------------------------------------------------------------------
# _is_reconstruction_candidate
# ---------------------------------------------------------------------------


def test_candidate_list_marker_prefix():
    assert _is_reconstruction_candidate("(3) Restrain competition.")


def test_candidate_short_word_count():
    assert _is_reconstruction_candidate("Required NM data update rates.")


def test_candidate_dangling_clause_bare_copula():
    assert _is_reconstruction_candidate(
        "Is designated Computer Network Defense Service Provider (CNDSP) "
        "Certification Authority (CA) for Special Access Program (SAP) networks "
        "and is responsible for coordinating and directing SAP enclave-wide "
        "CNDSP activities."
    )


def test_not_a_candidate_long_complete_sentence():
    # No list marker, > 20 words, not a bare-copula opener.
    assert not _is_reconstruction_candidate(
        "National security information will be classified, safeguarded, and "
        "declassified in accordance with References (c), (d), and DoD Manual "
        "5200.01 (Reference (i))."
    )


def test_empty_quote_not_a_candidate():
    assert not _is_reconstruction_candidate("")
    assert not _is_reconstruction_candidate("   ")


# ---------------------------------------------------------------------------
# _extract_stem_from_record_text
# ---------------------------------------------------------------------------


def test_extract_stem_colon_at_end():
    text = (
        "Information will not be classified, continue to be maintained as "
        "classified, or fail to be declassified, or be designated CUI under "
        "any circumstances in order to:"
    )
    assert _extract_stem_from_record_text(text) == text


def test_extract_stem_colon_mid_string_truncates():
    # REQ-48f549669bb2: Step C merged the stem with its first sibling item into
    # one combined quote ending in a period, not a colon.
    text = (
        "This section will define for all parties: The characteristics of the "
        "NM information to be exchanged (e.g., data schema(s) used, specialized "
        "data formatting (if any), and any non-standard characteristics)."
    )
    assert _extract_stem_from_record_text(text) == "This section will define for all parties:"


def test_extract_stem_no_terminal_punctuation_used_as_is():
    # REQ-c62e41aaf181's antecedent: an unfinished clause Step C split from its
    # own continuation, no colon anywhere.
    text = "establish, direct, and administer all aspects of their respective organization's SCI security programs"
    assert _extract_stem_from_record_text(text) == text


def test_extract_stem_terminal_period_no_colon_returns_none():
    assert _extract_stem_from_record_text("(3) Restrain competition.") is None


def test_extract_stem_url_colon_is_not_a_list_intro_colon():
    # REQ-cf527f39c8d7's chunk 12: a list item's own body text contains two URLs
    # whose "https:" colon must not be mistaken for a list-introducing colon.
    text = (
        "Track on the classified network in the Classified PPSM registry at "
        "https://pnp.cert.smil.mil/pnp and the unclassified system in the PPSM "
        "registry at https://pnp.cert.mil/pnp."
    )
    assert _extract_stem_from_record_text(text) is None


def test_extract_stem_empty_text():
    assert _extract_stem_from_record_text("") is None
    assert _extract_stem_from_record_text(None) is None


def test_extract_stem_semicolon_terminated_sibling_is_not_a_stem():
    # NIST SP 800-53-style control statements commonly end list items with ";"
    # rather than "." -- not present in the WP-39.1 calibration corpus itself,
    # but a real shape elsewhere in this project's corpus (Gemini review, PR #185).
    assert _extract_stem_from_record_text("(1) Implement access controls;") is None


def test_extract_stem_comma_terminated_sibling_is_not_a_stem():
    assert _extract_stem_from_record_text("(1) Implement access controls,") is None


def test_extract_stem_marker_prefixed_no_terminal_punctuation_is_not_a_stem():
    # A malformed/truncated marker-prefixed sibling shouldn't be mistaken for a
    # governing stem just because it happens to lack terminal punctuation.
    assert _extract_stem_from_record_text("(1) Implement access controls") is None


def test_reconstruct_parent_stem_walks_past_semicolon_terminated_siblings():
    step_c_by_chunk = {
        5: [
            {"source_quote": "The organization shall:"},
            {"source_quote": "(1) Implement access controls;"},
            {"source_quote": "(2) Audit system logs;"},
        ],
    }
    req = {"source_quote": "(2) Audit system logs;", "chunk_id": 5}
    assert reconstruct_parent_stem(req, step_c_by_chunk, {}) == "The organization shall:"


# ---------------------------------------------------------------------------
# _find_cross_chunk_stem: the "unrelated colon in the previous chunk" false
# positive found during calibration (DODI 5200.44 chunk 24 -> chunk 25).
# ---------------------------------------------------------------------------


def test_cross_chunk_stem_not_attempted_when_own_chunk_is_self_contained():
    # Chunk 25 opens with its own fresh, complete governing sentence -- not a
    # continuation of chunk 24, even though chunk 24 (unrelated) also happens to
    # end with its own colon-terminated header ("...the Director, DIA:").
    step_c_by_chunk = {
        24: [{"source_quote": "Assesses significant ICT supply chain threats to national security systems."}],
    }
    chunks_by_id = {
        25: {
            "raw_text": (
                "Under the authority, direction, and control of the USD(I&S), in "
                "addition to the responsibilities in Paragraph 2.9., and in "
                "accordance with Paragraphs 2.2, 4.1, and 11.2 of Volume 1 of DoD "
                "Manual 5220.32, the Director, Defense Counterintelligence and "
                "Security Agency:\n- a.  Grants facility and personnel security "
                "clearances..."
            ),
        },
        24: {"raw_text": "Under the authority, direction, and control of the USD(I&S), and in addition to the responsibilities in Paragraph 2.9., the Director, DIA:"},
    }
    assert _find_cross_chunk_stem(25, step_c_by_chunk, chunks_by_id) is None


def test_cross_chunk_stem_not_attempted_when_own_chunk_starts_a_fresh_list():
    # Chunk 64 opens with "a." -- the first item of its own list, not a
    # continuation, even though it's still a bare list-marker prefix.
    chunks_by_id = {
        64: {"raw_text": "- a.  The release or disclosure to foreign governments..."},
        63: {"raw_text": "...the OCA will:\n- a.  Notify the organization..."},
    }
    assert _find_cross_chunk_stem(64, {}, chunks_by_id) is None


def test_cross_chunk_stem_found_via_raw_text_when_never_extracted_by_step_c():
    # REQ-cf527f39c8d7: the real stem ("b. Oversee...") was never extracted as
    # its own Step C record -- only present in the previous chunk's raw_text,
    # and only reachable by walking past a sibling item containing a URL colon.
    step_c_by_chunk = {
        12: [
            {"source_quote": "Implement standards established by the PPSM CCB and in accordance with DoDI 8500.01, CJCSI 6510.01F, and CJCSI 6211.02D."},
            {"source_quote": "Verify PPS before authorization, incorporation, or connection to systems or technology in accordance with DoDI 8510.01."},
            {"source_quote": "Validate PPS for DoD systems in accordance with DoDI 8510.01."},
            {"source_quote": "Maintain information technology interoperability in accordance with DoDI 8330.01."},
        ],
    }
    chunks_by_id = {
        13: {"raw_text": "- (7)  Communicate PPS securely across the DODIN.\n- (8)  Block invalid PPS using appropriate boundary protection devices."},
        12: {
            "raw_text": (
                "- (3)  A representative from OIG DoD may attend in a non-voting role only.\n"
                "- b.  Oversee their respective Component's PPSM program to:\n"
                "- (1)  Assess it for vulnerabilities and document them in an internal vulnerability assessment report for internal PPS by the system owner in accordance with PPSM component local service assessment process.\n"
                "- (2)  Track on the classified network in the Classified PPSM registry at https://pnp.cert.smil.mil/pnp and the unclassified system in the PPSM registry at https://pnp.cert.mil/pnp.\n"
                "- (3)  Implement standards established by the PPSM CCB and in accordance with DoDI 8500.01, CJCSI 6510.01F, and CJCSI 6211.02D.\n"
                "- (4)  Verify PPS before authorization, incorporation, or connection to systems or technology in accordance with DoDI 8510.01.\n"
                "- (5)  Validate PPS for DoD systems in accordance with DoDI 8510.01.\n"
                "- (6)  Maintain information technology interoperability in accordance with DoDI 8330.01."
            ),
        },
    }
    assert _find_cross_chunk_stem(13, step_c_by_chunk, chunks_by_id) == "b. Oversee their respective Component's PPSM program to:"


# ---------------------------------------------------------------------------
# Regression: all 18 known FRAGMENT examples from WP-39.1's audit.
# ---------------------------------------------------------------------------

_STEP_C = {
    "DODI 5200.01": {
        2: [
            {"source_quote": "National security information will be classified, safeguarded, and declassified in accordance with References (c), (d), and DoD Manual 5200.01 (Reference (i))."},
            {"source_quote": "CUI will be identified and safeguarded consistent with the requirements of References (g) and (i)."},
            {"source_quote": "Declassification of information will receive equal attention as the classification of information so that information remains classified only as long as required by national security considerations."},
            {"source_quote": "Information will not be classified, continue to be maintained as classified, or fail to be declassified, or be designated CUI under any circumstances in order to:"},
            {"source_quote": "(1) Conceal violations of law, inefficiency, or administrative error."},
            {"source_quote": "(2) Prevent embarrassment to a person, organization, or agency."},
            {"source_quote": "(3) Restrain competition."},
            {"source_quote": "(4) Prevent or delay the release of information that does not require protection in the interests of national security or as required by statute or regulation."},
            {"source_quote": "The volume of classified national security information and CUI, in whatever format or media, will be reduced to the minimum necessary to meet operational requirements."},
        ],
        14: [
            {"source_quote": "establish, direct, and administer all aspects of their respective organization's SCI security programs"},
            {"source_quote": "consistent with Reference (a) and applicable authorities as heads of elements of the IC in accordance with Reference (h)"},
        ],
        16: [
            {"source_quote": "The Chief Information Officer of the Department of Defense coordinates with the USD(I&S) when developing policies, including those for information assurance, that provide for the security of information in a networked environment and are consistent with the requirements of References (i) and (n),  DoDI 5200.02 (Reference (ae)), and other guidance issued by the USD(I&S) and the DNI."},
        ],
        17: [
            {"source_quote": "Under the authority, direction, and control of the Chief Management Officer of the Department of Defense, in addition to the responsibilities in section 11 of this enclosure and in accordance with References (a), (c), and DoDD 5110.04 (Reference (af)),"},
            {"source_quote": "Directs and administers a DoD Mandatory Declassification Review Program in accordance with DoD 5230.30-M (Reference (ag) ) and consistent with subsection 3.5 of Reference (c), to include establishing:"},
            {"source_quote": "to include establishing: the procedures for declassifying classified information, as required by section 6.1 of DoD Instruction 5230.29."},
        ],
    },
    "DODI 5200.44": {
        24: [
            {"source_quote": "Assesses significant ICT supply chain threats to national security systems."},
        ],
        25: [
            {"source_quote": "in addition to the responsibilities in Paragraph 2.9."},
            {"source_quote": "in accordance with Paragraphs 2.2, 4.1, and 11.2 of Volume 1 of DoD Manual 5220.32"},
        ],
    },
    "DODI 5200.48": {
        63: [],
        64: [
            {"source_quote": "The release or disclosure to foreign governments, international organizations, coalitions, or allied personnel of CUI not controlled as NOFORN will be in accordance with a law, regulation, or government-wide policy."},
            {"source_quote": "Access to such CUI during official foreign national visits and assignments to DoD Components and cleared contractor facilities, when applied by contract, will be in accordance with DoDD 5230.20."},
            {"source_quote": "Access to such information is within the scope of their assigned duties."},
            {"source_quote": "Access to such information would help accomplish a lawful and authorized DoD mission or purpose and would not be detrimental to the interests of the DoD or the U.S. Government."},
            {"source_quote": "There are no contract restrictions prohibiting access to such information."},
            {"source_quote": "Access to such information is in accordance with DoDIs 8500.01 and 5200.02 and export control regulations, as applicable."},
        ],
    },
    "afi17-203": {
        17: [],
        18: [
            {"source_quote": "recommends security protection of new projects/capabilities in accordance with established classification guidance and Department of Defense Instruction (DoDI) O-3600.02, Information Operation (IO) Security Classification Guidance."},
            {"source_quote": "Is designated Computer Network Defense Service Provider (CNDSP) Certification Authority (CA) for Special Access Program (SAP) networks and is responsible for coordinating and directing SAP enclave-wide CNDSP activities."},
        ],
        55: [
            {"source_quote": "Coordination of technical and organizational steps taken to implement preliminary actions across all affected C/S/As."},
            {"source_quote": "Documentation of any actions taken."},
            {"source_quote": "More detailed updates of analysis performed."},
            {"source_quote": "Documentation of analysis results."},
            {"source_quote": "Coordination of incident analysis activities between DCO, DoDIN Operations, mission owners, technical and management components and internal/external subject matter experts."},
            {"source_quote": "Updates on actions taken and submission of final report for closure."},
        ],
    },
    "afman17-2101": {
        25: [
            {"source_quote": "Denies/terminates DISN LHC requests when it is in the best interest of the AF. This activity will not be accomplished indiscriminately and shall be coordinated with the customer."},
            {"source_quote": "shall be coordinated with the customer"},
        ],
    },
    "DODI 8410.03": {
        31: [
            {"source_quote": "NM systems shall be located within the network topology in a manner that ensures they can monitor and report on SLA compliance."},
            {"source_quote": "NM SLAs shall at a minimum address the following areas identified in International Telecommunications Union - Telecommunications Recommendation M.3342 (Reference (z)) and TM Forum GB917 Release 3.0 (Reference (aa)):"},
            {"source_quote": "(1) Identification of the organizations between which the agreement is established, to include technical and organizational points of contact."},
            {"source_quote": "(2) A description of the NM services that will be provided along with scope, limitations, and other terms of reference that might be needed."},
            {"source_quote": "(3) A basic description of the NM system and supporting equipment information and who is responsible for providing, maintaining, and operating it."},
            {"source_quote": "(4) Detailed explanations of the expected levels and quality of NM services that will be provided."},
        ],
        32: [
            {"source_quote": "This section must include: where, how, and in what format NM information and data will be collected; how it will be shared with the customer; how often it will be shared with the customer; how NM information and data will be archived; and duration archived information will be retained IAW Reference (h)."},
            {"source_quote": "This section will define for all parties: The characteristics of the NM information to be exchanged (e.g., data schema(s) used, specialized data formatting (if any), and any non-standard characteristics)."},
        ],
        33: [
            {"source_quote": "Required NM data update rates."},
            {"source_quote": "Maximum allowable time from when an event takes place to when it is reported by the NM system, as well as the location of event."},
        ],
        34: [
            {"source_quote": "SLAs and other agreements that include tactical edge and non-tactical edge networks shall take into consideration the unique characteristics of tactical edge networks (e.g., dynamic, adhoc, bandwidth constrained, and intermittent connections); however these characteristics shall not be used to exempt tactical edge and non-tactical edge networks from the requirement to have SLAs."},
            {"source_quote": "Implementation of SLAs for tactical edge and non-tactical edge networks shall not impact network or mission effectiveness."},
            {"source_quote": "NM SLAs and other agreements shall be structured to complement or extend other SLAs entered into by DoD Components."},
            {"source_quote": "NM SLAs and other agreements shall establish baseline and minimum service levels and address provisioning and measurement of the following network performance parameters:"},
            {"source_quote": "(1) Network latency and packet loss on per-hop and end-to-end basis by traffic type."},
            {"source_quote": "(2) Minimum and maximum bandwidth provided."},
            {"source_quote": "(3) Mean time between failures of network equipment or connectivity."},
        ],
    },
    "DODI 8551.01": {
        12: [
            {"source_quote": "Implement standards established by the PPSM CCB and in accordance with DoDI 8500.01, CJCSI 6510.01F, and CJCSI 6211.02D."},
            {"source_quote": "Verify PPS before authorization, incorporation, or connection to systems or technology in accordance with DoDI 8510.01."},
            {"source_quote": "Validate PPS for DoD systems in accordance with DoDI 8510.01."},
            {"source_quote": "Maintain information technology interoperability in accordance with DoDI 8330.01."},
        ],
        13: [
            {"source_quote": "(7) Communicate PPS securely across the DODIN."},
            {"source_quote": "(8) Block invalid PPS using appropriate boundary protection devices."},
        ],
    },
    "afi10-2402": {
        20: [
            {"source_quote": "Suspicious activity reporting, as defined in DoDI 2000.26, Suspicious Activity Reporting."},
            {"source_quote": "Force Health Protection, as defined in DoDD 6200.04, Force Health Protection , and DoDI 6200.03, Public Health Emergency Management Within the DoD."},
            {"source_quote": "Readiness Reporting, as defined in DoDD 7730.65, DoD Readiness Reporting System, and AFI 10-201, Force Readiness Reporting ."},
            {"source_quote": "Insider Threat, as defined in DoDD 5205.16, The DoD Insider Threat Program, and AFI 16-1402, Insider Threat Program Management."},
        ],
        109: [
            {"source_quote": "Review of the AFI-mandated MAJCOM responsibilities and tasks."},
            {"source_quote": "Overview of programmatic and policy updates or changes."},
            {"source_quote": "Review of CAIP data and ongoing TCA remediation/mitigation efforts."},
            {"source_quote": "Briefing CARM TCA data management capabilities and status."},
        ],
    },
}

_CHUNKS = {
    "DODI 5200.01": {
        2: {"parent_header_text": "3.  POLICY.  It is DoD policy that:"},
        14: {"parent_header_text": "1.  UNDER SECRETARY OF DEFENSE FOR INTELLIGENCE AND SECURITY (USD(I&S))."},
        16: {"raw_text": "9.  CHIEF INFORMATION OFFICER OF THE DEPARTMENT OF DEFENSE.  The Chief Information Officer of the Department of Defense coordinates with the USD(I&S) when developing policies, including those for information assurance, that provide for the security of information in a networked environment and are consistent with the requirements of References (i) and (n),  DoDI 5200.02 (Reference (ae)), and other guidance issued by the USD(I&S) and the DNI."},
        17: {
            "raw_text": "10. DIRECTOR, WASHINGTON HEADQUARTERS SERVICE.  Under the authority, direction, and control of the Chief Management Officer of the Department of Defense, in addition to the responsibilities in section 11 of this enclosure and in accordance with References (a), (c), and DoDD 5110.04 (Reference (af)), the Director, Washington Headquarters Service, develops implementing guidance, as necessary, for the protection of information related to providing a broad range of administrative, management, and common support services.\n- a. Directs and administers a DoD Mandatory Declassification Review Program in accordance with DoD 5230.30-M (Reference (ag) ) and consistent with subsection 3.5 of Reference (c), to include establishing:",
            "parent_header_text": "7.  UNDER SECRETARY OF DEFENSE FOR POLICY.  The Under Secretary of Defense for Policy:",
        },
    },
    "DODI 5200.44": {
        24: {"raw_text": "Under the authority, direction, and control of the USD(I&S), and in addition to the responsibilities in Paragraph 2.9., the Director, DIA:\n- a.  Produces intelligence and counterintelligence threat assessments...\n- d.  Assesses significant ICT supply chain threats to national security systems."},
        25: {"raw_text": "Under the authority, direction, and control of the USD(I&S), in addition to the responsibilities in Paragraph 2.9., and in accordance with Paragraphs 2.2, 4.1, and 11.2 of Volume 1 of DoD Manual 5220.32, the Director, Defense Counterintelligence and Security Agency:\n- a.  Grants facility and personnel security clearances for contractors..."},
    },
    "DODI 5200.48": {
        63: {"raw_text": "DoD OCAs will determine if CUI under their control, when compiled, is classified.  If so, the applicable SCGs must address the compilation.  Any time an OCA discovers that compiled or aggregated information is not properly classified on websites, folders, or documents, the OCA will:\n- a.  Notify the organization using the compiled information to remove or protect the information.\n- e.  Since OCAs are the owners of the information under their authority, they are authorized to identify and mark such information as CUI."},
        64: {
            "raw_text": "- a.  The release or disclosure to foreign governments, international organizations, coalitions, or allied personnel of CUI not controlled as NOFORN will be in accordance with a law, regulation, or government-wide policy.  Access to such CUI during official foreign national visits and assignments to DoD Components and cleared contractor facilities, when applied by contract, will be in accordance with DoDD 5230.20.\n- b.  CUI not controlled as NOFORN may be released or disclosed to non-U.S. citizens employed by the DoD if:\n- (1)  Access to such information is within the scope of their assigned duties.\n- (2)  Access to such information would help accomplish a lawful and authorized DoD mission or purpose and would not be detrimental to the interests of the DoD or the U.S. Government.\n- (3)  There are no contract restrictions prohibiting access to such information.\n- (4)  Access to such information is in accordance with DoDIs 8500.01 and 5200.02 and export control regulations, as applicable.",
            "parent_header_text": "3.9.  GENERAL RELEASE AND DISCLOSURE REQUIREMENTS.",
        },
    },
    "afi17-203": {
        18: {
            "raw_text": "2.2.1.  In coordination with AF/A3, SAF/A6 and SAF/AQ, recommends security protection of new projects/capabilities in accordance with established classification guidance and Department of Defense Instruction (DoDI) O-3600.02, Information Operation (IO) Security Classification Guidance.\n2.2.2.  Is designated Computer Network Defense Service Provider (CNDSP) Certification Authority (CA) for Special Access Program (SAP) networks and is responsible for coordinating and directing SAP enclave-wide CNDSP activities.",
            "parent_header_text": "2.2. Directorate of Security, Special Access Program Oversight and Information Protection (SAF/AAZ).",
        },
        55: {
            "raw_text": "\n handling..Reporting& Notification = Update of actions taken. Preliminary Response Action...Documentation = Documentation of analysis results. Incident Analysis...Updates on actions taken and submission of final report for closure.",
            "parent_header_text": "3.7.3. Post-Incident Analysis.",
        },
    },
    "afman17-2101": {
        25: {"parent_header_text": "2.3. AF  Long  Haul  Communications  Flight,  38th  Cyberspace  Readiness  Squadron/SCC (38 CYRS/SCC). The AF LHC Flight is the Air Force's DISN LHC Program manager who:"},
    },
    "DODI 8410.03": {
        31: {"parent_header_text": "4.  SLAs"},
        32: {"parent_header_text": "4.  SLAs"},
        33: {
            "raw_text": "- (b)  Required NM data update rates.\n- (c)  Maximum allowable time from when an event takes place to when it is reported by the NM system, as well as the location of event.",
            "parent_header_text": "4.  SLAs",
        },
        34: {"parent_header_text": "4.  SLAs"},
    },
    "DODI 8551.01": {
        12: {
            "raw_text": (
                "- (3)  A representative from OIG DoD may attend in a non-voting role only.\n"
                "- b.  Oversee their respective Component's PPSM program to:\n"
                "- (1)  Assess it for vulnerabilities and document them in an internal vulnerability assessment report for internal PPS by the system owner in accordance with PPSM component local service assessment process.\n"
                "- (2)  Track on the classified network in the Classified PPSM registry at https://pnp.cert.smil.mil/pnp and the unclassified system in the PPSM registry at https://pnp.cert.mil/pnp.\n"
                "- (3)  Implement standards established by the PPSM CCB and in accordance with DoDI 8500.01, CJCSI 6510.01F, and CJCSI 6211.02D.\n"
                "- (4)  Verify PPS before authorization, incorporation, or connection to systems or technology in accordance with DoDI 8510.01.\n"
                "- (5)  Validate PPS for DoD systems in accordance with DoDI 8510.01.\n"
                "- (6)  Maintain information technology interoperability in accordance with DoDI 8330.01."
            ),
        },
        13: {"raw_text": "- (7)  Communicate PPS securely across the DODIN.\n- (8)  Block invalid PPS using appropriate boundary protection devices."},
    },
    "afi10-2402": {
        20: {"raw_text": "- 1.4.1.7.  Law  Enforcement  (LE).    Suspicious  activity  reporting,  as  defined  in  DoDI 2000.26, Suspicious Activity Reporting.\n- 1.4.1.8.  Force Health Protection, as defined in DoDD 6200.04..."},
        109: {"raw_text": "- 4.3.1.  Review of the AFI-mandated MAJCOM responsibilities and tasks.\n- 4.3.2.  Overview of programmatic and policy updates or changes."},
    },
}

# (requirement_id, doc_key, chunk_id, source_quote, expected_stem_or_None)
_REGRESSION_CASES = [
    ("REQ-4aeeff50f15b", "DODI 5200.01", 17, "Under the authority, direction, and control of the Chief Management Officer of the Department of Defense, in addition to the responsibilities in section 11 of this enclosure and in accordance with References (a), (c), and DoDD 5110.04 (Reference (af)),", None),
    ("REQ-c62e41aaf181", "DODI 5200.01", 14, "consistent with Reference (a) and applicable authorities as heads of elements of the IC in accordance with Reference (h)", "establish, direct, and administer all aspects of their respective organization's SCI security programs"),
    ("REQ-8105d9acb410", "DODI 5200.44", 25, "in addition to the responsibilities in Paragraph 2.9.", None),
    ("REQ-1cc75ab1ae84", "DODI 5200.48", 64, "There are no contract restrictions prohibiting access to such information.", None),
    ("REQ-1b1071c8d317", "afi17-203", 18, "Is designated Computer Network Defense Service Provider (CNDSP) Certification Authority (CA) for Special Access Program (SAP) networks and is responsible for coordinating and directing SAP enclave-wide CNDSP activities.", "2.2. Directorate of Security, Special Access Program Oversight and Information Protection (SAF/AAZ)."),
    ("REQ-9700722b04cd", "afman17-2101", 25, "shall be coordinated with the customer", "Denies/terminates DISN LHC requests when it is in the best interest of the AF. This activity will not be accomplished indiscriminately and shall be coordinated with the customer."),
    ("REQ-626b98fef9aa", "DODI 5200.01", 2, "(4) Prevent or delay the release of information that does not require protection in the interests of national security or as required by statute or regulation.", "Information will not be classified, continue to be maintained as classified, or fail to be declassified, or be designated CUI under any circumstances in order to:"),
    ("REQ-c6aeb8df528b", "DODI 5200.01", 2, "(3) Restrain competition.", "Information will not be classified, continue to be maintained as classified, or fail to be declassified, or be designated CUI under any circumstances in order to:"),
    ("REQ-3097aa5d306c", "DODI 8410.03", 31, "(4) Detailed explanations of the expected levels and quality of NM services that will be provided.", "NM SLAs shall at a minimum address the following areas identified in International Telecommunications Union - Telecommunications Recommendation M.3342 (Reference (z)) and TM Forum GB917 Release 3.0 (Reference (aa)):"),
    ("REQ-c6d23854cd0b", "DODI 8410.03", 34, "(3) Mean time between failures of network equipment or connectivity.", "NM SLAs and other agreements shall establish baseline and minimum service levels and address provisioning and measurement of the following network performance parameters:"),
    ("REQ-48f549669bb2", "DODI 8410.03", 33, "Required NM data update rates.", "This section will define for all parties:"),
    ("REQ-7464da5820b8", "DODI 8410.03", 34, "(1) Network latency and packet loss on per-hop and end-to-end basis by traffic type.", "NM SLAs and other agreements shall establish baseline and minimum service levels and address provisioning and measurement of the following network performance parameters:"),
    ("REQ-cf527f39c8d7", "DODI 8551.01", 13, "(7) Communicate PPS securely across the DODIN.", "b. Oversee their respective Component's PPSM program to:"),
    ("REQ-4523443092b8", "afi10-2402", 20, "Suspicious activity reporting, as defined in DoDI 2000.26, Suspicious Activity Reporting.", None),
    ("REQ-364e0be72ebb", "afi10-2402", 109, "Overview of programmatic and policy updates or changes.", None),
    ("REQ-e0471aa64a63", "afi10-2402", 20, "Force Health Protection, as defined in DoDD 6200.04, Force Health Protection , and DoDI 6200.03, Public Health Emergency Management Within the DoD.", None),
    ("REQ-5c349cdc3656", "afi17-203", 55, "Documentation of analysis results.", None),
    ("REQ-68e7c7d2ba86", "afi17-203", 55, "Updates on actions taken and submission of final report for closure.", None),
]


def test_regression_all_18_known_examples():
    failures = []
    for rid, doc_key, chunk_id, quote, expected in _REGRESSION_CASES:
        req = {"source_quote": quote, "chunk_id": chunk_id}
        stem = reconstruct_parent_stem(req, _STEP_C[doc_key], _CHUNKS[doc_key])
        if stem != expected:
            failures.append(f"{rid}: expected {expected!r}, got {stem!r}")
    assert not failures, "\n".join(failures)


def test_no_stem_when_chunk_id_missing():
    assert reconstruct_parent_stem({"source_quote": "(3) Restrain competition."}, {}, {}) is None


def test_no_stem_when_quote_empty():
    assert reconstruct_parent_stem({"source_quote": "", "chunk_id": 2}, {}, {}) is None


# ---------------------------------------------------------------------------
# apply_parent_stem_reconstruction: end-to-end on a normalized JSONL file.
# ---------------------------------------------------------------------------


def test_apply_parent_stem_reconstruction_writes_fields(tmp_path, monkeypatch):
    doc_key = "testdoc"
    norm_file = tmp_path / f"{doc_key}_requirements_normalized.jsonl"
    records = [
        {"requirement_id": "R-1", "source_quote": "(3) Restrain competition.", "chunk_id": 2},
        {"requirement_id": "R-2", "source_quote": "A complete, unrelated standalone requirement with plenty of its own context and detail.", "chunk_id": 2},
    ]
    with open(norm_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    step_c_file = tmp_path / f"{doc_key}_extracted_requirements.jsonl"
    step_c_records = [
        {"chunk_id": 2, "source_quote": "Information will not be classified, continue to be maintained as classified, or fail to be declassified, or be designated CUI under any circumstances in order to:"},
        {"chunk_id": 2, "source_quote": "(3) Restrain competition."},
    ]
    with open(step_c_file, "w", encoding="utf-8") as f:
        for r in step_c_records:
            f.write(json.dumps(r) + "\n")

    chunks_file = tmp_path / f"{doc_key}_chunks.jsonl"
    with open(chunks_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"chunk_id": 2, "raw_text": "irrelevant", "parent_header_text": "irrelevant"}) + "\n")

    apply_parent_stem_reconstruction(str(norm_file))

    written = [json.loads(line) for line in norm_file.read_text(encoding="utf-8").splitlines()]
    assert written[0]["parent_stem"] == "Information will not be classified, continue to be maintained as classified, or fail to be declassified, or be designated CUI under any circumstances in order to:"
    assert written[0]["embedding_text"] == written[0]["parent_stem"] + "\n" + written[0]["source_quote"]
    assert written[1]["parent_stem"] == ""
    assert written[1]["embedding_text"] == ""


def test_apply_parent_stem_reconstruction_idempotent(tmp_path):
    doc_key = "testdoc2"
    norm_file = tmp_path / f"{doc_key}_requirements_normalized.jsonl"
    norm_file.write_text(json.dumps({"requirement_id": "R-1", "source_quote": "Standalone.", "chunk_id": 1}) + "\n", encoding="utf-8")

    apply_parent_stem_reconstruction(str(norm_file))
    first = norm_file.read_text(encoding="utf-8")
    apply_parent_stem_reconstruction(str(norm_file))
    second = norm_file.read_text(encoding="utf-8")
    assert first == second


def test_dangling_clause_recovered_end_to_end_through_step_d_and_reconstruction(tmp_path):
    """WP-41: chains parse_and_normalize.run() (Step D) and
    apply_parent_stem_reconstruction() together exactly as run_pipeline.py's real
    call sequence does, reproducing the real REQ-1b1071c8d317 (afi17-203) shape
    found during WP-41 scoping. Before the fix, Step D rejected this record
    outright (dangling_clause_quote) so reconstruction never got the chance to
    run on it, even though _find_heading_stem() already correctly recovers this
    exact shape when given the chance (test_regression_all_18_known_examples).
    This test proves the full chain now works end-to-end, not just each half in
    isolation."""
    doc_key = "test"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    dangling_quote = (
        "Is designated Computer Network Defense Service Provider Certification "
        "Authority for Special Access Program networks."
    )
    chunk_text = (
        "2.2.1. Recommends security protection of new projects.\n"
        f"2.2.2. {dangling_quote}"
    )
    header = "2.2. Directorate of Security, Special Access Program Oversight and Information Protection (SAF/AAZ)."

    req_path = out_dir / f"{doc_key}_extracted_requirements.jsonl"
    chunks_path = out_dir / f"{doc_key}_chunks.jsonl"
    req_path.write_text(json.dumps({
        "requirement_id": "R-1", "source_quote": dangling_quote, "source_ref": "2.2.2",
        "description": "", "requirement_type": "", "domain_tags": [], "chunk_id": 1, "confidence": 0.9,
    }) + "\n", encoding="utf-8")
    chunks_path.write_text(json.dumps({
        "chunk_id": 1, "page_start": 1, "page_end": 1, "text": chunk_text,
        "section_ref_path": [], "section_title_path": [], "parent_header_text": header,
        "parent_context": None, "document_id": "abc123", "source_pdf": "TEST.pdf",
    }) + "\n", encoding="utf-8")

    normalize_run(str(req_path), str(chunks_path), "", str(out_dir))

    norm_path = out_dir / f"{doc_key}_requirements_normalized.jsonl"
    normalized = [json.loads(line) for line in norm_path.read_text(encoding="utf-8").splitlines()]
    assert len(normalized) == 1
    assert normalized[0]["source_quote"] == dangling_quote

    apply_parent_stem_reconstruction(str(norm_path))
    reconstructed = [json.loads(line) for line in norm_path.read_text(encoding="utf-8").splitlines()]
    assert reconstructed[0]["parent_stem"] == header
    assert reconstructed[0]["embedding_text"] == header + "\n" + dangling_quote


def test_apply_parent_stem_reconstruction_writes_via_tmp_file_and_replace(tmp_path):
    # Atomic write-then-replace (Gemini review, PR #185) -- no stray .tmp file left
    # behind after a successful run, and no direct in-place truncation window.
    doc_key = "testdoc3"
    norm_file = tmp_path / f"{doc_key}_requirements_normalized.jsonl"
    norm_file.write_text(json.dumps({"requirement_id": "R-1", "source_quote": "(3) Restrain competition.", "chunk_id": 2}) + "\n", encoding="utf-8")

    apply_parent_stem_reconstruction(str(norm_file))

    assert not (tmp_path / f"{doc_key}_requirements_normalized.jsonl.tmp").exists()
    assert json.loads(norm_file.read_text(encoding="utf-8").splitlines()[0])["parent_stem"] == ""


def test_apply_parent_stem_reconstruction_missing_source_files_is_a_noop(tmp_path):
    # No *_extracted_requirements.jsonl / *_chunks.jsonl alongside the normalized
    # file -- must degrade gracefully (empty parent_stem), not raise.
    doc_key = "orphandoc"
    norm_file = tmp_path / f"{doc_key}_requirements_normalized.jsonl"
    norm_file.write_text(json.dumps({"requirement_id": "R-1", "source_quote": "(3) Restrain competition.", "chunk_id": 2}) + "\n", encoding="utf-8")

    apply_parent_stem_reconstruction(str(norm_file))

    written = json.loads(norm_file.read_text(encoding="utf-8").splitlines()[0])
    assert written["parent_stem"] == ""
    assert written["embedding_text"] == ""


# ---------------------------------------------------------------------------
# embed_and_index.py: build_embedding_text() / build_payload()
# ---------------------------------------------------------------------------


def test_build_embedding_text_prefers_embedding_text_when_present():
    req = {
        "source_quote": "(3) Restrain competition.",
        "parent_stem": "Information will not be classified... in order to:",
        "embedding_text": "Information will not be classified... in order to:\n(3) Restrain competition.",
    }
    assert embed_mod.build_embedding_text(req) == req["embedding_text"]


def test_build_embedding_text_falls_back_to_source_quote_when_absent():
    req = {"source_quote": "A complete standalone requirement."}
    assert embed_mod.build_embedding_text(req) == "A complete standalone requirement."


def test_build_embedding_text_appends_ref_after_embedding_text():
    req = {
        "source_quote": "(3) Restrain competition.",
        "embedding_text": "Stem.\n(3) Restrain competition.",
        "source_ref": "T-1",
    }
    assert embed_mod.build_embedding_text(req) == "Stem.\n(3) Restrain competition.\nRef: T-1"


def test_build_payload_includes_parent_stem_and_embedding_text():
    req = {
        "requirement_id": "R-1",
        "source_quote": "(3) Restrain competition.",
        "parent_stem": "Information will not be classified... in order to:",
        "embedding_text": "Information will not be classified... in order to:\n(3) Restrain competition.",
    }
    payload = embed_mod.build_payload(req, embedding_model="test-model", embedding_dim=768)
    assert payload["parent_stem"] == req["parent_stem"]
    assert payload["embedding_text"] == req["embedding_text"]


def test_build_payload_defaults_when_fields_absent():
    payload = embed_mod.build_payload({"requirement_id": "R-1", "source_quote": "x"}, embedding_model="m", embedding_dim=1)
    assert payload["parent_stem"] == ""
    assert payload["embedding_text"] == ""
