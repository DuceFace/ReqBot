#!/usr/bin/env python3
"""
eval/docling_spike.py — Docling evaluation spike for Phase 14

Tests Docling on one representative document per class and compares output
against the existing ReqBot Step A+B artifacts.

Test documents:
  NIST SP:    NIST.SP.800-128.pdf
  DODI/DoDM:  DODI 8551.01.pdf
  AFI/DAF:    afman17-204.pdf

For each document this script:
  1. Runs Docling and captures raw structural output
  2. Inspects heading hierarchy depth and quality
  3. Inspects table extraction behavior
  4. Runs HybridChunker and captures chunk samples
  5. Compares chunk count, text coverage, and mid-paragraph split evidence
     against the existing Step B chunks.jsonl
  6. Attempts a thin bridge: maps Docling chunks into ReqBot Phase 14 schema shape

Outputs:
  eval/spike_results/report.md           — human-readable decision memo
  eval/spike_results/<stem>/             — per-document JSON artifacts

Usage:
  python3 eval/docling_spike.py
  python3 eval/docling_spike.py --doc nist    # single doc class
  python3 eval/docling_spike.py --max-pages 20  # limit pages for faster testing
"""

import argparse
import json
import os
import re
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
RAW_PDFS = REPO_ROOT / "raw_pdfs"
PROCESSED_BASE = Path.home() / "documents" / "processed"
SPIKE_OUT = REPO_ROOT / "eval" / "spike_results"

# (pdf_stem, document_class, existing_artifact_dir_name)
TEST_DOCS = [
    ("NIST.SP.800-128",  "nist_sp",   "NIST.SP.800-128_20260320_015840"),
    ("DODI 8551.01",     "dodi_dodm", "DODI 8551.01_20260322_171740"),
    ("afman17-204",      "afi_daf",   "afman17-204_20260322_172408"),
]

# Chunk size used in the existing Step B chunker (for comparison framing)
EXISTING_CHUNK_SIZE = 3000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DocResult:
    stem: str
    doc_class: str
    pdf_path: Path
    artifact_dir: Path

    # Docling outputs
    docling_ok: bool = False
    docling_error: str = ""
    convert_seconds: float = 0.0

    # Structure
    total_items: int = 0
    heading_items: int = 0
    table_items: int = 0
    text_items: int = 0
    max_heading_depth: int = 0
    heading_samples: list = field(default_factory=list)   # list of (depth, text)
    table_samples: list = field(default_factory=list)     # list of str summaries

    # Docling chunks
    docling_chunk_count: int = 0
    docling_chunk_samples: list = field(default_factory=list)  # list of dicts
    docling_avg_chars: float = 0.0

    # Existing Step B chunks
    existing_chunk_count: int = 0
    existing_avg_chars: float = 0.0
    existing_chunk_samples: list = field(default_factory=list)

    # Bridge output (Phase 14 schema shape)
    bridge_samples: list = field(default_factory=list)    # list of dicts

    # Judgment
    structure_verdict: str = ""   # pass / partial / fail
    chunk_verdict: str = ""
    parent_context_verdict: str = ""
    bridge_verdict: str = ""
    overall_verdict: str = ""
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_existing_chunks(artifact_dir: Path, stem: str) -> list[dict]:
    path = artifact_dir / f"{stem}_chunks.jsonl"
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def truncate(text: str, n: int = 300) -> str:
    text = text.strip()
    return text[:n] + "…" if len(text) > n else text


def count_mid_paragraph_splits(chunks: list[dict]) -> int:
    """
    Rough heuristic: a split is 'mid-paragraph' if the chunk ends with a
    lowercase letter or comma (no sentence terminator at the boundary).
    """
    bad = 0
    for c in chunks:
        text = (c.get("text") or "").rstrip()
        if text and text[-1] not in ".!?:\"'":
            bad += 1
    return bad


# ---------------------------------------------------------------------------
# Docling evaluation
# ---------------------------------------------------------------------------

