#!/usr/bin/env python3
"""Status analyzer for Claude Cowboy.

Status detection via hook-based status files.
Adapted from tmux-claude-status by samleeney (MIT License)
https://github.com/samleeney/tmux-claude-status
"""

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
try:
    from .config import load_config, get_cowboy_data_dir
except ImportError:
    from config import load_config, get_cowboy_data_dir


class SessionStatus(Enum):
    """Possible session status values."""

    WORKING = "working"
    DONE = "done"
    WAIT = "wait"
    NEEDS_INPUT = "needs input"
    PERMISSION_PENDING = "permission pending"
    IDLE = "idle"
    ORCHESTRATING = "orchestrating"  # Parent is coordinating child sessions
    UNKNOWN = "unknown"


@dataclass
class StatusResult:
    """Result of status analysis."""

    status: SessionStatus
    reason: str
    last_activity: datetime | None = None
    is_plan_mode: bool = False
    has_pid: bool = False
    show_by_default: bool = True


@dataclass
class DisplayStatus:
    """Display-friendly status for UI."""

    label: str
    emoji: str
    color_hint: str


@dataclass
class HookState:
    """State from Claude Code hooks."""

    session_id: str
    state: str  # "permission_pending" or "tool_completed"
    tool: str
    command: str | None = None
    description: str | None = None
    timestamp: str | None = None

    @property
    def is_stale(self) -> bool:
        """Check if the hook state is stale (> 5 minutes old)."""
        if not self.timestamp:
            return True
        try:
            ts = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - ts
            return age.total_seconds() > 300  # 5 minutes
        except ValueError:
            return True


def get_hook_state_dir() -> Path:
    """Get the directory where hook state files are stored."""
    return get_cowboy_data_dir() / "hook-state"


def get_hook_status_dir() -> Path:
    """Get the directory where hook status files are stored."""
    return get_cowboy_data_dir() / "status"


def get_wait_dir() -> Path:
    """Get the directory where wait timer files are stored."""
    return get_cowboy_data_dir() / "wait"


def wait_for_session_idle(
    session_id: str,
    timeout_seconds: int = 480,  # 8 minutes default
    poll_interval: float = 2.0,
    max_poll_interval: float = 10.0,
) -> tuple[bool, str]:
    """Wait for a session to become idle (not working).

    Polls the session status until it's no longer WORKING, or timeout is reached.
    Uses exponential backoff to avoid excessive polling.

    Args:
        session_id: The session UUID to monitor.
        timeout_seconds: Maximum time to wait (default 8 minutes).
        poll_interval: Initial polling interval in seconds.
        max_poll_interval: Maximum polling interval (for backoff).

    Returns:
        Tuple of (success, message):
        - (True, "") if session became idle
        - (False, error_message) if timeout or other error
    """
    if not session_id:
        return False, "No session ID provided"

    start_time = time.time()
    current_interval = poll_interval
    last_status = None

    while True:
        elapsed = time.time() - start_time
        if elapsed >= timeout_seconds:
            return False, f"Timeout waiting for session to become idle (waited {int(elapsed)}s)"

        status, suffix = get_session_status(session_id)
        last_status = status

        # Session is idle - we can proceed
        if status != SessionStatus.WORKING:
            if status == SessionStatus.NEEDS_INPUT:
                return True, "Warning: Session is waiting for user input"
            return True, ""

        # Still working - wait and retry with backoff
        time.sleep(current_interval)
        current_interval = min(current_interval * 1.2, max_poll_interval)


def get_session_status(session_id: str) -> tuple[SessionStatus, str]:
    """Get session status from hook status file.

    This is the authoritative status source - hooks are event-driven
    and always current.

    Args:
        session_id: The session UUID.

    Returns:
        Tuple of (SessionStatus, display_suffix). Display suffix may include
        wait time remaining, e.g., "(5m)".
    """
    if not session_id:
        return SessionStatus.UNKNOWN, ""

    status_file = get_hook_status_dir() / f"{session_id}.status"
    wait_file = get_wait_dir() / f"{session_id}.wait"

    # Check for wait timer first
    wait_remaining = ""
    if wait_file.exists():
        try:
            expires = int(wait_file.read_text().strip())
            remaining = expires - int(time.time())
            if remaining > 0:
                minutes = remaining // 60
                wait_remaining = f" ({minutes}m)" if minutes > 0 else " (<1m)"
                return SessionStatus.WAIT, wait_remaining
            else:
                # Timer expired, remove the wait file
                wait_file.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass

    # Read status file
    if not status_file.exists():
        return SessionStatus.UNKNOWN, ""

    try:
        status_text = status_file.read_text().strip().lower()

        if status_text == "working":
            return SessionStatus.WORKING, ""
        elif status_text == "done":
            return SessionStatus.DONE, ""
        elif status_text == "wait":
            return SessionStatus.WAIT, wait_remaining
        else:
            return SessionStatus.UNKNOWN, ""
    except OSError:
        return SessionStatus.UNKNOWN, ""


def read_hook_state(session_id: str | None) -> HookState | None:
    """Read the hook state for a session.

    Args:
        session_id: The JSONL session UUID.

    Returns:
        HookState or None if no state file exists.
    """
    if not session_id:
        return None

    state_file = get_hook_state_dir() / f"{session_id}.json"

    if not state_file.exists():
        return None

    try:
        with open(state_file) as f:
            data = json.load(f)

        hook_state = HookState(
            session_id=data.get("session_id", session_id),
            state=data.get("state", "unknown"),
            tool=data.get("tool", ""),
            command=data.get("command"),
            description=data.get("description"),
            timestamp=data.get("timestamp"),
        )

        # Don't return stale state
        if hook_state.is_stale:
            return None

        return hook_state

    except (json.JSONDecodeError, OSError):
        return None


