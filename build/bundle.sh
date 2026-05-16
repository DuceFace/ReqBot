#!/usr/bin/env bash
# build/bundle.sh — Assemble the ReqBot bundle for Linux x86_64
#
# Produces: build/linux-x86_64/  (self-contained, runnable tree)
# Test:     build/linux-x86_64/reqbot ask "test"
#
# Run from anywhere; paths are resolved relative to this script.
# The Python tarball is cached in build/.cache/ to avoid re-downloading.
set -euo pipefail

# ---------------------------------------------------------------
# Host arch check — the bundled Python binary is Linux x86_64 only.
# Running pip on an ARM or macOS host produces "Exec format error".
# ---------------------------------------------------------------
if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
    echo "[-] Error: bundle.sh requires a Linux x86_64 host." >&2
    echo "    Detected: $(uname -s) $(uname -m)" >&2
    echo "    The bundled CPython binary cannot execute on this architecture." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE_DIR="$SCRIPT_DIR/linux-x86_64"
CACHE_DIR="$SCRIPT_DIR/.cache"

# --- Pinned versions ---
PYTHON_VERSION="3.12.13"
PYTHON_RELEASE="20260303"
PYTHON_FILENAME="cpython-${PYTHON_VERSION}+${PYTHON_RELEASE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_RELEASE}/${PYTHON_FILENAME}"
PYTHON_SHA256="c710dd6b63e4df92f4c5b7b29ccad4276226a024a9017d5018f15321c7854af4"

# Application source files to bundle (paths relative to repo root)
APP_FILES=(
    cli/reqbot.py
    cli/console.py
    cli/__init__.py
    core/config.py
    core/constants.py
    core/synthesis.py
    core/ask.py
    core/__init__.py
    pipeline/run_pipeline.py
    pipeline/extract_pdf_to_text.py
    pipeline/chunk_text.py
    pipeline/section_parser.py
    pipeline/llm_extract_requirements.py
    pipeline/parse_and_normalize.py
    pipeline/enrich_requirements.py
    pipeline/aggregate_and_export.py
    pipeline/embed_and_index.py
    pipeline/embed_context_index.py
    pipeline/__init__.py
    services/__init__.py
    services/ask_service.py
    services/status_service.py
    services/docs_service.py
    services/trace_service.py
    services/compare_service.py
    services/evidence_service.py
    api/__init__.py
    api/app.py
    api/routes/__init__.py
    api/routes/ask.py
    api/routes/docs.py
    api/routes/status.py
    api/routes/trace.py
    models/__init__.py
)

BUNDLED_PYTHON="$BUNDLE_DIR/python/bin/python3"

echo "=== ReqBot bundle assembly (Linux x86_64) ==="
echo ""

# ---------------------------------------------------------------
# Step 1: Prepare directory tree
# ---------------------------------------------------------------
echo "[1/5] Preparing bundle directories..."
# Always start clean so stale files from prior runs do not survive into the
# new bundle. The .cache/ dir is preserved separately to avoid re-downloading
# the Python tarball on every run.
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR/python" "$BUNDLE_DIR/app" "$BUNDLE_DIR/models"
mkdir -p "$CACHE_DIR"

# ---------------------------------------------------------------
# Step 2: Fetch portable Python
# ---------------------------------------------------------------
echo "[2/5] Fetching portable CPython ${PYTHON_VERSION}..."
PYTHON_CACHE="$CACHE_DIR/$PYTHON_FILENAME"

if [ -f "$PYTHON_CACHE" ]; then
    echo "  Using cached $PYTHON_FILENAME"
else
    echo "  Downloading $PYTHON_FILENAME (~32 MB)..."
    curl -fL --progress-bar "$PYTHON_URL" -o "$PYTHON_CACHE"
fi

echo "  Verifying SHA256..."
echo "${PYTHON_SHA256}  ${PYTHON_CACHE}" | sha256sum -c --status
echo "  SHA256 OK"