def run_docling(result: DocResult, max_pages: Optional[int]) -> None:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        result.docling_error = f"Import error: {e}"
        return

    try:
        converter = DocumentConverter()
    except Exception as e:
        result.docling_error = f"Converter init error: {e}"
        return

    # page_range=(1, N) limits *which* pages are processed.
    # max_num_pages is a rejection gate (refuse docs > N pages) — do NOT use it here.
    convert_kwargs = {}
    if max_pages:
        convert_kwargs["page_range"] = (1, max_pages)

    t0 = time.time()
    try:
        conv_result = converter.convert(str(result.pdf_path), **convert_kwargs)
    except Exception as e:
        result.docling_error = f"Conversion error: {e}"
        return
    result.convert_seconds = round(time.time() - t0, 1)
    result.docling_ok = True

    doc = conv_result.document
    _inspect_structure(result, doc)
    _inspect_chunks(result, doc)


def _inspect_structure(result: DocResult, doc) -> None:
    """Walk the document and collect heading/table/text counts and samples."""
    try:
        from docling.datamodel.document import DocItemLabel
        HEADER_LABELS = {DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE}
        TABLE_LABELS  = {DocItemLabel.TABLE}
    except ImportError:
        # Fallback: use string label comparison
        HEADER_LABELS = None
        TABLE_LABELS  = None

    heading_depth_map: dict = {}  # heading_text -> depth based on numbering

    for item, level in doc.iterate_items():
        label = getattr(item, "label", None)
        label_str = str(label).lower() if label else ""

        result.total_items += 1

        # Heading detection
        is_header = (
            (HEADER_LABELS and label in HEADER_LABELS)
            or ("section_header" in label_str)
            or ("title" in label_str and "sub" not in label_str)
        )
        if is_header:
            result.heading_items += 1
            text = _item_text(item)
            depth = _estimate_heading_depth(text)
            if depth > result.max_heading_depth:
                result.max_heading_depth = depth
            if len(result.heading_samples) < 20:
                result.heading_samples.append((depth, truncate(text, 120)))

        # Table detection
        is_table = (
            (TABLE_LABELS and label in TABLE_LABELS)
            or "table" in label_str
        )
        if is_table:
            result.table_items += 1
            if len(result.table_samples) < 5:
                try:
                    md = item.export_to_markdown()
                    result.table_samples.append(truncate(md, 400))
                except Exception:
                    result.table_samples.append("[table — export failed]")

        # Text
        if "text" in label_str or "paragraph" in label_str or "list" in label_str:
            result.text_items += 1


def _inspect_chunks(result: DocResult, doc) -> None:
    """Run HybridChunker and collect stats."""
    try:
        from docling.chunking import HybridChunker
    except ImportError:
        result.notes.append("HybridChunker not available in this Docling version")
        return

    try:
        chunker = HybridChunker()
    except Exception as e:
        result.notes.append(f"HybridChunker init failed: {e}")
        return

    try:
        chunks = list(chunker.chunk(dl_doc=doc))
    except Exception as e:
        result.notes.append(f"Chunker.chunk() failed: {e}")
        return

    result.docling_chunk_count = len(chunks)
    if not chunks:
        return

    total_chars = sum(len(getattr(c, "text", "") or "") for c in chunks)
    result.docling_avg_chars = round(total_chars / len(chunks), 0)

    for c in chunks[:5]:
        text = getattr(c, "text", "") or ""
        meta = getattr(c, "meta", None)
        headings = []
        if meta:
            headings = getattr(meta, "headings", []) or []
        result.docling_chunk_samples.append({
            "text_preview": truncate(text, 400),
            "char_count": len(text),
            "headings": [truncate(h, 80) for h in headings],
        })
        # Bridge sample: map to Phase 14 schema shape
        if len(result.bridge_samples) < 3:
            result.bridge_samples.append(_bridge_chunk(c, len(result.bridge_samples)))


