#!/usr/bin/env bash
# Action menu preview for Claude Cowboy session browser
# Shows available actions for the selected session

LINE="$1"

# Skip separator lines
if echo "$LINE" | grep -q "━━━"; then
    echo "Select a session first"
    exit 0
fi

# Extract session name (first word, skipping (*) indicator for orchestrated children)
# Strip ANSI codes, then remove (*) prefix if present, then get first word
SESSION=$(echo "$LINE" | sed 's/\x1b\[[0-9;]*m//g' | sed 's/^[[:space:]]*(\*)[[:space:]]*//' | awk '{print $1}')

if [ -z "$SESSION" ]; then
    echo "No session selected"
    exit 0
fi

# Get session CWD
SESSION_CWD=$(tmux display-message -t "$SESSION" -p '#{pane_current_path}' 2>/dev/null)

cat << EOF

  ╭─────────────────────────────────────╮
  │         Actions for: $SESSION
  ╰─────────────────────────────────────╯

     [s]  Switch to session
     [o]  Open folder in Finder
     [t]  Open in terminal (iTerm)
     [e]  Open in editor (VS Code)
     [n]  New session (this dir)
     [l]  Lasso (coming soon)
     [k]  Kill session

     [Esc]  Cancel / back to browse

  ─────────────────────────────────────
  Path: ${SESSION_CWD:-unknown}

EOF
