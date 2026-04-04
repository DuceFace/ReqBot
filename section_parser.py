#!/usr/bin/env python3
"""WP-14.1: Docling-based section ancestry parser (Step A, structure-aware path).

Replaces extract_pdf_to_text.py for Phase 14+ ingestion.

Input:  PDF file path
Output: <stem>_ancestry.json  — full heading ancestry map per document item

The ancestry map records full heading path (section_ref_path +
section_title_path + parent_header_text + parent_context) for every document
item, keyed by Docling self_ref.  WP-14.2 (chunk_text.py rewrite) consumes
this map to attach hierarchy metadata to each HybridChunker chunk.

run() also returns the DoclingDocument in-process so WP-14.2 can call
HybridChunker on the same doc object without re-running PDF conversion.

--- Decision C note (parent_context scope) ---
Decision C has not been formally locked.  This implementation uses the
recommended default from PHASE14_REQUIREMENTS.md §5.3:
  parent_context = first significant clause text following the immediate
  parent heading (up to 600 chars), falling back to parent header text.
Update _PARENT_CONTEXT_MAX_CHARS and the body accumulation logic once
Decision C is locked.
"""

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum chars of body text collected per section for parent_context.
# Update this once Decision C is formally locked.
_PARENT_CONTEXT_MAX_CHARS = 600

# Maximum body paragraphs to accumulate per section (prevents collecting
# the full document body for sections with hundreds of children).
_PARENT_CONTEXT_MAX_PARAGRAPHS = 5

# Docling label substrings (lowercased partial match)
_HEADING_LABEL_SUBS = ("section_header",)
_TITLE_LABEL_SUBS = ("title",)
_BODY_LABEL_SUBS = ("text", "paragraph", "list_item", "list-item")

# Section ref derivation: numbered heading prefix
# Examples: "3.1.4 Requirements" → "3.1.4"
#           "A4.2. Annex"        → "A4.2"
#           "ENCLOSURE 3:"       → "ENCLOSURE-3"
_NUMBERED_RE = re.compile(r'^([A-Z]?\d+(\.\d+)*\.?)', re.IGNORECASE)
_KEYWORD_RE  = re.compile(r'^(SECTION|ENCLOSURE|APPENDIX|ANNEX|ATTACHMENT)\s+(\w+)',
                           re.IGNORECASE)

# Heading depth estimation from numbering prefix
# "3.1.4" → 3 dots → depth 3
_DEPTH_RE = re.compile(r'^[A-Z]?\d+(\.\d+)*', re.IGNORECASE)

# Heading text that looks like a ToC entry (dotted leaders or trailing page number).
# These are sometimes labeled section_header by Docling on ToC pages.
_TOC_HEADING_RE = re.compile(r'\.{5,}|\s+\d{1,4}\s*$')


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AncestryResult:
    """Return value from run()."""
    ancestry_path: str                  # written JSON file
    sections: list[dict]                # all detected heading items in doc order
    item_ancestry: dict[str, dict]      # self_ref → ancestry context
    section_bodies: dict[str, str]      # self_ref → body text (for parent_context)
    doc: Any                            # DoclingDocument (for in-process WP-14.2 use)
    heading_count: int = 0
    total_items: int = 0
    parse_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _item_text(item: Any) -> str:
    """Extract text from a Docling item, trying .text first then export_to_text()."""
    try:
        t = item.text
        if t:
            return t
    except AttributeError:
        pass
    try:
        return item.export_to_text() or ""
    except Exception:
        return ""


def _estimate_heading_depth(text: str) -> int:
    """Estimate hierarchy depth from heading text numbering prefix.

    Examples:
      "1. Introduction"         → 1
      "2.1 Policy"              → 2
      "3.1.4 Requirements"      → 3
      "A4.2. Annex"             → 2
      "SECTION 3: ..."          → 1
      "Authority"               → 1 (prose; depth 1 is the shallowest fallback)

    NOTE — text-based vs Docling structural level:
    This uses the numbering prefix to estimate depth rather than the `level`
    parameter from doc.iterate_items().  For numbered headings ("3.1.4") this
    is reliable.  For prose-titled headings, all non-numbered titles return
    depth=1 — this collapses sibling prose labels ("Chapter 1" and "ROLES AND
    RESPONSIBILITIES") to the same depth level, which is correct for documents
    where they are parallel section identifiers rather than true parent/child
    nodes.  A future improvement could use Docling's structural level as the
    primary depth signal (falling back to numbering), but that requires
    validation against all 3 doc classes to avoid regression on numbered docs.
    """
    text = text.strip()
    m = _DEPTH_RE.match(text)
    if m:
        prefix = m.group(0)
        # Count separators: "3.1.4" has 2 dots → depth 3
        return prefix.count('.') + 1
    if _KEYWORD_RE.match(text):
        return 1
    return 1  # prose title — treat as top-level


