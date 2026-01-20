#!/usr/bin/env bash
# Preview script for Claude Cowboy session browser
# Shows metadata panel (1/3) + pane capture (2/3)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(dirname "$SCRIPT_DIR")/lib"

# Get session name from first argument (fzf selection line)
LINE="$1"

# Skip separator lines
if echo "$LINE" | grep -q "━━━"; then
    echo "Select a session to preview"
    exit 0
fi

# Extract session name (first word, skipping (*) indicator for orchestrated children)
# Strip ANSI codes, then remove (*) prefix if present, then get first word
SESSION=$(echo "$LINE" | sed 's/\x1b\[[0-9;]*m//g' | sed 's/^[[:space:]]*(\*)[[:space:]]*//' | awk '{print $1}')

if [ -z "$SESSION" ]; then
    echo "No session selected"
    exit 0
fi

# Run Python script for metadata
python3 "$LIB_DIR/session_preview.py" "$SESSION"