def _bridge_chunk(chunk, idx: int) -> dict:
    """
    Thin prototype: map a Docling HybridChunker chunk to the ReqBot Phase 14
    chunk schema shape.  This is a proof-of-concept, not production code.
    """
    text = getattr(chunk, "text", "") or ""
    meta = getattr(chunk, "meta", None)

    headings: list[str] = []
    page_start = None
    page_end = None

    if meta:
        headings = list(getattr(meta, "headings", []) or [])
        # Provenance / page numbers
        doc_items = getattr(meta, "doc_items", []) or []
        for item in doc_items:
            for prov in getattr(item, "prov", []) or []:
                pg = getattr(prov, "page_no", None)
                if pg is not None:
                    if page_start is None or pg < page_start:
                        page_start = pg
                    if page_end is None or pg > page_end:
                        page_end = pg

    # Derive section_ref_path: extract leading numbering from each heading
    section_ref_path = []
    section_title_path = []
    for h in headings:
        ref = _extract_section_ref(h)
        section_ref_path.append(ref if ref else "")
        section_title_path.append(h.strip())

    parent_header = headings[-1].strip() if headings else None
    breadcrumb = " > ".join(h.strip() for h in headings) if headings else ""
    full_text = f"[{breadcrumb}]\n\n{text}" if breadcrumb else text

    return {
        "chunk_id": idx,
        "page_start": page_start,
        "page_end": page_end,
        "text": truncate(full_text, 600),
        "raw_text": truncate(text, 400),
        "breadcrumb": breadcrumb or None,
        "section_ref_path": section_ref_path,
        "section_title_path": section_title_path,
        "parent_header_text": parent_header,
        "parent_context": None,  # requires paragraph-level parent body; bridge only
    }


def _item_text(item) -> str:
    try:
        return item.text or ""
    except AttributeError:
        pass
    try:
        return item.export_to_text()
    except Exception:
        return ""


def _estimate_heading_depth(text: str) -> int:
    """
    Estimate hierarchy depth from numbering prefix.
    Examples:
      "1. Introduction"           -> 1
      "2.1 Policy"                -> 2
      "3.1.4 Requirements"        -> 3
      "A4.1. Enclosure"           -> 2
      "SECTION 3: ..."            -> 1
    """
    text = text.strip()
    # Dotted numbering: 3.1.4 → depth 3
    m = re.match(r'^[A-Z]?\d+(\.\d+)*', text)
    if m:
        return m.group(0).count('.') + 1
    # SECTION/ENCLOSURE/APPENDIX keyword
    if re.match(r'^(SECTION|ENCLOSURE|APPENDIX|ANNEX)\s+\w+', text, re.IGNORECASE):
        return 1
    return 1


def _extract_section_ref(heading: str) -> str:
    """Extract leading reference number from a heading string."""
    m = re.match(r'^([A-Z]?\d+(\.\d+)*\.?)', heading.strip())
    if m:
        return m.group(1).rstrip('.')
    m2 = re.match(r'^(SECTION|ENCLOSURE|APPENDIX|ANNEX)\s+(\w+)', heading.strip(), re.IGNORECASE)
    if m2:
        return f"{m2.group(1).upper()}-{m2.group(2).upper()}"
    return ""


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_existing(result: DocResult) -> None:
    chunks = load_existing_chunks(result.artifact_dir, result.stem.replace(" ", " "))
    if not chunks:
        result.notes.append("Could not load existing Step B chunks for comparison")
        return

    result.existing_chunk_count = len(chunks)
    total_chars = sum(len(c.get("text", "")) for c in chunks)
    result.existing_avg_chars = round(total_chars / len(chunks), 0) if chunks else 0
    result.existing_chunk_samples = [
        {"chunk_id": c["chunk_id"],
         "pages": f"{c.get('page_start','?')}–{c.get('page_end','?')}",
         "text_preview": truncate(c.get("text", ""), 300)}
        for c in chunks[:3]
    ]

    mid_splits = count_mid_paragraph_splits(chunks)
    pct = round(100 * mid_splits / len(chunks)) if chunks else 0
    result.notes.append(
        f"Existing Step B: {len(chunks)} chunks, avg {result.existing_avg_chars:.0f} chars, "
        f"~{pct}% end without sentence terminator (rough mid-split proxy)"
    )


