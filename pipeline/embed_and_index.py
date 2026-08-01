#!/usr/bin/env python3
"""Step F: Embed normalized requirements and index into Qdrant.

Input:  requirements_normalized.jsonl (from Step D)
Output: Qdrant collection "grc_requirements" with vector + payload per requirement

This step reads the canonical JSONL, generates embeddings via Ollama
(nomic-embed-text), and upserts into Qdrant. Qdrant is a rebuildable
search index — JSONL remains the system of record.
"""

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

import ollama
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models

# Fixed namespace for deterministic uuid5 generation from requirement_id.
# This must never change, or all existing point IDs become invalid.
QDRANT_UUID_NAMESPACE = uuid.UUID("a3e7c1d4-9f2b-4e8a-b6d5-1c3f5a7e9b2d")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

COLLECTION_NAME = "grc_requirements"
EMBEDDING_MODEL = "nomic-embed-text"
SPARSE_MODEL = "Qdrant/bm25"


def load_jsonl(path: Path) -> list[dict]:
    """Load records from a JSONL file."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_embedding_text(req: dict) -> str | None:
    """Build deterministic embedding text from a requirement record.

    Returns None if source_quote is empty — callers must skip that record.
    source_quote is required at ingest; an empty value indicates a data
    integrity violation that should have been caught at Step C or Step D.

    WP-39.2: prefers the precomputed embedding_text field (source_quote prefixed with
    parent_stem, when reconstruction found one — see pipeline/enrich_requirements.py's
    apply_parent_stem_reconstruction()) over bare source_quote when present. Backward
    compatible: absent on older/unreconstructed records, which fall back to the
    original behavior unchanged.
    """
    source_quote = (req.get("source_quote") or "").strip()
    if not source_quote:
        return None
    text = (req.get("embedding_text") or "").strip() or source_quote
    source_ref = (req.get("source_ref") or "").strip()
    if source_ref:
        text += f"\nRef: {source_ref}"
    return text


def build_payload(req: dict, embedding_model: str, embedding_dim: int) -> dict:
    """Build lean Qdrant payload from a requirement record.

    embedding_model/embedding_dim are indexing-time facts, not JSONL fields —
    the same JSONL can be reindexed multiple times with a different embedding
    model over its lifetime, so this is captured here (payload), not baked
    into the source-of-record artifact (WP-25.6c).
    """
    return {
        "requirement_id": req["requirement_id"],
        "document_id": req.get("document_id", ""),
        "source_pdf": req.get("source_pdf", ""),
        "source_ref": req.get("source_ref", ""),
        "domain_tags": req.get("domain_tags", []),
        "requirement_type": req.get("requirement_type", ""),
        "source_quote": req.get("source_quote", ""),
        "parent_stem": req.get("parent_stem", ""),
        "embedding_text": req.get("embedding_text", ""),
        "description": req.get("description", ""),
        "page_start": req.get("page_start"),
        "page_end": req.get("page_end"),
        "confidence": req.get("confidence", 0.0),
        "chunk_id": req.get("chunk_id"),
        # Hierarchy metadata (WP-14.3) — empty for pre-WP-14.2 artifacts
        "section_ref_path": req.get("section_ref_path", []),
        "section_title_path": req.get("section_title_path", []),
        "parent_section_ref": req.get("parent_section_ref"),
        "parent_context": req.get("parent_context"),
        "child_section_refs": req.get("child_section_refs", []),
        "domain_profile": req.get("domain_profile", "cybersecurity"),
        "schema_version": req.get("schema_version", ""),
        "pipeline_version": req.get("pipeline_version", ""),
        "extraction_model": req.get("extraction_model", ""),
        "run_timestamp": req.get("run_timestamp", ""),
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
    }


def embed_batch(texts: list[str], client: ollama.Client, model: str = EMBEDDING_MODEL) -> list[list[float]]:
    """Embed a batch of texts using Ollama (dense vectors)."""
    result = client.embed(model=model, input=texts)
    return result.embeddings


def embed_sparse_batch(texts: list[str], model: SparseTextEmbedding) -> list[models.SparseVector]:
    """Generate sparse BM25 vectors for a batch of texts."""
    return [
        models.SparseVector(indices=emb.indices.tolist(), values=emb.values.tolist())
        for emb in model.embed(texts)
    ]


def prepare_collection(client: QdrantClient, collection_name: str, recreate: bool) -> bool:
    """Delete the collection if recreate=True, and report whether creation is
    still needed.

    Creation is deferred to create_collection() below rather than done here,
    because the dense vector dimension depends on the configured
    embedding_model (WP-25.6c) — it's only known once the first embedding
    actually comes back, not before any text has been embedded.
    """
    exists = client.collection_exists(collection_name)

    if exists and recreate:
        log.info("Recreating collection '%s'", collection_name)
        client.delete_collection(collection_name)
        exists = False

    if exists:
        log.info("Collection '%s' already exists, will upsert", collection_name)

    return not exists


def create_collection(client: QdrantClient, collection_name: str, vector_dim: int) -> None:
    """Create the collection with a dense vector size matching the actual
    embedding output — not a hardcoded constant, so a non-default
    embedding_model with a dimension other than nomic-embed-text's 768
    still produces a correctly-shaped collection (WP-25.6c, Codex review
    PR #108)."""
    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            "dense": models.VectorParams(
                size=vector_dim,
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=False),
            ),
        },
    )
    log.info(
        "Created collection '%s' (dense cosine %d-dim + sparse BM25)",
        collection_name, vector_dim,
    )


