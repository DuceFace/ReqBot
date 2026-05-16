#!/usr/bin/env python3
"""Step A: Extract text from PDF pages into JSONL format.

Input:  PDF file path
Output: pages.jsonl — one JSON object per line: {"page_num": int, "text": str}

This step is deterministic and uses no LLM. It extracts raw text from each
page of a PDF using PyMuPDF (fitz), preserving page boundaries.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Sentinel markers written around structured table text.
# Must match TABLE_START_SENTINEL / TABLE_END_SENTINEL in chunk_text.py.
TABLE_START_SENTINEL = "<<<TABLE_START>>>"
TABLE_END_SENTINEL = "<<<TABLE_END>>>"


def extract_pages(pdf_path: Path) -> list[dict]:
    """Extract text from each page of a PDF using PyMuPDF.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        List of dicts with keys 'page_num' (1-indexed) and 'text'.
    """
    with fitz.open(pdf_path) as doc:
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text")
            pages.append({"page_num": i + 1, "text": text})
    return pages


def _extract_plumber_page(page) -> str:
    """Extract text from one pdfplumber page with table detection.

    Tables are extracted as pipe-delimited rows and wrapped in sentinel
    markers so chunk_text.py can identify and protect them from mid-row
    splits. Non-table text is extracted via pdfplumber's layout-aware
    text extraction with table regions filtered out.
    """
    tables = page.find_tables()

    if not tables:
        return page.extract_text() or ""

    # Sort tables top-to-bottom so we can slice the page vertically in order.
    tables.sort(key=lambda t: t.bbox[1])

    parts: list[str] = []
    y_cursor: float = 0.0

    for table in tables:
        top, bottom = table.bbox[1], table.bbox[3]

        # 1. Extract standard text above this table
        if top > y_cursor:
            try:
                text_above = page.crop((0, y_cursor, page.width, top)).extract_text()
                if text_above and text_above.strip():
                    parts.append(text_above.strip())
            except ValueError:
                pass  # Ignore invalid crop boxes (e.g. zero-height region)

        # 2. Format and sentinel-wrap the table
        rows = table.extract()
        if rows:
            formatted = "\n".join(
                " | ".join((cell.strip() if cell else "") for cell in row)
                for row in rows
                if any(cell and cell.strip() for cell in row)
            )
            if formatted.strip():
                parts.append(f"\n{TABLE_START_SENTINEL}\n{formatted}\n{TABLE_END_SENTINEL}")

        y_cursor = max(y_cursor, bottom)

    # 3. Extract any remaining text below the last table
    if y_cursor < page.height:
        try:
            text_below = page.crop((0, y_cursor, page.width, page.height)).extract_text()
            if text_below and text_below.strip():
                parts.append(text_below.strip())
        except ValueError:
            pass

    return "\n\n".join(parts)


def extract_pages_pdfplumber(pdf_path: Path) -> list[dict]:
    """Extract text from each page using pdfplumber with table detection.

    Tables are wrapped in TABLE_START_SENTINEL / TABLE_END_SENTINEL markers
    so chunk_text.py --table-aware can prevent mid-row splits.

    Returns:
        List of dicts with keys 'page_num' (1-indexed) and 'text'.
    """
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber is not installed. Run: pip3 install pdfplumber")
        raise

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            try:
                text = _extract_plumber_page(page)
            except Exception as e:
                log.warning("pdfplumber failed on page %d (%s) — falling back to PyMuPDF", i + 1, e)
                with fitz.open(pdf_path) as doc:
                    text = doc[i].get_text("text")
            pages.append({"page_num": i + 1, "text": text})
    return pages


def write_jsonl(pages: list[dict], output_path: Path) -> None:
    """Write page records to a JSONL file.

    Args:
        pages: List of page dicts.
        output_path: Path to write the JSONL file.
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for page in pages:
            f.write(json.dumps(page, ensure_ascii=False) + "\n")


def run(pdf_path: str, output_path: str, *, layout_mode: str = "pymupdf") -> str:
    """Extract text from a PDF and write pages JSONL.

    Callable interface for in-process use by run_pipeline.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        pdf_path:    Path to the input PDF file.
        output_path: Path to write the output JSONL file.
        layout_mode: "pymupdf" (default) or "pdfplumber".

    Returns:
        output_path (str) — the file that was written.
    """
    pdf = Path(pdf_path).resolve()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    log.info("Extracting text from: %s (layout-mode=%s)", pdf, layout_mode)
    start = time.time()

    if layout_mode == "pdfplumber":
        pages = extract_pages_pdfplumber(pdf)
    else:
        pages = extract_pages(pdf)
    elapsed = time.time() - start

    total_chars = sum(len(p["text"]) for p in pages)
    non_empty = sum(1 for p in pages if p["text"].strip())
    log.info(
        "Extracted %d pages (%d non-empty) in %.2fs — %d total chars",
        len(pages), non_empty, elapsed, total_chars,
    )

    write_jsonl(pages, out)
    log.info("Wrote %s", out)
    return str(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract text from a PDF into pages.jsonl"
    )
    parser.add_argument("pdf_path", type=str, help="Path to the input PDF file")
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output JSONL file path (default: <pdf_stem>_pages.jsonl in same directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: same directory as PDF)",
    )
    parser.add_argument(
        "--layout-mode",
        choices=["pymupdf", "pdfplumber"],
        default="pymupdf",
        help="PDF extraction backend (default: pymupdf). Use 'pdfplumber' for table-aware extraction.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).resolve()
    if not pdf_path.exists():
        log.error("PDF file not found: %s", pdf_path)
        sys.exit(1)
    if not pdf_path.suffix.lower() == ".pdf":
        log.warning("File does not have .pdf extension: %s", pdf_path)

    # Determine output path
    if args.output:
        output_path = Path(args.output).resolve()
    else:
        out_dir = Path(args.output_dir).resolve() if args.output_dir else pdf_path.parent
        output_path = out_dir / f"{pdf_path.stem}_pages.jsonl"

    run(str(pdf_path), str(output_path), layout_mode=args.layout_mode)


if __name__ == "__main__":
    main()
