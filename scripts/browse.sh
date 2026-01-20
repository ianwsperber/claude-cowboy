#!/usr/bin/env bash
# Claude Cowboy Session Browser with Auto-Refresh
#
# Uses fzf's --listen mode with a background process that sends
# periodic reload commands for auto-refresh.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(dirname "$SCRIPT_DIR")/lib"
REFRESH_INTERVAL="${COWBOY_REFRESH_INTERVAL:-3}"

# Generate session list
generate_sessions() {
    python3 "$LIB_DIR/session_browser.py" --no-fzf
}

# Find an available port for fzf --listen
find_port() {
    python3 -c "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1]); s.close()"
}

# Check for fzf
if ! command -v fzf &>/dev/null; then
    echo "Error: fzf is not installed. Please install it first." >&2
    echo "  macOS: brew install fzf" >&2
    echo "  Linux: apt install fzf / dnf install fzf" >&2
    exit 1
fi

# Check fzf version for --listen support
FZF_VERSION=$(fzf --version | head -1 | cut -d' ' -f1)
FZF_MAJOR=$(echo "$FZF_VERSION" | cut -d. -f1)
FZF_MINOR=$(echo "$FZF_VERSION" | cut -d. -f2)

# --listen requires fzf 0.36+
if [ "$FZF_MAJOR" -eq 0 ] && [ "$FZF_MINOR" -lt 36 ]; then
    echo "Warning: fzf version $FZF_VERSION doesn't support auto-refresh (need 0.36+)" >&2
    echo "Falling back to manual refresh with Ctrl-R" >&2

    # Fallback: run without auto-refresh (preview-based action menu)
    # Action keys start unbound, Enter activates them
    # n is also in unbind list (only available in action menu), ctrl-n is always available
    RESULT=$(generate_sessions | fzf \
        --ansi \
        --no-sort \
        --color="bg+:#D87757,fg+:#000000" \
        --header="Sessions | Enter: actions | Ctrl-N: new | Ctrl-K: kill | Ctrl-R: refresh" \
        --prompt="Session> " \
        --layout=reverse \
        --info=inline \
        --preview="$SCRIPT_DIR/preview.sh {}" \
        --preview-window=right:50%:wrap:~10:follow \
        --bind="start:unbind(s,o,t,e,l,k,c,n)" \
        --bind="ctrl-j:preview-down" \
        --bind="ctrl-r:reload(python3 '$LIB_DIR/session_browser.py' --no-fzf)" \
        --bind='ctrl-k:execute-silent('"$SCRIPT_DIR"'/execute_action.sh kill {})+reload(python3 '"'"$LIB_DIR"'"'/session_browser.py --no-fzf)' \
        --bind='ctrl-n:execute('"$SCRIPT_DIR"'/new_session.sh)+reload(python3 '"'"$LIB_DIR"'"'/session_browser.py --no-fzf)' \
        --bind='enter:change-preview('"$SCRIPT_DIR"'/action_menu.sh {})+change-prompt(Action> )+disable-search+rebind(s,o,t,e,l,k,c,n)' \
        --bind='esc:change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
        --bind='s:become(echo switch:{})' \
        --bind='o:execute-silent('"$SCRIPT_DIR"'/execute_action.sh open {})+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
        --bind='t:execute-silent('"$SCRIPT_DIR"'/execute_action.sh terminal {})+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
        --bind='e:execute-silent('"$SCRIPT_DIR"'/execute_action.sh editor {})+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
        --bind='l:execute-silent('"$SCRIPT_DIR"'/execute_action.sh lasso {})+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
        --bind='k:execute-silent('"$SCRIPT_DIR"'/execute_action.sh kill {})+reload(python3 '"'"$LIB_DIR"'"'/session_browser.py --no-fzf)+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
        --bind='n:execute('"$SCRIPT_DIR"'/new_session.sh --session-line {})+reload(python3 '"'"$LIB_DIR"'"'/session_browser.py --no-fzf)+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
        --bind='c:change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
        || true)

    # Handle switch action (the only one that exits fzf)
    if [ -n "$RESULT" ] && echo "$RESULT" | grep -q "^switch:"; then
        # Strip ANSI codes, remove (*) prefix for orchestrated children, then get first word
        SESSION_NAME=$(echo "$RESULT" | sed 's/^switch://' | sed 's/\x1b\[[0-9;]*m//g' | sed 's/^[[:space:]]*(\*)[[:space:]]*//' | awk '{print $1}')
        if [ -n "$SESSION_NAME" ] && ! echo "$SESSION_NAME" | grep -q "━━━"; then
            if [ -n "$TMUX" ]; then
                tmux switch-client -t "$SESSION_NAME"
            else
                tmux attach-session -t "$SESSION_NAME"
            fi
        fi
    fi
    exit 0