def _extract_section_ref(heading: str) -> str:
    """Extract canonical section identifier from a heading string.

    Returns a non-empty string for numbered headings, empty string for
    prose-titled sections (per WP-14.1 Req 3 — do not derive slugs).

    Examples:
      "3.1.4 Requirements"         → "3.1.4"
      "A4.2. Annex"                → "A4.2"
      "ENCLOSURE 3: ..."           → "ENCLOSURE-3"
      "Authority"                  → ""
      "COMPLIANCE WITH THIS..."    → ""
    """
    heading = heading.strip()
    m = _NUMBERED_RE.match(heading)
    if m:
        return m.group(1).rstrip('.')
    m2 = _KEYWORD_RE.match(heading)
    if m2:
        return f"{m2.group(1).upper()}-{m2.group(2).upper()}"
    # Prose title — leave empty, do not derive a slug
    return ""


def _is_heading_label(label_str: str) -> bool:
    """Return True if label string indicates a section heading."""
    if any(sub in label_str for sub in _HEADING_LABEL_SUBS):
        return True
    # Title labels that are not sub-titles
    if any(sub in label_str for sub in _TITLE_LABEL_SUBS) and "sub" not in label_str:
        return True
    return False


def _is_body_label(label_str: str) -> bool:
    """Return True if label string indicates prose body content."""
    return any(sub in label_str for sub in _BODY_LABEL_SUBS)


def _is_toc_heading(text: str) -> bool:
    """Return True if a heading text looks like a ToC entry rather than a real heading.

    Docling occasionally labels ToC lines as section_header.  These must be
    excluded from the heading stack and sections list to avoid corrupting
    ancestry for content items that follow them.

    Heuristic: dotted-line leaders (5+ dots) or a bare trailing page number.
    """
    return bool(_TOC_HEADING_RE.search(text.strip()))


def _ancestry_from_stack(stack: list[dict]) -> dict:
    """Compute ancestry fields from the current heading stack.

    Returns a dict with:
      section_ref_path   — canonical IDs (empty strings excluded)
      section_title_path — full heading texts
      parent_header_text — immediate parent heading text
      _parent_self_ref   — internal: self_ref of immediate parent (removed from output)
      parent_context     — filled in by caller after body accumulation
    """
    if not stack:
        return {
            "section_ref_path": [],
            "section_title_path": [],
            "parent_header_text": None,
            "_parent_self_ref": None,
            "parent_context": None,
        }
    ref_path = [h["section_ref"] for h in stack if h["section_ref"]]
    title_path = [h["heading_text"] for h in stack]
    return {
        "section_ref_path": ref_path,
        "section_title_path": title_path,
        "parent_header_text": stack[-1]["heading_text"],
        "_parent_self_ref": stack[-1]["self_ref"],
        "parent_context": None,   # filled in after body accumulation
    }


# ---------------------------------------------------------------------------
# Core ancestry traversal
# ---------------------------------------------------------------------------