# ---------------------------------------------------------------------------
# Judgment
# ---------------------------------------------------------------------------

def judge(result: DocResult) -> None:
    if not result.docling_ok:
        result.structure_verdict = "fail"
        result.chunk_verdict = "fail"
        result.parent_context_verdict = "fail"
        result.bridge_verdict = "fail"
        result.overall_verdict = "FAIL"
        return

    # Structure quality
    if result.heading_items >= 5 and result.max_heading_depth >= 2:
        result.structure_verdict = "pass"
    elif result.heading_items >= 2:
        result.structure_verdict = "partial"
    else:
        result.structure_verdict = "fail"

    # Chunk quality: more chunks than existing + Docling has them
    if result.docling_chunk_count > result.existing_chunk_count * 1.5:
        result.chunk_verdict = "pass"
    elif result.docling_chunk_count > result.existing_chunk_count:
        result.chunk_verdict = "partial"
    elif result.docling_chunk_count == 0:
        result.chunk_verdict = "fail"
    else:
        result.chunk_verdict = "partial"

    # Parent context: do Docling chunks carry heading metadata?
    chunks_with_headings = sum(
        1 for c in result.docling_chunk_samples if c.get("headings")
    )
    if chunks_with_headings >= 3:
        result.parent_context_verdict = "pass"
    elif chunks_with_headings >= 1:
        result.parent_context_verdict = "partial"
    else:
        result.parent_context_verdict = "fail"

    # Bridge: did we produce schema-shaped output?
    if result.bridge_samples and result.bridge_samples[0].get("section_ref_path"):
        result.bridge_verdict = "pass"
    elif result.bridge_samples:
        result.bridge_verdict = "partial"
    else:
        result.bridge_verdict = "fail"

    verdicts = [
        result.structure_verdict,
        result.chunk_verdict,
        result.parent_context_verdict,
        result.bridge_verdict,
    ]
    if verdicts.count("pass") >= 3:
        result.overall_verdict = "PASS"
    elif "fail" not in verdicts:
        result.overall_verdict = "PARTIAL PASS"
    elif verdicts.count("fail") >= 3:
        result.overall_verdict = "FAIL"
    else:
        result.overall_verdict = "PARTIAL PASS"


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def write_report(results: list[DocResult], out_dir: Path) -> Path:
    lines = []
    a = lines.append

    a("# Docling Spike Evaluation Report")
    a("")
    a("**Phase 14 — Pre-implementation evaluation**")
    a(f"**Generated by:** `eval/docling_spike.py`")
    a("")
    a("---")
    a("")

    # Summary table
    a("## Summary")
    a("")
    a("| Document | Class | Overall | Structure | Chunks | Parent Context | Bridge |")
    a("|---|---|---|---|---|---|---|")
    for r in results:
        if r.docling_ok:
            a(f"| {r.stem} | {r.doc_class} | **{r.overall_verdict}** | "
              f"{r.structure_verdict} | {r.chunk_verdict} | "
              f"{r.parent_context_verdict} | {r.bridge_verdict} |")
        else:
            a(f"| {r.stem} | {r.doc_class} | **FAIL** | — | — | — | — |")
    a("")

    # Per-document sections
    for r in results:
        a(f"---")
        a("")
        a(f"## {r.stem} ({r.doc_class})")
        a("")

        if not r.docling_ok:
            a(f"**Docling conversion failed:** `{r.docling_error}`")
            a("")
            continue

        a(f"**Conversion time:** {r.convert_seconds}s")
        a(f"**Overall verdict:** {r.overall_verdict}")
        a("")

        # Comparison
        a("### Step B Comparison")
        a("")
        a(f"| Metric | Existing Step B | Docling HybridChunker |")
        a(f"|---|---|---|")
        a(f"| Chunk count | {r.existing_chunk_count} | {r.docling_chunk_count} |")
        a(f"| Avg chars/chunk | {r.existing_avg_chars:.0f} | {r.docling_avg_chars:.0f} |")
        a("")

        # Structure
        a("### Structure Quality")
        a("")
        a(f"- Total document items: {r.total_items}")
        a(f"- Heading items detected: {r.heading_items}")
        a(f"- Table items detected: {r.table_items}")
        a(f"- Text/paragraph items: {r.text_items}")
        a(f"- Max heading depth: {r.max_heading_depth}")
        a(f"- **Verdict: {r.structure_verdict}**")
        a("")
        if r.heading_samples:
            a("**Heading samples (first 20):**")
            a("")
            a("```")
            for depth, text in r.heading_samples:
                a(f"{'  ' * (depth-1)}[depth {depth}] {text}")
            a("```")
            a("")

        # Tables
        if r.table_items > 0:
            a("### Table Extraction")
            a("")
            a(f"Tables detected: {r.table_items}")
            a("")
            for i, t in enumerate(r.table_samples):
                a(f"**Table {i+1} preview:**")
                a("```")
                a(t)
                a("```")
                a("")

        # Chunks
        a("### Chunk Samples (Docling HybridChunker)")
        a("")
        a(f"**Verdict: {r.chunk_verdict}**")
        a("")
        for i, c in enumerate(r.docling_chunk_samples):
            a(f"**Chunk {i+1}** ({c['char_count']} chars)")
            if c.get("headings"):
                a(f"  Headings: {' > '.join(c['headings'])}")
            a("```")
            a(c["text_preview"])
            a("```")
            a("")

        # Bridge
        a("### Bridge Prototype (Phase 14 Schema Shape)")
        a("")
        a(f"**Parent context verdict: {r.parent_context_verdict}**")
        a(f"**Bridge verdict: {r.bridge_verdict}**")
        a("")
        for i, b in enumerate(r.bridge_samples):
            a(f"**Bridge chunk {i+1}:**")
            a("```json")
            a(json.dumps(b, indent=2, ensure_ascii=False))
            a("```")
            a("")

        # Existing Step B samples
        a("### Existing Step B Samples (for comparison)")
        a("")
        for c in r.existing_chunk_samples:
            a(f"**Chunk {c['chunk_id']}** (pages {c['pages']}):")
            a("```")
            a(c["text_preview"])
            a("```")
            a("")

        # Notes
        if r.notes:
            a("### Notes")
            a("")
            for n in r.notes:
                a(f"- {n}")
            a("")

    # Final recommendation
    a("---")
    a("")
    a("## Recommendation")
    a("")

    pass_count = sum(1 for r in results if r.overall_verdict == "PASS")
    partial_count = sum(1 for r in results if r.overall_verdict == "PARTIAL PASS")
    fail_count = sum(1 for r in results if r.overall_verdict == "FAIL")

    a(f"Results across {len(results)} document classes: "
      f"{pass_count} PASS / {partial_count} PARTIAL PASS / {fail_count} FAIL")
    a("")
    if fail_count == 0 and pass_count >= 2:
        a("**Preliminary recommendation: Outcome A or B (adopt or hybrid)**")
        a("")
        a("Docling shows material improvement. Recommend proceeding with integration.")
        a("Verify whether canonical section ID derivation is tractable before committing fully.")
    elif fail_count <= 1 and (pass_count + partial_count) >= 2:
        a("**Preliminary recommendation: Outcome B (hybrid)**")
        a("")
        a("Docling provides structural improvement on most doc classes but needs")
        a("deterministic post-processing for canonical section ID derivation.")
    else:
        a("**Preliminary recommendation: Outcome C (reject)**")
        a("")
        a("Docling does not show sufficient improvement to justify the integration burden.")
        a("Proceed with the custom regex parser/chunker plan.")
    a("")
    a("*Human review required — scores above are heuristic. Read the samples.*")
    a("")

    report_path = out_dir / "report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    return report_path


