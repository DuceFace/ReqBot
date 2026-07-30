#!/usr/bin/env python3
"""Step B: Chunk a Docling-parsed PDF into overlapping segments with hierarchy metadata.

DoclingDocument + ancestry map (from section_parser.py) → HybridChunker chunks with
breadcrumb injection and ToC filtering. Use run_structure_aware().

(WP-34.1: legacy pymupdf/pdfplumber fixed-size chunking removed — docling is now the
only ingestion path. See docs/PHASE34_REQUIREMENTS.md.)

Output schema (WP-14.2):
  {"chunk_id": int, "page_start": int, "page_end": int,
   "raw_text": str, "breadcrumb": str, "text": str,
   "section_ref_path": list[str], "section_title_path": list[str],
   "parent_header_text": str|null, "parent_context": str|null}
"""

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

# Ensure repo root is on sys.path when run as a standalone script from pipeline/.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Strips leading numbering or common section-label prefixes from a heading before
# matching against skip_sections.  Examples removed: "Attachment 1 - ", "A. ", "1.2.3 ".
_HEADING_PREFIX_RE = re.compile(
    r"^(?:"
    r"(?:appendix|attachment|annex|section|chapter|part|addendum|enclosure|exhibit)"
    r"\s+[\w.-]+\s*[-–—:.]?\s*"  # named prefix + identifier
    r"|[\d]+(?:\.[\d]+)*\.?\s+"             # numeric: "1.2.3 "
    r"|[A-Za-z]\.\s+"                       # lettered: "A. "
    r")",
    re.IGNORECASE,
)


def _normalize_heading(text: str) -> str:
    """Lowercase, collapse whitespace, and strip common numbering prefixes."""
    text = re.sub(r"\s+", " ", text.strip()).lower()
    text = _HEADING_PREFIX_RE.sub("", text).strip()
    return text


def _should_skip_section(section_title_path: list[str], skip_sections: list[str]) -> bool:
    """Return True if any heading in section_title_path matches a skip_sections entry.

    Checks every element in the path (parent and child headings) so nested glossary
    or reference sections are caught regardless of nesting depth.  Matching is
    case-insensitive, whitespace-normalized, and prefix-stripped; a heading matches
    if it equals or starts with a skip phrase.

    Known tradeoff (WP-34.3): prefix matching means a heading like "References to
    External Systems" would incorrectly match "REFERENCES", same as the genuinely
    skip-worthy "Abbreviations and Acronyms" matches "ABBREVIATIONS" -- both have
    the identical shape (skip-word + more free words), so there's no cheap
    syntactic rule that accepts one and rejects the other without real semantic
    understanding. A 5-document survey found no live instance of the bad case, and
    a stricter rule risks breaking the confirmed-real one -- left as-is on purpose,
    not an oversight. See docs/PHASE34_REQUIREMENTS.md's WP-34.3 section.
    """
    if not skip_sections or not section_title_path:
        return False
    normalized_skips = [v for v in (re.sub(r"\s+", " ", s.strip()).lower() for s in skip_sections) if v]
    if not normalized_skips:
        return False
    for heading in section_title_path:
        normalized = _normalize_heading(heading)
        for skip in normalized_skips:
            if normalized == skip or normalized.startswith(skip):
                return True
    return False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def write_jsonl(records: list[dict], output_path: Path) -> None:
    """Write records to a JSONL file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Structure-aware path (WP-14.2) — Docling HybridChunker + ancestry injection
# ---------------------------------------------------------------------------

# ToC chunk filter: same dotted-leader heuristic as section_parser._is_toc_heading,
# applied at the chunk level.  If >40% of non-empty lines look like ToC entries, drop
# the chunk.  The 40% threshold matches the WP-14.1 Req 4 specification.
_TOC_LINE_RE = re.compile(r'\.{5,}')


def _is_toc_chunk(text: str) -> bool:
    """Return True if the chunk is predominantly Table of Contents content.

    Applies the WP-14.1 Req 4 specification: filter chunks where >40% of
    lines are dotted-line entries.  Uses the same dotted-leader regex as
    section_parser._is_toc_heading to stay in sync.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    toc_lines = sum(1 for ln in lines if _TOC_LINE_RE.search(ln))
    return (toc_lines / len(lines)) > 0.40


def _chunk_page_range(chunk: object) -> tuple[int, int]:
    """Extract (page_start, page_end) from a DocChunk's doc_items provenance."""
    pages: list[int] = []
    for item in chunk.meta.doc_items:
        for prov in (getattr(item, "prov", None) or []):
            page_no = getattr(prov, "page_no", None)
            if page_no:
                pages.append(page_no)
    if not pages:
        return (1, 1)
    return (min(pages), max(pages))


