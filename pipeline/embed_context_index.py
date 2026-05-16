#!/usr/bin/env python3
"""Step F2: Embed raw text chunks and index into Qdrant grc_context collection.

Input:  <stem>_chunks.jsonl (from Step B)
Output: Qdrant collection "grc_context" — one point per chunk

This is the companion to embed_and_index.py (Step F). Together they build
two collections:
  - grc_requirements: extracted, normalized obligation statements (Step F)
  - grc_context:      raw surrounding chunk text for explanatory context (Step F2)

ask.py --context uses grc_context to retrieve the source chunk for each
matched requirement and feed both to the synthesis LLM.

Point IDs are derived from uuid5(CONTEXT_UUID_NAMESPACE, "{document_id}:{chunk_id}").
The namespace UUID must never change, or all existing point IDs become invalid.
It must also match CONTEXT_UUID_NAMESPACE in ask.py.

grc_context is a rebuildable index — chunks.jsonl is the system of record.
"""

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

# Ensure repo root is on sys.path when run as a standalone script from pipeline/.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import ollama
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models

from core import constants as _const

# Canonical source is core/constants.py — imported above.
CONTEXT_UUID_NAMESPACE = _const.CONTEXT_UUID_NS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

COLLECTION_NAME = "grc_context"
EMBEDDING_MODEL = "nomic-embed-text"
SPARSE_MODEL = "Qdrant/bm25"
VECTOR_DIM = 768