def run(
    requirements_jsonl: str,
    *,
    qdrant_url: str = "http://localhost:6333",
    ollama_url: str = "http://localhost:11434",
    recreate: bool = False,
    collection_name: str = COLLECTION_NAME,
    batch_size: int = 32,
    embedding_model: str = EMBEDDING_MODEL,
) -> int:
    """Embed requirements and index into Qdrant.

    Callable interface for in-process use by reqbot.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        requirements_jsonl: Path to requirements_normalized.jsonl from Step D.
        qdrant_url:         Qdrant HTTP API URL.
        ollama_url:         Ollama API base URL.
        recreate:           Drop and recreate the collection if True.
        collection_name:    Qdrant collection name.
        batch_size:         Requirements per embedding batch.
        embedding_model:    Ollama embedding model — written into each point's
                             payload as provenance (WP-25.6c).

    Returns:
        Number of requirements successfully indexed.
    """
    if batch_size <= 0:
        raise ValueError(f"batch_size must be > 0, got {batch_size}")
    reqs_path = Path(requirements_jsonl).resolve()
    log.info("Loading requirements from: %s", reqs_path)
    requirements = load_jsonl(reqs_path)
    log.info("Loaded %d requirements", len(requirements))

    if not requirements:
        log.warning("No requirements to index")
        return 0

    ollama_client = ollama.Client(host=ollama_url)
    log.info("Using Ollama at: %s", ollama_url)

    log.info("Loading sparse embedding model: %s", SPARSE_MODEL)
    sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL)

    client = QdrantClient(url=qdrant_url)
    needs_creation = prepare_collection(client, collection_name, recreate)

    start = time.time()
    total_indexed = 0
    total_skipped = 0

    for batch_start in range(0, len(requirements), batch_size):
        raw_batch = requirements[batch_start:batch_start + batch_size]

        # Reject records without source_quote before embedding — they violate the
        # Phase 12.1 contract and must not enter Qdrant as "Ref: ..." only.
        batch = []
        texts = []
        for req in raw_batch:
            text = build_embedding_text(req)
            if text is None:
                log.warning(
                    "Skipping requirement %s — empty source_quote (data integrity violation, should have been rejected at Step C/D)",
                    req.get("requirement_id", "?"),
                )
                total_skipped += 1
            else:
                batch.append(req)
                texts.append(text)

        if not batch:
            continue

        try:
            dense_embeddings = embed_batch(texts, ollama_client, embedding_model)
        except Exception as e:
            log.error("Dense batch failed at offset %d: %s — falling back to individual", batch_start, e)
            dense_embeddings = []
            for text in texts:
                try:
                    result = ollama_client.embed(model=embedding_model, input=text)
                    dense_embeddings.append(result.embeddings[0])
                except Exception as e2:
                    log.error("Individual dense embed failed: %s — item will be skipped", e2)
                    dense_embeddings.append(None)

        try:
            sparse_embeddings = embed_sparse_batch(texts, sparse_model)
        except Exception as e:
            log.error("Sparse batch failed at offset %d: %s — falling back to individual", batch_start, e)
            sparse_embeddings = []
            for text in texts:
                try:
                    embs = list(sparse_model.embed([text]))
                    sparse_embeddings.append(
                        models.SparseVector(indices=embs[0].indices.tolist(), values=embs[0].values.tolist())
                    )
                except Exception as e2:
                    log.error("Individual sparse embed failed: %s — item will be skipped", e2)
                    sparse_embeddings.append(None)

        if needs_creation:
            first_dense = next((e for e in dense_embeddings if e is not None), None)
            if first_dense is not None:
                create_collection(client, collection_name, len(first_dense))
                needs_creation = False
            # else: every embedding in this batch failed — nothing to create
            # from yet; retry on the next batch. The points loop below will
            # skip every item in this batch anyway (no dense_emb to build a
            # point from), so there's nothing to upsert either way.

        points = []
        batch_skipped = 0
        for req, dense_emb, sparse_emb in zip(batch, dense_embeddings, sparse_embeddings):
            if dense_emb is None or sparse_emb is None:
                log.warning("Skipping requirement %s — embedding failed", req.get("requirement_id", "?"))
                batch_skipped += 1
                continue
            point_id = str(uuid.uuid5(QDRANT_UUID_NAMESPACE, req["requirement_id"]))
            points.append(models.PointStruct(
                id=point_id,
                vector={"dense": dense_emb, "sparse": sparse_emb},
                payload=build_payload(req, embedding_model, len(dense_emb)),
            ))

        total_skipped += batch_skipped
        if not points:
            continue

        client.upsert(collection_name=collection_name, points=points)
        total_indexed += len(points)
        log.info("Indexed %d/%d requirements", total_indexed, len(requirements))

    elapsed = time.time() - start

    if total_skipped:
        log.warning("%d requirements skipped due to embedding failures", total_skipped)

    collection_info = client.get_collection(collection_name)
    log.info(
        "Done: %d requirements indexed in %.1fs — collection has %d points",
        total_indexed, elapsed, collection_info.points_count,
    )
    return total_indexed


