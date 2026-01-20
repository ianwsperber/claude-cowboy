#!/usr/bin/env bash
# New session script for Claude Cowboy session browser
# Shows directory picker and creates new Claude session without switching to it
#
# Usage: new_session.sh [--session-dir DIR]
#   --session-dir DIR  Optional starting directory for the picker

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(dirname "$SCRIPT_DIR")/lib"

# Parse arguments
SESSION_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --session-dir)
            SESSION_DIR="$2"
            shift 2
            ;;
        --session-line)
            # Extract session name from fzf line and get its CWD
            # Strip ANSI codes, remove (*) prefix for orchestrated children, then get first word
            LINE="$2"
            SESSION_NAME=$(echo "$LINE" | sed 's/\x1b\[[0-9;]*m//g' | sed 's/^[[:space:]]*(\*)[[:space:]]*//' | awk '{print $1}')
            if [ -n "$SESSION_NAME" ] && ! echo "$SESSION_NAME" | grep -q "━━━"; then
                SESSION_DIR=$(tmux display-message -t "$SESSION_NAME" -p '#{pane_current_path}' 2>/dev/null)
            fi
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Check if directory is a git repo
is_git_repo() {
    git -C "$1" rev-parse --git-dir &>/dev/null
}

# Check if directory is a worktree (not the main repo)
is_worktree() {
    local git_dir=$(git -C "$1" rev-parse --git-dir 2>/dev/null)
    local common_dir=$(git -C "$1" rev-parse --git-common-dir 2>/dev/null)
    [ "$git_dir" != "$common_dir" ]
}

# Get main repo from worktree
get_main_repo() {
    local common_dir=$(git -C "$1" rev-parse --git-common-dir 2>/dev/null)
    # common_dir is the .git directory of the main repo
    # We need its parent directory
    dirname "$common_dir"
}

# Expand ~ to home directory
expand_path() {
    local path="$1"
    if [[ "$path" == "~"* ]]; then
        path="${HOME}${path:1}"
    fi
    echo "$path"
}

# Generate session name from directory, avoiding conflicts
# Usage: generate_session_name <dir> [suffix]
# If suffix is provided, uses base_name-suffix pattern
generate_session_name() {
    local dir="$1"
    local suffix="$2"
    local base_name=$(basename "$dir" | tr '.:' '-')
    local name

    if [ -n "$suffix" ]; then
        # Use suffix pattern: base_name-suffix
        suffix=$(echo "$suffix" | tr '.:' '-')
        name="${base_name}-${suffix}"
    else
        name="$base_name"
    fi

    # Handle conflicts by appending counter
    if tmux has-session -t "$name" 2>/dev/null; then
        local original_name="$name"
        local counter=1
        while tmux has-session -t "$name" 2>/dev/null; do
            name="${original_name}-${counter}"
            counter=$((counter + 1))
        done
    fi

    echo "$name"
}

# Create a worktree using Python helper
create_worktree_path() {
    local repo_path="$1"
    local result
    result=$(python3 -c "
import sys
import os
sys.path.insert(0, '$LIB_DIR/..')
from lib.git_worktree import create_worktree as git_create_worktree, find_reusable_worktree, get_active_session_cwds
from lib.config import load_config

try:
    config = load_config('$repo_path')
    location = config.get('worktreeLocation', 'home')
    active_cwds = get_active_session_cwds()

    # Try to reuse an existing idle worktree
    wt = find_reusable_worktree('$repo_path', active_cwds, location)
    if wt and os.path.isdir(wt):
        print(wt)
    else:
        new_wt = git_create_worktree('$repo_path', location)
        if new_wt and os.path.isdir(new_wt):
            print(new_wt)
        else:
            sys.exit(1)
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)

    if [ $? -ne 0 ] || [ -z "$result" ] || [ ! -d "$result" ]; then
        echo "Failed to create worktree: $result" >&2
        return 1
    fi
    echo "$result"
}

# Generate directory list
DIRS=$(python3 "$LIB_DIR/session_directories.py")

# Prepend "(Type)" option
DIRS="(Type)"$'\n'"$DIRS"

# Build fzf options
FZF_OPTS=(
    --ansi
    --no-sort
    --print-query
    --color="bg+:#D87757,fg+:#000000"
    --header="Select directory for new session | Enter: select | Esc: cancel"
    --prompt="Directory> "
    --layout=reverse
    --info=inline
)

# If invoked from action menu with session directory, start at that position
if [ -n "$SESSION_DIR" ]; then
    # Find line number of matching directory (accounting for "(Type)" being line 1)
    # Match both with and without ~ expansion
    SHORT_DIR=$(echo "$SESSION_DIR" | sed "s|^$HOME|~|")
    POS=$(echo "$DIRS" | grep -n "^${SHORT_DIR}$" | head -1 | cut -d: -f1)
    if [ -n "$POS" ]; then
        FZF_OPTS+=(--bind="start:pos($((POS - 1)))")
    fi
fi

# Run fzf and capture both query and selection
# --print-query outputs: line 1 = query, line 2 = selection (if any)
RESULT=$(echo "$DIRS" | fzf "${FZF_OPTS[@]}" 2>/dev/null || true)

