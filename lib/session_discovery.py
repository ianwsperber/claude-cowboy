#!/usr/bin/env python3
"""Session discovery module for Claude Cowboy.

Session-ID centric approach: scans JSONL files directly, then correlates to PIDs.
This catches multiple sessions per directory and IDE sessions.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .config import get_claude_home, is_debug_enabled, load_config
except ImportError:
    from config import get_claude_home, is_debug_enabled, load_config


@dataclass
class SessionInfo:
    """Information about a Claude Code session."""

    session_id: str
    cwd: str
    jsonl_path: str
    pid: int | None = None  # None if no running process found
    git_branch: str = ""
    project_path: str = ""
    last_activity: datetime | None = None
    message_count: int = 0
    slug: str = ""


def find_claude_processes() -> dict[str, list[int]]:
    """Find all running Claude Code CLI processes.

    Returns:
        Dict mapping CWD -> list of PIDs for running Claude processes.
        Multiple processes can have the same CWD.
    """
    cwd_to_pids: dict[str, list[int]] = {}

    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return {}

        for line in result.stdout.split("\n"):
            # Match CLI claude processes
            # Exclude Claude.app helpers (GPU, Renderer, network, etc.)
            if ("claude" in line.lower() and
                "Claude.app" not in line and
                "chrome_crashpad" not in line and
                "disclaimer" not in line and
                "grep" not in line):

                parts = line.split()
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1])
                        cwd = get_process_cwd(pid)
                        if cwd and cwd.startswith("/"):
                            if cwd not in cwd_to_pids:
                                cwd_to_pids[cwd] = []
                            cwd_to_pids[cwd].append(pid)
                    except (ValueError, IndexError):
                        continue

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        if is_debug_enabled():
            print(f"Error finding Claude processes: {e}")

    return cwd_to_pids


def get_process_cwd(pid: int) -> str | None:
    """Get the current working directory of a process.

    Args:
        pid: Process ID.

    Returns:
        Working directory path or None.
    """
    try:
        result = subprocess.run(
            ["lsof", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )

        for line in result.stdout.split("\n"):
            if "cwd" in line:
                parts = line.split()
                if len(parts) >= 9:
                    return parts[-1]

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        if is_debug_enabled():
            print(f"Error getting CWD for PID {pid}: {e}")

    return None


def get_ide_sessions() -> dict[str, list[int]]:
    """Get IDE sessions from lock files.

    Returns:
        Dict mapping workspace folder -> list of PIDs for IDE sessions.
    """
    cwd_to_pids: dict[str, list[int]] = {}
    claude_home = get_claude_home()
    ide_dir = claude_home / "ide"

    if not ide_dir.exists():
        return {}

    for lock_file in ide_dir.glob("*.lock"):
        try:
            with open(lock_file) as f:
                data = json.load(f)

            pid = data.get("pid")
            workspace_folders = data.get("workspaceFolders", [])

            if pid and workspace_folders:
                # Check if process is still running
                try:
                    os.kill(pid, 0)
                    for folder in workspace_folders:
                        if folder not in cwd_to_pids:
                            cwd_to_pids[folder] = []
                        if pid not in cwd_to_pids[folder]:
                            cwd_to_pids[folder].append(pid)
                except OSError:
                    pass  # Process not running

        except (json.JSONDecodeError, OSError) as e:
            if is_debug_enabled():
                print(f"Error reading IDE lock file {lock_file}: {e}")

    return cwd_to_pids


def scan_session_files(discovery_hours: int = 24) -> list[tuple[str, Path]]:
    """Scan for all session JSONL files modified within threshold.

    Excludes subagent sessions (agent-* files in subagents/ directories).

    Args:
        discovery_hours: How far back to look for sessions.

    Returns:
        List of (session_id, jsonl_path) tuples.
    """
    sessions = []
    claude_home = get_claude_home()
    projects_dir = claude_home / "projects"

    if not projects_dir.exists():
        return []

    cutoff = datetime.now() - timedelta(hours=discovery_hours)

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        # Only scan top-level JSONL files, not subagents/ subdirectories
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                # Skip subagent sessions (they start with "agent-")
                session_id = jsonl_file.stem
                if session_id.startswith("agent-"):
                    continue

                mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
                if mtime >= cutoff:
                    sessions.append((session_id, jsonl_file))
            except OSError:
                continue

    return sessions


def get_session_metadata(jsonl_path: Path) -> dict:
    """Extract metadata from a session JSONL file.

    Args:
        jsonl_path: Path to the session .jsonl file.

    Returns:
        Dict with cwd, git_branch, last_activity, message_count, slug.
    """
    metadata = {
        "cwd": "",
        "git_branch": "",
        "last_activity": None,
        "message_count": 0,
        "slug": "",
    }

    try:
        with open(jsonl_path, "r") as f:
            lines = f.readlines()

        metadata["message_count"] = len(lines)

        if not lines:
            return metadata

        # Parse the last line for most recent info
        try:
            last_entry = json.loads(lines[-1])
            if "timestamp" in last_entry:
                ts = last_entry["timestamp"]
                if ts.endswith("Z"):
                    ts = ts.replace("Z", "+00:00")
                metadata["last_activity"] = datetime.fromisoformat(ts)
            if "cwd" in last_entry:
                metadata["cwd"] = last_entry["cwd"]
            if "gitBranch" in last_entry:
                metadata["git_branch"] = last_entry["gitBranch"]
            if "slug" in last_entry:
                metadata["slug"] = last_entry["slug"]
        except json.JSONDecodeError:
            pass

        # Scan backwards for missing fields
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if not metadata["cwd"] and entry.get("cwd"):
                    metadata["cwd"] = entry["cwd"]
                if not metadata["git_branch"] and entry.get("gitBranch"):
                    metadata["git_branch"] = entry["gitBranch"]
                if not metadata["slug"] and entry.get("slug"):
                    metadata["slug"] = entry["slug"]
                # Break early if we have all fields
                if metadata["cwd"] and metadata["git_branch"]:
                    break
            except json.JSONDecodeError:
                continue

    except (OSError, IOError) as e:
        if is_debug_enabled():
            print(f"Error reading session metadata: {e}")

    return metadata


def discover_all_sessions(discovery_hours: int | None = None) -> list[SessionInfo]:
    """Discover ALL sessions within the discovery window.

    This is used for --all flag. Returns all sessions regardless of PID status.

    Args:
        discovery_hours: How far back to look (default from config).

    Returns:
        List of SessionInfo objects for all sessions.
    """
    config = load_config()
    if discovery_hours is None:
        discovery_hours = config.get("sessionDiscoveryHours", 24)

    # Get running processes for PID correlation
    # Merge IDE and CLI processes (CLI takes precedence for same CWD)
    ide_processes = get_ide_sessions()
    cli_processes = find_claude_processes()

    # Merge: start with IDE, then add/extend with CLI
    all_processes: dict[str, list[int]] = {}
    for cwd, pids in ide_processes.items():
        all_processes[cwd] = pids.copy()
    for cwd, pids in cli_processes.items():
        if cwd in all_processes:
            # CLI PIDs go first (higher priority)
            all_processes[cwd] = pids + [p for p in all_processes[cwd] if p not in pids]
        else:
            all_processes[cwd] = pids.copy()

    # Scan all session files
    session_files = scan_session_files(discovery_hours)

    # Build sessions list
    sessions = []
    for session_id, jsonl_path in session_files:
        metadata = get_session_metadata(jsonl_path)
        cwd = metadata["cwd"]

        sessions.append(
            SessionInfo(
                session_id=session_id,
                cwd=cwd,
                jsonl_path=str(jsonl_path),
                pid=None,  # Assigned below
                git_branch=metadata["git_branch"],
                project_path=cwd,
                last_activity=metadata["last_activity"],
                message_count=metadata["message_count"],
                slug=metadata["slug"],
            )
        )

    # Sort by last activity (most recent first)
    sessions.sort(
        key=lambda s: s.last_activity or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    # Assign PIDs to sessions, matching by CWD or parent directory
    # Each PID is assigned to at most one session (most recent first)
    # Sessions are already sorted by last_activity (most recent first)

    for session in sessions:
        if not session.cwd:
            continue

        # Try exact CWD match first
        pids = all_processes.get(session.cwd, [])

        # If no exact match, check if session CWD is under a process CWD
        if not pids:
            for proc_cwd, proc_pids in all_processes.items():
                if session.cwd.startswith(proc_cwd + "/") and proc_pids:
                    pids = proc_pids
                    break

        # Assign the first available PID from the list
        if pids:
            session.pid = pids.pop(0)  # Remove from list so it's not reused

    return sessions


def discover_sessions(
    discovery_hours: int | None = None,
    include_hidden: bool = False,
) -> list[SessionInfo]:
    """Discover sessions with visibility filtering (hybrid PID + recency).

    Default behavior: Only show sessions that either:
    - Have a matched PID (definitely running), OR
    - Have activity within hideThresholdMinutes (probably running)

    Args:
        discovery_hours: How far back to look for JSONL files.
        include_hidden: If True, include all sessions (like --all flag).

    Returns:
        List of SessionInfo objects for visible sessions.
    """
    config = load_config()
    hide_threshold = config.get("hideThresholdMinutes", 15)

    all_sessions = discover_all_sessions(discovery_hours)

    if include_hidden:
        return all_sessions

    # Filter to visible sessions
    now = datetime.now(timezone.utc)
    visible = []

    for session in all_sessions:
        # Has PID -> always show
        if session.pid is not None:
            visible.append(session)
            continue

        # No PID -> check recency
        if session.last_activity:
            elapsed_minutes = (now - session.last_activity).total_seconds() / 60
            if elapsed_minutes < hide_threshold:
                visible.append(session)

    return visible


def get_session_by_id(session_id: str) -> SessionInfo | None:
    """Get session info by session ID.

    Args:
        session_id: The session UUID (full or partial).

    Returns:
        SessionInfo or None if not found.
    """
    sessions = discover_all_sessions()
    for session in sessions:
        if session.session_id == session_id or session.session_id.startswith(session_id):
            return session
    return None


def get_session_by_pid(pid: int) -> SessionInfo | None:
    """Get session info by process ID.

    Args:
        pid: The process ID.

    Returns:
        SessionInfo or None if not found.
    """
    sessions = discover_sessions()
    for session in sessions:
        if session.pid == pid:
            return session
    return None


if __name__ == "__main__":
    # Test session discovery
    print("Discovering Claude Code sessions...\n")

    print("=== Visible sessions (default) ===\n")
    sessions = discover_sessions()

    if not sessions:
        print("No active Claude Code sessions found.\n")
    else:
        print(f"Found {len(sessions)} visible session(s):\n")
        for s in sessions:
            print(f"Session ID: {s.session_id[:8]}...")
            print(f"  PID: {s.pid or '-'}")
            print(f"  CWD: {s.cwd}")
            print(f"  Git Branch: {s.git_branch or '(none)'}")
            print(f"  Messages: {s.message_count}")
            print(f"  Last Activity: {s.last_activity}")
            print(f"  Slug: {s.slug or '(none)'}")
            print()

    print("=== All sessions (--all) ===\n")
    all_sessions = discover_all_sessions()
    print(f"Total sessions in last 24h: {len(all_sessions)}")
    print(f"Hidden: {len(all_sessions) - len(sessions)}")
