#!/usr/bin/env python3
"""Orchestrator: Run the full GRC requirements extraction pipeline (Steps A-E).

Usage:
    python run_pipeline.py <pdf_path> [options]

This script calls each step in sequence, passing artifacts between them.
All intermediate artifacts are stored in a timestamped output directory.
Individual steps can also be run standalone for debugging or reruns.
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure repo root is on sys.path when run as a standalone script from pipeline/.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent



def run(
    pdf_path: str,
    output_dir: str,
    *,
    extraction_model: str = "llama3.1:8b-instruct-q4_K_M",
    enrichment_model: str = "llama3.1:8b-instruct-q4_K_M",
    ollama_url: str = "http://localhost:11434",
    chunk_size: int = 3000,
    overlap: int = 200,
    max_chunks: int | None = None,
    timeout: int = 120,
    skip_to: str = "A",
    layout_mode: str = "pymupdf",
    pass1_only: bool = True,
    skip_enrichment: bool = False,
    profile_name: str = "cybersecurity",
) -> str:
    """Run the full extraction pipeline (Steps A-E + optional enrichment) in-process.

    Callable interface for in-process use by reqbot.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        pdf_path:          Path to the input PDF file.
        output_dir:        Directory to write all artifacts into.
        extraction_model:  Ollama model for Step C (LLM extraction). (R-2.2)
        enrichment_model:  Ollama model for Step D.5 (enrichment). (R-2.2)
        ollama_url:        Ollama API base URL.
        chunk_size:        Target chunk size in characters.
        overlap:           Overlap characters between chunks.
        max_chunks:        Limit LLM processing to first N chunks.
        timeout:           Per-request LLM timeout in seconds.
        skip_to:           Skip to step ('A'-'E'). Requires prior artifacts.
        layout_mode:       PDF extraction backend ('pymupdf' or 'pdfplumber').
        pass1_only:        Use Pass 1 prompt in Step C (source_quote + source_ref only).
                           Default True — enrichment (Step D.5) fills in description/tags/type.
        skip_enrichment:   Skip Step D.5 enrichment. Returns normalized JSONL path directly.
        profile_name:      Domain profile name to load from profiles/<name>.json.
                           Default 'cybersecurity'. Profile is loaded once and passed to
                           Steps C and D.5.

    Returns:
        Path to requirements_enriched.jsonl if enrichment ran, else
        requirements_normalized.jsonl (str).

    Raises:
        RuntimeError: If any pipeline step fails.
    """
    from core.profiles import load_profile as _load_profile
    try:
        profile = _load_profile(profile_name)
    except (FileNotFoundError, ValueError) as e:
        raise RuntimeError(f"Failed to load profile '{profile_name}': {e}") from e

    from pipeline import extract_pdf_to_text
    from pipeline import chunk_text as chunk_text_mod
    from pipeline import llm_extract_requirements
    from pipeline import parse_and_normalize
    from pipeline import aggregate_and_export

    pdf = Path(pdf_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info("Output directory: %s", out_dir)

    stem = pdf.stem
    steps_to_run = "ABCDE"
    if skip_to != "A":
        skip_idx = steps_to_run.index(skip_to)
        steps_to_run = steps_to_run[skip_idx:]
        log.info("Skipping to Step %s", skip_to)

    pages_path = out_dir / f"{stem}_pages.jsonl"
    chunks_path = out_dir / f"{stem}_chunks.jsonl"
    reqs_path = out_dir / f"{stem}_extracted_requirements.jsonl"
    norm_path = out_dir / f"{stem}_requirements_normalized.jsonl"

    pipeline_start = time.time()

    # Steps A and B: PDF → chunks.  Two paths depending on layout_mode.
    #
    # Docling path (layout_mode="docling"):
    #   Step A = section_parser.run() → DoclingDocument + *_ancestry.json
    #   Step B = chunk_text.run_structure_aware() → enriched *_chunks.jsonl
    #   The ancestry_result is passed in-process so HybridChunker reuses the
    #   already-parsed DoclingDocument without a second PDF conversion.
    #
    # Legacy path (layout_mode="pymupdf" or "pdfplumber"):
    #   Step A = extract_pdf_to_text.run() → *_pages.jsonl
    #   Step B = chunk_text.run()          → *_chunks.jsonl (fixed-size)

    ancestry_result = None  # populated by Step A in docling mode; used in Step B

    if layout_mode == "docling":
        if "A" in steps_to_run:
            log.info("=" * 60)
            log.info("Starting Step A (PDF → Docling ancestry map)")
            log.info("=" * 60)
            try:
                from pipeline import section_parser as _section_parser
                ancestry_result = _section_parser.run(str(pdf), str(out_dir))
            except Exception as e:
                raise RuntimeError(f"Step A (Docling) failed: {e}") from e

        if "B" in steps_to_run:
            log.info("=" * 60)
            log.info("Starting Step B (Docling HybridChunker + breadcrumb injection)")
            log.info("=" * 60)
            # If --skip-to B in docling mode, Step A was skipped so we need the ancestry
            if ancestry_result is None:
                log.info("Step A was skipped — running section_parser to obtain DoclingDocument")
                try:
                    from pipeline import section_parser as _section_parser
                    ancestry_result = _section_parser.run(str(pdf), str(out_dir))
                except Exception as e:
                    raise RuntimeError(f"Step A (Docling, skip-to-B recovery) failed: {e}") from e
            try:
                chunk_text_mod.run_structure_aware(
                    str(chunks_path),
                    ancestry_result=ancestry_result,
                    skip_sections=profile.get("skip_sections", []),
                )
            except Exception as e:
                raise RuntimeError(f"Step B (Docling) failed: {e}") from e

    else:
        # Legacy path
        if "A" in steps_to_run:
            log.info("=" * 60)
            log.info("Starting Step A (PDF → Text)")
            log.info("=" * 60)
            try:
                extract_pdf_to_text.run(str(pdf), str(pages_path), layout_mode=layout_mode)
            except Exception as e:
                raise RuntimeError(f"Step A failed: {e}") from e

        if "B" in steps_to_run:
            log.info("=" * 60)
            log.info("Starting Step B (Text → Chunks)")
            log.info("=" * 60)
            try:
                chunk_text_mod.run(
                    str(pages_path), str(chunks_path),
                    chunk_size=chunk_size, overlap=overlap,
                    table_aware=(layout_mode == "pdfplumber"),
                    skip_sections=profile.get("skip_sections", []),
                )
            except Exception as e:
                raise RuntimeError(f"Step B failed: {e}") from e

    if "C" in steps_to_run:
        log.info("=" * 60)
        log.info("Starting Step C (LLM Extraction%s)", " — Pass 1 mode" if pass1_only else "")
        log.info("Step C — extraction model: %s", extraction_model)
        log.info("=" * 60)
        try:
            llm_extract_requirements.run(
                str(chunks_path), str(out_dir),
                model=extraction_model, ollama_url=ollama_url,
                timeout=timeout, max_chunks=max_chunks,
                pass1_only=pass1_only,
                profile=profile,
            )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Step C failed: {e}") from e

    if "D" in steps_to_run:
        log.info("=" * 60)
        log.info("Starting Step D (Normalize)")
        log.info("=" * 60)
        try:
            parse_and_normalize.run(
                str(reqs_path), str(chunks_path), str(pdf), str(out_dir),
                profile=profile,
            )
        except Exception as e:
            raise RuntimeError(f"Step D failed: {e}") from e

    # Step D.5: Enrich requirements with description, domain_tags, requirement_type.
    # Only runs when Step D ran in this invocation (ensures fresh norm_path exists
    # and prevents unexpected LLM work when skip_to skips past D, e.g. --skip-to E).
    # Skipped if --skip-enrichment is set.
    # If enrichment fails, the pipeline continues with the normalized JSONL.
    index_path = norm_path
    if "D" in steps_to_run and not skip_enrichment:
        log.info("=" * 60)
        log.info("Starting Step D.5 (Enrich — Pass 2)")
        log.info("Step D.5 — enrichment model: %s", enrichment_model)
        log.info("=" * 60)
        try:
            from pipeline import enrich_requirements as _enrich_mod
            enrich_result = _enrich_mod.run(
                str(norm_path), str(out_dir),
                model=enrichment_model, ollama_url=ollama_url, timeout=timeout,
                profile=profile,
            )
            index_path = Path(enrich_result)
        except Exception as e:
            log.warning(
                "Step D.5 enrichment failed (%s) — proceeding with normalized JSONL for indexing",
                e,
            )
    elif skip_enrichment:
        log.info("Step D.5 skipped (--skip-enrichment)")
    else:
        log.info("Step D.5 skipped (Step D did not run in this invocation)")

    if "E" in steps_to_run:
        log.info("=" * 60)
        log.info("Starting Step E (Aggregate)")
        log.info("=" * 60)
        try:
            aggregate_and_export.run(str(index_path), str(out_dir), source_pdf=pdf.name)
        except Exception as e:
            raise RuntimeError(f"Step E failed: {e}") from e

    total_elapsed = time.time() - pipeline_start
    log.info("=" * 60)
    log.info("Pipeline complete in %.1fs", total_elapsed)
    log.info("Artifacts in: %s", out_dir)
    log.info("=" * 60)

    return str(index_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full GRC requirements extraction pipeline"
    )
    parser.add_argument("pdf_path", type=str, help="Path to the input PDF file")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for all artifacts. Default: documents/processed/<pdf_stem>_<timestamp>/",
    )
    parser.add_argument(
        "--extraction-model",
        type=str,
        default="llama3.1:8b-instruct-q4_K_M",
        dest="extraction_model",
        help="Ollama model for Step C extraction (default: llama3.1:8b-instruct-q4_K_M)",
    )
    parser.add_argument(
        "--enrichment-model",
        type=str,
        default="llama3.1:8b-instruct-q4_K_M",
        dest="enrichment_model",
        help="Ollama model for Step D.5 enrichment (default: llama3.1:8b-instruct-q4_K_M)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Convenience alias: sets both --extraction-model and --enrichment-model",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama API base URL",
    )
    parser.add_argument(
        "--qdrant-url",
        type=str,
        default="http://localhost:6333",
        help="Qdrant API base URL (used with --index; default: http://localhost:6333)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=3000,
        help="Chunk size in characters (default: 3000)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=200,
        help="Chunk overlap in characters (default: 200)",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help="Limit LLM processing to first N chunks (for testing)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Per-request LLM timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--skip-to",
        type=str,
        choices=["A", "B", "C", "D", "E"],
        default="A",
        help="Skip to a specific step (requires prior artifacts in output-dir)",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="After pipeline completes, embed and index requirements into Qdrant",
    )
    parser.add_argument(
        "--layout-mode",
        choices=["pymupdf", "pdfplumber", "docling"],
        default="pymupdf",
        help="PDF extraction backend for Step A (default: pymupdf). "
             "Use 'pdfplumber' for table-aware extraction. "
             "Use 'docling' for structure-aware chunking (WP-14.2 path).",
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        dest="skip_enrichment",
        help="Skip Step D.5 enrichment (Pass 2). Index normalized JSONL directly without adding description/tags/type.",
    )
    parser.add_argument(
        "--full-extraction",
        action="store_true",
        dest="full_extraction",
        help="Use legacy single-pass Step C prompt (description+tags+type in one LLM call). "
             "Default is Pass 1 mode (source_quote+source_ref only, enriched separately).",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).resolve()
    if not pdf_path.exists():
        log.error("PDF file not found: %s", pdf_path)
        sys.exit(1)

    if args.output_dir:
        out_dir = Path(args.output_dir).resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = SCRIPTS_DIR.parent / "documents" / "processed" / f"{pdf_path.stem}_{timestamp}"

    # --model is a convenience alias; individual flags take precedence when --model not given
    if args.model:
        extraction_model = args.model
        enrichment_model = args.model
    else:
        extraction_model = args.extraction_model
        enrichment_model = args.enrichment_model

    try:
        index_path = run(
            str(pdf_path),
            str(out_dir),
            extraction_model=extraction_model,
            enrichment_model=enrichment_model,
            ollama_url=args.ollama_url,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
            max_chunks=args.max_chunks,
            timeout=args.timeout,
            skip_to=args.skip_to,
            layout_mode=args.layout_mode,
            pass1_only=not args.full_extraction,
            skip_enrichment=args.skip_enrichment,
        )
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(1)

    # Step F: Embed and index into Qdrant (optional)
    if args.index:
        import json as _json
        from pipeline import embed_and_index as _embed
        from pipeline import embed_context_index as _embed_ctx

        try:
            _embed.run(index_path, ollama_url=args.ollama_url, qdrant_url=args.qdrant_url)
        except Exception as e:
            log.warning("Qdrant indexing failed (%s) — pipeline artifacts are still available", e)

        # Also index raw chunks into grc_context.
        # Use the PDF-hash document_id from the indexed JSONL so that
        # ask --context can resolve chunks by the same ID as requirements payloads.
        out_dir_path = Path(index_path).parent
        chunk_files = list(out_dir_path.glob("*_chunks.jsonl"))
        if chunk_files:
            norm_doc_id: str | None = None
            try:
                with open(index_path) as _nf:
                    first_line = _nf.readline()
                if first_line:
                    norm_doc_id = _json.loads(first_line).get("document_id")
            except Exception as e:
                log.warning("Could not read document_id from %s: %s — context chunks will use filename-derived ID", index_path, e)

            try:
                _embed_ctx.run(
                    str(chunk_files[0]),
                    document_id=norm_doc_id,
                    ollama_url=args.ollama_url,
                    qdrant_url=args.qdrant_url,
                )
            except Exception as e:
                log.warning("Context indexing failed (%s) — requirements index is still available", e)
        else:
            log.warning("No chunks.jsonl found in %s — skipping context index", out_dir_path)


if __name__ == "__main__":
    main()
