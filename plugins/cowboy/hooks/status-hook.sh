#!/usr/bin/env bash
# Claude Cowboy Status Hook
#
# Adapted from tmux-claude-status by samleeney (MIT License)
# https://github.com/samleeney/tmux-claude-status
#
# Updates status files based on Claude Code hook events.
# Called by Claude Code for: SessionStart, UserPromptSubmit, PreToolUse,
# PermissionRequest, PostToolUse, Stop, SubagentStop, Notification
#
# Status files are keyed by tmux session name, enabling the session
# browser to show status for each Claude session.

set -e

STATUS_DIR="$HOME/.claude/cowboy/status"
WAIT_DIR="$HOME/.claude/cowboy/wait"

# Use CLAUDE_PLUGIN_ROOT if available (when called as plugin hook)
# Otherwise fall back to script directory
if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
    PLUGIN_DIR="$CLAUDE_PLUGIN_ROOT"
else
    PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

mkdir -p "$STATUS_DIR" "$WAIT_DIR"

# Read JSON from stdin (required by Claude Code hooks)
JSON_INPUT=$(cat)

# Extract session_id from JSON input - this is the Claude session UUID
# The hook receives JSON like: {"session_id": "abc123-...", "cwd": "/path", ...}
SESSION_ID=""
if command -v jq &> /dev/null; then
    SESSION_ID=$(echo "$JSON_INPUT" | jq -r '.session_id // empty' 2>/dev/null)
fi

# Get tmux session name if running in tmux (for session browser)
# Try multiple methods since hook subprocess may not inherit $TMUX
TMUX_SESSION=""

# Method 1: Try tmux display-message directly (works if we're in a tmux pane)
if command -v tmux &> /dev/null; then
    TMUX_SESSION=$(tmux display-message -p '#{session_name}' 2>/dev/null || echo "")
fi

# Method 2: Try with common tmux paths if command not found
if [ -z "$TMUX_SESSION" ]; then
    for tmux_path in /opt/homebrew/bin/tmux /usr/local/bin/tmux /usr/bin/tmux; do
        if [ -x "$tmux_path" ]; then
            TMUX_SESSION=$("$tmux_path" display-message -p '#{session_name}' 2>/dev/null || echo "")
            [ -n "$TMUX_SESSION" ] && break
        fi
    done
fi

# Method 3: Try using $TMUX pane info as fallback
# $TMUX format: /socket/path,pane-id,window-id - we can query tmux using the socket
if [ -z "$TMUX_SESSION" ] && [ -n "$TMUX" ]; then
    SOCKET_PATH=$(echo "$TMUX" | cut -d',' -f1)
    PANE_ID=$(echo "$TMUX" | cut -d',' -f2)
    if [ -n "$SOCKET_PATH" ] && [ -n "$PANE_ID" ]; then
        # Query tmux using the socket to get the actual session name
        TMUX_SESSION=$(tmux -S "$SOCKET_PATH" display-message -t "%$PANE_ID" -p '#{session_name}' 2>/dev/null || echo "")
    fi
fi

# Need at least one identifier to proceed
if [ -z "$SESSION_ID" ] && [ -z "$TMUX_SESSION" ]; then
    exit 0
fi

HOOK_TYPE="$1"

# Helper function to write status to all relevant files
write_status() {
    local status="$1"
    # Write by Claude session UUID (for sessions_cli)
    if [ -n "$SESSION_ID" ]; then
        echo "$status" > "$STATUS_DIR/${SESSION_ID}.status"
    fi
    # Write by tmux session name (for session_browser)
    if [ -n "$TMUX_SESSION" ]; then
        echo "$status" > "$STATUS_DIR/${TMUX_SESSION}.status"
    fi
}

# Wait file uses session_id if available, else tmux session
WAIT_KEY="${SESSION_ID:-$TMUX_SESSION}"
WAIT_FILE="$WAIT_DIR/${WAIT_KEY}.wait"

case "$HOOK_TYPE" in
    "SessionStart")
        # Write initial status as "done" - session is idle, waiting for user input
        write_status "done"

        # Configure tmux status bar for this session
        if [ -n "$TMUX_SESSION" ]; then
            # Get the path to status_line.sh (in same hooks directory)
            STATUS_SCRIPT="$PLUGIN_DIR/hooks/status_line.sh"

            # Configure status-left to call our script with session name
            # #S is expanded by tmux to the session name when rendering
            tmux set-option -t "$TMUX_SESSION" status-left "#($STATUS_SCRIPT --session #S) " 2>/dev/null || true

            # Set length to accommodate all content
            tmux set-option -t "$TMUX_SESSION" status-left-length 100 2>/dev/null || true

            # Update every 2 seconds
            tmux set-option -t "$TMUX_SESSION" status-interval 2 2>/dev/null || true
        fi
        ;;
    "UserPromptSubmit")
        # User submitted input (answered question or new prompt)
        # Cancel wait mode and show working - Claude is about to process
        if [ -f "$WAIT_FILE" ]; then
            rm -f "$WAIT_FILE"
        fi
        write_status "working"
        ;;
    "PreToolUse")
        # Cancel wait mode if active
        if [ -f "$WAIT_FILE" ]; then
            rm -f "$WAIT_FILE"
        fi

        # Extract tool_name to detect AskUserQuestion
        TOOL_NAME=""
        if command -v jq &> /dev/null; then
            TOOL_NAME=$(echo "$JSON_INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
        fi

        # Determine status based on what Claude is doing
        if [ "$TOOL_NAME" = "AskUserQuestion" ]; then
            # Claude is asking the user a question - needs attention
            write_status "needs_attention"
        else
            # Claude is actively working on a tool
            write_status "working"
        fi
        ;;
    "PermissionRequest")
        # Permission dialog is being shown - needs attention
        write_status "needs_attention"
        ;;
    "PostToolUse")
        # Tool completed execution - user granted permission or tool ran
        # Set working since Claude may continue with more tools
        write_status "working"
        ;;
    "Stop"|"SubagentStop")
        # Claude has finished responding
        write_status "done"
        # Play notification sound via Python (handles cross-platform)
        if [ -f "$PLUGIN_DIR/lib/notifications.py" ]; then
            python3 -c "import sys; sys.path.insert(0, '$PLUGIN_DIR'); from lib.notifications import play_notification; play_notification()" 2>/dev/null &
        fi

        # Check if this is an orchestrated child session and handle completion
        if [ -f "$PLUGIN_DIR/lib/orchestration_cli.py" ]; then
            # Build args for orchestration check
            ORCH_ARGS=""
            if [ -n "$SESSION_ID" ]; then
                ORCH_ARGS="$ORCH_ARGS --session-id $SESSION_ID"
            fi
            if [ -n "$TMUX_SESSION" ]; then
                ORCH_ARGS="$ORCH_ARGS --tmux-session $TMUX_SESSION"
            fi

            if [ -n "$ORCH_ARGS" ]; then
                # Run orchestration completion handler in background
                python3 "$PLUGIN_DIR/lib/orchestration_cli.py" handle-child-completion $ORCH_ARGS 2>/dev/null &
            fi
        fi
        ;;
    "Notification")
        # Notification fires when Claude sends alerts (including completion alerts).
        # Don't set status here - PreToolUse already handles needs_attention cases
        # (AskUserQuestion, permission prompts), and Stop handles completion.
        # Setting needs_attention here would overwrite "done" status incorrectly.
        ;;
esac

# Always exit successfully (required by Claude Code)
exit 0
