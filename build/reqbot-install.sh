#!/usr/bin/env bash
# reqbot-install.sh — Self-extracting installer for ReqBot (Linux x86_64)
#
# Usage:
#   ./reqbot-install.sh              # Fresh install to ~/.reqbot/
#   ./reqbot-install.sh --upgrade    # Upgrade, preserving ~/.config/reqbot/config.json
#   ./reqbot-install.sh --uninstall  # Remove ~/.reqbot/ and ~/.local/bin/reqbot
#
# Requirements: bash, tar, gzip, sed (no Python, no pip, no venv)
# Platform: Linux x86_64 only
#
# The archive embedded in this file (after __ARCHIVE_BELOW__) is appended
# by build/build.sh at build time — this template file has no archive.
set -euo pipefail

INSTALL_DIR="$HOME/.reqbot"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/reqbot"
CONFIG_FILE="$HOME/.config/reqbot/config.json"
REQBOT_VERSION="__REQBOT_VERSION__"   # Replaced by build.sh at build time

# ---------------------------------------------------------------
# Root check — must come first, before any side effects
# ---------------------------------------------------------------
if [ "$(id -u)" -eq 0 ]; then
    echo "[-] reqbot-install.sh must not be run as root."
    echo "    Install as a normal user — no root access required."
    exit 1
fi

# ---------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------
MODE="install"   # install | upgrade | uninstall
for arg in "$@"; do
    case "$arg" in
        --upgrade)   MODE="upgrade" ;;
        --uninstall) MODE="uninstall" ;;
        --help|-h)
            cat <<'HELP'
Usage: reqbot-install.sh [OPTION]

  (no option)   Fresh install to ~/.reqbot/
  --upgrade     Upgrade to this version; ~/.config/reqbot/config.json is preserved
  --uninstall   Remove ~/.reqbot/ and ~/.local/bin/reqbot
  --help        Show this message

Config lives at ~/.config/reqbot/config.json and is never touched by install or upgrade.
HELP
            exit 0
            ;;
        *)
            echo "[-] Unknown option: $arg" >&2
            echo "    Run '$0 --help' for usage." >&2
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------
# OS / arch detection
# ---------------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"
if [ "$OS" != "Linux" ] || [ "$ARCH" != "x86_64" ]; then
    echo "[!] Warning: This installer targets Linux x86_64."
    echo "    Detected: $OS $ARCH"
    echo "    Installation may fail or produce a non-functional result."
    read -r -p "    Continue anyway? [y/N]: " _yn || true
    case "$_yn" in [yY]*) ;; *) echo "Aborted."; exit 1 ;; esac
fi

# ---------------------------------------------------------------
# Uninstall path
# ---------------------------------------------------------------
if [ "$MODE" = "uninstall" ]; then
    echo "=== ReqBot Uninstall ==="
    echo ""
    if [ ! -d "$INSTALL_DIR" ] && [ ! -f "$LAUNCHER" ]; then
        echo "Nothing to uninstall (no installation found at $INSTALL_DIR)."
        exit 0
    fi
    echo "This will remove:"
    [ -d "$INSTALL_DIR" ] && echo "  $INSTALL_DIR"
    [ -f "$LAUNCHER"    ] && echo "  $LAUNCHER"
    echo ""
    echo "Your config ($CONFIG_FILE) will NOT be removed."
    echo ""
    read -r -p "Proceed with uninstall? [y/N]: " _yn || true
    case "$_yn" in [yY]*) ;; *) echo "Aborted."; exit 0 ;; esac

    rm -rf "$INSTALL_DIR"
    rm -f  "$LAUNCHER"
    echo ""
    echo "[+] Removed $INSTALL_DIR"
    echo "[+] Removed $LAUNCHER"
    echo "[+] Config preserved: $CONFIG_FILE"
    echo ""
    echo "Uninstall complete."
    exit 0
fi

# ---------------------------------------------------------------
# Install / upgrade pre-flight
# ---------------------------------------------------------------
echo "=== ReqBot Installer (v${REQBOT_VERSION}) ==="
echo ""

if [ -d "$INSTALL_DIR" ]; then
    if [ "$MODE" = "install" ]; then
        echo "[-] Existing installation found at $INSTALL_DIR"
        echo "    Run with --upgrade to upgrade while preserving your config."
        echo "    Run with --uninstall to remove the current installation first."
        exit 1
    fi
    # upgrade: wipe the old install tree; config at ~/.config/reqbot/ is untouched
    echo "[*] Removing old installation..."
    rm -rf "$INSTALL_DIR"
    echo "    Done."
