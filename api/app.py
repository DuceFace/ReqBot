"""ReqBot FastAPI application — read-only API (Phase 16C).

Start with: reqbot serve [--host 0.0.0.0] [--port 8000]

Endpoints:
  GET  /status           — Ollama + Qdrant health checks + processed doc listing
  POST /ask              — Hybrid vector search with optional synthesis
  GET  /trace/{req_id}   — Full requirement provenance by ID
  GET  /docs             — Indexed document listing

Swagger UI is at /api-docs (moved from default /docs to avoid endpoint collision).
"""
import sys
from pathlib import Path

# Ensure repo root is on sys.path when the app module is imported directly.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import ask, docs, status, trace

app = FastAPI(
    title="ReqBot API",
    version="0.1.0",
    description="Read-only compliance requirements intelligence API.",
    docs_url="/api-docs",
    redoc_url="/api-redoc",
)

# CORS — restricted to known local GUI origins.
# Extend this list when deploying a hosted frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(status.router)
app.include_router(ask.router)
app.include_router(trace.router)
app.include_router(docs.router)
