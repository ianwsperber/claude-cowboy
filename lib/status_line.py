#!/usr/bin/env python3
"""tmux status line output for Claude Cowboy.

Adapted from tmux-claude-status by samleeney (MIT License)
https://github.com/samleeney/tmux-claude-status
"""

import os
import subprocess
import sys
from pathlib import Path

try:
    from .status_analyzer import get_hook_status_dir, get_wait_dir, SessionStatus
    from .session_registry import get_cached_git_info
except ImportError:
    from status_analyzer import get_hook_status_dir, get_wait_dir, SessionStatus
    from session_registry import get_cached_git_info


def get_status_counts() -> dict[str, int]:
    """Get counts of sessions by status.

    Returns:
        Dict with keys 'working', 'done', 'wait'.
    """
    counts = {"working": 0, "done": 0, "wait": 0}

    status_dir = get_hook_status_dir()
    if not status_dir.exists():
        return counts

    for status_file in status_dir.glob("*.status"):
        try:
            status = status_file.read_text().strip().lower()
            if status == "working":
                counts["working"] += 1
            elif status == "done":
                counts["done"] += 1
            elif status == "wait":
                counts["wait"] += 1
        except OSError:
            continue

    # Also count wait timers (they may not have updated status yet)
    wait_dir = get_wait_dir()
    if wait_dir.exists():
        import time
        current_time = int(time.time())
        for wait_file in wait_dir.glob("*.wait"):
            try:
                expires = int(wait_file.read_text().strip())
                if current_time < expires:
                    # Count as waiting if timer hasn't expired
                    # This may double count some, but better than missing
                    pass
            except (ValueError, OSError):
                continue

    return counts


def get_current_session_info(session_name: str | None = None) -> tuple[str | None, str | None, str | None]:
    """Get current tmux session name, CWD, and git branch.

    Args:
        session_name: If provided, query this specific session. Otherwise auto-detect.

    Returns:
        Tuple of (session_name, cwd, git_branch). Any can be None.
    """
    # If session name not provided, try to detect it
    if not session_name:
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#{session_name}"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode != 0:
                return None, None, None
            session_name = result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            return None, None, None

    # Get the session's current pane CWD using -t to target specific session
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-t", session_name, "-p", "#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        cwd = result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.SubprocessError, FileNotFoundError):
        cwd = None

    # Get git branch if in a git repo
    git_branch = None
    if cwd:
        git_info = get_cached_git_info(cwd)
        git_branch = git_info.branch

    return session_name, cwd, git_branch


def format_status_line(use_color: bool = True, session_name: str | None = None) -> str:
    """Format status line for tmux.

    Args:
        use_color: If True, include tmux color codes (currently unused).
        session_name: If provided, query this specific session.

    Returns:
        Formatted status string.
    """
    session_name, cwd, git_branch = get_current_session_info(session_name)

    parts = []

    # Current session info
    if session_name:
        parts.append(session_name)

    if git_branch:
        parts.append(git_branch)

    if cwd:
        # Shorten CWD
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        if len(cwd) > 30:
            cwd = "..." + cwd[-27:]
        parts.append(cwd)

    return " | ".join(parts)


def main():
    """Output status line for tmux."""
    import argparse

    parser = argparse.ArgumentParser(description="Claude Cowboy tmux status line")
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable tmux color codes",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="tmux session name (passed via tmux #S variable)",
    )
    args = parser.parse_args()

    if args.json:
        import json
        counts = get_status_counts()
        print(json.dumps(counts))
    else:
        output = format_status_line(use_color=not args.no_color, session_name=args.session)
        if output:
            print(output)


if __name__ == "__main__":
    main()
