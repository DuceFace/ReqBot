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
    toc_chunk_count: int = 0                              # ToC garbage chunks filtered out
    docling_chunk_samples: list = field(default_factory=list)  # list of dicts (non-ToC only)
    docling_avg_chars: float = 0.0

    # Parent-child reconstruction test
    parent_child_groups: int = 0       # number of parent headings with 2+ children
    parent_child_example: dict = field(default_factory=dict)
    chunk_heading_dist: dict = field(default_factory=dict)  # {"0": N, "1": N, "2+": N}

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

    # Separate ToC chunks from content chunks
    content_chunks = []
    for c in chunks:
        text = getattr(c, "text", "") or ""
        if _is_toc_chunk(text):
            result.toc_chunk_count += 1
        else:
            content_chunks.append(c)

    if result.toc_chunk_count:
        result.notes.append(
            f"ToC filter: {result.toc_chunk_count} of {result.docling_chunk_count} chunks "
            f"flagged as Table of Contents noise and excluded from samples"
        )

    # Stats based on all chunks (ToC excluded from avg to avoid skew)
    if content_chunks:
        total_chars = sum(len(getattr(c, "text", "") or "") for c in content_chunks)
        result.docling_avg_chars = round(total_chars / len(content_chunks), 0)
    else:
        total_chars = sum(len(getattr(c, "text", "") or "") for c in chunks)
        result.docling_avg_chars = round(total_chars / len(chunks), 0)

    # Collect samples from content chunks (skip ToC garbage)
    for c in content_chunks[:5]:
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

    # Parent-child reconstruction test: run on ALL content chunks
    result.parent_child_groups, result.parent_child_example, result.chunk_heading_dist = (
        _find_parent_child_groups(content_chunks)
    )


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


# Regex for lines that look like ToC entries: lots of dots, or line ending
# with a bare page number.
_TOC_LINE_RE = re.compile(r'\.{5,}|\s+\d{1,4}\s*$')


def _is_toc_chunk(text: str) -> bool:
    """
    Heuristic: returns True if the chunk looks like a Table of Contents page.
    A chunk is flagged as ToC if >40% of its non-empty lines match the ToC pattern
    (series of dots, or line ending with a page number).
    """
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return False
    toc_lines = sum(1 for l in lines if _TOC_LINE_RE.search(l))
    return (toc_lines / len(lines)) > 0.4


def _find_parent_child_groups(chunks) -> tuple[int, dict, dict]:
    """
    Scan all Docling chunks for parent-child heading ancestry relationships.

    A parent-child group exists when multiple chunks share the same topmost
    heading but differ in their deeper headings (i.e., the parent section has
    multiple sub-paragraph children that Docling kept separate).

    Also returns a heading-depth distribution so callers can detect the case
    where HybridChunker only provides the immediate heading (not full ancestry).

    Returns:
        (group_count, best_example, heading_dist)
        - group_count: number of parent headings with 2+ children
        - best_example: dict describing the group with the most children
        - heading_dist: {"0": N, "1": N, "2+": N} counts of heading list lengths
    """
    parent_groups: dict[str, list] = {}
    depth_counts = {"0": 0, "1": 0, "2+": 0}

    for c in chunks:
        meta = getattr(c, "meta", None)
        headings = list(getattr(meta, "headings", []) or []) if meta else []

        # Track heading depth distribution
        n = len(headings)
        if n == 0:
            depth_counts["0"] += 1
        elif n == 1:
            depth_counts["1"] += 1
        else:
            depth_counts["2+"] += 1

        if len(headings) >= 2:
            parent_key = headings[0]
            if parent_key not in parent_groups:
                parent_groups[parent_key] = []
            parent_groups[parent_key].append({
                "child_heading": headings[-1].strip() if len(headings) > 1 else None,
                "full_ancestry": [h.strip() for h in headings],
                "text_preview": truncate(getattr(c, "text", "") or "", 150),
            })

    # Only groups with 2+ children demonstrate actual parent-child linkage
    multi_child = {k: v for k, v in parent_groups.items() if len(v) >= 2}
    if not multi_child:
        return 0, {}, depth_counts

    best_key = max(multi_child, key=lambda k: len(multi_child[k]))
    example = {
        "parent_heading": best_key,
        "child_count": len(multi_child[best_key]),
        "children_sample": multi_child[best_key][:3],
    }
    return len(multi_child), example, depth_counts