def save_artifacts(result: DocResult, out_dir: Path) -> None:
    doc_dir = out_dir / result.stem.replace(" ", "_")
    doc_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "stem": result.stem,
        "doc_class": result.doc_class,
        "docling_ok": result.docling_ok,
        "docling_error": result.docling_error,
        "convert_seconds": result.convert_seconds,
        "total_items": result.total_items,
        "heading_items": result.heading_items,
        "table_items": result.table_items,
        "text_items": result.text_items,
        "max_heading_depth": result.max_heading_depth,
        "heading_samples": result.heading_samples,
        "table_samples": result.table_samples,
        "docling_chunk_count": result.docling_chunk_count,
        "docling_avg_chars": result.docling_avg_chars,
        "docling_chunk_samples": result.docling_chunk_samples,
        "existing_chunk_count": result.existing_chunk_count,
        "existing_avg_chars": result.existing_avg_chars,
        "existing_chunk_samples": result.existing_chunk_samples,
        "bridge_samples": result.bridge_samples,
        "structure_verdict": result.structure_verdict,
        "chunk_verdict": result.chunk_verdict,
        "parent_context_verdict": result.parent_context_verdict,
        "bridge_verdict": result.bridge_verdict,
        "overall_verdict": result.overall_verdict,
        "notes": result.notes,
    }
    with open(doc_dir / "spike_data.json", "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Docling spike evaluation for Phase 14")
    parser.add_argument(
        "--doc",
        choices=["nist", "dodi", "afi", "all"],
        default="all",
        help="Which document class to test (default: all)"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit PDF to first N pages (faster for testing)"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=SPIKE_OUT,
        help="Output directory for report and artifacts"
    )
    args = parser.parse_args()

    # Filter docs
    doc_filter = {
        "nist": ["nist_sp"],
        "dodi": ["dodi_dodm"],
        "afi":  ["afi_daf"],
        "all":  ["nist_sp", "dodi_dodm", "afi_daf"],
    }[args.doc]

    selected = [d for d in TEST_DOCS if d[1] in doc_filter]

    print(f"Docling spike — testing {len(selected)} document(s)")
    print(f"Output dir: {args.out_dir}")
    print()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for stem, doc_class, artifact_dir_name in selected:
        pdf_path = RAW_PDFS / f"{stem}.pdf"
        artifact_dir = PROCESSED_BASE / artifact_dir_name

        if not pdf_path.exists():
            print(f"[{stem}] PDF not found at {pdf_path} — skipping")
            continue

        result = DocResult(
            stem=stem,
            doc_class=doc_class,
            pdf_path=pdf_path,
            artifact_dir=artifact_dir,
        )

        print(f"[{stem}] Loading existing Step B artifacts…")
        compare_existing(result)

        print(f"[{stem}] Running Docling conversion (may take several minutes)…")
        run_docling(result, args.max_pages)

        if not result.docling_ok:
            print(f"[{stem}] Docling FAILED: {result.docling_error}")
        else:
            print(f"[{stem}] Conversion done in {result.convert_seconds}s — "
                  f"{result.heading_items} headings, {result.table_items} tables, "
                  f"{result.docling_chunk_count} chunks")

        judge(result)
        save_artifacts(result, args.out_dir)
        results.append(result)
        print(f"[{stem}] Overall verdict: {result.overall_verdict}")
        print()

    if not results:
        print("No documents processed.")
        sys.exit(1)

    report_path = write_report(results, args.out_dir)
    print(f"Report written to: {report_path}")

    # Print summary to console
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        status = r.overall_verdict if r.docling_ok else f"FAILED ({r.docling_error})"
        print(f"  {r.stem:<35} {status}")
    print()
    print(f"Full report: {report_path}")


if __name__ == "__main__":
    main()