fi

# Get a port for fzf to listen on
PORT=$(find_port)
LISTEN_ADDR="localhost:$PORT"

# Background process that sends reload commands
reload_loop() {
    sleep 1  # Initial delay to let fzf start
    while true; do
        sleep "$REFRESH_INTERVAL"
        # Send reload command to fzf
        curl -s "http://$LISTEN_ADDR" -d "reload(python3 '$LIB_DIR/session_browser.py' --no-fzf)" 2>/dev/null || break
    done
}

# Start the reload loop in background
reload_loop &
RELOAD_PID=$!

# Cleanup function
cleanup() {
    kill "$RELOAD_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Run fzf with --listen for external control (preview-based action menu)
# Action keys start unbound, Enter activates them
# n is also in unbind list (only available in action menu), ctrl-n is always available
RESULT=$(generate_sessions | fzf \
    --ansi \
    --no-sort \
    --color="bg+:#D87757,fg+:#000000" \
    --listen="$LISTEN_ADDR" \
    --header="Sessions | Enter: actions | Ctrl-N: new | Ctrl-K: kill | Ctrl-R: refresh (auto: ${REFRESH_INTERVAL}s)" \
    --prompt="Session> " \
    --layout=reverse \
    --info=inline \
    --preview="$SCRIPT_DIR/preview.sh {}" \
    --preview-window=right:50%:wrap:~10:follow \
    --bind="start:unbind(s,o,t,e,l,k,c,n)" \
    --bind="ctrl-j:preview-down" \
    --bind="ctrl-r:reload(python3 '$LIB_DIR/session_browser.py' --no-fzf)" \
    --bind='ctrl-k:execute-silent('"$SCRIPT_DIR"'/execute_action.sh kill {})+reload(python3 '"'"$LIB_DIR"'"'/session_browser.py --no-fzf)' \
    --bind='ctrl-n:execute('"$SCRIPT_DIR"'/new_session.sh)+reload(python3 '"'"$LIB_DIR"'"'/session_browser.py --no-fzf)' \
    --bind='enter:change-preview('"$SCRIPT_DIR"'/action_menu.sh {})+change-prompt(Action> )+disable-search+rebind(s,o,t,e,l,k,c,n)' \
    --bind='esc:change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
    --bind='s:become(echo switch:{})' \
    --bind='o:execute-silent('"$SCRIPT_DIR"'/execute_action.sh open {})+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
    --bind='t:execute-silent('"$SCRIPT_DIR"'/execute_action.sh terminal {})+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
    --bind='e:execute-silent('"$SCRIPT_DIR"'/execute_action.sh editor {})+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
    --bind='l:execute-silent('"$SCRIPT_DIR"'/execute_action.sh lasso {})+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
    --bind='k:execute-silent('"$SCRIPT_DIR"'/execute_action.sh kill {})+reload(python3 '"'"$LIB_DIR"'"'/session_browser.py --no-fzf)+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
    --bind='n:execute('"$SCRIPT_DIR"'/new_session.sh --session-line {})+reload(python3 '"'"$LIB_DIR"'"'/session_browser.py --no-fzf)+change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
    --bind='c:change-preview('"$SCRIPT_DIR"'/preview.sh {})+change-prompt(Session> )+enable-search+unbind(s,o,t,e,l,k,c,n)' \
    || true)

# Kill the reload loop
cleanup

# Handle switch action (the only one that exits fzf)
if [ -n "$RESULT" ] && echo "$RESULT" | grep -q "^switch:"; then
    # Strip ANSI codes, remove (*) prefix for orchestrated children, then get first word
    SESSION_NAME=$(echo "$RESULT" | sed 's/^switch://' | sed 's/\x1b\[[0-9;]*m//g' | sed 's/^[[:space:]]*(\*)[[:space:]]*//' | awk '{print $1}')
    if [ -n "$SESSION_NAME" ] && ! echo "$SESSION_NAME" | grep -q "━━━"; then
        if [ -n "$TMUX" ]; then
            tmux switch-client -t "$SESSION_NAME"
        else
            tmux attach-session -t "$SESSION_NAME"
        fi
    fi
fi