else
    if [ "$MODE" = "upgrade" ]; then
        echo "[-] No existing installation found at $INSTALL_DIR"
        echo "    Run without --upgrade for a fresh install."
        exit 1
    fi
fi

# ---------------------------------------------------------------
# Rollback trap — fires on any non-zero exit during install/upgrade.
# Cleans up a partial ~/.reqbot/ tree and broken launcher so the
# user is not left with a broken half-installed state.
# The flag is cleared right before the final exit 0 on success.
# ---------------------------------------------------------------
_ROLLBACK=true
_rollback_on_exit() {
    if [ "$_ROLLBACK" = "true" ]; then
        echo "" >&2
        echo "[!] Installation failed — rolling back partial install." >&2
        rm -rf "$INSTALL_DIR"
        rm -f  "$LAUNCHER"
        echo "[!] Cleanup complete. No files were left behind." >&2
    fi
}
trap _rollback_on_exit EXIT

# ---------------------------------------------------------------
# Step 1: Extract bundle (binary-safe via sed)
# sed deletes every line from line 1 through the __ARCHIVE_BELOW__
# sentinel line, then pipes the raw bytes directly into tar.
# This is binary-safe: it never tries to count newlines in binary data.
# ---------------------------------------------------------------
echo "[1/3] Extracting bundle to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
sed '1,/^__ARCHIVE_BELOW__/d' "$0" | tar xz -C "$INSTALL_DIR" --strip-components=1
echo "      Extraction complete."

# ---------------------------------------------------------------
# Step 2: Write ~/.local/bin/reqbot launcher
# ---------------------------------------------------------------
echo "[2/3] Writing launcher to $LAUNCHER ..."
mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" << 'LAUNCHER_SCRIPT'
#!/usr/bin/env bash
# ReqBot launcher — written by reqbot-install.sh
# Do not edit this file; re-run the installer to update it.
export FASTEMBED_CACHE_PATH="$HOME/.reqbot/models"
# -I (isolated mode) — without it, Python auto-appends this user's own
# ~/.local/lib/pythonX.Y/site-packages to sys.path, so the bundled
# interpreter would silently import whatever's pip-installed on this
# machine instead of the bundle's own copies.
exec "$HOME/.reqbot/python/bin/python3" -I "$HOME/.reqbot/app/cli/reqbot.py" "$@"
LAUNCHER_SCRIPT
chmod +x "$LAUNCHER"
echo "      Launcher written."

# ---------------------------------------------------------------
# Step 3: Smoke test
# ---------------------------------------------------------------
echo "[3/3] Running smoke test..."
if "$LAUNCHER" --help > /dev/null 2>&1; then
    echo "      reqbot --help  OK"
else
    echo ""
    echo "[-] Smoke test failed — 'reqbot --help' exited with an error." >&2
    echo "    Installation may be incomplete or the bundle may be corrupted." >&2
    exit 1
fi

# ---------------------------------------------------------------
# Security: enforce 600 on config if it already exists.
# A pre-existing world-readable config exposes Qdrant URLs and
# API key env vars to other users on shared machines.
# ---------------------------------------------------------------
if [ -f "$CONFIG_FILE" ]; then
    chmod 600 "$CONFIG_FILE"
fi

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
_ROLLBACK=false   # Installation succeeded — disable rollback trap

echo ""
echo "=== Installation complete ==="
echo ""
echo "  Installed to : $INSTALL_DIR"
echo "  Launcher     : $LAUNCHER"
echo ""

# PATH hint — only shown if ~/.local/bin is not already on PATH
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        echo "[!] $BIN_DIR is not on your PATH."
        echo "    Add this line to your ~/.bashrc or ~/.profile:"
        echo ""
        echo "      export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo ""
        echo "    Then reload your shell:  source ~/.bashrc"
        echo ""
        ;;
esac

if [ -f "$CONFIG_FILE" ]; then
    echo "Config found — run 'reqbot' to launch the interactive shell."
else
    echo "Next step: run 'reqbot init' to configure your Ollama and Qdrant endpoints."
fi
echo ""

# End of script — archive bytes follow
exit 0

__ARCHIVE_BELOW__
