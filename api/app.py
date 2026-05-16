"""ReqBot FastAPI application — Phase 18: API prefix + static file serving.

Start with: reqbot serve [--host 0.0.0.0] [--port 8000]

Endpoints (all prefixed /api/):
  GET  /api/status           — Ollama + Qdrant health checks + processed doc listing
  POST /api/ask              — Hybrid vector search with optional synthesis
  GET  /api/trace/{req_id}   — Full requirement provenance by ID
  GET  /api/docs             — Indexed document listing

GUI (when frontend/dist/ is built):
  GET  /{any}                — catch-all: serves real file if it exists in dist/,
                               otherwise index.html (React Router handles routing)

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
# Registered after all /api/ routes so it never shadows an API endpoint.
#
# The catch-all checks whether the requested path maps to a real file under
# dist/ first (favicon.ico, robots.txt, assets/*.js, assets/*.css, etc.).
# If it does, serve that file. Otherwise serve index.html so React Router
# handles the client-side route (/search, /trace/:id, etc.).
#
# A resolved-path check guards against directory traversal: only files that
# actually live under _DIST_DIR are served directly.
_INDEX_HTML = _DIST_DIR / "index.html"
_DIST_DIR_RESOLVED = _DIST_DIR.resolve()

if _INDEX_HTML.exists():
    from fastapi.responses import FileResponse as _FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> _FileResponse:
        candidate = (_DIST_DIR / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(_DIST_DIR_RESOLVED):
            return _FileResponse(str(candidate))
        return _FileResponse(str(_INDEX_HTML))

else:
    log.info("Frontend build not found; serving API only")
