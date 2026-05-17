"""POST /compare — cross-framework requirement comparison on a topic."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core import config as _config
from services import compare_service
from services.docs_service import resolve_source_pdfs

router = APIRouter()


class CompareRequest(BaseModel):
    doc_id_1: str
    doc_id_2: str
    topic: str
    top_k: int = Field(default=10, ge=1, le=100)


def _canonical(doc_key: str, resolved: dict[str, str]) -> str:
    """Return canonical source_pdf; fall back to doc_key + '.pdf' if unresolved."""
    pdf = resolved.get(doc_key, "")
    if pdf:
        return pdf
    # caller may have passed source_pdf directly
    if doc_key.lower().endswith(".pdf"):
        return doc_key
    return doc_key + ".pdf"


@router.post("/compare")
def post_compare(req: CompareRequest) -> dict:
    """Compare requirements from two documents on a topic.

    Returns the compare_service result with canonical source_pdf values echoed:
      doc_id_1:   first document key (from request)
      doc_id_2:   second document key (from request)
      doc_pdf_1:  canonical source_pdf value for doc_id_1 (key in ref_groups)
      doc_pdf_2:  canonical source_pdf value for doc_id_2 (key in ref_groups)
      query:      the topic string
      mode:       "exact" | "semantic"

      For semantic mode:
        ref_order:   list of source_ref strings in rank order
        ref_groups:  dict[source_ref, dict[source_pdf, payload]]
                     Use doc_pdf_1 / doc_pdf_2 to split into three sections:
                       both docs  → source_ref appears under both source_pdf keys
                       doc1 only  → source_ref appears only under doc_pdf_1
                       doc2 only  → source_ref appears only under doc_pdf_2

      For exact mode:
        source_ref:  the matched control ID
        groups:      dict[source_pdf, payload]
    """
    cfg = _config.load()

    # Resolve canonical source_pdf values from JSONL — reads only the first
    # record of each matching file, so cost is O(1) per requested document.
    try:
        resolved = resolve_source_pdfs(
            cfg.processed_dir_path(), [req.doc_id_1, req.doc_id_2]
        )
    except Exception:
        resolved = {}

    doc_pdf_1 = _canonical(req.doc_id_1, resolved)
    doc_pdf_2 = _canonical(req.doc_id_2, resolved)

    try:
        result = compare_service.compare(
            query=req.topic,
            qdrant_url=cfg.qdrant_url,
            ollama_url=cfg.ollama_url,
            top_k=req.top_k,
            doc_keys=[doc_pdf_1, doc_pdf_2],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Unexpected backend error: {e}")

    result["doc_id_1"] = req.doc_id_1
    result["doc_id_2"] = req.doc_id_2
    result["doc_pdf_1"] = doc_pdf_1
    result["doc_pdf_2"] = doc_pdf_2
    return result
