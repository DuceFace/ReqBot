# ReqBot — production image
#
# Multi-stage build:
#   1. frontend — pinned node:20 image builds frontend/dist/. Anyone building this
#      image never needs Node/npm on their own host, regardless of what a bare
#      source/dev checkout requires (see build/build-frontend.sh).
#   2. runtime  — installs the reqbot package (with the docling extra) and copies
#      the built frontend in as package data.
#
# This image does not install, start, or manage Qdrant or Ollama — point it at
# existing instances via REQBOT_QDRANT_URL / REQBOT_OLLAMA_URL (see
# docker-compose.example.yml).

FROM node:20-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

COPY pyproject.toml MANIFEST.in README.md ./
COPY api/ ./api/
COPY cli/ ./cli/
COPY core/ ./core/
COPY mcp_server/ ./mcp_server/
COPY models/ ./models/
COPY pipeline/ ./pipeline/
COPY profiles/ ./profiles/
COPY services/ ./services/
COPY frontend/__init__.py ./frontend/__init__.py
COPY --from=frontend /frontend/dist ./frontend/dist

RUN pip install --no-cache-dir ".[docling]"

EXPOSE 8000
CMD ["reqbot", "serve", "--host", "0.0.0.0", "--port", "8000"]
