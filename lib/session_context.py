#!/usr/bin/env python3
"""Session context loading for Claude Cowboy.

Provides functions to load and format conversation transcripts from Claude sessions.
Used by the lasso subagent to query other sessions' context.
"""

import json
import subprocess
from pathlib import Path
from typing import Optional

try:
    from .config import get_claude_home, is_debug_enabled
    from .session_discovery import scan_session_files, get_session_metadata
except ImportError:
    from config import get_claude_home, is_debug_enabled
    from session_discovery import scan_session_files, get_session_metadata


def get_tmux_session_cwd(session_name: str) -> Optional[str]:
    """Get the current working directory of a tmux session.

    Args:
        session_name: tmux session name.

    Returns:
        CWD path or None if session not found.
    """
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-t", session_name, "-p", "#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_git_branch(cwd: str) -> Optional[str]:
    """Get the current git branch for a directory.

    Args:
        cwd: Working directory path.

    Returns:
        Branch name or None.
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def cwd_to_project_dir(cwd: str) -> Path:
    """Convert a CWD path to the Claude projects directory path.

    Claude stores sessions in ~/.claude/projects/{encoded_path}/

    Args:
        cwd: Working directory path.

    Returns:
        Path to the project directory in ~/.claude/projects/
    """
    # Claude encodes the CWD path by replacing / with -
    # and using the absolute path starting from root
    encoded = cwd.replace("/", "-").lstrip("-")
    return get_claude_home() / "projects" / encoded


def find_session_jsonl(session_name: str) -> Optional[Path]:
    """Find a session's JSONL file by tmux session name.

    Args:
        session_name: tmux session name.

    Returns:
        Path to JSONL file or None.
    """
    # Get the session's CWD
    cwd = get_tmux_session_cwd(session_name)
    if not cwd:
        if is_debug_enabled():
            print(f"Could not get CWD for session '{session_name}'")
        return None

    # Convert to project directory
    project_dir = cwd_to_project_dir(cwd)
    if not project_dir.exists():
        if is_debug_enabled():
            print(f"Project directory not found: {project_dir}")
        return None

    # Find JSONL files in this project directory
    jsonl_files = list(project_dir.glob("*.jsonl"))
    if not jsonl_files:
        if is_debug_enabled():
            print(f"No JSONL files found in {project_dir}")
        return None

    # Filter out agent files and sort by modification time
    main_sessions = [f for f in jsonl_files if not f.stem.startswith("agent-")]
    if not main_sessions:
        # Fallback to all files if no main sessions
        main_sessions = jsonl_files

    # Return most recently modified
    main_sessions.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return main_sessions[0]


def find_jsonl_by_uuid(uuid: str) -> Optional[Path]:
    """Find a session's JSONL file by UUID.

    Args:
        uuid: Session UUID (full or partial).

    Returns:
        Path to JSONL file or None.
    """
    claude_home = get_claude_home()
    projects_dir = claude_home / "projects"

    if not projects_dir.exists():
        return None

    # Search all project directories for matching UUID
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        for jsonl_file in project_dir.glob("*.jsonl"):
            if jsonl_file.stem == uuid or jsonl_file.stem.startswith(uuid):
                return jsonl_file

    return None


def format_assistant_message(entry: dict) -> str:
    """Format an assistant message entry.

    Args:
        entry: JSONL entry dict.

    Returns:
        Formatted string with text and tool call summaries.
    """
    content_parts = []
    message = entry.get("message", {})
    content = message.get("content", [])

    # Handle both string and list content
    if isinstance(content, str):
        return content

    for block in content:
        if isinstance(block, str):
            content_parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    content_parts.append(text)
            elif block.get("type") == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                # Summarize tool call
                if tool_name == "Read":
                    file_path = tool_input.get("file_path", "")
                    content_parts.append(f"[Read: {file_path}]")
                elif tool_name == "Write":
                    file_path = tool_input.get("file_path", "")
                    content_parts.append(f"[Write: {file_path}]")
                elif tool_name == "Edit":
                    file_path = tool_input.get("file_path", "")
                    content_parts.append(f"[Edit: {file_path}]")
                elif tool_name == "Bash":
                    cmd = tool_input.get("command", "")[:80]
                    content_parts.append(f"[Bash: {cmd}...]")
                elif tool_name == "TodoWrite":
                    content_parts.append("[Updated todo list]")
                else:
                    content_parts.append(f"[{tool_name}]")

    return "\n".join(content_parts)


def format_user_message(entry: dict) -> str:
    """Format a user message entry.

    Args:
        entry: JSONL entry dict.

    Returns:
        Formatted message string.
    """
    message = entry.get("message", {})
    content = message.get("content", "")

    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Extract text from content blocks
        texts = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)

    return str(content)


def load_jsonl_transcript(jsonl_path: Path, max_messages: int = 100) -> str:
    """Load JSONL and format as human-readable transcript.

    Args:
        jsonl_path: Path to JSONL file.
        max_messages: Maximum number of messages to include.

    Returns:
        Formatted transcript string.
    """
    messages = []
    truncated = False

    try:
        with open(jsonl_path) as f:
            lines = f.readlines()

        # Process lines
        for line in lines:
            try:
                entry = json.loads(line)
                entry_type = entry.get("type", "")

                # Skip warmup/sidechain messages
                if entry.get("isSidechain"):
                    continue
                if entry.get("message", {}).get("content") == "Warmup":
                    continue

                if entry_type == "human":
                    content = format_user_message(entry)
                    if content.strip():
                        messages.append(f"USER:\n{content}")
                elif entry_type == "assistant":
                    content = format_assistant_message(entry)
                    if content.strip():
                        messages.append(f"ASSISTANT:\n{content}")
                # Skip tool_result, summary, and other types

            except json.JSONDecodeError:
                continue

        # Truncate if too long
        if len(messages) > max_messages:
            truncated = True
            messages = messages[-max_messages:]

    except (OSError, IOError) as e:
        return f"Error reading JSONL file: {e}"

    # Build transcript
    transcript = "\n\n---\n\n".join(messages)

    if truncated:
        transcript = f"[... earlier messages truncated, showing last {max_messages} messages ...]\n\n" + transcript

    return transcript


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python session_context.py <session_name|uuid|jsonl_path>")
        sys.exit(1)

    target = sys.argv[1]

    # Try to determine what kind of target it is
    jsonl_path = None

    if target.endswith(".jsonl"):
        jsonl_path = Path(target)
    elif "-" in target and len(target) > 30:
        # Looks like a UUID
        jsonl_path = find_jsonl_by_uuid(target)
    else:
        # Try as tmux session name
        jsonl_path = find_session_jsonl(target)

    if not jsonl_path or not jsonl_path.exists():
        print(f"Could not find JSONL for '{target}'")
        sys.exit(1)

    print(f"# Session JSONL: {jsonl_path}")
    print()
    transcript = load_jsonl_transcript(jsonl_path)
    print(transcript)
