#!/bin/bash
#
# uninstall-dev.sh - Remove claude-cowboy development symlinks and hooks
#
# Removes:
#   - CLI binary symlink: ~/.local/bin/cowboy
#   - Claude plugin symlink: ~/.claude/plugins/claude-cowboy
#   - Hook configuration from ~/.claude/settings.json
#
# Note: Does not uninstall the Python package. Run `pip uninstall claude-cowboy` if needed.

set -e

# Get the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BIN_TARGET="$HOME/.local/bin/cowboy"
PLUGIN_TARGET="$HOME/.claude/plugins/claude-cowboy"

echo "Uninstalling claude-cowboy development setup..."
echo

# --- Remove CLI binary symlink ---
if [[ -L "$BIN_TARGET" ]]; then
    rm "$BIN_TARGET"
    echo "Removed: $BIN_TARGET"
elif [[ -e "$BIN_TARGET" ]]; then
    echo "WARNING: $BIN_TARGET exists but is not a symlink, skipping"
else
    echo "Not found: $BIN_TARGET (already removed)"
fi

# --- Remove Claude plugin symlink ---
if [[ -L "$PLUGIN_TARGET" ]]; then
    rm "$PLUGIN_TARGET"
    echo "Removed: $PLUGIN_TARGET"
elif [[ -e "$PLUGIN_TARGET" ]]; then
    echo "WARNING: $PLUGIN_TARGET exists but is not a symlink, skipping"
else
    echo "Not found: $PLUGIN_TARGET (already removed)"
fi

# --- Plugin hooks are auto-removed ---
echo
echo "Plugin hooks..."
echo "  Hooks are removed automatically when plugin symlink is removed"

echo
echo "Uninstall complete!"
echo
echo "Note: Python package was not removed."
echo "To remove it, run: pip uninstall claude-cowboy"
echo
echo "Note: Data directories were not removed."
echo "To remove them, run: rm -rf ~/.claude/cowboy"
