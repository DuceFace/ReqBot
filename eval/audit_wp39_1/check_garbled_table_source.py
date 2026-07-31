#!/usr/bin/env python3
"""WP-39.1: for the 2 GARBLED_TABLE examples (REQ-5c349cdc3656, REQ-68e7c7d2ba86,
afi17-203 chunk_id=55, page 20), check whether the mangled run-on text seen in the
chunk's raw_text originates in Docling's own raw parse, or is introduced later by
chunking's serialization of the table.

Codex review, PR #183 (P1): trace_examples.py never loaded the raw DoclingDocument or
checked its table/list structure directly, so the original Findings couldn't
distinguish "Docling parsed this badly" from "Docling parsed this fine, chunking
flattened it badly" -- this script answers that question directly rather than leaving
it asserted without evidence.

Requires running DocumentConverter fresh (page-range-limited to keep it fast) --
not something the committed *_ancestry.json/*_chunks.jsonl artifacts alone can answer,
since those only contain the *serialized* text, not the live DoclingDocument's table
model.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PDF_PATH = _ROOT / "raw_pdfs" / "afi17-203.pdf"
PAGE = 20  # chunk_id=55's page_start/page_end in afi17-203_chunks.jsonl


def main():
    if not PDF_PATH.exists():
        # raw_pdfs/ is gitignored (see docs/PHASE38_REQUIREMENTS.md's Phase Framing) --
        # a fresh checkout or CI environment won't have it (Gemini review, PR #183).
        raise SystemExit(
            f"Source PDF not found at {PDF_PATH}. raw_pdfs/ is gitignored and not part "
            f"of this repo -- place afi17-203.pdf there to run this check."
        )

    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(str(PDF_PATH), page_range=(PAGE, PAGE))
    doc = result.document

    tables = [item for item, _ in doc.iterate_items() if str(getattr(item, "label", "")) == "table"]
    print(f"Table items found on page {PAGE}: {len(tables)}")

    for i, table in enumerate(tables):
        print(f"\n--- table {i}: raw .text attribute ---")
        print(repr(getattr(table, "text", "") or "")[:200])

        print(f"\n--- table {i}: export_to_dataframe() (Docling's structured table model) ---")
        try:
            df = table.export_to_dataframe(doc)
        except TypeError:
            df = table.export_to_dataframe()
        print(df.to_string()[:2000])

    print(
        "\nConclusion: if export_to_dataframe() above shows real, distinct row/column "
        "values (not run-on repeated text), Docling's own raw parse correctly recognizes "
        "table structure -- the garbling in *_chunks.jsonl's raw_text is introduced by "
        "chunk_text.py's handling of body-label items (which does not use this "
        "structured export), not by Docling's parse itself."
    )


if __name__ == "__main__":
    main()
