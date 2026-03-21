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
    model: str = "llama3.1:8b-instruct-q4_K_M",
    ollama_url: str = "http://192.168.90.100:11434",
    chunk_size: int = 3000,
    overlap: int = 200,
    max_chunks: int | None = None,
    timeout: int = 120,
    skip_to: str = "A",
    layout_mode: str = "pymupdf",
) -> str:
    """Run the full extraction pipeline (Steps A-E) in-process.

    Callable interface for in-process use by reqbot.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        pdf_path:    Path to the input PDF file.
        output_dir:  Directory to write all artifacts into.
        model:       Ollama model name for Step C.
        ollama_url:  Ollama API base URL.
        chunk_size:  Target chunk size in characters.
        overlap:     Overlap characters between chunks.
        max_chunks:  Limit LLM processing to first N chunks.
        timeout:     Per-request LLM timeout in seconds.
        skip_to:     Skip to step ('A'-'E'). Requires prior artifacts.
        layout_mode: PDF extraction backend ('pymupdf' or 'pdfplumber').

    Returns:
        Path to the requirements_normalized.jsonl file (str).

    Raises:
        RuntimeError: If any pipeline step fails.
    """
    import extract_pdf_to_text
    import chunk_text as chunk_text_mod
    import llm_extract_requirements
    import parse_and_normalize
    import aggregate_and_export

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
            )
        except Exception as e:
            raise RuntimeError(f"Step B failed: {e}") from e

    if "C" in steps_to_run:
        log.info("=" * 60)
        log.info("Starting Step C (LLM Extraction)")
        log.info("=" * 60)
        try:
            llm_extract_requirements.run(
                str(chunks_path), str(out_dir),
                model=model, ollama_url=ollama_url,
                timeout=timeout, max_chunks=max_chunks,
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
            )
        except Exception as e:
            raise RuntimeError(f"Step D failed: {e}") from e

    if "E" in steps_to_run:
        log.info("=" * 60)
        log.info("Starting Step E (Aggregate)")
        log.info("=" * 60)
        try:
            aggregate_and_export.run(str(norm_path), str(out_dir), source_pdf=pdf.name)
        except Exception as e:
            raise RuntimeError(f"Step E failed: {e}") from e

    total_elapsed = time.time() - pipeline_start
    log.info("=" * 60)
    log.info("Pipeline complete in %.1fs", total_elapsed)
    log.info("Artifacts in: %s", out_dir)
    log.info("=" * 60)

    return str(norm_path)


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
        "--model",
        type=str,
        default="llama3.1:8b-instruct-q4_K_M",
        help="Ollama model name (default: llama3.1:8b-instruct-q4_K_M)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://192.168.90.100:11434",
        help="Ollama API base URL",
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
        choices=["pymupdf", "pdfplumber"],
        default="pymupdf",
        help="PDF extraction backend for Step A (default: pymupdf). Use 'pdfplumber' for table-aware extraction.",
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

    try:
        norm_path = run(
            str(pdf_path),
            str(out_dir),
            model=args.model,
            ollama_url=args.ollama_url,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
            max_chunks=args.max_chunks,
            timeout=args.timeout,
            skip_to=args.skip_to,
            layout_mode=args.layout_mode,
        )
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(1)

    # Step F: Embed and index into Qdrant (optional)
    if args.index:
        import embed_and_index as _embed
        try:
            _embed.run(norm_path)
        except Exception as e:
            log.warning("Qdrant indexing failed (%s) — pipeline artifacts are still available", e)


if __name__ == "__main__":
    main()