def _parse_ancestry(doc: Any) -> tuple[list[dict], dict[str, dict], dict[str, str], int]:
    """Walk doc.iterate_items() to build full heading ancestry.

    Returns:
        sections        — list of section/heading items in document order
        item_ancestry   — {self_ref: ancestry_dict}
        section_bodies  — {self_ref: body_text} for parent_context
        total_items     — total items iterated
    """
    heading_stack: list[dict] = []   # ordered by depth ascending
    sections: list[dict] = []
    item_ancestry: dict[str, dict] = {}
    body_accum: dict[str, list[str]] = {}  # heading self_ref → body paragraphs
    total_items = 0

    try:
        items = list(doc.iterate_items())
    except Exception as e:
        log.error("doc.iterate_items() failed: %s", e)
        return sections, item_ancestry, {}, 0

    for item, _ in items:
        self_ref = getattr(item, "self_ref", None)
        if not self_ref:
            continue

        total_items += 1
        label_str = str(getattr(item, "label", "")).lower()
        text = _item_text(item)

        if _is_heading_label(label_str):
            # Skip ToC entries that Docling may label as section_header.
            # These must not enter the heading stack or sections list.
            if _is_toc_heading(text):
                log.debug("Skipping ToC-like heading: %r", text[:80])
                continue

            depth = _estimate_heading_depth(text)
            section_ref = _extract_section_ref(text)

            if not section_ref:
                log.debug("Prose title (no canonical ref): %r", text[:80])

            # Pop same-or-deeper headings before pushing the new one.
            heading_stack = [h for h in heading_stack if h["depth"] < depth]

            # Record ancestry for this heading BEFORE pushing it onto the stack.
            # The heading's own parent is the current stack top, not itself.
            # (Codex P1: recording after push would make stack[-1] == self → self-referential parent)
            item_ancestry[self_ref] = _ancestry_from_stack(heading_stack)

            # Now push this heading so children below will see it as their parent.
            heading_stack.append({
                "depth": depth,
                "self_ref": self_ref,
                "heading_text": text.strip(),
                "section_ref": section_ref,
            })

            # Compute full paths for the sections list (stack now includes this heading).
            ref_path = [h["section_ref"] for h in heading_stack if h["section_ref"]]
            title_path = [h["heading_text"] for h in heading_stack]

            sections.append({
                "self_ref": self_ref,
                "heading_text": text.strip(),
                "depth": depth,
                "section_ref": section_ref,
                "section_ref_path": ref_path,
                "section_title_path": title_path,
                "body_preview": "",   # filled after accumulation
            })
            body_accum[self_ref] = []

        else:
            # Non-heading items: ancestry from current stack (heading above is the parent).
            item_ancestry[self_ref] = _ancestry_from_stack(heading_stack)

            # Accumulate body text for the immediate parent heading.
            if _is_body_label(label_str) and heading_stack and text.strip():
                parent_ref = heading_stack[-1]["self_ref"]
                if parent_ref not in body_accum:
                    body_accum[parent_ref] = []
                if len(body_accum[parent_ref]) < _PARENT_CONTEXT_MAX_PARAGRAPHS:
                    body_accum[parent_ref].append(text.strip())

    # Finalize section_bodies: join and truncate
    section_bodies: dict[str, str] = {
        ref: " ".join(texts)[:_PARENT_CONTEXT_MAX_CHARS]
        for ref, texts in body_accum.items()
        if texts
    }

    # Back-fill body_preview into section entries
    for section in sections:
        section["body_preview"] = section_bodies.get(section["self_ref"], "")

    # Back-fill parent_context into item_ancestry
    fallback_count = 0
    for self_ref, ancestry in item_ancestry.items():
        parent_self_ref = ancestry.pop("_parent_self_ref", None)
        if parent_self_ref:
            body = section_bodies.get(parent_self_ref, "")
            if body:
                ancestry["parent_context"] = body
            else:
                # Fallback: use parent header text
                ancestry["parent_context"] = ancestry.get("parent_header_text")
                fallback_count += 1
        else:
            ancestry["parent_context"] = None

    if fallback_count:
        log.warning(
            "parent_context: %d items fell back to header text (no body available). "
            "Lock Decision C to refine scope.",
            fallback_count,
        )

    return sections, item_ancestry, section_bodies, total_items


# ---------------------------------------------------------------------------
# Docling conversion
# ---------------------------------------------------------------------------