def _best_ancestry(chunk: object, item_ancestry: dict) -> dict:
    """Return the deepest ancestry context for a chunk from its doc_items.

    Scans ALL doc_items and returns the ancestry with the longest
    section_title_path (most specific hierarchy).  Ties are broken by keeping
    the last match in document order.

    This full scan is required to handle chunks that span a section transition:
    an early break on the first non-empty title path can yield a shallower
    breadcrumb than items later in the same chunk.
    """
    empty: dict = {
        "section_ref_path": [],
        "section_title_path": [],
        "parent_header_text": None,
        "parent_context": None,
    }
    best = empty
    best_depth = -1
    for item in chunk.meta.doc_items:
        self_ref = getattr(item, "self_ref", None)
        if not self_ref:
            continue
        ancestry = item_ancestry.get(self_ref)
        if ancestry is None:
            continue
        depth = len(ancestry.get("section_title_path") or [])
        if depth >= best_depth:  # >= so last deepest item wins on tie
            best = ancestry
            best_depth = depth
    return best


def _format_breadcrumb(section_title_path: list[str], parent_header_text: str | None) -> str:
    """Format a human-readable breadcrumb from section_title_path.

    Uses " > " as the separator.  Falls back to parent_header_text if path is
    empty.  Returns empty string when no context is available.
    """
    if section_title_path:
        return " > ".join(section_title_path)
    if parent_header_text:
        return parent_header_text
    return ""


def _chunk_raw_text(chunk: object) -> str:
    """Extract body text from a DocChunk, excluding heading items.

    HybridChunker includes heading text in chunk.text as a prefix.  For
    raw_text we want only the non-heading body so that source_quote
    verification works against the original document text.

    Falls back to chunk.text when doc_items cannot be inspected.
    """
    try:
        from docling_core.types.doc import TitleItem, SectionHeaderItem
    except ImportError:
        return chunk.text or ""

    parts: list[str] = []
    for item in chunk.meta.doc_items:
        if isinstance(item, (TitleItem, SectionHeaderItem)):
            continue
        text = getattr(item, "text", "") or ""
        if not text:
            try:
                text = item.export_to_text() or ""
            except Exception:
                text = ""
        text = text.strip()
        if text:
            parts.append(text)

    return "\n".join(parts) if parts else (chunk.text or "")


def _chunk_body_items(chunk: object) -> list:
    """Return non-heading doc_items from a DocChunk.

    Excludes TitleItem and SectionHeaderItem so only content-bearing items
    are considered when deciding whether a chunk falls in a skipped section.
    Falls back to all items when docling_core is not importable.
    """
    try:
        from docling_core.types.doc import SectionHeaderItem, TitleItem
    except ImportError:
        return list(chunk.meta.doc_items)
    return [
        item for item in chunk.meta.doc_items
        if not isinstance(item, (TitleItem, SectionHeaderItem))
    ]


def _should_skip_chunk(chunk: object, item_ancestry: dict, skip_sections: list[str]) -> bool:
    """Return True only when every body item with known ancestry is in a skipped section.

    Conservative by design: if any body item is under a non-skipped heading, has
    no self_ref, or has no entry in item_ancestry, the chunk is kept.  This prevents
    silently discarding valid requirements from chunks that straddle a section boundary
    (e.g. the last paragraph of Access Control followed by the first line of Glossary).
    """
    if not skip_sections:
        return False
    body_items = _chunk_body_items(chunk)
    if not body_items:
        return False
    found_skippable = False
    for item in body_items:
        self_ref = getattr(item, "self_ref", None)
        if not self_ref:
            return False  # no ref → can't determine → keep
        ancestry = item_ancestry.get(self_ref)
        if ancestry is None:
            return False  # missing ancestry → keep (conservative)
        path = ancestry.get("section_title_path") or []
        if not _should_skip_section(path, skip_sections):
            return False  # at least one body item is in a non-skipped section → keep
        found_skippable = True
    return found_skippable  # True only if every body item was under a skipped heading


