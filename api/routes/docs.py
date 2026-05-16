"""GET /docs — indexed document listing from the processed JSONL directory."""
from fastapi import APIRouter, HTTPException

from core import config as _config
from services import docs_service

router = APIRouter()


@router.get("/docs")
def get_docs() -> dict:
    """Return the list of indexed documents with requirement counts and metadata.

    Returns:
      docs:       list of {doc_key, path, count, mode, run_date}
      total_reqs: total requirement count across all documents
      total_docs: number of unique documents
    """
    cfg = _config.load()
    try:
        return docs_service.list_docs(cfg.processed_dir_path())
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
