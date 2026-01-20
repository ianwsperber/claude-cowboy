#!/usr/bin/env python3
"""Session preview for Claude Cowboy browser.

Generates a preview with metadata panel (sticky header) and pane capture.
The metadata section outputs exactly HEADER_LINES lines for fzf's sticky header.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ANSI colors
CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
GREEN = "\033[1;32m"
RED = "\033[1;31m"
GRAY = "\033[1;90m"
MAGENTA = "\033[1;35m"
WHITE = "\033[1;37m"
RESET = "\033[0m"
DIM = "\033[2m"

# Box drawing characters
BOX_TL = "╭"
BOX_TR = "╮"
BOX_BL = "╰"
BOX_BR = "╯"
BOX_H = "─"
BOX_V = "│"
BOX_ML = "├"
BOX_MR = "┤"

# Fixed header size (must match fzf --preview-window ~N setting)
HEADER_LINES = 10
BOX_WIDTH = 52

# Model context window sizes (tokens)
MODEL_CONTEXT_WINDOWS = {
    "claude-opus-4-5": 200000,
    "claude-sonnet-4-5": 200000,
    "claude-haiku-4-5": 100000,
    "default": 200000,
}


def get_pane_title(session_name: str) -> str | None:
    """Get the pane title (conversation summary) from tmux."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-t", session_name, "-p", "#{pane_title}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            title = result.stdout.strip()
            return title if title else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_session_cwd(session_name: str) -> str | None:
    """Get the working directory from tmux."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-t", session_name, "-p", "#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            cwd = result.stdout.strip()
            return cwd if cwd else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_git_branch(cwd: str) -> tuple[str | None, bool]:
    """Get git branch for a directory.

    Returns:
        Tuple of (branch_display_name, is_worktree).
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch:
                # Check if it's a worktree (--git-dir contains .git/worktrees for worktrees)
                wt_result = subprocess.run(
                    ["git", "-C", cwd, "rev-parse", "--git-dir"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                is_worktree = (
                    wt_result.returncode == 0 and
                    ".git/worktrees" in wt_result.stdout
                )
                if is_worktree:
                    return f"{branch} (wt)", True
                return branch, False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None, False


def get_safety_status(cwd: str) -> tuple[str, str]:
    """Get branch safety status for worktree deletion.

    Returns:
        Tuple of (status, display_indicator).
        Status is: in_remote_main, pushed, in_local_main, in_local_branch, unpushed, worktree_only
    """
    try:
        # Import here to avoid circular imports
        from session_registry import get_branch_safety_status
        safety = get_branch_safety_status(cwd)
        return safety.status, safety.display_indicator
    except ImportError:
        pass

    # Fallback: compute inline if import fails
    try:
        # Check if in origin/main
        result = subprocess.run(
            ["git", "-C", cwd, "merge-base", "--is-ancestor", "HEAD", "origin/main"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "in_remote_main", "[in remote main]"

        # Check if in any remote branch
        result = subprocess.run(
            ["git", "-C", cwd, "branch", "-r", "--contains", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "pushed", "[pushed]"

        # Check if in local main
        result = subprocess.run(
            ["git", "-C", cwd, "merge-base", "--is-ancestor", "HEAD", "main"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "in_local_main", "[in local main]"

        return "worktree_only", "[worktree only]"

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "worktree_only", "[worktree only]"


def find_session_jsonl(cwd: str) -> Path | None:
    """Find the most recent JSONL file for a session directory."""
    claude_home = Path.home() / ".claude"
    projects_dir = claude_home / "projects"

    if not projects_dir.exists():
        return None

    # Convert cwd to project path format
    cwd_encoded = cwd.replace("/", "-")
    if cwd_encoded.startswith("-"):
        cwd_encoded = cwd_encoded[1:]

    # Look for matching project directories
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        dir_name = project_dir.name
        if (cwd_encoded in dir_name or
            dir_name.endswith(cwd_encoded) or
            cwd.split("/")[-1] in dir_name):

            jsonl_files = list(project_dir.glob("*.jsonl"))
            if jsonl_files:
                jsonl_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                for f in jsonl_files:
                    if not f.stem.startswith("agent-"):
                        return f

    return None


def get_session_metadata(jsonl_path: Path) -> dict:
    """Extract metadata from session JSONL."""
    metadata = {
        "message_count": 0,
        "last_activity": None,
        "first_activity": None,
        "slug": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "model": None,
        "context_percent": None,
        "current_context_tokens": None,
    }

    try:
        with open(jsonl_path, "r") as f:
            lines = f.readlines()

        metadata["message_count"] = len(lines)

        if not lines:
            return metadata

        # Scan forward to find first timestamp
        for line in lines:
            try:
                entry = json.loads(line)
                if "timestamp" in entry:
                    ts = entry["timestamp"]
                    if ts.endswith("Z"):
                        ts = ts.replace("Z", "+00:00")
                    metadata["first_activity"] = datetime.fromisoformat(ts)
                    break
            except json.JSONDecodeError:
                continue

        # Scan backward to find last timestamp, slug, model, and current context
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if not metadata["last_activity"] and "timestamp" in entry:
                    ts = entry["timestamp"]
                    if ts.endswith("Z"):
                        ts = ts.replace("Z", "+00:00")
                    metadata["last_activity"] = datetime.fromisoformat(ts)
                if not metadata["slug"] and entry.get("slug"):
                    metadata["slug"] = entry["slug"]
                if "message" in entry:
                    msg = entry["message"]
                    if isinstance(msg, dict):
                        if not metadata["model"] and "model" in msg:
                            metadata["model"] = msg["model"]
                        # Get current context from most recent usage data
                        if metadata["current_context_tokens"] is None and "usage" in msg:
                            usage = msg["usage"]
                            # Current context = input + cache_read + cache_creation
                            current = (
                                usage.get("input_tokens", 0)
                                + usage.get("cache_read_input_tokens", 0)
                                + usage.get("cache_creation_input_tokens", 0)
                            )
                            if current > 0:
                                metadata["current_context_tokens"] = current
                all_found = (
                    metadata["last_activity"]
                    and metadata["slug"]
                    and metadata["model"]
                    and metadata["current_context_tokens"] is not None
                )
                if all_found:
                    break
            except json.JSONDecodeError:
                continue

        # Aggregate token counts
        for line in lines:
            try:
                entry = json.loads(line)
                if "message" in entry and isinstance(entry["message"], dict):
                    usage = entry["message"].get("usage", {})
                    metadata["input_tokens"] += usage.get("input_tokens", 0)
                    metadata["output_tokens"] += usage.get("output_tokens", 0)
            except json.JSONDecodeError:
                continue

        # Calculate context percentage from current context size
        if metadata["current_context_tokens"] and metadata["model"]:
            # Extract base model name (e.g., "claude-opus-4-5" from "claude-opus-4-5-20251101")
            model_base = "-".join(metadata["model"].split("-")[:4])
            context_window = MODEL_CONTEXT_WINDOWS.get(
                model_base, MODEL_CONTEXT_WINDOWS["default"]
            )
            metadata["context_percent"] = (
                metadata["current_context_tokens"] / context_window
            ) * 100

    except (OSError, IOError):
        pass

    return metadata


def format_duration(delta) -> str:
    """Format a timedelta as human-readable duration."""
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds}s"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes}m"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours}h"
    else:
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        if hours > 0:
            return f"{days}d {hours}h"
        return f"{days}d"


def format_tokens(count: int) -> str:
    """Format token count with K/M suffix."""
    if count < 1000:
        return str(count)
    elif count < 1000000:
        return f"{count / 1000:.1f}K"
    else:
        return f"{count / 1000000:.1f}M"


def capture_pane(session_name: str) -> str:
    """Capture the tmux pane content."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-ep", "-t", session_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "No preview available"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', text)


def visible_len(text: str) -> int:
    """Get visible length of text (excluding ANSI codes)."""
    return len(strip_ansi(text))


def box_line(content: str, width: int = BOX_WIDTH) -> str:
    """Create a line inside the box with proper padding."""
    # Account for box characters and padding
    inner_width = width - 4  # 2 for box chars, 2 for padding
    visible = visible_len(content)

    # Truncate if too long (based on visible length)
    if visible > inner_width:
        # Need to truncate carefully to not break ANSI codes
        stripped = strip_ansi(content)
        truncated = stripped[:inner_width - 1] + "…"
        # Rebuild without colors for simplicity when truncating
        content = truncated
        visible = len(truncated)

    # Pad to fill (accounting for invisible ANSI codes)
    padding_needed = inner_width - visible
    padded = content + " " * padding_needed
    return f"{CYAN}{BOX_V}{RESET} {padded} {CYAN}{BOX_V}{RESET}"


def print_header_box(
    metadata: dict,
    pane_title: str | None,
    cwd: str | None,
    git_branch: str | None,
    is_worktree: bool = False,
    safety_status: str = "",
    safety_indicator: str = "",
):
    """Print the metadata box with exactly HEADER_LINES lines."""
    lines_printed = 0
    inner_width = BOX_WIDTH - 2

    # Line 1: Top border
    print(f"{CYAN}{BOX_TL}{BOX_H * inner_width}{BOX_TR}{RESET}")
    lines_printed += 1

    # Line 2: Title (summary)
    if pane_title:
        summary = pane_title.strip()
        # Keep the asterisk/symbol prefix for visual indication
        title = f" {summary}"
    else:
        title = " (no summary)"
    # Truncate if needed
    if len(title) > inner_width:
        title = title[:inner_width - 1] + "…"
    # Use YELLOW for visibility on both light and dark backgrounds
    print(f"{CYAN}{BOX_V}{YELLOW}{title.ljust(inner_width)}{RESET}{CYAN}{BOX_V}{RESET}")
    lines_printed += 1

    # Line 3: Separator
    print(f"{CYAN}{BOX_ML}{BOX_H * inner_width}{BOX_MR}{RESET}")
    lines_printed += 1

    # Line 4: Directory
    if cwd:
        display_cwd = cwd
        home = os.path.expanduser("~")
        if display_cwd.startswith(home):
            display_cwd = "~" + display_cwd[len(home):]
        print(box_line(f"{GREEN}Dir:{RESET} {display_cwd}"))
    else:
        print(box_line(f"{GRAY}Dir: (unknown){RESET}"))
    lines_printed += 1

    # Line 5: Branch
    if git_branch:
        print(box_line(f"{GREEN}Branch:{RESET} {git_branch}"))
    else:
        print(box_line(f"{GRAY}Branch: (none){RESET}"))
    lines_printed += 1

    # Line 6: Worktree status (only for worktrees)
    if is_worktree and safety_indicator:
        # Color based on safety status
        if safety_status in ("in_remote_main", "pushed"):
            color = GREEN
        elif safety_status in ("in_local_main", "in_local_branch", "unpushed"):
            color = YELLOW
        else:  # worktree_only
            color = RED
        print(box_line(f"{GREEN}Worktree:{RESET} {color}{safety_indicator}{RESET}"))
    else:
        print(box_line(f"{GRAY}Worktree: -{RESET}"))
    lines_printed += 1

    # Line 7: Age
    if metadata.get("first_activity"):
        now = datetime.now(timezone.utc)
        age = now - metadata["first_activity"]
        age_str = format_duration(age)
        print(box_line(f"{GREEN}Age:{RESET} {age_str}"))
    else:
        print(box_line(f"{GRAY}Age: (unknown){RESET}"))
    lines_printed += 1

    # Line 8: Tokens
    input_tokens = metadata.get("input_tokens", 0)
    output_tokens = metadata.get("output_tokens", 0)
    total_tokens = input_tokens + output_tokens
    context_percent = metadata.get("context_percent")
    if total_tokens > 0:
        token_str = f"{format_tokens(total_tokens)} ({format_tokens(input_tokens)}↓ {format_tokens(output_tokens)}↑)"
        if context_percent is not None:
            token_str += f" · {context_percent:.0f}%"
        print(box_line(f"{GREEN}Tokens:{RESET} {token_str}"))
    else:
        print(box_line(f"{GRAY}Tokens: 0{RESET}"))
    lines_printed += 1

    # Line 9: Messages
    msg_count = metadata.get("message_count", 0)
    print(box_line(f"{GREEN}Messages:{RESET} {msg_count}"))
    lines_printed += 1

    # Line 10: Bottom border
    print(f"{CYAN}{BOX_BL}{BOX_H * inner_width}{BOX_BR}{RESET}")
    lines_printed += 1

    # Pad to exactly HEADER_LINES if needed
    while lines_printed < HEADER_LINES:
        print()
        lines_printed += 1


def main():
    if len(sys.argv) < 2:
        print("Usage: session_preview.py <session_name>")
        sys.exit(1)

    session_name = sys.argv[1]

    # Gather metadata
    pane_title = get_pane_title(session_name)
    cwd = get_session_cwd(session_name)

    git_branch = None
    is_worktree = False
    safety_status = ""
    safety_indicator = ""

    if cwd:
        git_branch, is_worktree = get_git_branch(cwd)
        if is_worktree:
            safety_status, safety_indicator = get_safety_status(cwd)

    # Try to find JSONL for additional metadata
    jsonl_path = find_session_jsonl(cwd) if cwd else None
    jsonl_meta = get_session_metadata(jsonl_path) if jsonl_path else {}

    # Print the header box (exactly HEADER_LINES lines)
    print_header_box(
        jsonl_meta,
        pane_title,
        cwd,
        git_branch,
        is_worktree=is_worktree,
        safety_status=safety_status,
        safety_indicator=safety_indicator,
    )

    # Print pane content (scrollable)
    pane_content = capture_pane(session_name)
    print(pane_content)


if __name__ == "__main__":
    main()
