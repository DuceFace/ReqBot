#!/usr/bin/env bash
# build/build-frontend.sh — Build the React frontend into frontend/dist/
#
# Runs npm ci (clean install from lockfile) then npm run build (Vite production build).
# Output lands in frontend/dist/ — the path api/app.py resolves to at runtime.
#
# Run from anywhere; paths are resolved relative to this script.
# Requires Node.js 20.19+ or 22.12+ and npm on the PATH (Vite 8's minimum).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"

if ! command -v npm >/dev/null 2>&1; then
    echo "[-] npm not found on PATH." >&2
    echo "    Install Node.js 20.19+ or 22.12+ (npm is bundled with it): https://nodejs.org/" >&2
    exit 1
fi

if ! command -v node >/dev/null 2>&1; then
    echo "[-] node not found on PATH." >&2
    echo "    Install Node.js 20.19+ or 22.12+: https://nodejs.org/" >&2
    exit 1
fi

NODE_VERSION="$(node --version | sed -E 's/^v//')"
NODE_MAJOR="$(echo "$NODE_VERSION" | cut -d. -f1)"
NODE_MINOR="$(echo "$NODE_VERSION" | cut -d. -f2)"
if [ "$NODE_MAJOR" -lt 20 ] || [ $((NODE_MAJOR % 2)) -ne 0 ] || \
   { [ "$NODE_MAJOR" -eq 20 ] && [ "$NODE_MINOR" -lt 19 ]; } || \
   { [ "$NODE_MAJOR" -eq 22 ] && [ "$NODE_MINOR" -lt 12 ]; }; then
    echo "[-] Node $(node --version) found. This project requires Node 20.19+ or 22.12+ (Vite 8's floor) — odd-numbered releases (Node's non-LTS lines: 21.x, 23.x, 25.x, ...) and earlier 20.x/22.x patches aren't supported." >&2
    echo "    Install Node.js 20.19+ or 22.12+ LTS: https://nodejs.org/" >&2
    exit 1
fi

echo "[+] Building frontend (Vite + React + Tailwind)..."
cd "$FRONTEND_DIR"
npm ci
npm run build
echo "[+] Frontend built → frontend/dist/"
