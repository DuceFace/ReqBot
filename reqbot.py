#!/usr/bin/env python3
"""ReqBot — Single CLI entrypoint for the requirements extraction pipeline.

Subcommands:
    reqbot ingest <pdf>     Run the full extraction pipeline on a PDF
    reqbot index <jsonl>    Embed and index requirements into Qdrant
    reqbot ask "question"   Query requirements via vector search
    reqbot status           Show system status (Qdrant, Ollama, docs)
"""

__version__ = "0.1.0"
__build_date__ = "dev"
try:
    from _build_info import __version__, __build_date__  # type: ignore[import,assignment]
except ImportError:
    pass

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime as _dt
from pathlib import Path

import requests

import config as _config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

_cfg = _config.load()


def cmd_ingest(args: argparse.Namespace) -> int:
    """Run the full extraction pipeline on a PDF."""
    import run_pipeline as _run_pipeline
    import embed_and_index as _embed
    import embed_context_index as _embed_ctx

    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        log.error("PDF not found: %s", pdf_path)
        return 1

    if args.output_dir:
        out_dir = Path(args.output_dir).resolve()
    else:
        timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        out_dir = _cfg.processed_dir_path() / f"{pdf_path.stem}_{timestamp}"

    try:
        index_path = _run_pipeline.run(
            str(pdf_path),
            str(out_dir),
            ollama_url=args.ollama_url,
            model=args.model or "llama3.1:8b-instruct-q4_K_M",
            max_chunks=args.max_chunks,
            layout_mode=args.layout_mode,
            skip_enrichment=args.skip_enrichment,
        )
    except RuntimeError as e:
        log.error("%s", e)
        return 1

    if not args.index:
        return 0

    # Optionally chain indexing (uses enriched JSONL if enrichment ran, else normalized)
    try:
        _embed.run(index_path, qdrant_url=args.qdrant_url, ollama_url=args.ollama_url)
    except Exception as e:
        log.error("Index into Qdrant failed: %s", e)
        return 1

    # Also index raw chunks into grc_context for dual-retrieval.
    # Pass the PDF-hash document_id from the indexed JSONL so that
    # ask.py can resolve context chunks by the same ID used in requirements payloads.
    out_dir_path = Path(index_path).parent
    chunk_files = list(out_dir_path.glob("*_chunks.jsonl"))
    if chunk_files:
        # Extract the PDF-hash document_id written by parse_and_normalize
        norm_doc_id: str | None = None
        try:
            with open(index_path) as _nf:
                first_line = _nf.readline()
            if first_line:
                norm_doc_id = json.loads(first_line).get("document_id")
        except Exception as e:
            log.warning("Could not read document_id from %s: %s — context chunks will use filename-derived ID", index_path, e)

        try:
            _embed_ctx.run(
                str(chunk_files[0]),
                document_id=norm_doc_id,
                qdrant_url=args.qdrant_url,
                ollama_url=args.ollama_url,
            )
        except Exception as e:
            log.error("Index context into Qdrant failed: %s", e)
            return 1
    else:
        log.warning("No chunks.jsonl found in %s — skipping context index", out_dir_path)

    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Embed and index requirements into Qdrant."""
    import embed_and_index as _embed
    try:
        _embed.run(
            args.jsonl,
            qdrant_url=args.qdrant_url,
            ollama_url=args.ollama_url,
            recreate=args.recreate,
            batch_size=args.batch_size or 32,
        )
        return 0
    except Exception as e:
        log.error("Embed and index failed: %s", e)
        return 1


def cmd_ask(args: argparse.Namespace) -> int:
    """Query requirements via vector search."""
    import ask as _ask
    try:
        _ask.run(
            args.question,
            top_k=args.top_k,
            min_score=args.min_score,
            synthesize=args.synthesize,
            model=args.model or _ask.DEFAULT_SYNTHESIS_MODEL,
            domain_tags=args.domain_tags,
            requirement_types=args.requirement_types,
            document_ids=args.document_ids,
            no_rewrite=args.no_rewrite,
            rewrite_model=args.rewrite_model,
            qdrant_url=args.qdrant_url,
            ollama_url=args.ollama_url,
            json_output=args.json_output,
            context=args.context,
            context_collection=args.context_collection,
        )
        return 0
    except Exception as e:
        log.error("Query failed: %s", e)
        return 1


def cmd_index_context(args: argparse.Namespace) -> int:
    """Embed and index raw chunks into the grc_context collection."""
    import embed_context_index as _embed_ctx
    try:
        _embed_ctx.run(
            args.chunks_jsonl,
            document_id=args.document_id or None,
            source_pdf=args.source_pdf or "",
            qdrant_url=args.qdrant_url,
            ollama_url=args.ollama_url,
            recreate=args.recreate,
            batch_size=args.batch_size or 32,
        )
        return 0
    except Exception as e:
        log.error("Embed and index context failed: %s", e)
        return 1


def cmd_batch(args: argparse.Namespace) -> int:
    """Run the full pipeline on every PDF in a directory."""
    import run_pipeline as _run_pipeline
    import embed_and_index as _embed
    import embed_context_index as _embed_ctx
    pdf_dir = Path(args.pdf_dir).resolve()
    if not pdf_dir.is_dir():
        log.error("Not a directory: %s", pdf_dir)
        return 1

    pdfs = sorted(pdf_dir.glob("*.pdf")) + sorted(pdf_dir.glob("*.PDF"))
    if not pdfs:
        log.error("No PDF files found in: %s", pdf_dir)
        return 1

    log.info("Found %d PDF(s) to process in %s", len(pdfs), pdf_dir)

    succeeded = []
    failed = []

    for i, pdf_path in enumerate(pdfs, 1):
        log.info("=" * 60)
        log.info("[%d/%d] Processing: %s", i, len(pdfs), pdf_path.name)
        log.info("=" * 60)

        timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        out_dir = _cfg.processed_dir_path() / f"{pdf_path.stem}_{timestamp}"

        try:
            index_path = _run_pipeline.run(
                str(pdf_path),
                str(out_dir),
                ollama_url=args.ollama_url,
                model=args.model or "llama3.1:8b-instruct-q4_K_M",
                layout_mode=args.layout_mode,
                skip_enrichment=args.skip_enrichment,
            )
        except RuntimeError as e:
            log.error("Pipeline FAILED for %s: %s", pdf_path.name, e)
            failed.append(pdf_path.name)
            continue

        try:
            _embed.run(index_path, qdrant_url=args.qdrant_url, ollama_url=args.ollama_url)
        except Exception as e:
            log.warning("Indexing failed for %s: %s — pipeline artifacts still saved", pdf_path.name, e)
            failed.append(pdf_path.name)
            continue

        # Also index raw chunks into grc_context for dual-retrieval.
        # Pass the PDF-hash document_id so ask.py can resolve context chunks
        # by the same ID stored in requirements payloads.
        chunk_files = list(out_dir.glob("*_chunks.jsonl"))
        if chunk_files:
            batch_doc_id: str | None = None
            try:
                with open(index_path) as _nf:
                    first_line = _nf.readline()
                if first_line:
                    batch_doc_id = json.loads(first_line).get("document_id")
            except Exception as e:
                log.warning("Could not read document_id from %s: %s — context chunks will use filename-derived ID", index_path, e)

            try:
                _embed_ctx.run(
                    str(chunk_files[0]),
                    document_id=batch_doc_id,
                    qdrant_url=args.qdrant_url,
                    ollama_url=args.ollama_url,
                )
            except Exception as e:
                log.warning("Context indexing failed for %s: %s — requirements still indexed", pdf_path.name, e)
        else:
            log.warning("No chunks.jsonl found for %s — skipping context index", pdf_path.name)

        succeeded.append(pdf_path.name)

    # Summary
    log.info("=" * 60)
    log.info("BATCH COMPLETE: %d succeeded, %d failed", len(succeeded), len(failed))
    for name in succeeded:
        log.info("  OK:   %s", name)
    for name in failed:
        log.error("  FAIL: %s", name)
    log.info("=" * 60)

    return 0 if not failed else 1


def cmd_reindex(args: argparse.Namespace) -> int:
    """Rebuild the Qdrant collection from all existing normalized JSONL files.

    Uses an atomic alias swap so the live collection is never touched until
    all indexing succeeds:
      1. Index everything into a temp collection (grc_requirements_<timestamp>)
      2. On full success: swap the 'grc_requirements' alias to the new collection
         and delete the old one.
      3. On any failure: delete the temp collection, leave live index untouched.

    No LLM re-extraction needed — JSONL is the system of record.
    """
    import time as _time
    import embed_and_index as _embed
    from qdrant_client import QdrantClient as _QC
    from qdrant_client.models import (
        CreateAliasOperation, CreateAlias,
        DeleteAliasOperation, DeleteAlias,
    )

    LIVE_ALIAS = "grc_requirements"

    processed_dir = _cfg.processed_dir_path()
    if not processed_dir.exists():
        log.error("Processed documents directory not found: %s", processed_dir)
        return 1

    import re as _re
    all_norm_files = sorted(processed_dir.rglob("*_requirements_normalized.jsonl"))
    if not all_norm_files:
        log.error("No normalized JSONL files found in: %s", processed_dir)
        return 1

    # For each document, keep only the most recently modified JSONL.
    # Directory names are: {doc_stem}_{YYYYMMDD}_{HHMMSS}/
    # Strip the trailing timestamp to get the canonical doc name.
    _ts_pattern = _re.compile(r"_\d{8}_\d{6}$")
    latest: dict[str, Path] = {}
    for p in all_norm_files:
        doc_key = _ts_pattern.sub("", p.parent.name)
        if doc_key not in latest or p.stat().st_mtime > latest[doc_key].stat().st_mtime:
            latest[doc_key] = p
    norm_files = sorted(latest.values())

    skipped = len(all_norm_files) - len(norm_files)
    if skipped:
        log.info("Deduped to %d unique document(s) — skipping %d older run(s)", len(norm_files), skipped)
    log.info("Found %d JSONL file(s) to reindex", len(norm_files))

    temp_name = f"{LIVE_ALIAS}_{int(_time.time())}"
    log.info("Building into temp collection: %s", temp_name)

    failed = []
    for i, jsonl_path in enumerate(norm_files):
        log.info("[%d/%d] Indexing: %s", i + 1, len(norm_files), jsonl_path.name)
        try:
            _embed.run(
                str(jsonl_path),
                qdrant_url=args.qdrant_url,
                ollama_url=args.ollama_url,
                collection_name=temp_name,
                recreate=(i == 0),
            )
        except Exception as e:
            log.error("Indexing failed for %s: %s", jsonl_path.name, e)
            failed.append(jsonl_path.name)

    if failed:
        log.error("=" * 60)
        log.error("REINDEX FAILED — %d file(s) failed. Live index untouched.", len(failed))
        for name in failed:
            log.error("  FAIL: %s", name)
        log.error("=" * 60)
        # Clean up the incomplete temp collection
        try:
            _QC(url=args.qdrant_url).delete_collection(temp_name)
            log.info("Deleted incomplete temp collection: %s", temp_name)
        except Exception as e:
            log.warning("Could not delete temp collection %s: %s", temp_name, e)
        return 1

    # All files indexed — perform atomic alias swap
    qdrant = _QC(url=args.qdrant_url)

    # Discover what 'grc_requirements' currently is: alias or real collection
    old_backing = None
    try:
        for a in qdrant.get_aliases().aliases:
            if a.alias_name == LIVE_ALIAS:
                old_backing = a.collection_name
                break
    except Exception:
        pass

    alias_ops = []
    if old_backing:
        # Already an alias — atomically replace it
        alias_ops.append(DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=LIVE_ALIAS)))
    else:
        # Real collection exists — delete it before creating alias (brief window)
        try:
            qdrant.delete_collection(LIVE_ALIAS)
            log.info("Deleted old real collection '%s'", LIVE_ALIAS)
        except Exception as e:
            log.warning("Could not delete old collection '%s': %s", LIVE_ALIAS, e)

    alias_ops.append(CreateAliasOperation(
        create_alias=CreateAlias(collection_name=temp_name, alias_name=LIVE_ALIAS),
    ))
    qdrant.update_collection_aliases(change_aliases_operations=alias_ops)
    log.info("Alias '%s' now points to '%s'", LIVE_ALIAS, temp_name)

    # Delete the old backing collection (if this was an alias swap)
    if old_backing and old_backing != temp_name:
        try:
            qdrant.delete_collection(old_backing)
            log.info("Deleted old backing collection: %s", old_backing)
        except Exception as e:
            log.warning("Could not delete old backing collection %s: %s", old_backing, e)

    log.info("=" * 60)
    log.info("REINDEX COMPLETE: %d files indexed, live alias swapped", len(norm_files))
    log.info("=" * 60)
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    """List all indexed documents with requirement counts and extraction mode."""
    import re as _re

    processed_dir = _cfg.processed_dir_path()
    if not processed_dir.exists():
        log.error("Processed documents directory not found: %s", processed_dir)
        return 1

    all_files = sorted(processed_dir.rglob("*_requirements_normalized.jsonl"))
    latest: dict[str, Path] = {}
    for p in all_files:
        # Key off filename stem, not directory name — robust to custom --output-dir usage
        doc_key = p.stem.replace("_requirements_normalized", "")
        if doc_key not in latest or p.stat().st_mtime > latest[doc_key].stat().st_mtime:
            latest[doc_key] = p

    total_reqs = 0
    print(f"\n{'Document':<30} {'Reqs':>6}  {'Extraction':<12}  {'Run Date'}")
    print("-" * 68)

    for doc_key, path in sorted(latest.items()):
        count = sum(1 for line in open(path, encoding="utf-8") if line.strip())
        total_reqs += count

        # Detect pdfplumber by scanning chunks for TABLE_START sentinels
        chunks = list(path.parent.glob("*_chunks.jsonl"))
        mode = "pymupdf"
        if chunks:
            with open(chunks[0], encoding="utf-8") as f:
                for line in f:
                    if "<<<TABLE_START>>>" in line:
                        mode = "pdfplumber"
                        break

        # Run date from directory timestamp suffix
        dir_name = path.parent.name
        ts_match = _re.search(r"_(\d{4})(\d{2})(\d{2})_\d{6}$", dir_name)
        run_date = f"{ts_match.group(1)}-{ts_match.group(2)}-{ts_match.group(3)}" if ts_match else "unknown"

        print(f"{doc_key:<30} {count:>6}  {mode:<12}  {run_date}")

    print("-" * 68)
    print(f"{'TOTAL':<30} {total_reqs:>6}  ({len(latest)} documents)")
    print()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show system status."""
    print("=" * 60)
    print("ReqBot System Status")
    print("=" * 60)

    ollama_url = getattr(args, "ollama_url", _cfg.ollama_url)
    qdrant_url = getattr(args, "qdrant_url", _cfg.qdrant_url)

    # Check Ollama
    print(f"\n--- Ollama ({ollama_url}) ---")
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        print(f"  Status: Running ({len(models)} models)")
        for m in models:
            size_gb = m.get("size", 0) / (1024**3)
            print(f"  - {m['name']} ({size_gb:.1f} GB)")
    except requests.RequestException:
        print("  Status: NOT REACHABLE")

    # Check Qdrant
    print(f"\n--- Qdrant ({qdrant_url}) ---")
    try:
        resp = requests.get(f"{qdrant_url}/collections", timeout=5)
        resp.raise_for_status()
        collections = resp.json().get("result", {}).get("collections", [])
        print(f"  Status: Running ({len(collections)} collections)")
        for c in collections:
            name = c.get("name", "?")
            # Get collection details
            detail_resp = requests.get(f"{qdrant_url}/collections/{name}", timeout=5)
            if detail_resp.ok:
                info = detail_resp.json().get("result", {})
                points = info.get("points_count", "?")
                print(f"  - {name}: {points} points")
            else:
                print(f"  - {name}")
    except requests.RequestException:
        print("  Status: NOT REACHABLE")

    # Check processed documents
    print("\n--- Processed Documents ---")
    processed_dir = _cfg.processed_dir_path()
    if processed_dir.exists():
        norm_files = list(processed_dir.rglob("*_requirements_normalized.jsonl"))
        for nf in sorted(norm_files):
            count = sum(1 for line in open(nf, encoding="utf-8") if line.strip())
            try:
                display = "~/" + str(nf.relative_to(Path.home()))
            except ValueError:
                display = str(nf)
            print(f"  - {display}: {count} requirements")
    else:
        print("  No processed documents found")

    print()
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    """Trace the full provenance of a specific requirement by ID."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue
    except ImportError:
        log.error("qdrant_client not installed — run: pip3 install qdrant-client")
        return 1

    import textwrap as _tw

    # Must match CONTEXT_UUID_NAMESPACE in ask.py and embed_context_index.py
    _CONTEXT_UUID_NS = uuid.UUID("b5f2e8d1-3a7c-4e9f-b8a2-6d4f1c7e3b5a")

    qdrant_url = getattr(args, "qdrant_url", _cfg.qdrant_url)
    req_id = args.requirement_id
    json_output = getattr(args, "json_output", False)
    show_context = getattr(args, "context", False)

    try:
        client = QdrantClient(url=qdrant_url, timeout=10)
    except Exception as e:
        log.error("Could not connect to Qdrant: %s", e)
        return 1

    # Step 1: Look up requirement by ID — scroll with filter, no vector search
    try:
        results, _ = client.scroll(
            collection_name="grc_requirements",
            scroll_filter=Filter(
                must=[FieldCondition(key="requirement_id", match=MatchValue(value=req_id))]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        log.error("Qdrant query failed: %s", e)
        return 1

    if not results:
        log.error("Requirement not found: %s", req_id)
        return 1

    payload = results[0].payload or {}

    # Step 2: Cross-framework matches — same source_ref, one representative per other document.
    # Skip by requirement_id first (the exact point being traced), then deduplicate by
    # document_id. If document_id is None, include without deduplication — can't group them.
    source_ref = payload.get("source_ref", "")
    cross_matches: list[dict] = []
    if source_ref:
        try:
            all_matches, _ = client.scroll(
                collection_name="grc_requirements",
                scroll_filter=Filter(
                    must=[FieldCondition(key="source_ref", match=MatchValue(value=source_ref))]
                ),
                limit=200,
                with_payload=True,
                with_vectors=False,
            )
            target_doc_id = payload.get("document_id")
            seen_docs: set = set()
            if target_doc_id:
                seen_docs.add(target_doc_id)
            for r in all_matches:
                p = r.payload or {}
                # Always skip the exact requirement being traced
                if p.get("requirement_id") == req_id:
                    continue
                doc_id = p.get("document_id")
                if doc_id:
                    if doc_id not in seen_docs:
                        seen_docs.add(doc_id)
                        cross_matches.append(p)
                else:
                    # No document_id — can't deduplicate, include it
                    cross_matches.append(p)
        except Exception as e:
            log.warning("Cross-framework query failed: %s", e)

    # Step 3: Retrieve context chunk from grc_context (optional, --context flag)
    context_text: str | None = None
    if show_context:
        doc_id = payload.get("document_id", "")
        chunk_id = payload.get("chunk_id")
        if doc_id and chunk_id is not None:
            pid = str(uuid.uuid5(_CONTEXT_UUID_NS, f"{doc_id}:{chunk_id}"))
            try:
                ctx_hits = client.retrieve(
                    collection_name="grc_context",
                    ids=[pid],
                    with_payload=True,
                )
                if ctx_hits:
                    ctx = ctx_hits[0].payload.get("text", "") if ctx_hits[0].payload else ""
                    if ctx:
                        # Window around the source_quote (300 chars each side)
                        quote = payload.get("source_quote", "")
                        window = 300
                        if quote and quote in ctx:
                            idx = ctx.find(quote)
                            start = max(0, idx - window)
                            end = min(len(ctx), idx + len(quote) + window)
                            prefix = "..." if start > 0 else ""
                            suffix = "..." if end < len(ctx) else ""
                            context_text = prefix + ctx[start:end] + suffix
                        else:
                            context_text = ctx[:window * 2] + ("..." if len(ctx) > window * 2 else "")
            except Exception as e:
                log.warning("Context retrieval failed: %s", e)
        else:
            log.warning("No chunk_id or document_id — cannot retrieve context chunk")

    if json_output:
        out: dict = {
            "requirement": payload,
            "cross_framework_matches": cross_matches,
        }
        if show_context:
            out["context_text"] = context_text
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    # --- Terminal display ---
    LABEL_W = 16

    def _labeled(label: str, text: str) -> None:
        lines = _tw.wrap(str(text), width=80 - LABEL_W) if text else [""]
        print(f"{label:<{LABEL_W}}{lines[0] if lines else ''}")
        for line in lines[1:]:
            print(f"{' ' * LABEL_W}{line}")

    page_start = payload.get("page_start", "")
    page_end = payload.get("page_end", "")
    page_str = str(page_start) if page_start else "—"
    if page_end and page_end != page_start:
        page_str += f"–{page_end}"

    print("\nRequirement Trace")
    print("=================")
    _labeled("ID:", req_id)
    if payload.get("description"):
        _labeled("Description:", payload.get("description", ""))

    print("\nProvenance")
    print("----------")
    print(f"  {'Document:':<14} {payload.get('source_pdf', '—')}")
    print(f"  {'Source ref:':<14} {source_ref or '—'}")
    print(f"  {'Page:':<14} {page_str}")
    print(f"  {'Extracted by:':<14} {payload.get('extraction_model', 'unknown')}")
    print(f"  {'Run date:':<14} {payload.get('run_timestamp', 'unknown')}")
    _auth_weight = _cfg.authority_weight(payload.get("source_pdf", ""))
    if _auth_weight is not None:
        _auth_fw = _cfg.authority_framework(payload.get("source_pdf", ""))
        _auth_label = f"{_auth_weight}/5" + (f"  ({_auth_fw})" if _auth_fw else "")
        print(f"  {'Authority:':<14} {_auth_label}")

    source_quote = payload.get("source_quote", "")
    if source_quote:
        print("\nSource Quote")
        print("------------")
        quote_lines = _tw.wrap(source_quote, width=76)
        for i, line in enumerate(quote_lines):
            prefix = '  "' if i == 0 else '   '
            suffix = '"' if i == len(quote_lines) - 1 else ""
            print(f"{prefix}{line}{suffix}")

    if context_text:
        print("\nSurrounding Context")
        print("-------------------")
        for line in _tw.wrap(context_text, width=78):
            print(f"  {line}")

    if cross_matches:
        print(f"\nCross-Framework Matches (same source_ref: {source_ref})")
        print("-" * 50)
        for m in cross_matches:
            m_pdf = (m.get("source_pdf") or "")[:30]
            m_ref = m.get("source_ref", "")
            m_page = m.get("page_start", "")
            m_weight = _cfg.authority_weight(m.get("source_pdf", ""))
            weight_str = f"  [auth:{m_weight}/5]" if m_weight is not None else ""
            print(f"  {m_pdf:<30} {m_ref:<14} Page {m_page}{weight_str}")
    elif source_ref:
        print(f"\n  No other documents found with source_ref: {source_ref}")

    print()
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Compare a control ID or free-text query across all indexed documents."""
    import re as _re
    import textwrap as _tw

    try:
        from qdrant_client import QdrantClient
        from qdrant_client import models as _qm
    except ImportError:
        log.error("qdrant_client not installed — run: pip3 install qdrant-client")
        return 1

    query = args.query.strip()
    qdrant_url = getattr(args, "qdrant_url", _cfg.qdrant_url)
    ollama_url = getattr(args, "ollama_url", _cfg.ollama_url)
    top_k = getattr(args, "top_k", _cfg.top_k)
    json_output = getattr(args, "json_output", False)
    markdown_output = getattr(args, "markdown_output", False)
    document_ids = getattr(args, "document_ids", None) or []

    # Control ID detection: AC-2, IA-5(1), AU-9, AC-2(j), IA-5(1)(a), SA-4(10)
    # Pattern: letter block, hyphen, digits, optional parenthetical suffixes
    CONTROL_ID_RE = _re.compile(r'^[A-Z]{1,4}-\d+(\([0-9a-z]+\))*$', _re.IGNORECASE)
    is_control_id = bool(CONTROL_ID_RE.match(query))

    try:
        client = QdrantClient(url=qdrant_url, timeout=10)
    except Exception as e:
        log.error("Could not connect to Qdrant: %s", e)
        return 1

    # -----------------------------------------------------------------------
    # Exact match path — control ID detected, scroll with source_ref filter
    # -----------------------------------------------------------------------
    if is_control_id:
        query = query.upper()  # Federal control IDs are always uppercase; Qdrant MatchValue is case-sensitive
        log.info("Control ID detected — using exact source_ref match for: %s", query)
        conditions: list = [
            _qm.FieldCondition(key="source_ref", match=_qm.MatchValue(value=query))
        ]
        if document_ids:
            conditions.append(
                _qm.FieldCondition(key="document_id", match=_qm.MatchAny(any=document_ids))
            )

        try:
            scroll_results, _ = client.scroll(
                collection_name="grc_requirements",
                scroll_filter=_qm.Filter(must=conditions),
                limit=200,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as e:
            log.error("Qdrant query failed: %s", e)
            return 1

        if not scroll_results:
            log.error("No requirements found with source_ref: %s", query)
            return 1

        # One representative per document — highest confidence wins ties
        doc_groups: dict[str, dict] = {}
        for r in scroll_results:
            p = r.payload or {}
            doc_key = p.get("source_pdf") or p.get("document_id") or "unknown"
            existing = doc_groups.get(doc_key)
            if existing is None or (p.get("confidence") or 0) > (existing.get("confidence") or 0):
                doc_groups[doc_key] = p

        if json_output:
            print(json.dumps({
                "query": query,
                "mode": "exact",
                "source_ref": query,
                "groups": list(doc_groups.values()),
            }, indent=2, ensure_ascii=False))
            return 0

        title = f"Cross-Framework Comparison: {query}"
        if markdown_output:
            print(f"# {title}\n")
            print(f"*{len(doc_groups)} document(s) — 1 control ID*\n")
            for doc_key, p in sorted(doc_groups.items()):
                page = p.get("page_start", "")
                header = f"{doc_key} (Page {page})" if page else doc_key
                print(f"## {header}\n")
                primary = p.get("description") or p.get("source_quote", "")
                print(f"{primary}\n")
                if p.get("source_quote") and p.get("description"):
                    print(f"> {p['source_quote']}\n")
                print("---\n")
        else:
            print(f"\n{title}")
            print("=" * len(title))
            for doc_key, p in sorted(doc_groups.items()):
                page = p.get("page_start", "")
                aw = _cfg.authority_weight(doc_key)
                auth_tag = f"  [auth:{aw}/5]" if aw is not None else ""
                subheader = (f"{doc_key} (Page {page})" if page else doc_key) + auth_tag
                print(f"\n{subheader}")
                print("-" * len(subheader))
                primary = p.get("description") or p.get("source_quote", "")
                for line in _tw.wrap(primary, width=76):
                    print(f"  {line}")
            print(f"\n{len(doc_groups)} document(s) — 1 control ID")
            print()

    # -----------------------------------------------------------------------
    # Semantic path — free text, hybrid search, group results by source_ref
    # -----------------------------------------------------------------------
    else:
        log.info("Free-text query — using hybrid semantic search for: %s", query)

        # Dense embedding — use the ollama package (consistent with ask.py; handles API version drift)
        try:
            import ollama as _ollama
            dense_vector = _ollama.Client(host=ollama_url).embed(
                model="nomic-embed-text", input=query
            ).embeddings[0]
        except Exception as e:
            log.error("Dense embedding failed: %s", e)
            return 1

        # Sparse embedding via fastembed BM25
        try:
            from fastembed import SparseTextEmbedding as _STE
            sparse_emb = next(iter(_STE(model_name="Qdrant/bm25").embed([query])))
            sparse_vector = _qm.SparseVector(
                indices=sparse_emb.indices.tolist(),
                values=sparse_emb.values.tolist(),
            )
        except Exception as e:
            log.error("Sparse embedding failed: %s", e)
            return 1

        prefetch_limit = max(100, top_k * 5)
        filter_obj = (
            _qm.Filter(must=[
                _qm.FieldCondition(key="document_id", match=_qm.MatchAny(any=document_ids))
            ])
            if document_ids else None
        )

        try:
            hits = client.query_points(
                collection_name="grc_requirements",
                prefetch=[
                    _qm.Prefetch(
                        query=dense_vector, using="dense",
                        filter=filter_obj, limit=prefetch_limit,
                    ),
                    _qm.Prefetch(
                        query=sparse_vector, using="sparse",
                        filter=filter_obj, limit=prefetch_limit,
                    ),
                ],
                query=_qm.FusionQuery(fusion=_qm.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            ).points
        except Exception as e:
            log.error("Hybrid search failed: %s", e)
            return 1

        if not hits:
            log.error("No results found for: %s", query)
            return 1

        # Group by source_ref, one representative per (source_ref, document) pair.
        # Preserve rank order — first occurrence of each source_ref wins ordering.
        ref_groups: dict[str, dict[str, dict]] = {}  # source_ref -> {doc_key -> payload}
        ref_order: list[str] = []
        for hit in hits:
            p = hit.payload or {}
            ref = p.get("source_ref") or "(no ref)"
            doc_key = p.get("source_pdf") or p.get("document_id") or "unknown"
            if ref not in ref_groups:
                ref_groups[ref] = {}
                ref_order.append(ref)
            if doc_key not in ref_groups[ref]:
                ref_groups[ref][doc_key] = p

        if json_output:
            print(json.dumps({
                "query": query,
                "mode": "semantic",
                "groups": [
                    {"source_ref": ref, "documents": list(ref_groups[ref].values())}
                    for ref in ref_order
                ],
            }, indent=2, ensure_ascii=False))
            return 0

        total_docs = sum(len(v) for v in ref_groups.values())
        title = f"Cross-Framework Comparison: {query}"
        if markdown_output:
            print(f"# {title}\n")
            print(f"*{len(ref_groups)} control group(s), {total_docs} source(s)*\n")
            for ref in ref_order:
                print(f"## {ref}\n")
                for doc_key, p in ref_groups[ref].items():
                    page = p.get("page_start", "")
                    sub = f"**{doc_key}**" + (f" (Page {page})" if page else "")
                    print(f"### {sub}\n")
                    primary = p.get("description") or p.get("source_quote", "")
                    print(f"{primary}\n")
                print("---\n")
        else:
            print(f"\n{title}")
            print("=" * len(title))
            for ref in ref_order:
                docs = ref_groups[ref]
                ref_line = f"\n  [{ref}]  {len(docs)} document(s)"
                print(ref_line)
                print("  " + "-" * (len(ref) + 18))
                for doc_key, p in docs.items():
                    page = p.get("page_start", "")
                    aw = _cfg.authority_weight(doc_key)
                    auth_tag = f"  [auth:{aw}/5]" if aw is not None else ""
                    print(f"\n  {doc_key}" + (f" (Page {page})" if page else "") + auth_tag)
                    primary = p.get("description") or p.get("source_quote", "")
                    for line in _tw.wrap(primary, width=72):
                        print(f"    {line}")
            print(f"\n{len(ref_groups)} control group(s) — {total_docs} source(s)")
            print()

    return 0


_EVIDENCE_AUDITOR_PROMPT = """You are a strict compliance auditor reviewing evidence for a System Security Plan (SSP).
You have been given a set of retrieved compliance requirements grouped by control ID.
Your task is to produce a concise Executive Summary for the evidence pack.

Rules you MUST follow:
1. Identify the dominant control families present in the evidence (e.g., AC, IA, AU).
2. Summarize what the evidence collectively requires — in plain, precise language an auditor would use.
3. Flag any gaps: controls that appear in only one framework, or controls with conflicting language across frameworks.
4. Do NOT invent requirements not present in the evidence.
5. Do NOT provide implementation guidance — only describe what the evidence says.
6. Keep the summary under 250 words. Use bullet points for clarity.

QUERY: {query}

EVIDENCE GROUPS ({group_count} control groups, {source_count} sources):
{evidence_summary}

Write the Executive Summary now:"""


def cmd_evidence(args: argparse.Namespace) -> int:
    """Export a defensible evidence pack grouped by control ID."""
    import textwrap as _tw
    from datetime import datetime as _datetime, timezone as _tz

    try:
        from qdrant_client import QdrantClient
        from qdrant_client import models as _qm
    except ImportError:
        log.error("qdrant_client not installed — run: pip3 install qdrant-client")
        return 1

    # Must match CONTEXT_UUID_NAMESPACE in ask.py and embed_context_index.py
    _CONTEXT_UUID_NS = uuid.UUID("b5f2e8d1-3a7c-4e9f-b8a2-6d4f1c7e3b5a")

    query = args.query.strip()
    qdrant_url = getattr(args, "qdrant_url", _cfg.qdrant_url)
    ollama_url = getattr(args, "ollama_url", _cfg.ollama_url)
    top_k = getattr(args, "top_k", _cfg.top_k)
    fmt = getattr(args, "output_format", "markdown")
    output_file = getattr(args, "output_file", None)
    show_context = getattr(args, "context", False)
    document_ids = getattr(args, "document_ids", None) or []
    domain_tags = getattr(args, "domain_tags", None) or []
    requirement_types = getattr(args, "requirement_types", None) or []

    timestamp = _datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        client = QdrantClient(url=qdrant_url, timeout=10)
    except Exception as e:
        log.error("Could not connect to Qdrant: %s", e)
        return 1

    # Dense embedding
    try:
        import ollama as _ollama
        dense_vector = _ollama.Client(host=ollama_url).embed(
            model="nomic-embed-text", input=query
        ).embeddings[0]
    except Exception as e:
        log.error("Dense embedding failed: %s", e)
        return 1

    # Sparse embedding
    try:
        from fastembed import SparseTextEmbedding as _STE
        sparse_emb = next(iter(_STE(model_name="Qdrant/bm25").embed([query])))
        sparse_vector = _qm.SparseVector(
            indices=sparse_emb.indices.tolist(),
            values=sparse_emb.values.tolist(),
        )
    except Exception as e:
        log.error("Sparse embedding failed: %s", e)
        return 1

    # Build filter
    filter_conditions: list = []
    if document_ids:
        filter_conditions.append(
            _qm.FieldCondition(key="document_id", match=_qm.MatchAny(any=document_ids))
        )
    if domain_tags:
        filter_conditions.append(
            _qm.FieldCondition(key="domain_tags", match=_qm.MatchAny(any=domain_tags))
        )
    if requirement_types:
        filter_conditions.append(
            _qm.FieldCondition(key="requirement_type", match=_qm.MatchAny(any=requirement_types))
        )
    filter_obj = _qm.Filter(must=filter_conditions) if filter_conditions else None

    prefetch_limit = max(100, top_k * 5)

    try:
        hits = client.query_points(
            collection_name="grc_requirements",
            prefetch=[
                _qm.Prefetch(
                    query=dense_vector, using="dense",
                    filter=filter_obj, limit=prefetch_limit,
                ),
                _qm.Prefetch(
                    query=sparse_vector, using="sparse",
                    filter=filter_obj, limit=prefetch_limit,
                ),
            ],
            query=_qm.FusionQuery(fusion=_qm.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        ).points
    except Exception as e:
        log.error("Search failed: %s", e)
        return 1

    if not hits:
        log.error("No results found for: %s", query)
        return 1

    # Group by source_ref.
    # Every result in a group becomes a "source" row in the evidence table.
    # The representative (canonical description) is the highest-confidence result per group.
    groups: dict[str, dict] = {}
    group_order: list[str] = []
    for hit in hits:
        p = hit.payload or {}
        ref = p.get("source_ref") or "(no ref)"
        if ref not in groups:
            groups[ref] = {
                "source_ref": ref,
                "representative": p,
                "sources": [],
                "context_text": None,
            }
            group_order.append(ref)
        groups[ref]["sources"].append(p)
        if (p.get("confidence") or 0) > (groups[ref]["representative"].get("confidence") or 0):
            groups[ref]["representative"] = p

    # Context retrieval — batch fetch for all group representatives in one call
    if show_context:
        pid_to_ref: dict[str, str] = {}
        pids: list[str] = []
        for ref in group_order:
            rep = groups[ref]["representative"]
            doc_id = rep.get("document_id", "")
            chunk_id = rep.get("chunk_id")
            if doc_id and chunk_id is not None:
                pid = str(uuid.uuid5(_CONTEXT_UUID_NS, f"{doc_id}:{chunk_id}"))
                pids.append(pid)
                pid_to_ref[pid] = ref
        if pids:
            try:
                ctx_hits = client.retrieve(
                    collection_name="grc_context",
                    ids=pids,
                    with_payload=True,
                )
                for point in ctx_hits:
                    ref = pid_to_ref.get(str(point.id))
                    if not ref:
                        continue
                    ctx = (point.payload or {}).get("text", "")
                    if not ctx:
                        continue
                    rep = groups[ref]["representative"]
                    quote = rep.get("source_quote", "")
                    window = 300
                    if quote and quote in ctx:
                        idx = ctx.find(quote)
                        start = max(0, idx - window)
                        end = min(len(ctx), idx + len(quote) + window)
                        prefix = "..." if start > 0 else ""
                        suffix = "..." if end < len(ctx) else ""
                        groups[ref]["context_text"] = prefix + ctx[start:end] + suffix
                    else:
                        groups[ref]["context_text"] = (
                            ctx[:window * 2] + ("..." if len(ctx) > window * 2 else "")
                        )
            except Exception as e:
                log.warning("Context batch retrieval failed: %s", e)

    total_sources = sum(len(g["sources"]) for g in groups.values())

    # -----------------------------------------------------------------------
    # LLM Synthesis — Compliance Auditor Executive Summary
    # -----------------------------------------------------------------------
    # Build a compact evidence summary for the LLM (control IDs + descriptions only,
    # not the full source table — keeps the prompt tight and within context window).
    _evidence_lines: list[str] = []
    for i, ref in enumerate(group_order, 1):
        g = groups[ref]
        rep = g["representative"]
        _primary = rep.get("description") or rep.get("source_quote") or "(no text)"
        _evidence_lines.append(
            f"[{i}] Control: {ref}  |  Sources: {len(g['sources'])}\n"
            f"    {_primary}"
        )

    _evidence_summary = "\n\n".join(_evidence_lines)
    _auditor_prompt = _EVIDENCE_AUDITOR_PROMPT.format(
        query=query,
        group_count=len(groups),
        source_count=total_sources,
        evidence_summary=_evidence_summary,
    )

    _synthesis_text: str = ""
    _api_key = (
        __import__("os").environ.get(_cfg.api_key_env, "")
        if _cfg.synthesis_backend == "remote" else ""
    )
    try:
        import synthesis as _syn
        _synthesis_text = _syn.synthesize(
            question="",
            evidence="",
            backend=_cfg.synthesis_backend,
            model=_cfg.synthesis_model,
            ollama_url=ollama_url,
            provider=_cfg.remote_provider,
            api_key=_api_key,
            raw_prompt=_auditor_prompt,
        )
    except Exception as e:
        log.warning("Evidence synthesis failed (%s) — producing evidence pack without summary", e)

    # -----------------------------------------------------------------------
    # Build output (JSON or Markdown)
    # -----------------------------------------------------------------------
    if fmt == "json":
        out_groups = []
        for ref in group_order:
            g = groups[ref]
            rep = g["representative"]
            entry: dict = {
                "source_ref": ref,
                "description": rep.get("description", ""),
                "source_quote": rep.get("source_quote", ""),
                "primary_text": rep.get("description") or rep.get("source_quote", ""),
                "confidence": rep.get("confidence"),
                "sources": [
                    {
                        "source_pdf": s.get("source_pdf", ""),
                        "source_ref": s.get("source_ref", ""),
                        "page_start": s.get("page_start"),
                        "page_end": s.get("page_end"),
                        "document_id": s.get("document_id", ""),
                    }
                    for s in g["sources"]
                ],
            }
            if show_context:
                entry["context_text"] = g.get("context_text")
            out_groups.append(entry)
        output_text = json.dumps({
            "query": query,
            "generated": timestamp,
            "group_count": len(groups),
            "source_count": total_sources,
            "executive_summary": _synthesis_text or None,
            "groups": out_groups,
        }, indent=2, ensure_ascii=False)

    else:  # markdown (default)
        lines: list[str] = []
        title = f"Evidence Pack: {query}"
        lines += [
            title,
            "=" * len(title),
            f"Generated: {timestamp}",
            f"Query:     {query}",
            f"Results:   {len(groups)} requirement group(s), {total_sources} source(s)",
            "",
        ]
        if _synthesis_text:
            lines.append("## Executive Summary")
            lines.append("")
            for line in _tw.wrap(_synthesis_text.strip(), width=80):
                lines.append(line)
            lines.append("")

        for i, ref in enumerate(group_order, 1):
            g = groups[ref]
            rep = g["representative"]

            lines.append("---")
            lines.append("")
            lines.append(f"## Requirement Group {i} — {ref}")
            lines.append("")
            lines.append("**Requirement:**")
            lines.append(rep.get("description") or rep.get("source_quote", ""))
            lines.append("")
            lines.append("**Sources:**")
            lines.append("")
            _has_auth = any(
                _cfg.authority_weight(s.get("source_pdf", "")) is not None
                for s in g["sources"]
            )
            if _has_auth:
                lines.append("| Framework | Reference | Page | Authority |")
                lines.append("|-----------|-----------|------|-----------|")
                for s in g["sources"]:
                    framework = s.get("source_pdf") or "—"
                    ref_str = s.get("source_ref") or "—"
                    page = s.get("page_start") or "—"
                    aw = _cfg.authority_weight(framework)
                    auth_cell = f"{aw}/5" if aw is not None else "—"
                    lines.append(f"| {framework} | {ref_str} | {page} | {auth_cell} |")
            else:
                lines.append("| Framework | Reference | Page |")
                lines.append("|-----------|-----------|------|")
                for s in g["sources"]:
                    framework = s.get("source_pdf") or "—"
                    ref_str = s.get("source_ref") or "—"
                    page = s.get("page_start") or "—"
                    lines.append(f"| {framework} | {ref_str} | {page} |")
            lines.append("")

            if show_context and g.get("context_text"):
                lines.append("**Context:**")
                lines.append("")
                for line in _tw.wrap(g["context_text"], width=78):
                    lines.append(f"> {line}")
                lines.append("")

            n = len(g["sources"])
            if n > 1:
                lines.append(f"**Notes:** Found in {n} sources across the corpus.")
            lines.append("")

        output_text = "\n".join(lines)

    # -----------------------------------------------------------------------
    # Write to file or stdout
    # -----------------------------------------------------------------------
    if output_file:
        try:
            Path(output_file).expanduser().write_text(output_text + "\n", encoding="utf-8")
            print(f"Evidence pack written to: {output_file}")
        except OSError as e:
            log.error("Could not write to file: %s", e)
            return 1
    else:
        print(output_text)

    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Interactive setup wizard — writes ~/.config/reqbot/config.json."""
    print("\nReqBot Setup")
    print("============")

    def _prompt(label: str, default: str) -> str:
        """Prompt with default in brackets; empty input returns default."""
        val = input(f"{label} [{default}]: ").strip()
        return val if val else default

    def _test_ollama(url: str) -> tuple[bool, str, list[str]]:
        """Returns (ok, message, model_names_list)."""
        try:
            resp = requests.get(f"{url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            names = [m["name"] for m in models]
            count = len(names)
            return True, f"OK ({count} model{'s' if count != 1 else ''} found)", names
        except requests.RequestException as e:
            return False, f"FAILED — {e}", []

    def _test_qdrant(url: str) -> tuple[bool, str]:
        try:
            resp = requests.get(f"{url}/collections", timeout=5)
            resp.raise_for_status()
            count = len(resp.json().get("result", {}).get("collections", []))
            return True, f"OK ({count} collection{'s' if count != 1 else ''})"
        except requests.RequestException as e:
            return False, f"FAILED — {e}"

    try:
        # Ollama URL — loop until connection succeeds or user accepts failure
        available_models: list[str] = []
        while True:
            ollama_url = _prompt("Ollama URL", _cfg.ollama_url).rstrip("/")
            connected, msg, available_models = _test_ollama(ollama_url)
            print(f"  Testing connection... {msg}")
            if connected:
                break
            keep = input("  Connection failed. Keep this URL anyway? (y/N): ").strip().lower()
            if keep == "y":
                break

        # Qdrant URL — same pattern
        while True:
            qdrant_url = _prompt("Qdrant URL", _cfg.qdrant_url).rstrip("/")
            connected2, msg2 = _test_qdrant(qdrant_url)
            print(f"  Testing connection... {msg2}")
            if connected2:
                break
            keep = input("  Connection failed. Keep this URL anyway? (y/N): ").strip().lower()
            if keep == "y":
                break

        # Models — warn if not present on the server
        default_model = _prompt("Default extraction model", _cfg.default_model)
        if available_models and default_model not in available_models:
            print(f"  [!] Warning: '{default_model}' not found on Ollama server.")
            print(f"      Available: {', '.join(available_models)}")

        synthesis_model = _prompt("Synthesis model", _cfg.synthesis_model)
        if available_models and synthesis_model not in available_models:
            print(f"  [!] Warning: '{synthesis_model}' not found on Ollama server.")
            print(f"      Available: {', '.join(available_models)}")

        # top_k — must be a positive int
        while True:
            raw = _prompt("Default top-k", str(_cfg.top_k))
            try:
                top_k = int(raw)
                if top_k > 0:
                    break
                print("  top-k must be a positive integer.")
            except ValueError:
                print("  Invalid value — enter a positive integer.")

        # min_score — must be a non-negative float
        while True:
            raw = _prompt("Minimum relevance score (0 = disabled)", str(_cfg.min_score))
            try:
                min_score = float(raw)
                if min_score >= 0:
                    break
                print("  min-score must be 0 or greater.")
            except ValueError:
                print("  Invalid value — enter a number (e.g. 0.02).")

        # processed_dir — validate and attempt to create
        processed_dir = _prompt("Processed documents dir", _cfg.processed_dir)
        processed_dir_path = Path(processed_dir).expanduser().resolve()
        try:
            processed_dir_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            print(f"  [!] Warning: Cannot create directory — check permissions: {processed_dir_path}")

        # Remote synthesis (optional — skippable)
        print()
        print("  Remote Synthesis (optional — press Enter to skip)")
        print("  Allows using Claude or GPT-4o for higher-quality answers.")
        print("  All retrieval and indexing remain 100% local.")
        print("  Only retrieved evidence snippets (shown on screen) are sent externally.")
        use_remote_raw = input("  Enable remote synthesis? [y/N]: ").strip().lower()
        use_remote = use_remote_raw in ("y", "yes")

        synthesis_backend = "local"
        remote_provider = _cfg.remote_provider
        remote_model = _cfg.remote_model
        api_key_env = _cfg.api_key_env

        if use_remote:
            provider_raw = input(
                f"  Provider [anthropic/openai] (default: {_cfg.remote_provider}): "
            ).strip().lower()
            remote_provider = provider_raw if provider_raw in ("anthropic", "openai") else _cfg.remote_provider

            _default_model = "claude-sonnet-4-6" if remote_provider == "anthropic" else "gpt-4o"
            model_raw = input(
                f"  Remote model (default: {_default_model}): "
            ).strip()
            remote_model = model_raw if model_raw else _default_model

            _default_env = "ANTHROPIC_API_KEY" if remote_provider == "anthropic" else "OPENAI_API_KEY"
            env_raw = input(
                f"  API key environment variable (default: {_default_env}): "
            ).strip()
            api_key_env = env_raw if env_raw else _default_env

            synthesis_backend = "remote"
            print(f"  Remote synthesis configured: {remote_provider} / {remote_model}")
            print(f"  API key read from: ${api_key_env}")

    except (KeyboardInterrupt, EOFError):
        print("\n\n[!] Setup cancelled — config not saved.")
        return 1

    # Write config
    cfg_data = {
        "ollama_url": ollama_url,
        "qdrant_url": qdrant_url,
        "default_model": default_model,
        "synthesis_model": synthesis_model,
        "top_k": top_k,
        "min_score": min_score,
        "processed_dir": processed_dir,
        "synthesis_backend": synthesis_backend,
        "remote_provider": remote_provider,
        "remote_model": remote_model,
        "api_key_env": api_key_env,
    }

    config_path = _config.CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(cfg_data, indent=2) + "\n", encoding="utf-8"
    )
    config_path.chmod(0o600)

    print(f"\nConfig saved to {config_path} (permissions: 600)")
    print("Run 'reqbot' to launch the interactive shell.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="reqbot",
        description="ReqBot — Cybersecurity requirements extraction and search",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ReqBot {__version__} (built {__build_date__})",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="Run extraction pipeline on a PDF")
    p_ingest.add_argument("pdf", type=str, help="Path to the PDF file")
    p_ingest.add_argument("--output-dir", type=str, help="Output directory")
    p_ingest.add_argument("--model", type=str, help="Ollama model for extraction")
    p_ingest.add_argument("--max-chunks", type=int, help="Limit chunks for testing")
    p_ingest.add_argument("--index", action="store_true", help="Also index into Qdrant after extraction")
    p_ingest.add_argument(
        "--layout-mode",
        choices=["pymupdf", "pdfplumber"],
        default="pymupdf",
        dest="layout_mode",
        help="PDF extraction backend (default: pymupdf)",
    )
    p_ingest.add_argument(
        "--skip-enrichment",
        action="store_true",
        dest="skip_enrichment",
        help="Skip Pass 2 enrichment (description/tags/type). Index source_quote-only output directly.",
    )
    p_ingest.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")
    p_ingest.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")

    # index
    p_index = subparsers.add_parser("index", help="Embed and index requirements into Qdrant")
    p_index.add_argument("jsonl", type=str, help="Path to requirements_normalized.jsonl")
    p_index.add_argument("--recreate", action="store_true", help="Recreate Qdrant collection")
    p_index.add_argument("--batch-size", type=int, help="Embedding batch size")
    p_index.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")
    p_index.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")

    # ask
    p_ask = subparsers.add_parser("ask", help="Query requirements via vector search")
    p_ask.add_argument("question", type=str, help="Natural language question")
    p_ask.add_argument("--top-k", type=int, default=_cfg.top_k, help=f"Number of results (default: {_cfg.top_k})")
    p_ask.add_argument("--min-score", type=float, default=_cfg.min_score, dest="min_score", help=f"Minimum RRF score threshold (default: {_cfg.min_score}; 0 disables)")
    p_ask.add_argument("--synthesize", action="store_true", help="Generate LLM answer")
    p_ask.add_argument("--model", type=str, help="LLM model for synthesis")
    p_ask.add_argument("--domain-tag", action="append", dest="domain_tags", help="Filter by domain tag")
    p_ask.add_argument("--requirement-type", action="append", dest="requirement_types", help="Filter by type")
    p_ask.add_argument("--document-id", action="append", dest="document_ids", help="Filter by document")
    p_ask.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
    p_ask.add_argument("--context", action="store_true", help="Enrich with surrounding chunk text from grc_context")
    p_ask.add_argument("--no-rewrite", action="store_true", dest="no_rewrite", help="Skip query rewriting")
    p_ask.add_argument("--rewrite-model", type=str, default="llama3.1:8b-instruct-q4_K_M", dest="rewrite_model", help="LLM model for query rewriting")
    p_ask.add_argument("--context-collection", type=str, default="grc_context", dest="context_collection", help="Qdrant context collection name")
    p_ask.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")
    p_ask.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")

    # batch
    p_batch = subparsers.add_parser("batch", help="Run pipeline on all PDFs in a directory")
    p_batch.add_argument("pdf_dir", type=str, help="Directory containing PDF files")
    p_batch.add_argument("--model", type=str, help="Ollama model for extraction")
    p_batch.add_argument(
        "--layout-mode",
        choices=["pymupdf", "pdfplumber"],
        default="pymupdf",
        dest="layout_mode",
        help="PDF extraction backend (default: pymupdf)",
    )
    p_batch.add_argument(
        "--skip-enrichment",
        action="store_true",
        dest="skip_enrichment",
        help="Skip Pass 2 enrichment (description/tags/type). Index source_quote-only output directly.",
    )
    p_batch.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")
    p_batch.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")

    # index-context
    p_ictx = subparsers.add_parser(
        "index-context",
        help="Embed and index raw chunks into grc_context collection",
    )
    p_ictx.add_argument("chunks_jsonl", type=str, help="Path to <stem>_chunks.jsonl from Step B")
    p_ictx.add_argument("--document-id", type=str, default=None, dest="document_id",
                        help="Document identifier (default: derived from filename)")
    p_ictx.add_argument("--source-pdf", type=str, default="", dest="source_pdf",
                        help="Source PDF filename for display")
    p_ictx.add_argument("--recreate", action="store_true", help="Recreate grc_context collection")
    p_ictx.add_argument("--batch-size", type=int, dest="batch_size", help="Embedding batch size")
    p_ictx.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")
    p_ictx.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")

    # docs
    p_docs = subparsers.add_parser(
        "docs",
        help="List all indexed documents with requirement counts",
    )
    p_docs.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")
    p_docs.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")

    # reindex
    p_reindex = subparsers.add_parser(
        "reindex",
        help="Rebuild Qdrant collection from all existing JSONL (no re-extraction)",
    )
    p_reindex.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")
    p_reindex.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")

    # compare
    p_compare = subparsers.add_parser(
        "compare",
        help="Compare a control ID or query across all indexed documents",
    )
    p_compare.add_argument("query", type=str,
                           help="Control ID (e.g. AC-2) or free-text query")
    p_compare.add_argument("--top-k", type=int, default=_cfg.top_k, dest="top_k",
                           help=f"Results for semantic search (default: {_cfg.top_k})")
    p_compare.add_argument("--json", action="store_true", dest="json_output",
                           help="Output as JSON")
    p_compare.add_argument("--markdown", action="store_true", dest="markdown_output",
                           help="Output as Markdown")
    p_compare.add_argument("--document-id", action="append", dest="document_ids", default=[],
                           help="Filter by document ID (repeatable)")
    p_compare.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")
    p_compare.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")

    # evidence
    p_evidence = subparsers.add_parser(
        "evidence",
        help="Export a defensible evidence pack grouped by control ID",
    )
    p_evidence.add_argument("query", type=str, help="Query to retrieve requirements for")
    p_evidence.add_argument("--format", type=str, choices=["markdown", "json"],
                            default="markdown", dest="output_format",
                            help="Output format: markdown (default) or json")
    p_evidence.add_argument("--output", type=str, default=None, dest="output_file",
                            help="Write output to FILE instead of printing")
    p_evidence.add_argument("--context", action="store_true",
                            help="Include surrounding raw chunk text from grc_context")
    p_evidence.add_argument("--top-k", type=int, default=20, dest="top_k",
                            help="Number of results to retrieve (default: 20)")
    p_evidence.add_argument("--document-id", action="append", dest="document_ids", default=[],
                            help="Filter by document ID (repeatable)")
    p_evidence.add_argument("--domain-tag", action="append", dest="domain_tags", default=[],
                            help="Filter by domain tag (repeatable)")
    p_evidence.add_argument("--requirement-type", action="append", dest="requirement_types",
                            default=[],
                            help="Filter by requirement type (repeatable)")
    p_evidence.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")
    p_evidence.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")

    # trace
    p_trace = subparsers.add_parser("trace", help="Trace full provenance of a requirement by ID")
    p_trace.add_argument("requirement_id", type=str, help="Requirement ID (e.g. REQ-a3f2c1d4e5b6)")
    p_trace.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
    p_trace.add_argument("--context", action="store_true",
                         help="Include surrounding raw chunk text from grc_context")
    p_trace.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")

    # init
    subparsers.add_parser("init", help="Interactive setup wizard — writes ~/.config/reqbot/config.json")

    # status
    p_status = subparsers.add_parser("status", help="Show system status")
    p_status.add_argument("--ollama-url", type=str, default=_cfg.ollama_url, dest="ollama_url")
    p_status.add_argument("--qdrant-url", type=str, default=_cfg.qdrant_url, dest="qdrant_url")

    args = parser.parse_args()

    if not args.command:
        import console as _console
        _console.launch()
        sys.exit(0)

    commands = {
        "ingest": cmd_ingest,
        "index": cmd_index,
        "index-context": cmd_index_context,
        "ask": cmd_ask,
        "batch": cmd_batch,
        "docs": cmd_docs,
        "reindex": cmd_reindex,
        "status": cmd_status,
        "init": cmd_init,
        "trace": cmd_trace,
        "compare": cmd_compare,
        "evidence": cmd_evidence,
    }

    rc = commands[args.command](args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