# If empty result (user pressed Esc), exit
if [ -z "$RESULT" ]; then
    exit 0
fi

# Parse result: first line is query, second line is selection
QUERY=$(echo "$RESULT" | head -1)
SELECTION=$(echo "$RESULT" | tail -1)

# Determine the target directory
TARGET_DIR=""

if [ "$SELECTION" = "(Type)" ]; then
    # User selected "(Type)" - use the query as the path
    if [ -z "$QUERY" ]; then
        echo "No path entered" >&2
        exit 1
    fi
    TARGET_DIR=$(expand_path "$QUERY")
elif [ -n "$SELECTION" ] && [ "$SELECTION" != "$QUERY" ]; then
    # User selected a directory from the list
    TARGET_DIR=$(expand_path "$SELECTION")
else
    # Edge case: query matches selection exactly (could happen with fuzzy match)
    # or only query was returned (selection was the query itself)
    if [ -n "$QUERY" ] && [ -d "$(expand_path "$QUERY")" ]; then
        TARGET_DIR=$(expand_path "$QUERY")
    else
        echo "No valid directory selected" >&2
        exit 1
    fi
fi

# Validate directory exists
if [ ! -d "$TARGET_DIR" ]; then
    echo "Directory does not exist: $TARGET_DIR" >&2
    exit 1
fi

# Determine if we should use worktree
USE_WORKTREE=false
WORKTREE_REPO=""

if is_git_repo "$TARGET_DIR"; then
    if is_worktree "$TARGET_DIR"; then
        # Directory is already a worktree - offer to create new worktree from main repo
        MAIN_REPO=$(get_main_repo "$TARGET_DIR")
        echo ""
        echo "Selected directory is a git worktree."
        echo "Main repo: $MAIN_REPO"
        read -p "Create new worktree from main repo? (y/n): " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            USE_WORKTREE=true
            WORKTREE_REPO="$MAIN_REPO"
        fi
        # If n, just use the selected worktree directory as-is
    else
        # Regular git repo - offer worktree option
        echo ""
        read -p "Create in new worktree for isolation? (y/n): " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            USE_WORKTREE=true
            WORKTREE_REPO="$TARGET_DIR"
        fi
    fi
fi

# If worktree requested, create it first
if [ "$USE_WORKTREE" = true ]; then
    echo "Creating worktree..."
    NEW_WORKTREE=$(create_worktree_path "$WORKTREE_REPO")
    if [ $? -ne 0 ] || [ -z "$NEW_WORKTREE" ]; then
        echo "Failed to create worktree. Creating session in original directory instead." >&2
    else
        TARGET_DIR="$NEW_WORKTREE"
        echo "Created: $TARGET_DIR"
    fi
fi

# Generate session name
# For worktree mode: prompt for custom suffix
# For non-worktree mode: use directory name directly
if [ "$USE_WORKTREE" = true ] && [ -n "$NEW_WORKTREE" ] && [ -d "$NEW_WORKTREE" ]; then
    # Extract repo base name (sanitized)
    REPO_BASE=$(basename "$WORKTREE_REPO" | tr '.:' '-')
    # Extract worktree number from the worktree path
    WORKTREE_NUM=$(basename "$TARGET_DIR" | grep -oE '[0-9]+$' || echo "01")

    echo ""
    echo "Session name: ${REPO_BASE}-<suffix>"
    read -p "Enter suffix (or press Enter for '${WORKTREE_NUM}'): " NAME_SUFFIX

    if [ -z "$NAME_SUFFIX" ]; then
        # Use default (worktree number)
        SESSION_NAME="${REPO_BASE}-${WORKTREE_NUM}"
    else
        # Use custom suffix (sanitized)
        NAME_SUFFIX=$(echo "$NAME_SUFFIX" | tr '.:' '-')
        SESSION_NAME="${REPO_BASE}-${NAME_SUFFIX}"
    fi

    # Handle conflicts by appending counter
    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        echo "Warning: Session '$SESSION_NAME' exists. Appending number."
        COUNTER=1
        while tmux has-session -t "${SESSION_NAME}-${COUNTER}" 2>/dev/null; do
            COUNTER=$((COUNTER + 1))
        done
        SESSION_NAME="${SESSION_NAME}-${COUNTER}"
    fi
else
    # Non-worktree mode: generate from directory name
    SESSION_NAME=$(generate_session_name "$TARGET_DIR")
fi

echo ""
echo "Creating session: $SESSION_NAME"
echo "Directory: $TARGET_DIR"

# Create tmux session (detached, don't switch to it)
tmux new-session -d -s "$SESSION_NAME" -c "$TARGET_DIR"

# Determine claude command (check for local dev plugin)
CLAUDE_CMD="claude"
if [ -n "$COWBOY_PLUGIN_DIR" ]; then
    CLAUDE_CMD="claude --plugin-dir $COWBOY_PLUGIN_DIR"
fi

# Start Claude in the new session
tmux send-keys -t "$SESSION_NAME" "$CLAUDE_CMD" Enter

echo ""
echo "Session '$SESSION_NAME' created!"
echo "Press any key to return to dashboard..."
read -n 1 -s
