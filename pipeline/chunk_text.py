#!/usr/bin/env python3
"""Step B: Chunk extracted page text into overlapping segments.

Two paths:
  Legacy:          pages.jsonl (from extract_pdf_to_text.py) → fixed-size overlapping chunks.
  Structure-aware: DoclingDocument + ancestry map (from section_parser.py) → HybridChunker chunks
                   with breadcrumb injection and ToC filtering.  Use run_structure_aware().

Legacy output schema (unchanged):
  {"chunk_id": int, "page_start": int, "page_end": int, "text": str}

Structure-aware output schema (WP-14.2):
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

# Sentinel markers that may be present in pdfplumber-extracted pages.
# Must match TABLE_START_SENTINEL / TABLE_END_SENTINEL in extract_pdf_to_text.py.
TABLE_START_SENTINEL = "<<<TABLE_START>>>"
TABLE_END_SENTINEL = "<<<TABLE_END>>>"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def load_pages(pages_path: Path) -> list[dict]:
    """Load page records from a JSONL file.

    Args:
        pages_path: Path to the pages.jsonl file.

    Returns:
        List of page dicts sorted by page_num.
    """
    pages = []
    with open(pages_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                pages.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning("Skipping malformed JSON at line %d: %s", line_num, e)
    pages.sort(key=lambda p: p["page_num"])
    return pages


def build_page_index(pages: list[dict]) -> list[tuple[int, int, int]]:
    """Build an index mapping character offsets to page numbers.

    Returns a list of (start_offset, end_offset, page_num) tuples for the
    concatenated text of all pages.
    """
    index = []
    offset = 0
    for page in pages:
        length = len(page["text"])
        index.append((offset, offset + length, page["page_num"]))
        offset += length
    return index


def pages_for_span(page_index: list[tuple[int, int, int]], start: int, end: int) -> tuple[int, int]:
    """Find the page range that covers a character span.

    Args:
        page_index: Output of build_page_index.
        start: Start character offset (inclusive).
        end: End character offset (exclusive).

    Returns:
        (page_start, page_end) — 1-indexed page numbers.
    """
    page_start = None
    page_end = None
    for p_start, p_end, page_num in page_index:
        if p_start < end and p_end > start:
            if page_start is None:
                page_start = page_num
            page_end = page_num
    return (page_start or 1, page_end or 1)


def find_table_spans(full_text: str) -> list[tuple[int, int]]:
    """Return a list of (start, end) character spans for sentinel-wrapped table regions.

    Each span covers from the start of TABLE_START_SENTINEL through the end of
    TABLE_END_SENTINEL (inclusive), so chunk boundary logic can avoid splitting
    inside these regions.
    """
    spans = []
    search_from = 0
    start_len = len(TABLE_START_SENTINEL)
    end_len = len(TABLE_END_SENTINEL)
    while True:
        start_idx = full_text.find(TABLE_START_SENTINEL, search_from)
        if start_idx == -1:
            break
        end_idx = full_text.find(TABLE_END_SENTINEL, start_idx + start_len)
        if end_idx == -1:
            # Unmatched sentinel — treat rest of text as one span to be safe
            spans.append((start_idx, len(full_text)))
            break
        spans.append((start_idx, end_idx + end_len))
        search_from = end_idx + end_len
    return spans


def table_span_at(pos: int, table_spans: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Return the table span that contains pos, or None if pos is not inside a table."""
    for start, end in table_spans:
        if start <= pos < end:
            return (start, end)
    return None


def chunk_text(
    full_text: str,
    page_index: list[tuple[int, int, int]],
    chunk_size: int = 3000,
    overlap: int = 200,
    table_aware: bool = False,
) -> list[dict]:
    """Split concatenated text into overlapping chunks.

    Chunks are split at word boundaries. Each chunk records which pages
    it spans. When table_aware=True, split points that land inside a
    TABLE_START_SENTINEL…TABLE_END_SENTINEL region are pushed past the
    end of the table so no table is split mid-row.

    Args:
        full_text: The concatenated text of all pages.
        page_index: Output of build_page_index.
        chunk_size: Target chunk size in characters.
        overlap: Number of overlap characters between consecutive chunks.
        table_aware: If True, avoid splitting inside sentinel-wrapped tables.

    Returns:
        List of chunk dicts.
    """
    table_spans = find_table_spans(full_text) if table_aware else []

    chunks = []
    text_len = len(full_text)
    pos = 0
    chunk_id = 0

    while pos < text_len:
        end = min(pos + chunk_size, text_len)

        # If we're not at the end, try to break at a word boundary
        if end < text_len:
            # If end lands inside a table, push it past the table end
            if table_aware:
                span = table_span_at(end, table_spans)
                if span is not None:
                    end = min(span[1], text_len)

            # Look back from the end position for whitespace
            if end < text_len:
                break_pos = full_text.rfind(" ", pos, end)
                if break_pos > pos:
                    # Don't back up into a table region
                    if table_aware and table_span_at(break_pos, table_spans) is not None:
                        pass  # keep end at table boundary
                    else:
                        end = break_pos + 1  # include the space at the end

        chunk_text_str = full_text[pos:end]

        # Skip chunks that are only whitespace
        if chunk_text_str.strip():
            page_start, page_end = pages_for_span(page_index, pos, end)
            chunks.append({
                "chunk_id": chunk_id,
                "page_start": page_start,
                "page_end": page_end,
                "text": chunk_text_str,
            })
            chunk_id += 1

        # Advance position, applying overlap
        pos = end - overlap if end < text_len else text_len

        # Don't let the overlap pull us back inside a table we just finished.
        # If pos lands inside a table span, snap forward to the table end so
        # the next chunk starts with clean prose rather than a broken table tail.
        if table_aware and pos < text_len:
            span = table_span_at(pos, table_spans)
            if span is not None:
                pos = span[1]

    return chunks


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


