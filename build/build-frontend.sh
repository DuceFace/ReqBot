#!/usr/bin/env bash
# build/build-frontend.sh — Build the React frontend into frontend/dist/
#
# Standard, supported path: npm ci (clean install from lockfile) + npm run build
# (Vite production build). Requires Node.js 20+ and npm on the PATH — this is
# the real prerequisite for building ReqBot's frontend.
#
# Fallback (constrained dev containers only, e.g. some Coder/VS-Code-Server
# workspaces that bundle a node binary but expose no npm and don't put node on
# PATH): if npm is missing but frontend/node_modules/ already exists and a
# usable node binary can be found, run the local project's tsc/vite binaries
# directly via that node. This is NOT a substitute for `npm ci` — it does not
# verify node_modules/ matches package-lock.json, it just uses what's there.
#
# Never attempts to install Node/npm itself. If neither the standard path nor
# the fallback is usable, this script fails with a clear message rather than
# guessing.
#
# Output lands in frontend/dist/ — the path api/app.py resolves to at runtime.
# Run from anywhere; paths are resolved relative to this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"

cd "$FRONTEND_DIR"
echo "[+] Building frontend (Vite + React + Tailwind)..."

if command -v npm >/dev/null 2>&1; then
    echo "    npm found on PATH — using the standard build path."
    npm ci
    npm run build
    echo "[+] Frontend built → frontend/dist/"
    exit 0
fi

echo "    npm not found on PATH."

if [ ! -d node_modules ]; then
    echo "[-] npm not found and frontend/node_modules/ does not exist." >&2
    echo "    Install Node.js 20+ and npm (https://nodejs.org/), then re-run this script." >&2
    echo "    This script does not install Node/npm for you." >&2
    exit 1
fi

echo "    frontend/node_modules/ exists — attempting the constrained-container fallback"
echo "    (direct node invocation, not a substitute for 'npm ci')."

# Resolution order: explicit override > node already on PATH > a small set of
# optional, version-agnostic heuristics for bundled-node dev containers.
# Deliberately no hardcoded exact version strings (e.g. a specific VS Code
# Server release) — those go stale the moment the bundling tool updates.
NODE_BIN="${REQBOT_BUILD_NODE:-}"

if [ -z "$NODE_BIN" ] && command -v node >/dev/null 2>&1; then
    NODE_BIN="$(command -v node)"
    echo "    Found node on PATH: $NODE_BIN"
fi

if [ -z "$NODE_BIN" ]; then
    CANDIDATES="$(
        {
            find "$HOME/.vscode-server" -maxdepth 6 -type f -iname "node" -perm -u+x 2>/dev/null
            find /tmp/code-server -maxdepth 4 -type f -iname "node" -perm -u+x 2>/dev/null
        } | sort -u
    )"
    CANDIDATE_COUNT=$(printf '%s\n' "$CANDIDATES" | grep -c . || true)
    if [ "$CANDIDATE_COUNT" -eq 1 ]; then
        NODE_BIN="$CANDIDATES"
        echo "    Found a bundled node binary (no npm alongside it): $NODE_BIN"
    elif [ "$CANDIDATE_COUNT" -gt 1 ]; then
        echo "[-] npm not found, and multiple bundled node binaries were found — ambiguous:" >&2
        printf '%s\n' "$CANDIDATES" >&2
        echo "    Set REQBOT_BUILD_NODE=/path/to/node to pick one explicitly." >&2
        exit 1
    fi
fi

if [ -z "$NODE_BIN" ] || [ ! -x "$NODE_BIN" ]; then
    echo "[-] npm not found and no usable node binary found (checked PATH, REQBOT_BUILD_NODE," >&2
    echo "    ~/.vscode-server, /tmp/code-server)." >&2
    echo "    Install Node.js 20+ and npm, or set REQBOT_BUILD_NODE=/path/to/node if you have" >&2
    echo "    a bundled node available somewhere else." >&2
    exit 1
fi

echo "    Using: $NODE_BIN"
"$NODE_BIN" node_modules/.bin/tsc
"$NODE_BIN" node_modules/.bin/vite build
echo "[+] Frontend built → frontend/dist/ (fallback path — re-run with real npm when possible)"
