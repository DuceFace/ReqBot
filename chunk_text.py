#!/usr/bin/env python3
"""Step B: Chunk extracted page text into overlapping segments.

Input:  pages.jsonl (from Step A)
Output: chunks.jsonl — one JSON object per line:
        {"chunk_id": int, "page_start": int, "page_end": int, "text": str}

This step is deterministic and uses no LLM. It concatenates page texts and
splits them into chunks of approximately `chunk_size` characters with
`overlap` characters of context carried over between consecutive chunks.

Chunk boundaries respect word boundaries — the split point is moved back to
the last whitespace character within the target window so words are never
cut in half.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

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
        description="Chunk pages.jsonl into overlapping text chunks"
    )
    parser.add_argument("pages_jsonl", type=str, help="Path to pages.jsonl from Step A")
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output JSONL file path (default: <stem>_chunks.jsonl in same directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: same directory as input)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=3000,
        help="Target chunk size in characters (default: 3000)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=200,
        help="Overlap between consecutive chunks in characters (default: 200)",
    )
    parser.add_argument(
        "--table-aware",
        action="store_true",
        help="Avoid splitting inside sentinel-wrapped table regions (use with pdfplumber layout mode)",
    )
    args = parser.parse_args()

    pages_path = Path(args.pages_jsonl).resolve()
    if not pages_path.exists():
        log.error("Input file not found: %s", pages_path)
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = Path(args.output).resolve()
    else:
        out_dir = Path(args.output_dir).resolve() if args.output_dir else pages_path.parent
        stem = pages_path.stem.replace("_pages", "")
        output_path = out_dir / f"{stem}_chunks.jsonl"

    run(
        str(pages_path),
        str(output_path),
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        table_aware=args.table_aware,
    )


if __name__ == "__main__":
    main()