def run_structure_aware(
    output_path: str,
    *,
    ancestry_result: object,
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
            "Docling is not installed. Run: "
            "pip3 install --break-system-packages docling"
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

    records: list[dict] = []
    toc_filtered = 0
    empty_filtered = 0
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

        breadcrumb = _format_breadcrumb(
            ancestry.get("section_title_path") or [],
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
            "section_title_path": ancestry.get("section_title_path") or [],
            "parent_header_text": ancestry.get("parent_header_text"),
            "parent_context": ancestry.get("parent_context"),
        })
        chunk_id += 1

    log.info(
        "Structure-aware chunking: %d chunks kept, %d ToC filtered, %d empty filtered",
        len(records), toc_filtered, empty_filtered,
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


def run(
    pages_jsonl: str,
    output_path: str,
    *,
    chunk_size: int = 3000,
    overlap: int = 200,
    table_aware: bool = False,
) -> str:
    """Chunk pages JSONL into overlapping text segments and write chunks JSONL.

    Callable interface for in-process use by run_pipeline.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        pages_jsonl:  Path to the pages JSONL file from Step A.
        output_path:  Path to write the output chunks JSONL file.
        chunk_size:   Target chunk size in characters.
        overlap:      Overlap characters between consecutive chunks.
        table_aware:  If True, avoid splitting inside sentinel-wrapped tables.

    Returns:
        output_path (str) — the file that was written.
    """
    pages_path = Path(pages_jsonl).resolve()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    log.info("Loading pages from: %s", pages_path)
    pages = load_pages(pages_path)
    log.info("Loaded %d pages", len(pages))

    page_index = build_page_index(pages)
    full_text = "".join(p["text"] for p in pages)
    log.info("Total text length: %d chars", len(full_text))

    start = time.time()
    chunks = chunk_text(full_text, page_index, chunk_size=chunk_size, overlap=overlap, table_aware=table_aware)
    elapsed = time.time() - start

    chunk_sizes = [len(c["text"]) for c in chunks]
    avg_size = sum(chunk_sizes) / len(chunk_sizes) if chunk_sizes else 0
    log.info(
        "Created %d chunks in %.2fs — avg %.0f chars, min %d, max %d",
        len(chunks), elapsed, avg_size,
        min(chunk_sizes) if chunk_sizes else 0,
        max(chunk_sizes) if chunk_sizes else 0,
    )

    write_jsonl(chunks, out)
    log.info("Wrote %s", out)
    return str(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chunk pages.jsonl into overlapping text chunks (legacy), or "
                    "chunk a PDF with Docling HybridChunker + ancestry breadcrumbs (--docling).",
    )
    # The first positional is pages.jsonl in legacy mode, PDF in --docling mode.
    parser.add_argument(
        "input_path",
        type=str,
        help="Path to pages.jsonl (legacy) or PDF file (--docling mode)",
    )
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
    # Legacy-mode options
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=3000,
        help="(legacy) Target chunk size in characters (default: 3000)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=200,
        help="(legacy) Overlap between consecutive chunks in characters (default: 200)",
    )
    parser.add_argument(
        "--table-aware",
        action="store_true",
        help="(legacy) Avoid splitting inside sentinel-wrapped table regions",
    )
    # Structure-aware (Docling) mode
    parser.add_argument(
        "--docling",
        action="store_true",
        help="Use Docling HybridChunker + WP-14.1 ancestry breadcrumb injection "
             "(input_path must be a PDF)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="(--docling) Limit Docling conversion to first N pages (testing only)",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path).resolve()
    if not input_path.exists():
        log.error("Input file not found: %s", input_path)
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve() if args.output_dir else input_path.parent

    if args.docling:
        # Structure-aware path: run section_parser then run_structure_aware
        if input_path.suffix.lower() != ".pdf":
            log.error("--docling mode requires a PDF as input, got: %s", input_path)
            sys.exit(1)

        stem = input_path.stem
        if args.output:
            output_path = Path(args.output).resolve()
        else:
            output_path = out_dir / f"{stem}_chunks.jsonl"

        try:
            from pipeline import section_parser
        except ImportError:
            log.error("section_parser.py not found — it must be in the same directory")
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

    else:
        # Legacy path: pages.jsonl → fixed-size overlapping chunks
        stem = input_path.stem.replace("_pages", "")
        if args.output:
            output_path = Path(args.output).resolve()
        else:
            output_path = out_dir / f"{stem}_chunks.jsonl"

        run(
            str(input_path),
            str(output_path),
            chunk_size=args.chunk_size,
            overlap=args.overlap,
            table_aware=args.table_aware,
        )


if __name__ == "__main__":
    main()