def analyze_pane_status(
    pane_content: str | None, config: dict | None = None
) -> StatusResult:
    """Analyze tmux pane content to determine session status.

    Args:
        pane_content: Raw text captured from tmux pane.
        config: Optional config dict. If not provided, loads from default.

    Returns:
        StatusResult with detected status and plan mode.
    """
    if not pane_content:
        return StatusResult(
            status=SessionStatus.UNKNOWN,
            reason="No pane content",
            is_plan_mode=False,
        )

    if config is None:
        config = load_config()

    patterns = config.get("statusPatterns", {})

    # Detect plan mode from status bar
    plan_mode_pattern = patterns.get("planMode", "plan mode on")
    is_plan_mode = plan_mode_pattern in pane_content

    # Detect waiting for input
    waiting_pattern = patterns.get("waitingForInput", "Do you want to proceed?")
    is_waiting = waiting_pattern in pane_content

    if is_waiting:
        return StatusResult(
            status=SessionStatus.NEEDS_INPUT,
            reason="Waiting for user confirmation",
            is_plan_mode=is_plan_mode,
        )

    return StatusResult(
        status=SessionStatus.UNKNOWN,
        reason="Status detection not yet implemented",
        is_plan_mode=is_plan_mode,
    )


def analyze_session_status(
    pid: int | None,
    jsonl_path: str | None,
    idle_threshold_minutes: int | None = None,
    session_id: str | None = None,
) -> StatusResult:
    """Analyze session status using hook-based detection.

    Args:
        pid: Process ID if known.
        jsonl_path: Path to JSONL file (used to extract session_id if not provided).
        idle_threshold_minutes: Unused (kept for compatibility).
        session_id: Session UUID. If not provided, extracted from jsonl_path.

    Returns:
        StatusResult with detected status.
    """
    # Extract session_id from jsonl_path if not provided
    if not session_id and jsonl_path:
        # JSONL filename format: {session-id}.jsonl
        from pathlib import Path

        session_id = Path(jsonl_path).stem

    # Get hook-based status
    status, suffix = get_session_status(session_id) if session_id else (SessionStatus.UNKNOWN, "")

    reason = f"Hook status: {status.value}"
    if suffix:
        reason += suffix

    return StatusResult(
        status=status,
        reason=reason,
        has_pid=pid is not None,
        show_by_default=True,
    )


def get_status_emoji(status: SessionStatus) -> str:
    """Get an emoji representation of the status.

    Args:
        status: Session status.

    Returns:
        Emoji string.
    """
    return {
        SessionStatus.WORKING: "⚡",
        SessionStatus.DONE: "✓",
        SessionStatus.WAIT: "⏳",
        SessionStatus.NEEDS_INPUT: "💬",
        SessionStatus.PERMISSION_PENDING: "🔐",
        SessionStatus.IDLE: "💤",
        SessionStatus.ORCHESTRATING: "🎭",
        SessionStatus.UNKNOWN: "❓",
    }.get(status, "❓")


def get_display_status(
    status_result: StatusResult,
    waiting_threshold_minutes: int | None = None,
    hook_state: HookState | None = None,
    suffix: str = "",
) -> DisplayStatus:
    """Get display-friendly status based on analysis result.

    Args:
        status_result: Result from analyze_pane_status or analyze_session_status.
        waiting_threshold_minutes: Unused for now.
        hook_state: Optional hook state from read_hook_state().
        suffix: Optional suffix to append (e.g., wait time remaining).

    Returns:
        DisplayStatus with label, emoji, and color hint.
    """
    status = status_result.status
    is_plan_mode = status_result.is_plan_mode

    # Handle hook-based statuses first (most authoritative)
    if status == SessionStatus.WORKING:
        return DisplayStatus(f"Working{suffix}", "⚡", "working")

    if status == SessionStatus.DONE:
        return DisplayStatus(f"Done{suffix}", "✓", "done")

    if status == SessionStatus.WAIT:
        return DisplayStatus(f"Wait{suffix}", "⏳", "wait")

    # Check hook state for permission pending
    if hook_state and hook_state.state == "permission_pending":
        if is_plan_mode:
            return DisplayStatus("Plan (permit?)", "🔐", "waiting")
        return DisplayStatus("Permit?", "🔐", "waiting")

    # Handle needs input status
    if status == SessionStatus.NEEDS_INPUT:
        if is_plan_mode:
            return DisplayStatus("Plan Waiting", "📋", "waiting")
        return DisplayStatus("Waiting", "💬", "waiting")

    # Plan mode with unknown status
    if is_plan_mode:
        return DisplayStatus("Plan Mode", "📋", "plan")

    return DisplayStatus("Unknown", "❓", "unknown")


if __name__ == "__main__":
    # Test the status detection
    import sys

    print("Hook-based status detection test")
    print(f"Status dir: {get_hook_status_dir()}")
    print(f"Wait dir: {get_wait_dir()}")

    # List any existing status files
    status_dir = get_hook_status_dir()
    if status_dir.exists():
        status_files = list(status_dir.glob("*.status"))
        if status_files:
            print(f"\nFound {len(status_files)} status file(s):")
            for f in status_files:
                status, suffix = get_session_status(f.stem)
                print(f"  {f.stem[:8]}...: {status.value}{suffix}")
        else:
            print("\nNo status files found yet. Run a Claude session to generate them.")
    else:
        print("\nStatus directory does not exist yet.")
