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

if ! command -v npm >/dev/null 2>&1; then
    echo "[-] npm not found on PATH." >&2
    echo "    Install Node.js 20 LTS or newer (npm is bundled with it): https://nodejs.org/" >&2
    exit 1
fi

if ! command -v node >/dev/null 2>&1; then
    echo "[-] node not found on PATH." >&2
    echo "    Install Node.js 20 LTS or newer: https://nodejs.org/" >&2
    exit 1
fi

NODE_MAJOR="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
if [ "$NODE_MAJOR" -lt 20 ]; then
    echo "[-] Node $(node --version) found, this project requires Node 20 LTS or newer." >&2
    echo "    Install Node.js 20 LTS or newer: https://nodejs.org/" >&2
    exit 1
fi

echo "[+] Building frontend (Vite + React + Tailwind)..."
cd "$FRONTEND_DIR"
npm ci
npm run build
echo "[+] Frontend built → frontend/dist/"
