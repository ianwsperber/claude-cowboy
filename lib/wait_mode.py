#!/usr/bin/env python3
"""Wait mode for Claude Cowboy.

Adapted from tmux-claude-status by samleeney (MIT License)
https://github.com/samleeney/tmux-claude-status
"""

import sys
import time
from pathlib import Path

try:
    from .config import get_cowboy_data_dir
    from .status_analyzer import get_wait_dir, get_hook_status_dir
except ImportError:
    from config import get_cowboy_data_dir
    from status_analyzer import get_wait_dir, get_hook_status_dir


def set_wait(session_id: str, minutes: int) -> bool:
    """Set a wait timer for a session.

    Args:
        session_id: Session UUID.
        minutes: Number of minutes to wait.

    Returns:
        True if timer was set successfully.
    """
    if not session_id or minutes < 1:
        return False

    wait_dir = get_wait_dir()
    wait_dir.mkdir(parents=True, exist_ok=True)

    wait_file = wait_dir / f"{session_id}.wait"
    expires = int(time.time()) + (minutes * 60)

    try:
        wait_file.write_text(str(expires))

        # Also set status to "wait"
        status_dir = get_hook_status_dir()
        status_dir.mkdir(parents=True, exist_ok=True)
        status_file = status_dir / f"{session_id}.status"
        status_file.write_text("wait")

        return True
    except OSError:
        return False


def cancel_wait(session_id: str) -> bool:
    """Cancel a wait timer for a session.

    Args:
        session_id: Session UUID.

    Returns:
        True if timer was cancelled (or didn't exist).
    """
    if not session_id:
        return False

    wait_file = get_wait_dir() / f"{session_id}.wait"

    try:
        if wait_file.exists():
            wait_file.unlink()
        return True
    except OSError:
        return False


def get_wait_remaining(session_id: str) -> int | None:
    """Get the remaining wait time for a session.

    Args:
        session_id: Session UUID.

    Returns:
        Remaining seconds, or None if no timer is set.
    """
    if not session_id:
        return None

    wait_file = get_wait_dir() / f"{session_id}.wait"

    if not wait_file.exists():
        return None

    try:
        expires = int(wait_file.read_text().strip())
        remaining = expires - int(time.time())
        return max(0, remaining)
    except (ValueError, OSError):
        return None


def is_waiting(session_id: str) -> bool:
    """Check if a session has an active wait timer.

    Args:
        session_id: Session UUID.

    Returns:
        True if wait timer is active.
    """
    remaining = get_wait_remaining(session_id)
    return remaining is not None and remaining > 0


def check_expired_timers() -> list[str]:
    """Check for and clean up expired wait timers.

    Returns:
        List of session IDs whose timers expired.
    """
    expired = []
    wait_dir = get_wait_dir()

    if not wait_dir.exists():
        return expired

    current_time = int(time.time())
    status_dir = get_hook_status_dir()

    for wait_file in wait_dir.glob("*.wait"):
        try:
            expires = int(wait_file.read_text().strip())
            if current_time >= expires:
                # Timer expired
                session_id = wait_file.stem
                expired.append(session_id)

                # Remove wait file
                wait_file.unlink()

                # Update status to "done"
                status_file = status_dir / f"{session_id}.status"
                if status_file.exists():
                    try:
                        status_file.write_text("done")
                    except OSError:
                        pass
        except (ValueError, OSError):
            continue

    return expired


def list_waiting_sessions() -> list[tuple[str, int]]:
    """List all sessions with active wait timers.

    Returns:
        List of (session_id, remaining_seconds) tuples.
    """
    waiting = []
    wait_dir = get_wait_dir()

    if not wait_dir.exists():
        return waiting

    current_time = int(time.time())

    for wait_file in wait_dir.glob("*.wait"):
        try:
            expires = int(wait_file.read_text().strip())
            remaining = expires - current_time
            if remaining > 0:
                waiting.append((wait_file.stem, remaining))
        except (ValueError, OSError):
            continue

    return waiting


def main():
    """CLI for wait mode."""
    import argparse

    parser = argparse.ArgumentParser(description="Claude Cowboy wait mode")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # set
    set_parser = subparsers.add_parser("set", help="Set wait timer")
    set_parser.add_argument("session_id", help="Session UUID")
    set_parser.add_argument("minutes", type=int, help="Minutes to wait")

    # cancel
    cancel_parser = subparsers.add_parser("cancel", help="Cancel wait timer")
    cancel_parser.add_argument("session_id", help="Session UUID")

    # check
    check_parser = subparsers.add_parser("check", help="Check wait timer")
    check_parser.add_argument("session_id", help="Session UUID")

    # list
    subparsers.add_parser("list", help="List all waiting sessions")

    # cleanup
    subparsers.add_parser("cleanup", help="Clean up expired timers")

    args = parser.parse_args()

    if args.command == "set":
        if set_wait(args.session_id, args.minutes):
            print(f"Wait timer set for {args.minutes} minutes")
        else:
            print("Failed to set wait timer", file=sys.stderr)
            sys.exit(1)

    elif args.command == "cancel":
        if cancel_wait(args.session_id):
            print("Wait timer cancelled")
        else:
            print("Failed to cancel wait timer", file=sys.stderr)
            sys.exit(1)

    elif args.command == "check":
        remaining = get_wait_remaining(args.session_id)
        if remaining is None:
            print("No wait timer set")
        elif remaining == 0:
            print("Wait timer expired")
        else:
            minutes = remaining // 60
            seconds = remaining % 60
            print(f"Remaining: {minutes}m {seconds}s")

    elif args.command == "list":
        waiting = list_waiting_sessions()
        if not waiting:
            print("No sessions waiting")
        else:
            for session_id, remaining in waiting:
                minutes = remaining // 60
                print(f"{session_id[:8]}: {minutes}m remaining")

    elif args.command == "cleanup":
        expired = check_expired_timers()
        if expired:
            print(f"Cleaned up {len(expired)} expired timer(s)")
        else:
            print("No expired timers")


if __name__ == "__main__":
    main()