echo "  Extracting to $BUNDLE_DIR/python/..."
# python-build-standalone install_only tarballs always contain a top-level
# 'python/' directory — strip that component and extract directly into python/.
tar -xzf "$PYTHON_CACHE" -C "$BUNDLE_DIR/python/" --strip-components=1
echo "  Python extracted: $("$BUNDLED_PYTHON" --version)"

# ---------------------------------------------------------------
# Step 3: Install Python dependencies
# ---------------------------------------------------------------
echo "[3/5] Installing Python dependencies..."
# Upgrade pip first (bundled pip may be older)
"$BUNDLED_PYTHON" -m pip install --upgrade pip --quiet --disable-pip-version-check

# Install all required packages into the bundled Python's site-packages.
# Pinned to the exact versions running on the build machine.
"$BUNDLED_PYTHON" -m pip install \
    "pymupdf==1.27.1" \
    "pdfplumber==0.11.9" \
    "fastembed==0.7.4" \
    "qdrant-client==1.17.0" \
    "ollama==0.6.1" \
    "requests==2.32.5" \
    "fastapi==0.115.12" \
    "uvicorn==0.34.3" \
    --quiet --disable-pip-version-check

echo "  Dependencies installed"

# ---------------------------------------------------------------
# Step 4: Pre-seed fastembed BM25 model cache
# ---------------------------------------------------------------
echo "[4/5] Pre-seeding fastembed BM25 model cache..."
# fastembed defaults to /tmp/fastembed_cache/ (wiped on reboot).
# We force it to download into our models/ directory so the bundle is
# air-gap capable. The launcher sets FASTEMBED_CACHE_PATH at runtime.
FASTEMBED_CACHE_PATH="$BUNDLE_DIR/models" \
    "$BUNDLED_PYTHON" -c "
from fastembed import SparseTextEmbedding
import os
print('  Downloading Qdrant/bm25 model...')
SparseTextEmbedding(model_name='Qdrant/bm25')
cache = os.environ['FASTEMBED_CACHE_PATH']
print(f'  Model cached in: {cache}')
"
echo "  BM25 model ready"

# ---------------------------------------------------------------
# Step 5: Copy application source
# ---------------------------------------------------------------
echo "[5/5] Copying application source..."
for f in "${APP_FILES[@]}"; do
    src="$ROOT_DIR/$f"
    if [ ! -f "$src" ]; then
        echo "  ERROR: expected source file not found: $src" >&2
        exit 1
    fi
    dst="$BUNDLE_DIR/app/$f"
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  + $f"
done

# ---------------------------------------------------------------
# Write launcher script
# ---------------------------------------------------------------
echo ""
echo "Writing launcher script..."
cat > "$BUNDLE_DIR/reqbot" << 'LAUNCHER_SCRIPT'
#!/usr/bin/env bash
# ReqBot launcher — sets environment and execs the bundled Python.
# This script is self-relative: REQBOT_HOME is always the directory
# containing this script, whether run from build/linux-x86_64/ (testing)
# or from ~/.reqbot/ (installed).
REQBOT_HOME="$(cd "$(dirname "$0")" && pwd)"

# Point fastembed at the bundled model cache so it never reaches out to
# HuggingFace — required for air-gapped environments.
export FASTEMBED_CACHE_PATH="$REQBOT_HOME/models"

exec "$REQBOT_HOME/python/bin/python3" "$REQBOT_HOME/app/cli/reqbot.py" "$@"
LAUNCHER_SCRIPT

chmod +x "$BUNDLE_DIR/reqbot"

# ---------------------------------------------------------------
# Smoke test — verify the bundle works before declaring success
# ---------------------------------------------------------------
echo ""
echo "Running smoke test..."
if "$BUNDLE_DIR/reqbot" --help > /dev/null 2>&1; then
    echo "  reqbot --help  OK"
else
    echo "  ERROR: reqbot --help failed — bundle is broken" >&2
    exit 1
fi

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo ""
echo "=== Bundle complete ==="
echo ""
echo "Location : $BUNDLE_DIR"
echo "Size     : $(du -sh "$BUNDLE_DIR" | cut -f1)"
echo ""
echo "Manual milestone gate:"
echo "  $BUNDLE_DIR/reqbot ask 'what are the password requirements?'"
echo ""
