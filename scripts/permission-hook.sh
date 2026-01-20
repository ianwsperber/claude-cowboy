#!/bin/bash
# Claude Code hook for tracking permission request state
# Writes session state to ~/.claude/cowboy/hook-state/<session_id>.json

set -e

STATE_DIR="$HOME/.claude/cowboy/hook-state"
mkdir -p "$STATE_DIR"

# Read hook input from stdin
INPUT=$(cat)

# Parse the hook event details
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
HOOK_EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Exit if we don't have a session ID
if [ -z "$SESSION_ID" ]; then
    exit 0
fi

STATE_FILE="$STATE_DIR/$SESSION_ID.json"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

case "$HOOK_EVENT" in
    "PermissionRequest")
        # Extract tool input for context
        TOOL_INPUT=$(echo "$INPUT" | jq -c '.tool_input // {}')

        # For Bash, extract the command
        COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // empty')
        DESCRIPTION=$(echo "$TOOL_INPUT" | jq -r '.description // empty')

        # Write permission_pending state
        jq -n \
            --arg session_id "$SESSION_ID" \
            --arg state "permission_pending" \
            --arg tool "$TOOL_NAME" \
            --arg command "$COMMAND" \
            --arg description "$DESCRIPTION" \
            --arg timestamp "$TIMESTAMP" \
            '{
                session_id: $session_id,
                state: $state,
                tool: $tool,
                command: $command,
                description: $description,
                timestamp: $timestamp
            }' > "$STATE_FILE"
        ;;

    "PostToolUse")
        # Tool completed - clear the pending state
        # Write a "running" state briefly, or just remove the file
        if [ -f "$STATE_FILE" ]; then
            # Update to show tool completed
            jq -n \
                --arg session_id "$SESSION_ID" \
                --arg state "tool_completed" \
                --arg tool "$TOOL_NAME" \
                --arg timestamp "$TIMESTAMP" \
                '{
                    session_id: $session_id,
                    state: $state,
                    tool: $tool,
                    timestamp: $timestamp
                }' > "$STATE_FILE"
        fi
        ;;
esac

exit 0
