#!/usr/bin/env bash
# build/build-frontend.sh — Build the React frontend into frontend/dist/
#
# Runs npm ci (clean install from lockfile) then npm run build (Vite production build).
# Output lands in frontend/dist/ — the path api/app.py resolves to at runtime.
#
# Run from anywhere; paths are resolved relative to this script.
# Requires Node.js 20+ and npm on the PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"

echo "[+] Building frontend (Vite + React + Tailwind)..."
cd "$FRONTEND_DIR"
npm ci
npm run build
echo "[+] Frontend built → frontend/dist/"
