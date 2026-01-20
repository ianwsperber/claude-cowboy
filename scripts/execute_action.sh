#!/usr/bin/env bash
# Execute an action for Claude Cowboy session browser
# Usage: execute_action.sh <action> <session_line>

ACTION="$1"
LINE="$2"

# Extract session name (first word, skipping (*) indicator for orchestrated children)
# Strip ANSI codes, then remove (*) prefix if present, then get first word
SESSION=$(echo "$LINE" | sed 's/\x1b\[[0-9;]*m//g' | sed 's/^[[:space:]]*(\*)[[:space:]]*//' | awk '{print $1}')

if [ -z "$SESSION" ]; then
    exit 1
fi

# Get session CWD
SESSION_CWD=$(tmux display-message -t "$SESSION" -p '#{pane_current_path}' 2>/dev/null)

case "$ACTION" in
    open)
        if [ -n "$SESSION_CWD" ]; then
            open "$SESSION_CWD" 2>/dev/null || xdg-open "$SESSION_CWD" 2>/dev/null
        fi
        ;;
    terminal)
        if [ -n "$SESSION_CWD" ]; then
            if [ -n "$TERMINAL" ]; then
                open -a "$TERMINAL" "$SESSION_CWD" 2>/dev/null || "$TERMINAL" "$SESSION_CWD" 2>/dev/null
            else
                open -a iTerm "$SESSION_CWD" 2>/dev/null || \
                    open -a Terminal "$SESSION_CWD" 2>/dev/null || \
                    gnome-terminal --working-directory="$SESSION_CWD" 2>/dev/null || \
                    x-terminal-emulator --workdir "$SESSION_CWD" 2>/dev/null
            fi
        fi
        ;;
    editor)
        if [ -n "$SESSION_CWD" ]; then
            code "$SESSION_CWD" 2>/dev/null || ${EDITOR:-vim} "$SESSION_CWD" 2>/dev/null
        fi
        ;;
    lasso)
        # Placeholder - does nothing for now
        ;;
    kill)
        tmux kill-session -t "$SESSION" 2>/dev/null
        ;;
esac
