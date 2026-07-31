#!/usr/bin/env python3
"""Step D: Normalize and deduplicate extracted requirements.

Input:  extracted_requirements.jsonl (from Step C)
        chunks.jsonl (from Step B, for page reference lookup)
Output:
  - requirements_normalized.jsonl — final schema per requirement
  - normalization_failures.jsonl — requirements that failed normalization

This step is deterministic. It validates domain tags, adds page references
from chunk metadata, and deduplicates requirements by description similarity.
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz

# Ensure repo root is on sys.path when run as a standalone script from pipeline/.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.chunk_text import _normalize_heading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SCHEMA_VERSION = "2.0"
PIPELINE_VERSION = "1.0"

# WP-32.1: minimum fuzz.partial_ratio (0-100) between a requirement's source_quote
# and its own chunk's text before it's trusted as actually grounded in the source
# document, rather than fabricated by Step C. partial_ratio (not token_sort_ratio,
# which eval/eval_harness.py uses for a different comparison -- two same-length
# quotes) is the right tool here: it scores how well a short string matches the
# best-aligned substring of a long one, which is exactly "is this quote actually
# in this chunk." Exact substring matching was tried first and rejected -- it
# would have flagged ~16/30 real quotes reformatted from tabular source text
# (e.g. NIST.SP.800-53Ar5's assessment procedures) as fabricated.
#
# 60 was chosen by sweeping thresholds against eval/gold_eval_chunks_curated.jsonl's
# 2,452 hand-verified real quotes (the false-positive side) and the full local
# corpus's 33,462 requirements (the catch-rate side):
#   threshold  gold false-positive rate   corpus flagged rate
#       50            0.86%                     3.51%
#       60            1.75%                     4.42%
#       80            4.61%                     5.64%
# Diminishing returns above ~60: pushing to 80 nearly triples the gold
# false-positive rate for comparatively little extra corpus coverage -- most
# genuine fabrications score far below 60 anyway (the confirmed hallucination
# that motivated this WP scored 44). See archive/PHASE32_REQUIREMENTS.md for the
# full investigation.
QUOTE_GROUNDING_THRESHOLD = 60


# WP-34.2: minimum fuzz.ratio (0-100, whole-string similarity) between a
# normalized source_quote and its chunk's own heading before treating it as a
# heading echo rather than real body content. ratio (not partial_ratio, which
# QUOTE_GROUNDING_THRESHOLD above uses for a different comparison shape -- a
# short quote against a much longer chunk) is the right tool here: it scores
# the two full strings against each other, so a short generic heading (e.g.
# "Purpose") merely appearing as a substring inside an unrelated, much longer
# real quote scores low and passes through -- a literal substring-containment
# check does not have this property (confirmed against a real example: "Access
# badges shall be issued for the sole purpose of controlling entry to
# restricted areas." contains the heading "purpose" verbatim, but is a
# genuine, unrelated requirement). Both confirmed real fabrication fixtures are
# exact matches after normalization (ratio 100); 90 leaves headroom for
# incidental punctuation/whitespace differences without opening the substring
# false-positive risk above.
HEADING_ECHO_THRESHOLD = 90


def _is_heading_echo(source_quote: str, section_title_path: list[str]) -> bool:
    """True if source_quote is just a heading from its own ancestry, not body content.

    Step C occasionally extracts a heading (e.g. "COMPLIANCE WITH THIS
    PUBLICATION IS MANDATORY") as if it were a requirement in its own right.
    WP-34.2 originally checked only section_title_path[-1] (the chunk's
    immediate heading). WP-38.1's audit found a code-verified case
    (REQ-955ab005b394) where a quote echoes an *ancestor* heading two levels
    up instead -- section_title_path is ordered shallowest-first (root ...
    immediate parent, see section_parser.py's _ancestry_from_stack), so an
    echoed heading isn't always the last entry. WP-38.2 checks every entry in
    the path, not just the last one.

    Reuses chunk_text.py's _normalize_heading() for both sides so this matches
    on the same normalized form skip_sections filtering already uses -- not
    separate matching logic (WP-34.2).
    """
    if not section_title_path:
        return False
    normalized_quote = _normalize_heading(source_quote)
    if not normalized_quote:
        return False
    for heading in section_title_path:
        if not heading:
            continue
        normalized_heading = _normalize_heading(heading)
        if not normalized_heading:
            continue
        if fuzz.ratio(normalized_quote, normalized_heading) >= HEADING_ECHO_THRESHOLD:
            return True
    return False


def _is_unrepairable_fragment(source_quote: str) -> bool:
    """True if source_quote is a truncated list-header with no content of its own.

    A quote ending in a bare colon (e.g. "The process will be as follows:")
    carries no obligation content on its own -- Step D.5 enrichment was found
    fabricating plausible-sounding description text to "complete" it, content
    that appears nowhere in source_quote (WP-34.2). Only fires on quotes that
    literally end in a colon; a quote that merely contains one mid-sentence
    (and so has real content following it) is untouched.

    WP-34.2 originally also required the quote to be under 25 words, reasoning
    that a longer colon-terminated quote might be a genuinely complete quote
    that just happens to end mid-punctuation. WP-38.1's audit found 3 real
    colon-terminated list-header fragments at 30, 39, and 41 words that the cap
    let through, and turned up no example -- in WP-34.2's original spike or
    WP-38.1's 333-record hand-read audit -- of a genuinely complete quote that
    legitimately ends in a bare colon. A colon promises content the quote
    doesn't contain regardless of how many words precede it, so WP-38.2 removed
    the length cap: the trigger is "ends in a bare colon," full stop.
    """
    return source_quote.strip().endswith(":")


# WP-38.2: list-item marker prefix -- numbered "(1)", lettered "(a)"/"(A)", or
# a leading dash-letter marker like "- d." -- optionally followed by whitespace.
_LIST_MARKER_RE = re.compile(r"^(?:\(\d+\)|\([a-zA-Z]\)|-\s*[a-zA-Z]\.)\s*")

# WP-38.2: after stripping a list marker, a remainder this short (in words) is
# too terse to carry independent obligation content of its own -- it's a bare
# fragment of a larger enumerated list, not a self-contained requirement.
#
# History: originally 6, calibrated only against WP-38.1's specific fragment
# examples. Codex review (PR #181) found real, complete short directives
# getting swallowed too -- a hypothetical ("(a) Encrypt all stored CUI.",
# 4-word remainder) and a real live-corpus record (REQ-63cdc8363326, "(1)
# Identify individual responsibilities for protecting CUI.", 6-word
# remainder). Lowered to 3. Gemini review round 6 raised the same concern
# again at the new threshold, with three more hypotheticals, all 3-word
# remainders ("(1) Encrypt stored CUI.", "(2) Restrict root access.", "(3)
# Conduct annual audits.").
#
# This is now the third round pointing at the same fundamental tension:
# word-count alone can't reliably distinguish "(3) Restrain competition."
# (genuinely needs its "shall not be used to:" governing clause -- meaning
# inverts without it) from a genuinely self-contained short directive of the
# same length, and no regex can safely tell those apart without real
# grammatical analysis. Lowered again, to 2 -- still catches the one real,
# verified target in both WP-38.1's fixture and two full-corpus sweeps
# ("(3) Restrain competition.", 2-word remainder), while excluding Gemini's
# three new 3-word hypotheticals along with everything longer.
#
# Weighed deliberately against removing this signal entirely: Codex's and
# Gemini's counter-examples are hypotheticals, not found in the corpus --
# two independent full-corpus sweeps (1,872 records, before and after this
# change) found zero actual false positives from this specific marker+
# remainder-length branch, only the one real, correct catch. A real
# demonstrated false positive would be grounds to remove the signal outright
# (the discipline that reverted WP-37.2 and dropped the broader
# _is_dangling_clause() signals); a repeatedly-raised but so-far-unconfirmed
# theoretical risk against a signal with a real, verified catch is grounds to
# narrow it further, not necessarily abandon it. Documented here plainly so
# a future reviewer/session doesn't have to re-derive this reasoning --
# revisit if a real false positive is ever actually found.
ORPHANED_LIST_ITEM_MAX_REMAINDER_WORDS = 2

# WP-38.2: an entire quote whose only content is a term followed by a
# "as defined in <citation>" cross-reference carries no independent
# obligation -- it's a definitional pointer, not a requirement (e.g.
# "Suspicious activity reporting, as defined in DoDI 2000.26, Suspicious
# Activity Reporting."). Only anchors the START of the quote (no `$`) because
# a real citation's own reference text legitimately contains internal commas
# and periods (document numbers, titles) -- anchoring to end-of-string would
# reject real citation-only quotes just as readily as it rejects the false
# positive below, so it isn't a safe fix on its own (see
# _has_obligation_after_citation_opener()).
_DEFINED_IN_CITATION_RE = re.compile(r"^[^,]{1,80},\s*as defined in\b", re.IGNORECASE)

# WP-38.2 (Gemini review round 2, PR #181): the first fix here checked
# whether the remainder after "as defined in" contained a word from a small
# obligation-verb whitelist -- but that check was backwards-fragile: ANY real
# obligation verb missing from the list (e.g. "requires", "applies",
# "protects" -- Gemini's own example, "...as defined in Executive Order
# 13556, requires safeguarding controls.") caused the search to find nothing,
# which made the function return True (citation-only) and silently discard a
# real requirement. A verb whitelist can never be exhaustive enough to make
# that failure direction safe, so this doesn't use one anymore.
#
# Instead: a real citation's own reference text in this corpus is
# consistently made of Title-Case document titles, ALL-CAPS/mixed-case
# acronyms, and numeric document IDs (e.g. "DoDI 2000.26, Suspicious Activity
# Reporting"), joined only by commas/"and". A real continuing obligation
# clause is ordinary lowercase prose ("shall be reported...", "requires
# safeguarding controls..."). So: does the remainder consist *only* of
# citation-shaped tokens and a small closed set of connector words, with no
# other lowercase word at all? If even one ordinary lowercase word shows up,
# treat it as real prose continuing past the citation, not citation-only
# content -- this doesn't need to recognize every possible obligation verb,
# only to recognize what an ordinary English sentence fragment looks like,
# which is a much smaller, more robust thing to get right.
_CITATION_CONNECTOR_WORDS = {
    "and", "or", "the", "of", "for", "in", "a", "an", "at", "to", "within", "per",
}

# WP-38.2 (Gemini review round 4, PR #181): stripping a fixed, enumerated set
# of punctuation characters (originally just ",.()")  keeps finding new gaps
# -- quotes, brackets, smart quotes, dashes, whatever the next real example
# happens to be wrapped in. Stripping every non-alphanumeric character from
# both ends, regardless of which specific characters they are, closes that
# whole class of gap at once instead of growing the enumerated set one
# reviewer finding at a time.
_NON_ALNUM_EDGE_RE = re.compile(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$")


def _looks_like_citation_reference(word: str) -> bool:
    stripped = _NON_ALNUM_EDGE_RE.sub("", word)
    if not stripped:
        return True
    if stripped.lower() in _CITATION_CONNECTOR_WORDS:
        return True
    # Title Case, ALL CAPS, or a mix with digits/periods (acronyms, document
    # IDs like "2000.26") -- never a lowercase-first ordinary word.
    return not stripped[0].islower()


def _is_definitional_citation_only(source_quote: str) -> bool:
    """True if source_quote opens with "<term>, as defined in <citation>" and
    everything after that opener still looks like citation reference text --
    not a real, independent governing clause (WP-38.2, see
    _looks_like_citation_reference()'s docstring above for the reasoning)."""
    match = _DEFINED_IN_CITATION_RE.match(source_quote)
    if not match:
        return False
    remainder = source_quote[match.end():]
    if remainder.isupper():
        # WP-38.2 (Gemini review round 6, PR #181): _looks_like_citation_reference()
        # tells a citation token from real prose by checking whether a word's
        # first letter is lowercase -- meaningless when the whole quote is
        # ALL CAPS (e.g. a real requirement continuing "...SHALL BE REPORTED
        # IMMEDIATELY TO THE ISSO." would have every word "look like" a
        # citation token). Can't safely tell citation from prose by case in
        # that situation, so don't guess -- leave the quote alone.
        return False
    return all(_looks_like_citation_reference(w) for w in remainder.split())


def _is_orphaned_list_item(source_quote: str) -> bool:
    """True if source_quote is a bare enumerated-list item or definitional
    cross-reference with no governing clause or independent content of its
    own (WP-38.2 -- the largest single fragment sub-pattern WP-38.1's audit
    found, 12 of 25 fragment examples).

    Two narrow, safe signals rather than one broad one, deliberately, to
    avoid rejecting a genuinely complete short directive that happens to
    start with a list marker:

    1. A list-marker prefix ("(3)", "(a)", "- d.") followed by a very short
       remainder -- too terse to carry independent content.
    2. The entire quote is just "<term>, as defined in <citation>." -- a
       definitional pointer, not an obligation.

    Doesn't attempt to catch a bare noun-phrase list item with no marker and
    no citation (e.g. "Required NM data update rates.") -- no safe,
    non-overfit text-level signal for that shape was found during
    calibration; distinguishing it from a real short requirement needs actual
    grammatical analysis (is the quote's head a noun phrase or a finite verb
    clause), not something regex can reliably do. Left as an honest gap, not
    silently claimed as covered -- see docs/PHASE38_REQUIREMENTS.md's WP-38.2
    Findings.
    """
    stripped = source_quote.strip()
    if not stripped:
        return False

    if _is_definitional_citation_only(stripped):
        return True

    match = _LIST_MARKER_RE.match(stripped)
    if match:
        # WP-38.2 (Gemini review round 3, PR #181): no `remainder and` guard
        # here -- a bare marker with *zero* words after it (e.g. "(1)" alone)
        # is the most degenerate case of this shape, not an exemption from
        # it. The old truthiness check treated an empty remainder as "no
        # marker match" and let it through unrejected, backwards from every
        # other point on this scale (a 1-3 word remainder is correctly
        # rejected; 0 words is strictly less content, not more).
        remainder = stripped[match.end():].strip()
        if len(remainder.split()) <= ORPHANED_LIST_ITEM_MAX_REMAINDER_WORDS:
            return True

    return False


# WP-38.2: bare copulas that, as a quote's very first word, almost always
# indicate a missing subject (e.g. "Is designated..." extracted without the
# "[X]" that should precede "is").
_BARE_COPULA_OPENERS = ("is", "are", "was", "were")

# WP-38.2 (Gemini review round 5, PR #181): finds whatever trailing
# punctuation/wrapper run sits after the quote's last alphanumeric character,
# so a "?" can be detected even wrapped in a closing quote/bracket
# (`"...enforced?"` style). Same non-alphanumeric-edge idea as
# _NON_ALNUM_EDGE_RE above, applied at the end only.
_TRAILING_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]*$")


def _is_dangling_clause(source_quote: str) -> bool:
    """True if source_quote's first word is a bare copula with no subject
    before it (WP-38.2 -- e.g. "Is designated Computer Network Defense
    Service Provider..." extracted without the "[X]" that should precede
    "is").

    Three broader candidate signals were tried and rejected during
    calibration against WP-38.1's audit fixture (eval/audit_wp38_1/) because
    each produced a real false positive against a genuine, correctly-kept
    requirement in this corpus:

    - "Starts with a lowercase letter" -- this corpus's real DoD/AF-style
      responsibility lists commonly extract individual list items starting
      mid-sentence on a shared "will:" governing clause (e.g. a real,
      correctly-kept "establish, direct, and administer all aspects of
      their respective organization's SCI security programs"), so
      lowercase-first is common in genuine content here, not just fragments.
    - "First word is a bare modal (shall/will/must/should/may)" -- same
      cause: a real, correctly-kept record ("must have a lawful governmental
      purpose for such access") starts exactly this way.
    - "Ends in a bare trailing comma" -- a real, correctly-kept record
      ("Reporting or accounting for UD of CUI shall be done in accordance
      with Paragraph 3.5.a(4),") ends in one too; the comma there is a
      punctuation artifact of a longer source list, not a sign the quote's
      own content is incomplete.

    A copula-first quote ending in "?" is excluded too (Gemini round 5): a
    real interrogative requirement, the kind assessment-procedure documents
    like NIST SP 800-53A use (e.g. "Is multi-factor authentication enforced
    for all administrative access?"), puts the subject *after* the copula
    via subject-auxiliary inversion -- grammatically complete, not a missing
    subject the way the declarative case is. This corpus doesn't currently
    have any assessment-questionnaire-style documents ingested, but a future
    one plausibly could.

    Only the bare-copula-first-word signal survived calibration with zero
    false positives against the fixture's 284 real records -- catches 1 of
    WP-38.1's 6 dangling-clause fragment examples. The other 5 (a preamble
    ending mid-clause, a subordinate clause with no main clause, a bare
    modal predicate with no subject) are real fragments but aren't safely
    distinguishable from genuine subject-less-but-complete list items in
    this corpus without actual grammatical analysis -- left as an honest
    gap rather than a rule broad enough to risk discarding real data. See
    docs/PHASE38_REQUIREMENTS.md's WP-38.2 Findings.
    """
    stripped = source_quote.strip()
    if not stripped:
        return False
    if "?" in _TRAILING_NON_ALNUM_RE.search(stripped).group():
        return False
    first_word = _NON_ALNUM_EDGE_RE.sub("", stripped.split(maxsplit=1)[0])
    return first_word.lower() in _BARE_COPULA_OPENERS


def compute_document_identity(pdf_path: Path) -> dict:
    """Compute document identity from PDF file bytes.

    Returns dict with document_id (short), document_hash_full, source_pdf.
    Hashes in 64 KB chunks to avoid loading large PDFs fully into memory.
    """
    hasher = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            hasher.update(block)
    full_hash = hasher.hexdigest()
    return {
        "document_id": full_hash[:16],
        "document_hash_full": full_hash,
        "source_pdf": pdf_path.name,
    }


def normalize_for_hash(text: str) -> str:
    """Normalize text deterministically for stable ID hashing.

    Lowercase, collapse whitespace, strip leading/trailing whitespace.
    """
    return re.sub(r"\s+", " ", text.strip().lower())


def compute_stable_id(
    document_id: str,
    source_ref: str,
    source_quote: str,
    chunk_id: int | None,
    requirement_type: str,
    description: str,
) -> str:
    """Compute a stable requirement ID based on document content.

    Uses a cascade of hash inputs ordered by stability:
    1. document_id + source_ref + normalized_source_quote (most stable)
    2. document_id + normalized_source_quote (if no source_ref)
    3. document_id + chunk_id + requirement_type + normalized_description (last resort)
    """
    norm_quote = normalize_for_hash(source_quote)
    norm_desc = normalize_for_hash(description)

    if norm_quote and source_ref:
        basis = f"{document_id}:{source_ref}:{norm_quote}"
    elif norm_quote:
        basis = f"{document_id}:{norm_quote}"
    else:
        basis = f"{document_id}:{chunk_id}:{requirement_type}:{norm_desc}"

    short_hash = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    return f"REQ-{short_hash}"


def load_jsonl(path: Path) -> list[dict]:
    """Load records from a JSONL file."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_chunk_page_map(chunks: list[dict]) -> dict[int, tuple[int, int]]:
    """Build a mapping from chunk_id to (page_start, page_end)."""
    return {
        c["chunk_id"]: (c["page_start"], c["page_end"])
        for c in chunks
    }


def build_chunk_text_map(chunks: list[dict]) -> dict[int, str]:
    """Build a mapping from chunk_id to its chunk text.

    Uses the "text" field specifically -- the same field
    pipeline/llm_extract_requirements.py substitutes into Step C's prompt via
    {chunk_text}, not "raw_text" (a different, pre-cleaning field). Grounding a
    requirement's source_quote against anything other than what the LLM actually
    saw would be checking against the wrong text (WP-32.1).
    """
    return {c["chunk_id"]: c.get("text") or "" for c in chunks}


def build_chunk_hierarchy_map(chunks: list[dict]) -> dict[int, dict]:
    """Build a mapping from chunk_id to its hierarchy metadata fields.

    Returns empty-field dicts for chunks without WP-14.2 hierarchy output
    (legacy pymupdf/pdfplumber chunks) so callers get safe defaults.
    """
    result: dict[int, dict] = {}
    for c in chunks:
        result[c["chunk_id"]] = {
            "section_ref_path": c.get("section_ref_path") or [],
            "section_title_path": c.get("section_title_path") or [],
            "parent_header_text": c.get("parent_header_text"),
            "parent_context": c.get("parent_context"),
        }
    return result


def build_section_children_map(chunks: list[dict]) -> dict[str, list[str]]:
    """Build a mapping from each section ref to its direct child section refs.

    Walks every consecutive pair in each chunk's section_ref_path so that
    intermediate sections with no body chunk (heading-only, dropped by WP-14.2
    HybridChunker) are still represented.  For example, a chunk with path
    ["1", "1.1", "1.1.1"] contributes both "1" → "1.1" and "1.1" → "1.1.1",
    even if no chunk carries path ["1", "1.1"] directly.

    Only chunks with WP-14.2 numbered section_ref_path contribute; legacy
    chunks with empty paths are silently skipped.
    """
    parent_to_children: dict[str, set[str]] = {}
    for chunk in chunks:
        path = chunk.get("section_ref_path") or []
        for i in range(1, len(path)):
            parent_ref = path[i - 1]
            child_ref = path[i]
            parent_to_children.setdefault(parent_ref, set()).add(child_ref)
    return {k: sorted(v) for k, v in parent_to_children.items()}


def normalize_text(text: str) -> str:
    """Normalize whitespace and casing for comparison."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _dedup_score(req: dict) -> float:
    """Score a requirement for winner selection during deduplication.

    Higher score = preferred record. Formula:
      confidence * 1000 - len(source_quote)

    Confidence (0.0–1.0) dominates: a record with higher confidence always
    wins over one with lower confidence. For equal confidence, a shorter
    source_quote is preferred — it indicates a more precise verbatim capture
    rather than a padded or over-long quote.

    Tag count is intentionally excluded: the LLM can hallucinate tags, and
    more tags does not imply a better extraction.
    """
    confidence = req.get("confidence", 0.0)
    quote_len = len(req.get("source_quote", ""))
    return confidence * 1000 - quote_len


def deduplicate_requirements(requirements: list[dict]) -> list[dict]:
    """Remove duplicate requirements based on two keys:
    1. source_ref + normalized description (only when description is non-empty)
    2. source_ref + normalized source_quote (catches near-identical quotes)

    When duplicates exist, keep the higher-confidence record; for equal
    confidence, prefer the shorter (more precise) source_quote.

    Note: desc_key is skipped when description is empty. In Pass 1 mode all
    descriptions are empty, so using desc_key would collapse distinct requirements
    that share a source_ref into a single record, dropping valid extractions.
    """
    seen: dict[str, dict] = {}
    for req in requirements:
        source_ref = req.get("source_ref", "")
        description = normalize_text(req.get("description", ""))
        quote = normalize_text(req.get("source_quote", ""))

        # Only build desc_key when description is non-empty; an empty description
        # is not a meaningful dedupe signal and would cause false collisions in
        # Pass 1 mode where all descriptions are intentionally absent.
        desc_key = f"{source_ref}::desc::{description}" if description else None
        quote_key = f"{source_ref}::quote::{quote}" if quote else None

        # Check if either key was seen
        existing_key = None
        if desc_key and desc_key in seen:
            existing_key = desc_key
        elif quote_key and quote_key in seen:
            existing_key = quote_key

        if existing_key:
            existing = seen[existing_key]
            if _dedup_score(req) > _dedup_score(existing):
                seen[existing_key] = req
        else:
            if desc_key:
                seen[desc_key] = req
            if quote_key:
                seen[quote_key] = req
    # Deduplicate the values (a req may be stored under both keys)
    unique = {id(v): v for v in seen.values()}
    return list(unique.values())


def run(
    requirements_jsonl: str,
    chunks_jsonl: str,
    source_pdf_path: str,
    output_dir: str,
    *,
    extraction_model: str = "llama3.1:8b-instruct-q4_K_M",
    profile: dict | None = None,
) -> str:
    """Normalize and deduplicate extracted requirements and write output JSONL.

    Callable interface for in-process use by run_pipeline.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        requirements_jsonl: Path to extracted_requirements.jsonl from Step C.
        chunks_jsonl:       Path to chunks.jsonl from Step B (for page refs).
        source_pdf_path:    Path to original PDF (for document identity hash).
        output_dir:         Directory to write normalized JSONL into.
        extraction_model:   LLM name used in Step C (written to schema).
        profile:            Validated profile dict from core.profiles.load_profile().
                            When None, the cybersecurity default profile is loaded.

    Returns:
        Path to the requirements_normalized.jsonl file that was written (str).
    """
    if profile is None:
        from core.profiles import default_profile as _default_profile
        profile = _default_profile()

    _valid_domain_tags: frozenset[str] = frozenset(profile["domain_tags"])
    _valid_requirement_types: frozenset[str] = frozenset(profile["requirement_types"])

    reqs_path = Path(requirements_jsonl).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    doc_identity = {"document_id": "", "document_hash_full": "", "source_pdf": ""}
    if source_pdf_path:
        pdf_path = Path(source_pdf_path).resolve()
        if pdf_path.exists():
            doc_identity = compute_document_identity(pdf_path)
            log.info("Document identity: %s (%s)", doc_identity["document_id"], doc_identity["source_pdf"])
        else:
            log.warning("PDF file not found: %s — document_id will be empty", pdf_path)

    chunks_path = Path(chunks_jsonl).resolve()
    from core.artifact_resolver import doc_key_from_extracted_path
    stem = doc_key_from_extracted_path(reqs_path)
    norm_path = out_dir / f"{stem}_requirements_normalized.jsonl"
    fail_path = out_dir / f"{stem}_normalization_failures.jsonl"

    log.info("Loading requirements from: %s", reqs_path)
    raw_reqs = load_jsonl(reqs_path)
    log.info("Loaded %d raw requirements", len(raw_reqs))

    chunk_page_map: dict[int, tuple[int, int]] = {}
    chunk_hierarchy_map: dict[int, dict] = {}
    section_children_map: dict[str, list[str]] = {}
    chunk_text_map: dict[int, str] = {}
    if chunks_path.exists():
        log.info("Loading chunk metadata from: %s", chunks_path)
        chunks = load_jsonl(chunks_path)
        chunk_page_map = build_chunk_page_map(chunks)
        chunk_hierarchy_map = build_chunk_hierarchy_map(chunks)
        section_children_map = build_section_children_map(chunks)
        chunk_text_map = build_chunk_text_map(chunks)
        log.info("Loaded page references for %d chunks", len(chunk_page_map))
        sections_with_children = sum(1 for v in section_children_map.values() if v)
        log.info(
            "Hierarchy map: %d chunks, %d sections with children",
            len(chunk_hierarchy_map), sections_with_children,
        )
    else:
        log.warning("Chunks file not found: %s — page references will be empty", chunks_path)

    run_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    start = time.time()

    valid_reqs = []
    failures = []

    for req in raw_reqs:
        description = req.get("description", "").strip()
        source_ref = req.get("source_ref", "").strip()
        source_quote = req.get("source_quote", "").strip()
        req_type = req.get("requirement_type", "").strip().lower()
        chunk_id = req.get("chunk_id")

        # Hierarchy metadata — sourced from deterministic WP-14.2 parser output.
        # Falls back to empty values for legacy (pre-WP-14.2) chunks. Resolved here,
        # ahead of the validation checks below, because WP-34.2's heading-echo check
        # needs section_title_path -- it used to be resolved after this loop's checks.
        hierarchy = chunk_hierarchy_map.get(chunk_id) if chunk_id is not None else None
        if hierarchy:
            section_ref_path: list[str] = hierarchy["section_ref_path"]
            section_title_path: list[str] = hierarchy["section_title_path"]
            parent_context: str | None = hierarchy["parent_context"]
            # parent_section_ref: penultimate element of the ancestry path
            parent_section_ref: str | None = (
                section_ref_path[-2] if len(section_ref_path) >= 2 else None
            )
            # child_section_refs: direct children of this section across all chunks
            current_ref = section_ref_path[-1] if section_ref_path else None
            child_section_refs: list[str] = (
                section_children_map.get(current_ref, []) if current_ref else []
            )
        else:
            section_ref_path = []
            section_title_path = []
            parent_context = None
            parent_section_ref = None
            child_section_refs = []

        if not source_quote:
            failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "empty_source_quote", "raw": req})
            continue

        # WP-32.1: reject requirements whose source_quote isn't actually grounded in
        # its own chunk's text -- Step C's extraction model was found to sometimes
        # fabricate plausible-sounding requirements (confirmed at 21.55% across the
        # existing corpus during this WP's spike) rather than only extracting what's
        # present. Skipped (not rejected) only when the chunk itself is unverifiable
        # (chunk_id missing or not present in chunks.jsonl) -- a chunk that IS present
        # but has empty text is verifiable and must still be checked: any non-empty
        # quote scores 0 against empty text and correctly fails, rather than silently
        # passing through on an `if chunk_text:` truthiness check that treated "empty
        # but real" the same as "unverifiable" (Gemini review, PR #144).
        chunk_known = chunk_id is not None and chunk_id in chunk_text_map
        if chunk_known:
            chunk_text = chunk_text_map[chunk_id]
            grounding_score = fuzz.partial_ratio(normalize_text(source_quote), normalize_text(chunk_text))
            if grounding_score < QUOTE_GROUNDING_THRESHOLD:
                failures.append({
                    "requirement_id": req.get("requirement_id", "UNKNOWN"),
                    "chunk_id": chunk_id,
                    "error": "quote_not_grounded_in_chunk",
                    "grounding_score": round(grounding_score, 1),
                    "raw": req,
                })
                continue

        # WP-34.2: reject a chunk's own structural heading extracted as if it were
        # a body-content requirement (e.g. "COMPLIANCE WITH THIS PUBLICATION IS
        # MANDATORY", which is exactly that chunk's section_title_path[-1]).
        if _is_heading_echo(source_quote, section_title_path):
            failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "heading_echo_quote", "raw": req})
            continue

        # WP-34.2: reject a truncated list-header quote with no obligation content
        # of its own (e.g. "The process will be as follows:") -- left in place,
        # Step D.5 enrichment was found fabricating description text to "complete"
        # these rather than the pipeline ever inventing or assembling real content.
        if _is_unrepairable_fragment(source_quote):
            failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "unrepairable_fragment_quote", "raw": req})
            continue

        # WP-38.2: reject a bare enumerated-list item or definitional
        # cross-reference extracted without its governing clause (e.g. "(3)
        # Restrain competition." -- item 3 of a "shall not be used to:" list,
        # meaningless standalone).
        if _is_orphaned_list_item(source_quote):
            failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "orphaned_list_item_quote", "raw": req})
            continue

        # WP-38.2: reject a subordinate clause or predicate extracted without
        # its main clause or subject (e.g. "shall be coordinated with the
        # customer" -- a dangling predicate with no subject at all).
        if _is_dangling_clause(source_quote):
            failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "dangling_clause_quote", "raw": req})
            continue

        if description:
            desc_lower = description.lower()
            if desc_lower.startswith("not explicitly stated"):
                failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "not_actionable", "raw": req})
                continue

            if desc_lower.startswith("change ") and (" to " in desc_lower or " from " in desc_lower):
                if len(description) < 100:
                    failures.append({"requirement_id": req.get("requirement_id", "UNKNOWN"), "chunk_id": chunk_id, "error": "errata_change_entry", "raw": req})
                    continue

        raw_tags = req.get("domain_tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        domain_tags = [t.strip().lower() for t in raw_tags if isinstance(t, str)]
        domain_tags = [t for t in domain_tags if t in _valid_domain_tags]

        if req_type not in _valid_requirement_types:
            req_type = ""

        page_start = None
        page_end = None
        if chunk_id is not None and chunk_id in chunk_page_map:
            page_start, page_end = chunk_page_map[chunk_id]

        confidence = 1.0
        if not domain_tags:
            confidence -= 0.2
        if not source_quote:
            confidence -= 0.2
        if len(description) < 20:
            confidence -= 0.1
        if not source_ref:
            confidence -= 0.1

        normalized = {
            "requirement_id": req.get("requirement_id", f"R-{chunk_id}-X"),
            "description": description,
            "source_ref": source_ref,
            "domain_tags": domain_tags,
            "requirement_type": req_type,
            "source_quote": source_quote,
            "chunk_id": chunk_id,
            "page_start": page_start,
            "page_end": page_end,
            "confidence": round(max(0.0, confidence), 2),
            # Hierarchy metadata (WP-14.3) — deterministic parser output from WP-14.2.
            # Empty for requirements produced by the legacy fixed-size chunker.
            "section_ref_path": section_ref_path,
            "section_title_path": section_title_path,
            "parent_section_ref": parent_section_ref,
            "parent_context": parent_context,
            "child_section_refs": child_section_refs,
            "recovered_truncated": req.get("recovered_truncated", False),
            "domain_profile": profile["name"],
            "document_id": doc_identity["document_id"],
            "document_hash_full": doc_identity["document_hash_full"],
            "source_pdf": doc_identity["source_pdf"],
            "schema_version": SCHEMA_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "extraction_model": extraction_model,
            "run_timestamp": run_timestamp,
        }
        valid_reqs.append(normalized)

    before_dedup = len(valid_reqs)
    valid_reqs = deduplicate_requirements(valid_reqs)
    dedup_removed = before_dedup - len(valid_reqs)

    for req in valid_reqs:
        req["requirement_id"] = compute_stable_id(
            document_id=req["document_id"],
            source_ref=req["source_ref"],
            source_quote=req["source_quote"],
            chunk_id=req.get("chunk_id"),
            requirement_type=req["requirement_type"],
            description=req["description"],
        )

    elapsed = time.time() - start

    tagged_count = sum(1 for r in valid_reqs if r["domain_tags"])
    typed_count = sum(1 for r in valid_reqs if r["requirement_type"])
    log.info(
        "Normalized %d requirements in %.2fs — %d failures, %d duplicates removed",
        len(valid_reqs), elapsed, len(failures), dedup_removed,
    )
    log.info(
        "Domain tags assigned: %d/%d (%.1f%%), typed: %d/%d (%.1f%%)",
        tagged_count, len(valid_reqs),
        tagged_count / len(valid_reqs) * 100 if valid_reqs else 0,
        typed_count, len(valid_reqs),
        typed_count / len(valid_reqs) * 100 if valid_reqs else 0,
    )

    with open(norm_path, "w", encoding="utf-8") as f:
        for req in valid_reqs:
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
    log.info("Wrote %s", norm_path)

    with open(fail_path, "w", encoding="utf-8") as f:
        for failure in failures:
            f.write(json.dumps(failure, ensure_ascii=False) + "\n")
    log.info("Wrote %s (%d failures)", fail_path, len(failures))

    return str(norm_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize and deduplicate extracted requirements"
    )
    parser.add_argument(
        "requirements_jsonl",
        type=str,
        help="Path to extracted_requirements.jsonl from Step C",
    )
    parser.add_argument(
        "--chunks-jsonl",
        type=str,
        default=None,
        help="Path to chunks.jsonl from Step B (for page references). "
             "Auto-detected if not provided.",
    )
    parser.add_argument(
        "--source-pdf-path",
        type=str,
        default=None,
        help="Path to original PDF file (for document identity hashing). "
             "If not provided, document_id fields will be empty.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: same directory as input)",
    )
    parser.add_argument(
        "--extraction-model",
        type=str,
        default="llama3.1:8b-instruct-q4_K_M",
        help="Name of the LLM used in Step C extraction (written to schema metadata).",
    )
    args = parser.parse_args()

    reqs_path = Path(args.requirements_jsonl).resolve()
    if not reqs_path.exists():
        log.error("Input file not found: %s", reqs_path)
        sys.exit(1)

    # Auto-detect chunks file if not provided
    if args.chunks_jsonl:
        chunks_path = str(Path(args.chunks_jsonl).resolve())
    else:
        from core.artifact_resolver import doc_key_from_extracted_path
        stem = doc_key_from_extracted_path(reqs_path)
        chunks_path = str(reqs_path.parent / f"{stem}_chunks.jsonl")

    out_dir = Path(args.output_dir).resolve() if args.output_dir else reqs_path.parent

    run(
        str(reqs_path),
        chunks_path,
        args.source_pdf_path or "",
        str(out_dir),
        extraction_model=args.extraction_model,
    )


if __name__ == "__main__":
    main()