def _refs_are_real(bridge_samples: list) -> bool:
    """
    Returns True if at least one bridge sample has a section_ref_path where
    all elements are non-empty strings.  [""] is falsy evidence — do not count it.
    """
    for s in bridge_samples:
        refs = s.get("section_ref_path", [])
        if refs and all(r.strip() for r in refs):
            return True
    return False


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

    # Parent-child context: grade on heading ancestry enabling parent-child grouping.
    # NOTE: parent_context (clause body text) is always null in the bridge prototype;
    # we cannot grade it "pass" just because headings are present.  A "partial" grade
    # means ancestry metadata is present and enables parent-child linkage; deriving the
    # full parent clause body still requires implementation work.
    if result.parent_child_groups >= 2:
        result.parent_context_verdict = "partial"
        result.notes.append(
            f"parent_context_verdict=partial: {result.parent_child_groups} parent-child groups "
            f"found via heading ancestry — linkage is derivable; parent clause body text "
            f"(parent_context field) is not yet extracted in bridge prototype"
        )
    elif result.parent_child_groups == 1:
        result.parent_context_verdict = "partial"
        result.notes.append(
            "parent_context_verdict=partial: 1 parent-child group found; "
            "parent clause body text not yet extracted"
        )
    else:
        result.parent_context_verdict = "fail"
        # Distinguish: "no headings at all" vs "headings present but only immediate heading"
        # The latter means HybridChunker is giving leaf headings only, not full ancestry.
        only_one = result.chunk_heading_dist.get("1", 0)
        has_two_plus = result.chunk_heading_dist.get("2+", 0)
        if only_one > 0 and has_two_plus == 0:
            result.notes.append(
                f"parent_context_verdict=fail: HybridChunker provides only the IMMEDIATE heading "
                f"per chunk (not full ancestry path) — {only_one} chunks carry exactly 1 heading, "
                f"0 carry 2+. Full ancestry requires traversal of the Docling document model "
                f"(doc.body / item.parent), not just chunk.meta.headings. This is bridge complexity "
                f"that must be estimated before recommending Outcome A."
            )
        else:
            result.notes.append(
                "parent_context_verdict=fail: no multi-level heading groups found; "
                "parent-child linkage cannot be demonstrated from this run"
            )

    # Bridge: did we produce schema-shaped output with real (non-empty) section refs?
    # [""] is truthy but is not evidence of canonical ref derivation — explicitly reject it.
    if result.bridge_samples and _refs_are_real(result.bridge_samples):
        result.bridge_verdict = "pass"
    elif result.bridge_samples:
        result.bridge_verdict = "partial"
        result.notes.append(
            "bridge_verdict=partial: bridge samples produced but section_ref_path "
            "contains only empty strings (headings present without numbered prefixes)"
        )
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
        a(f"| Chunk count (total) | {r.existing_chunk_count} | {r.docling_chunk_count} |")
        a(f"| ToC chunks filtered | — | {r.toc_chunk_count} |")
        a(f"| Content chunks | — | {r.docling_chunk_count - r.toc_chunk_count} |")
        a(f"| Avg chars/chunk (content) | {r.existing_avg_chars:.0f} | {r.docling_avg_chars:.0f} |")
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

        # Parent-child reconstruction test
        a("### Parent-Child Reconstruction Test")
        a("")
        a(f"**Verdict: {r.parent_context_verdict}**")
        a(f"**Parent-child groups (2+ children sharing ancestry): {r.parent_child_groups}**")
        dist = r.chunk_heading_dist
        a(f"**Chunk heading depth distribution:** "
          f"no heading: {dist.get('0',0)}, "
          f"1 heading (immediate only): {dist.get('1',0)}, "
          f"2+ headings (full ancestry): {dist.get('2+',0)}")
        a("")
        if r.parent_child_example:
            ex = r.parent_child_example
            a(f"Best example — parent heading: `{ex.get('parent_heading', '?')}`  "
              f"({ex.get('child_count', 0)} children)")
            a("")
            for i, child in enumerate(ex.get("children_sample", [])):
                a(f"  Child {i+1}: ancestry = {child.get('full_ancestry', [])}")
                a(f"  Preview: {child.get('text_preview', '')[:120]}")
                a("")
        else:
            a("No multi-level heading groups found — parent-child linkage not demonstrated.")
            a("")
        a("> NOTE: `parent_context` (parent clause body text) is always null in this bridge "
          "prototype. The parent-child verdict grades ancestry metadata only.")
        a("")

        # Bridge
        a("### Bridge Prototype (Phase 14 Schema Shape)")
        a("")
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
        "toc_chunk_count": result.toc_chunk_count,
        "docling_avg_chars": result.docling_avg_chars,
        "docling_chunk_samples": result.docling_chunk_samples,
        "parent_child_groups": result.parent_child_groups,
        "parent_child_example": result.parent_child_example,
        "chunk_heading_dist": result.chunk_heading_dist,
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

def _positive_int(value: str) -> int:
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"--max-pages must be a positive integer, got {ivalue}")
    return ivalue


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
        type=_positive_int,
        default=None,
        help="Limit PDF to first N pages (must be > 0; faster for testing)"
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