def load_jsonl(path: Path) -> list[dict]:
    """Load records from a JSONL file."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def ensure_collection(client: QdrantClient, collection_name: str, recreate: bool) -> None:
    """Create or recreate the Qdrant collection."""
    exists = client.collection_exists(collection_name)

    if exists and recreate:
        log.info("Recreating collection '%s'", collection_name)
        client.delete_collection(collection_name)
        exists = False

    if not exists:
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=VECTOR_DIM,
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
            collection_name, VECTOR_DIM,
        )
    else:
        log.info("Collection '%s' already exists, will upsert", collection_name)


def embed_batch(texts: list[str], client: ollama.Client) -> list[list[float]]:
    """Embed a batch of texts using Ollama (dense vectors)."""
    result = client.embed(model=EMBEDDING_MODEL, input=texts)
    return result.embeddings


def embed_sparse_batch(texts: list[str], model: SparseTextEmbedding) -> list[models.SparseVector]:
    """Generate sparse BM25 vectors for a batch of texts."""
    return [
        models.SparseVector(indices=emb.indices.tolist(), values=emb.values.tolist())
        for emb in model.embed(texts)
    ]


def run(
    chunks_jsonl: str,
    *,
    document_id: str | None = None,
    source_pdf: str = "",
    qdrant_url: str = "http://localhost:6333",
    ollama_url: str = "http://localhost:11434",
    recreate: bool = False,
    collection_name: str = COLLECTION_NAME,
    batch_size: int = 32,
) -> int:
    """Embed text chunks and index into Qdrant grc_context.

    Callable interface for in-process use by reqbot.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Args:
        chunks_jsonl:    Path to <stem>_chunks.jsonl from Step B.
        document_id:     Document identifier. Derived from filename if None.
        source_pdf:      Source PDF filename for payload display.
        qdrant_url:      Qdrant HTTP API URL.
        ollama_url:      Ollama API base URL.
        recreate:        Drop and recreate the collection if True.
        collection_name: Qdrant collection name.
        batch_size:      Chunks per embedding batch.

    Returns:
        Number of chunks successfully indexed.
    """
    chunks_path = Path(chunks_jsonl).resolve()

    if not document_id:
        stem = chunks_path.stem
        document_id = stem[:-len("_chunks")] if stem.endswith("_chunks") else stem
        log.info("Derived document_id: %s", document_id)

    source_pdf = source_pdf or chunks_path.name

    log.info("Loading chunks from: %s", chunks_path)
    chunks = load_jsonl(chunks_path)
    log.info("Loaded %d chunks", len(chunks))

    if not chunks:
        log.warning("No chunks to index")
        return 0

    ollama_client = ollama.Client(host=ollama_url)
    log.info("Using Ollama at: %s", ollama_url)

    log.info("Loading sparse embedding model: %s", SPARSE_MODEL)
    sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL)

    client = QdrantClient(url=qdrant_url)
    ensure_collection(client, collection_name, recreate)

    start = time.time()
    total_indexed = 0
    total_skipped = 0

    for batch_start in range(0, len(chunks), batch_size):
        batch = chunks[batch_start:batch_start + batch_size]
        # Truncate to 1500 chars before embedding — nomic-embed-text has a 2048 token
        # context limit, and TOC/table chunks with dense dot leaders can hit ~1:1 char:token
        # ratio, making 3000-char chunks exceed the limit. Full text is stored in the
        # payload; only the embedding vector is affected.
        texts = [c["text"][:1500] for c in batch]

        # Dense embed — None marks a failed item
        try:
            dense_embeddings = embed_batch(texts, ollama_client)
        except Exception as e:
            log.error("Dense batch failed at offset %d: %s — falling back to individual", batch_start, e)
            dense_embeddings = []
            for text in texts:
                try:
                    result = ollama_client.embed(model=EMBEDDING_MODEL, input=text)
                    dense_embeddings.append(result.embeddings[0])
                except Exception as e2:
                    log.error("Individual dense embed failed: %s — item will be skipped", e2)
                    dense_embeddings.append(None)

        # Sparse embed — None marks a failed item
        try:
            sparse_embeddings = embed_sparse_batch(texts, sparse_model)
        except Exception as e:
            log.error("Sparse batch failed at offset %d: %s — falling back to individual", batch_start, e)
            sparse_embeddings = []
            for text in texts:
                try:
                    embs = list(sparse_model.embed([text]))
                    sparse_embeddings.append(
                        models.SparseVector(
                            indices=embs[0].indices.tolist(),
                            values=embs[0].values.tolist(),
                        )
                    )
                except Exception as e2:
                    log.error("Individual sparse embed failed: %s — item will be skipped", e2)
                    sparse_embeddings.append(None)

        # Build points — skip any item where either embedding failed
        points = []
        batch_skipped = 0
        for chunk, dense_emb, sparse_emb in zip(batch, dense_embeddings, sparse_embeddings):
            if dense_emb is None or sparse_emb is None:
                log.warning("Skipping chunk %s — embedding failed", chunk.get("chunk_id", "?"))
                batch_skipped += 1
                continue
            point_id = str(uuid.uuid5(
                CONTEXT_UUID_NAMESPACE,
                f"{document_id}:{chunk['chunk_id']}",
            ))
            points.append(models.PointStruct(
                id=point_id,
                vector={"dense": dense_emb, "sparse": sparse_emb},
                payload={
                    "document_id": document_id,
                    "source_pdf": source_pdf,
                    "chunk_id": chunk["chunk_id"],
                    "page_start": chunk.get("page_start"),
                    "page_end": chunk.get("page_end"),
                    "text": chunk["text"],
                },
            ))

        total_skipped += batch_skipped
        if not points:
            continue

        client.upsert(collection_name=collection_name, points=points)
        total_indexed += len(points)
        log.info("Indexed %d/%d chunks", total_indexed, len(chunks))

    elapsed = time.time() - start

    if total_skipped:
        log.warning("%d chunks skipped due to embedding failures", total_skipped)

    collection_info = client.get_collection(collection_name)
    log.info(
        "Done: %d chunks indexed in %.1fs — collection has %d points",
        total_indexed, elapsed, collection_info.points_count,
    )
    return total_indexed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed text chunks and index into Qdrant grc_context"
    )
    parser.add_argument(
        "chunks_jsonl",
        type=str,
        help="Path to <stem>_chunks.jsonl from Step B",
    )
    parser.add_argument(
        "--document-id",
        type=str,
        default=None,
        help="Document identifier (default: derived from filename, e.g. 'NIST.SP.800-53')",
    )
    parser.add_argument(
        "--source-pdf",
        type=str,
        default="",
        help="Source PDF filename for display (default: derived from chunks filename)",
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
        help="Drop and recreate the collection (use for first index of a new schema only)",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default=COLLECTION_NAME,
        help=f"Qdrant collection name (default: {COLLECTION_NAME})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Number of chunks to embed per batch (default: 32)",
    )
    args = parser.parse_args()

    chunks_path = Path(args.chunks_jsonl).resolve()
    if not chunks_path.exists():
        log.error("Input file not found: %s", chunks_path)
        sys.exit(1)

    try:
        run(
            str(chunks_path),
            document_id=args.document_id,
            source_pdf=args.source_pdf,
            qdrant_url=args.qdrant_url,
            ollama_url=args.ollama_url,
            recreate=args.recreate,
            collection_name=args.collection_name,
            batch_size=args.batch_size,
        )
    except RuntimeError as e:
        log.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
