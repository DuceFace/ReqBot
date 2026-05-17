"""POST /compare — cross-framework requirement comparison on a topic."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core import config as _config
from services import compare_service

router = APIRouter()


class CompareRequest(BaseModel):
    doc_id_1: str
    doc_id_2: str
    topic: str
    top_k: int = Field(default=10, ge=1, le=100)


@router.post("/compare")
def post_compare(req: CompareRequest) -> dict:
    """Compare requirements from two documents on a topic.

    Returns the compare_service result with the two input doc IDs echoed back:
      doc_id_1:  first document ID (from request)
      doc_id_2:  second document ID (from request)
      query:     the topic string
      mode:      "exact" | "semantic"

      For semantic mode:
        ref_order:   list of source_ref strings in rank order
        ref_groups:  dict[source_ref, dict[doc_key, payload]]
                     Payloads include document_id — use it to determine
                     which input doc_id each result belongs to.

      For exact mode:
        source_ref:  the matched control ID
        groups:      dict[doc_key, payload]
    """
    cfg = _config.load()
    try:
        result = compare_service.compare(
            query=req.topic,
            qdrant_url=cfg.qdrant_url,
            ollama_url=cfg.ollama_url,
            top_k=req.top_k,
            doc_keys=[req.doc_id_1, req.doc_id_2],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Unexpected backend error: {e}")

    result["doc_id_1"] = req.doc_id_1
    result["doc_id_2"] = req.doc_id_2
    return result