def _positive_int(value: str) -> int:
    """Argparse type: integer that must be > 0."""
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: '{value}'")
    if iv <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return iv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed requirements and index into Qdrant"
    )
    parser.add_argument(
        "requirements_jsonl",
        type=str,
        help="Path to requirements_normalized.jsonl from Step D",
    )
    parser.add_argument(
        "--qdrant-url",
        type=str,
        default="http://localhost:6333",
        help="Qdrant HTTP API URL (default: http://localhost:6333)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama API base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate the Qdrant collection (use for full reindex only)",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default=COLLECTION_NAME,
        help=f"Qdrant collection name (default: {COLLECTION_NAME})",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=32,
        help="Number of requirements to embed per batch (default: 32)",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default=EMBEDDING_MODEL,
        help=f"Ollama embedding model (default: {EMBEDDING_MODEL})",
    )
    args = parser.parse_args()

    reqs_path = Path(args.requirements_jsonl).resolve()
    if not reqs_path.exists():
        log.error("Input file not found: %s", reqs_path)
        sys.exit(1)

    try:
        run(
            str(reqs_path),
            qdrant_url=args.qdrant_url,
            ollama_url=args.ollama_url,
            recreate=args.recreate,
            collection_name=args.collection_name,
            batch_size=args.batch_size,
            embedding_model=args.embedding_model,
        )
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
