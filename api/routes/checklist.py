"""Checklist API routes — POST /checklist, POST /checklist/export, GET /profiles."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core import config as _config
from core.profiles import list_profiles
from pipeline import checklist_export
from services import checklist_service

router = APIRouter()

_EXPORT_CONTENT_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "markdown": "text/markdown",
}
_EXPORT_EXTENSIONS = {
    "csv": "csv",
    "json": "json",
    "markdown": "md",
}


class ChecklistRequest(BaseModel):
    doc_key: str
    profile: str = Field(default="cybersecurity")


class ChecklistExportRequest(BaseModel):
    doc_key: str
    profile: str = Field(default="cybersecurity")
    format: str = Field(default="csv")


def _generate(doc_key: str, profile: str) -> dict:
    """Call checklist_service.generate(), mapping exceptions to HTTP errors."""
    cfg = _config.load()
    processed_dir = cfg.processed_dir_path()
    try:
        return checklist_service.generate(processed_dir, doc_key, profile)
    except FileNotFoundError as e:
        msg = str(e)
        if "Profile not found" in msg:
            raise HTTPException(status_code=400, detail=msg)
        if "processed_dir not found" in msg:
            raise HTTPException(status_code=503, detail=f"Server configuration error: {msg}")
        raise HTTPException(status_code=503, detail=f"Internal server error: {msg}")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/profiles")
def get_profiles() -> dict:
    """List available profile names from the profiles/ directory."""
    return {"profiles": list_profiles()}


@router.post("/checklist")
def post_checklist(req: ChecklistRequest) -> dict:
    """Generate a checklist for a document and profile.

    Returns the full checklist envelope from checklist_service.generate().
    """
    return _generate(req.doc_key, req.profile)


@router.post("/checklist/export")
def post_checklist_export(req: ChecklistExportRequest) -> Response:
    """Generate and export a checklist as CSV, JSON, or Markdown.

    Returns the file content with Content-Disposition: attachment for browser download.
    """
    fmt = req.format.lower()
    if fmt not in _EXPORT_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{req.format}'. Valid values: csv, json, markdown.",
        )

    checklist = _generate(req.doc_key, req.profile)

    if fmt == "csv":
        content = checklist_export.to_csv(checklist)
    elif fmt == "json":
        content = checklist_export.to_json(checklist)
    else:
        content = checklist_export.to_markdown(checklist)

    ext = _EXPORT_EXTENSIONS[fmt]
    filename = f"{req.doc_key}_{req.profile}.{ext}"
    return Response(
        content=content,
        media_type=_EXPORT_CONTENT_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
