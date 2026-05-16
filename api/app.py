"""ReqBot FastAPI application — Phase 18: API prefix + static file serving.

Start with: reqbot serve [--host 0.0.0.0] [--port 8000]

Endpoints (all prefixed /api/):
  GET  /api/status           — Ollama + Qdrant health checks + processed doc listing
  POST /api/ask              — Hybrid vector search with optional synthesis
  GET  /api/trace/{req_id}   — Full requirement provenance by ID
  GET  /api/docs             — Indexed document listing

GUI (when frontend/dist/ is built):
  GET  /assets/*             — Vite-built JS/CSS assets (StaticFiles mount)
  GET  /{any}                — index.html catch-all; React Router handles client-side routing

Swagger UI is at /api-docs.
"""
import logging
import sys
from pathlib import Path

# Ensure repo root is on sys.path when the app module is imported directly.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import ask, docs, status, trace

log = logging.getLogger(__name__)

# Resolve frontend dist path relative to this file.
# Works identically in a dev checkout and the installed bundle because the
# bundler preserves this relative structure (api/app.py → frontend/dist/).
_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

app = FastAPI(
    title="ReqBot API",
    version="0.2.0",
    description="Read-only compliance requirements intelligence API.",
    docs_url="/api-docs",
    redoc_url="/api-redoc",
)

# CORS — restricted to known local GUI origins.
# :5173 added for Vite dev server (Phase 18).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# API routes — all under /api/ prefix so they don't shadow SPA client-side routes.
app.include_router(status.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(trace.router, prefix="/api")
app.include_router(docs.router, prefix="/api")

# SPA static file serving — only when the frontend build exists.
# StaticFiles(html=True) serves index.html for directory requests but does NOT
# serve it for arbitrary missing paths like /search or /trace/REQ-xxx (Starlette
# documented behaviour). We therefore use two steps:
#
#   1. Mount StaticFiles at /assets for Vite's JS/CSS bundles. This mount is
#      registered before the catch-all, so /assets/* requests hit it first.
#   2. Register a /{full_path:path} catch-all route that returns index.html,
#      giving React Router full control over client-side navigation.
#
# Both are registered after all /api/ routes so neither shadows any API endpoint.
_INDEX_HTML = _DIST_DIR / "index.html"
if _INDEX_HTML.exists():
    if (_DIST_DIR / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_DIST_DIR / "assets")),
            name="assets",
        )

    from fastapi.responses import FileResponse as _FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> _FileResponse:
        return _FileResponse(str(_INDEX_HTML))

else:
    log.info("Frontend build not found; serving API only")
