#!/bin/bash
#
# install-dev.sh - Set up claude-cowboy for local development
#
# Creates symlinks for:
#   - CLI binary: ~/.local/bin/cowboy
#   - Claude plugin: ~/.claude/plugins/claude-cowboy
#
# Also installs the Python package in editable mode.

set -e

# Get the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Target locations
BIN_DIR="$HOME/.local/bin"
BIN_TARGET="$BIN_DIR/cowboy"
PLUGIN_DIR="$HOME/.claude/plugins"
PLUGIN_TARGET="$PLUGIN_DIR/claude-cowboy"

echo "Installing claude-cowboy for local development..."
echo "Project directory: $PROJECT_DIR"
echo

# --- Symlink CLI binary ---
echo "Setting up CLI binary..."

if [[ ! -d "$BIN_DIR" ]]; then
    echo "  Creating $BIN_DIR"
    mkdir -p "$BIN_DIR"
fi

if [[ -L "$BIN_TARGET" ]]; then
    existing=$(readlink "$BIN_TARGET")
    if [[ "$existing" == "$PROJECT_DIR/bin/cowboy" ]]; then
        echo "  Symlink already exists: $BIN_TARGET -> $existing"
    else
        echo "  Updating symlink: $BIN_TARGET"
        rm "$BIN_TARGET"
        ln -s "$PROJECT_DIR/bin/cowboy" "$BIN_TARGET"
        echo "  Created: $BIN_TARGET -> $PROJECT_DIR/bin/cowboy"
    fi
elif [[ -e "$BIN_TARGET" ]]; then
    echo "  ERROR: $BIN_TARGET exists but is not a symlink"
    echo "  Please remove it manually and re-run this script"
    exit 1
else
    ln -s "$PROJECT_DIR/bin/cowboy" "$BIN_TARGET"
    echo "  Created: $BIN_TARGET -> $PROJECT_DIR/bin/cowboy"
fi

# --- Symlink Claude plugin ---
echo
echo "Setting up Claude plugin..."

if [[ ! -d "$PLUGIN_DIR" ]]; then
    echo "  Creating $PLUGIN_DIR"
    mkdir -p "$PLUGIN_DIR"
fi

if [[ -L "$PLUGIN_TARGET" ]]; then
    existing=$(readlink "$PLUGIN_TARGET")
    if [[ "$existing" == "$PROJECT_DIR" ]]; then
        echo "  Symlink already exists: $PLUGIN_TARGET -> $existing"
    else
        echo "  Updating symlink: $PLUGIN_TARGET"
        rm "$PLUGIN_TARGET"
        ln -s "$PROJECT_DIR" "$PLUGIN_TARGET"
        echo "  Created: $PLUGIN_TARGET -> $PROJECT_DIR"
    fi
elif [[ -e "$PLUGIN_TARGET" ]]; then
    echo "  ERROR: $PLUGIN_TARGET exists but is not a symlink"
    echo "  Please remove it manually and re-run this script"
    exit 1
else
    ln -s "$PROJECT_DIR" "$PLUGIN_TARGET"
    echo "  Created: $PLUGIN_TARGET -> $PROJECT_DIR"
fi

# --- Install Python package ---
echo
echo "Installing Python package in editable mode..."

cd "$PROJECT_DIR"
if command -v uv &> /dev/null; then
    echo "  Using uv..."
    uv pip install -e . --quiet
else
    echo "  Using pip..."
    pip install -e . --quiet
fi
echo "  Done"

# --- Create cowboy_localdev command ---
echo
echo "Setting up cowboy_localdev command..."

LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"

cat > "$LOCAL_BIN/cowboy_localdev" << EOF
#!/bin/bash
# Claude Cowboy local dev: start claude in tmux with the local plugin loaded
export COWBOY_PLUGIN_DIR="$PROJECT_DIR"
exec cowboy "\$@"
EOF

chmod +x "$LOCAL_BIN/cowboy_localdev"
echo "  Created $LOCAL_BIN/cowboy_localdev"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    echo "  NOTE: Add ~/.local/bin to your PATH if not already there"
fi

# --- Create data directories ---
echo
echo "Creating data directories..."
mkdir -p "$HOME/.claude/cowboy/status"
mkdir -p "$HOME/.claude/cowboy/wait"
echo "  Created ~/.claude/cowboy/status"
echo "  Created ~/.claude/cowboy/wait"

# --- Check PATH ---
echo
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "WARNING: $BIN_DIR is not in your PATH"
    echo "Add the following to your shell config (~/.bashrc, ~/.zshrc, etc.):"
    echo
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo
else
    echo "PATH check: $BIN_DIR is in PATH"
fi

# --- Check fzf ---
echo
if command -v fzf &> /dev/null; then
    echo "fzf check: fzf is installed"
else
    echo "WARNING: fzf is not installed"
    echo "The session browser requires fzf. Install it with:"
    echo "  macOS:  brew install fzf"
    echo "  Linux:  apt install fzf / dnf install fzf"
fi

echo
echo "Installation complete!"
echo
echo "Commands:"
echo "  cowboy_localdev     - Start Claude in tmux with local plugin loaded"
echo "  cowboy              - Start Claude in tmux (no plugin)"
echo "  cowboy dash         - Open the session browser"
echo "  cowboy list         - List all sessions"
echo
echo "Plugin commands (available in cowboy_localdev sessions):"
echo "  /sessions           - Show session status"
