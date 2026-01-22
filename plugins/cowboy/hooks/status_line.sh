#!/usr/bin/env bash
# tmux status line output for Claude Cowboy.
#
# Adapted from tmux-claude-status by samleeney (MIT License)
# https://github.com/samleeney/tmux-claude-status
#
# Called by tmux to render the status-left content.
# Usage: status_line.sh [--session SESSION_NAME]

set -e

SESSION_NAME=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --session)
            SESSION_NAME="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# If session name not provided, try to detect it
if [ -z "$SESSION_NAME" ]; then
    SESSION_NAME=$(tmux display-message -p '#{session_name}' 2>/dev/null) || exit 0
fi

[ -z "$SESSION_NAME" ] && exit 0

# Get the session's current pane CWD
CWD=$(tmux display-message -t "$SESSION_NAME" -p '#{pane_current_path}' 2>/dev/null) || CWD=""

# Get git branch if in a git repo
GIT_BRANCH=""
if [ -n "$CWD" ] && [ -d "$CWD" ]; then
    GIT_BRANCH=$(git -C "$CWD" rev-parse --abbrev-ref HEAD 2>/dev/null) || GIT_BRANCH=""

    # Check if this is a worktree and add indicator
    if [ -n "$GIT_BRANCH" ]; then
        GIT_DIR=$(git -C "$CWD" rev-parse --git-dir 2>/dev/null) || GIT_DIR=""
        if [ -n "$GIT_DIR" ] && [[ "$GIT_DIR" == *".git/worktrees/"* ]]; then
            GIT_BRANCH="${GIT_BRANCH} (wt)"
        fi
    fi
fi

# Shorten CWD - replace home with ~ and truncate if too long
if [ -n "$CWD" ]; then
    HOME_DIR="$HOME"
    if [[ "$CWD" == "$HOME_DIR"* ]]; then
        CWD="~${CWD#$HOME_DIR}"
    fi
    if [ ${#CWD} -gt 30 ]; then
        CWD="...${CWD: -27}"
    fi
fi

# Build output parts
OUTPUT=""

if [ -n "$SESSION_NAME" ]; then
    OUTPUT="$SESSION_NAME"
fi

if [ -n "$GIT_BRANCH" ]; then
    if [ -n "$OUTPUT" ]; then
        OUTPUT="$OUTPUT | $GIT_BRANCH"
    else
        OUTPUT="$GIT_BRANCH"
    fi
fi

if [ -n "$CWD" ]; then
    if [ -n "$OUTPUT" ]; then
        OUTPUT="$OUTPUT | $CWD"
    else
        OUTPUT="$CWD"
    fi
fi

echo "$OUTPUT"