def _run_docling(pdf_path: Path, max_pages: Optional[int]) -> tuple[Any, float]:
    """Run DocumentConverter and return (DoclingDocument, elapsed_seconds).

    Raises RuntimeError on failure.
    """
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        raise RuntimeError(
            f"Docling is not installed. Run: "
            f"pip3 install --break-system-packages docling"
        ) from e

    converter = DocumentConverter()
    convert_kwargs: dict = {}
    if max_pages:
        # page_range=(1, N) limits which pages are processed.
        # max_num_pages is a rejection gate, NOT a page limit — do not use it.
        convert_kwargs["page_range"] = (1, max_pages)

    log.info("Running Docling on: %s%s", pdf_path,
             f" (pages 1–{max_pages})" if max_pages else "")
    t0 = time.time()
    try:
        result = converter.convert(str(pdf_path), **convert_kwargs)
    except Exception as e:
        raise RuntimeError(f"Docling conversion failed: {e}") from e
    elapsed = round(time.time() - t0, 1)
    log.info("Docling conversion complete in %.1fs", elapsed)
    return result.document, elapsed


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(
    pdf_path: str,
    output_dir: str,
    *,
    max_pages: Optional[int] = None,
) -> AncestryResult:
    """Parse a PDF with Docling and write a section ancestry map.

    Args:
        pdf_path:   Path to the input PDF.
        output_dir: Directory to write <stem>_ancestry.json.
        max_pages:  If set, limit conversion to pages 1–N (for testing).

    Returns:
        AncestryResult with the ancestry map and the live DoclingDocument.

    Raises:
        RuntimeError if Docling conversion fails.
    """
    pdf = Path(pdf_path).resolve()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = AncestryResult(
        ancestry_path="",
        sections=[],
        item_ancestry={},
        section_bodies={},
        doc=None,
    )

    # --- Step 1: Docling conversion ---
    doc, parse_seconds = _run_docling(pdf, max_pages)
    result.doc = doc
    result.parse_seconds = parse_seconds

    # --- Step 2: Ancestry traversal ---
    log.info("Building section ancestry map…")
    t1 = time.time()
    try:
        sections, item_ancestry, section_bodies, total_items = _parse_ancestry(doc)
    except Exception as e:
        # Graceful degradation: emit empty ancestry, preserve the doc object
        log.error("Ancestry traversal failed (%s) — emitting empty ancestry", e)
        result.warnings.append(f"ancestry_traversal_failed: {e}")
        sections, item_ancestry, section_bodies, total_items = [], {}, {}, 0

    ancestry_elapsed = round(time.time() - t1, 2)

    result.sections = sections
    result.item_ancestry = item_ancestry
    result.section_bodies = section_bodies
    result.heading_count = len(sections)
    result.total_items = total_items

    # --- Step 3: Log summary ---
    log.info(
        "Ancestry: %d items, %d headings, %d with body text (%.2fs)",
        total_items, len(sections), len(section_bodies), ancestry_elapsed,
    )

    # Warn if no headings found
    if not sections:
        msg = "No headings detected — ancestry map is empty. Check document class."
        log.warning(msg)
        result.warnings.append(msg)

    # Count prose-only headings (no canonical ref)
    prose_count = sum(1 for s in sections if not s["section_ref"])
    if prose_count:
        log.info(
            "Prose-titled headings (no canonical ref): %d/%d — section_ref_path left empty",
            prose_count, len(sections),
        )

    # --- Step 4: Write ancestry artifact ---
    stem = pdf.stem
    ancestry_path = out_dir / f"{stem}_ancestry.json"

    payload = {
        "source_pdf": pdf.name,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "parse_seconds": parse_seconds,
        "ancestry_seconds": ancestry_elapsed,
        "total_items": total_items,
        "heading_count": len(sections),
        "prose_heading_count": prose_count,
        "warnings": result.warnings,
        "sections": sections,
        "item_ancestry": item_ancestry,
    }

    with open(ancestry_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log.info("Wrote ancestry map: %s (%d bytes)", ancestry_path, ancestry_path.stat().st_size)
    result.ancestry_path = str(ancestry_path)
    return result


# ---------------------------------------------------------------------------
# Validation helper (CLI --validate mode)
# ---------------------------------------------------------------------------

def _validate_result(result: AncestryResult, stem: str) -> None:
    """Print a human-readable validation summary for the WP-14.1 gate."""
    sections = result.sections
    item_ancestry = result.item_ancestry

    numbered = [s for s in sections if s["section_ref"]]
    prose    = [s for s in sections if not s["section_ref"]]
    max_depth = max((s["depth"] for s in sections), default=0)

    # Check: do numbered sections have non-empty section_ref_path?
    numbered_with_ref = [s for s in numbered if s["section_ref_path"]]
    numbered_missing  = [s for s in numbered if not s["section_ref_path"]]

    # Check: items with 2+ levels in section_title_path (proves ancestry, not just immediate).
    # Uses section_title_path (not section_ref_path) because prose-titled parents like
    # "Chapter 1" contribute to title depth but produce no canonical ref entry.
    deep_items = [v for v in item_ancestry.values() if len(v["section_title_path"]) >= 2]

    # Check: items with parent_context populated
    with_context = [v for v in item_ancestry.values() if v.get("parent_context")]

    print(f"\n{'='*60}")
    print(f"WP-14.1 Validation: {stem}")
    print(f"{'='*60}")
    print(f"  Total items:          {result.total_items}")
    print(f"  Headings detected:    {len(sections)}")
    print(f"    numbered:           {len(numbered)}")
    print(f"    prose (no ref):     {len(prose)}")
    print(f"  Max heading depth:    {max_depth}")
    print(f"  Items with depth>=2:  {len(deep_items)}  (proves full ancestry via section_title_path)")
    print(f"  Items with parent_context: {len(with_context)}")

    print(f"\n  Gate checks:")

    # Gate 1: hierarchy depth matches expected structure
    gate1 = max_depth >= 2
    print(f"    [{'PASS' if gate1 else 'FAIL'}] heading_depth >= 2: max={max_depth}")

    # Gate 2: numbered sections produce non-empty section_ref_path
    gate2 = len(numbered_missing) == 0 and len(numbered) > 0
    print(f"    [{'PASS' if gate2 else 'WARN'}] numbered sections have section_ref_path: "
          f"{len(numbered_with_ref)}/{len(numbered)}")
    if numbered_missing:
        for s in numbered_missing[:3]:
            print(f"      MISSING: {s['heading_text']!r}")

    # Gate 3: full ancestry (depth >= 2) exists for at least some items (via section_title_path)
    gate3 = len(deep_items) > 0
    print(f"    [{'PASS' if gate3 else 'FAIL'}] items with 2+ title ancestors: {len(deep_items)}")

    # Gate 4: failure mode — prose titles have empty section_ref_path
    prose_with_bad_ref = [s for s in prose if s["section_ref_path"]]
    gate4 = len(prose_with_bad_ref) == 0
    print(f"    [{'PASS' if gate4 else 'FAIL'}] prose titles have empty section_ref_path "
          f"(no slug leakage): {len(prose_with_bad_ref)} violations")

    # Gate 5 (advisory — does NOT affect Overall): parent_context populated.
    # Decision C has not been formally locked; gate 5 cannot be a hard gate until
    # the parent_context scope definition is finalised.
    items_with_parent = [v for v in item_ancestry.values() if v.get("parent_header_text")]
    items_parent_ctx  = [v for v in items_with_parent if v.get("parent_context")]
    gate5_pct = round(100 * len(items_parent_ctx) / len(items_with_parent), 0) if items_with_parent else 0
    gate5 = gate5_pct >= 50
    print(f"    [{'PASS' if gate5 else 'WARN'}] (advisory) parent_context coverage: "
          f"{len(items_parent_ctx)}/{len(items_with_parent)} ({gate5_pct:.0f}%)")

    # Overall = gates 1–4 only; gate 5 is advisory until Decision C is locked
    overall = gate1 and gate2 and gate3 and gate4
    print(f"\n  Overall: {'PASS' if overall else 'FAIL'} (gates 1–4; gate 5 advisory)")

    # Sample headings
    print(f"\n  Heading samples (first 10):")
    for s in sections[:10]:
        indent = "  " * (s["depth"] - 1)
        ref_str = f"[{s['section_ref']}]" if s["section_ref"] else "[prose]"
        print(f"    {indent}{ref_str} {s['heading_text'][:70]}")

    # Sample deep ancestry
    if deep_items:
        print(f"\n  Deep ancestry sample:")
        ex = deep_items[0]
        print(f"    section_ref_path:   {ex['section_ref_path']}")
        print(f"    section_title_path: {[t[:50] for t in ex['section_title_path']]}")
        if ex.get("parent_context"):
            print(f"    parent_context:     {ex['parent_context'][:120]!r}…")

    if result.warnings:
        print(f"\n  Warnings:")
        for w in result.warnings:
            print(f"    - {w}")


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _positive_int(value: str) -> int:
    """argparse type validator: accept only positive integers."""
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(
            f"--max-pages must be a positive integer, got {ivalue}"
        )
    return ivalue


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="WP-14.1: Parse PDF with Docling and build section ancestry map"
    )
    parser.add_argument("pdf_path", type=str, help="Path to the input PDF")
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory (default: same directory as PDF)",
    )
    parser.add_argument(
        "--max-pages", type=_positive_int, default=None,
        help="Limit conversion to first N pages (testing only; must be > 0)",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Print WP-14.1 validation gate summary after parsing",
    )
    args = parser.parse_args()

    pdf = Path(args.pdf_path).resolve()
    if not pdf.exists():
        log.error("PDF not found: %s", pdf)
        sys.exit(1)

    out_dir = Path(args.output_dir).resolve() if args.output_dir else pdf.parent

    try:
        result = run(str(pdf), str(out_dir), max_pages=args.max_pages)
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(1)

    if args.validate:
        _validate_result(result, pdf.stem)


if __name__ == "__main__":
    main()