def run_structure_aware(
    output_path: str,
    *,
    ancestry_result: object,
    skip_sections: list[str] | None = None,
) -> str:
    """Chunk a DoclingDocument with HybridChunker and inject WP-14.1 ancestry breadcrumbs.

    Callable interface for run_pipeline.py (in-process).

    Args:
        output_path:     Path to write the output *_chunks.jsonl file.
        ancestry_result: AncestryResult from section_parser.run().  Must carry
                         a live DoclingDocument in .doc and the ancestry map in
                         .item_ancestry.

    Returns:
        output_path (str) — the file that was written.

    Output record schema:
        chunk_id, page_start, page_end,
        raw_text, breadcrumb, text,
        section_ref_path, section_title_path,
        parent_header_text, parent_context
    """
    try:
        from docling.chunking import HybridChunker
    except ImportError as e:
        raise RuntimeError(
            "Docling is not installed or not importable. Run: pip install ."
        ) from e

    doc = ancestry_result.doc
    item_ancestry: dict = ancestry_result.item_ancestry

    if doc is None:
        raise RuntimeError(
            "ancestry_result.doc is None — section_parser.run() must return a live "
            "DoclingDocument for WP-14.2 chunking."
        )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    log.info("Running HybridChunker on Docling document…")
    t0 = time.time()
    chunker = HybridChunker()
    all_chunks = list(chunker.chunk(doc))
    elapsed_chunk = round(time.time() - t0, 2)
    log.info("HybridChunker produced %d raw chunks in %.2fs", len(all_chunks), elapsed_chunk)

    skip_sections = skip_sections or []
    if skip_sections:
        log.info(
            "Skip-section filtering active: %d configured section(s): %s",
            len(skip_sections),
            ", ".join(repr(s) for s in skip_sections),
        )

    records: list[dict] = []
    toc_filtered = 0
    empty_filtered = 0
    skip_filtered = 0
    skip_examples: list[list[str]] = []
    chunk_id = 0

    for chunk in all_chunks:
        raw_text = _chunk_raw_text(chunk)

        # Filter 1: drop ToC chunks (>40% dotted-leader lines)
        if _is_toc_chunk(chunk.text or ""):
            toc_filtered += 1
            log.debug("ToC chunk filtered: %r…", (chunk.text or "")[:60])
            continue

        # Filter 2: drop chunks with no body text (heading-only, empty)
        if not raw_text.strip():
            empty_filtered += 1
            log.debug("Empty-body chunk filtered (heading-only or whitespace)")
            continue

        page_start, page_end = _chunk_page_range(chunk)
        ancestry = _best_ancestry(chunk, item_ancestry)
        section_title_path = ancestry.get("section_title_path") or []

        # Filter 3: skip only when every body item is under a skipped heading.
        # Uses per-item ancestry rather than the single best-ancestry path so that
        # chunks straddling a section boundary (e.g. valid req + first line of
        # Glossary) are kept rather than silently dropped.
        if _should_skip_chunk(chunk, item_ancestry, skip_sections):
            skip_filtered += 1
            if len(skip_examples) < 5:
                skip_examples.append(section_title_path)
            continue

        breadcrumb = _format_breadcrumb(
            section_title_path,
            ancestry.get("parent_header_text"),
        )

        # Compose prompt-facing text: breadcrumb prefix + body
        if breadcrumb:
            text = f"[{breadcrumb}]\n\n{raw_text}"
        else:
            text = raw_text

        records.append({
            "chunk_id": chunk_id,
            "page_start": page_start,
            "page_end": page_end,
            "raw_text": raw_text,
            "breadcrumb": breadcrumb,
            "text": text,
            "section_ref_path": ancestry.get("section_ref_path") or [],
            "section_title_path": section_title_path,
            "parent_header_text": ancestry.get("parent_header_text"),
            "parent_context": ancestry.get("parent_context"),
        })
        chunk_id += 1

    log.info(
        "Structure-aware chunking: %d chunks kept, %d ToC filtered, "
        "%d empty filtered, %d skip-section filtered",
        len(records), toc_filtered, empty_filtered, skip_filtered,
    )
    if skip_filtered and skip_examples:
        log.info(
            "Skip-section examples (first %d of %d skipped): %s",
            len(skip_examples), skip_filtered,
            "; ".join(str(p) for p in skip_examples),
        )

    if records:
        chunk_sizes = [len(r["raw_text"]) for r in records]
        log.info(
            "raw_text sizes — avg %.0f chars, min %d, max %d",
            sum(chunk_sizes) / len(chunk_sizes),
            min(chunk_sizes),
            max(chunk_sizes),
        )
        with_breadcrumb = sum(1 for r in records if r["breadcrumb"])
        log.info(
            "Breadcrumb coverage: %d/%d chunks (%.0f%%)",
            with_breadcrumb, len(records),
            100 * with_breadcrumb / len(records),
        )

    write_jsonl(records, out)
    log.info("Wrote %s (%d records)", out, len(records))
    return str(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chunk a PDF with Docling HybridChunker + ancestry breadcrumbs.",
    )
    parser.add_argument("pdf_path", type=str, help="Path to the input PDF file")
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output JSONL file path (default: <stem>_chunks.jsonl alongside input)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: same directory as input)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit Docling conversion to first N pages (testing only)",
    )
    args = parser.parse_args()

    input_path = Path(args.pdf_path).resolve()
    if not input_path.exists():
        log.error("Input file not found: %s", input_path)
        sys.exit(1)
    if input_path.suffix.lower() != ".pdf":
        log.error("Input must be a PDF, got: %s", input_path)
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve() if args.output_dir else input_path.parent
    stem = input_path.stem
    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = out_dir / f"{stem}_chunks.jsonl"

    try:
        from pipeline import section_parser
    except ImportError:
        log.error("section_parser not found — ensure pipeline/ is a package and repo root is on sys.path")
        sys.exit(1)

    try:
        ancestry_result = section_parser.run(
            str(input_path), str(out_dir), max_pages=args.max_pages
        )
    except RuntimeError as e:
        log.error("section_parser failed: %s", e)
        sys.exit(1)

    try:
        run_structure_aware(str(output_path), ancestry_result=ancestry_result)
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
