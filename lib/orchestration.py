#!/usr/bin/env python3
"""Orchestration management for Claude Cowboy.

Manages parent-child relationships between Claude Code sessions
for /posse (synchronous) and /lasso (asynchronous) orchestration.

Registry stored at ~/.claude/cowboy/orchestration.json.
Task files at ~/.claude/cowboy/tasks/{child-session-id}.task.json.
Result files at ~/.claude/cowboy/results/{child-session-id}.result.json.
"""

import json
import secrets
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from .config import get_cowboy_data_dir, is_debug_enabled
except ImportError:
    from config import get_cowboy_data_dir, is_debug_enabled


ORCHESTRATION_VERSION = 1


@dataclass
class ChildSession:
    """A child session in an orchestration."""

    session_id: str  # Claude JSONL session UUID (may be empty initially)
    tmux_session: str  # tmux session name
    role: str  # e.g., "frontend", "backend", "e2e-tests"
    task: str  # Task description
    status: str = "pending"  # "pending", "working", "done", "error"
    started_at: Optional[str] = None  # ISO timestamp
    completed_at: Optional[str] = None  # ISO timestamp
    result_summary: Optional[str] = None  # Brief summary of what was accomplished


@dataclass
class Orchestration:
    """An orchestration coordinating multiple sessions."""

    id: str  # Unique orchestration ID (e.g., "posse-abc123")
    type: str  # "posse" or "lasso"
    parent_session_id: str  # Parent Claude JSONL session UUID
    parent_tmux_session: str  # Parent tmux session name
    status: str = "active"  # "active", "completed", "cancelled"
    created_at: str = ""  # ISO timestamp
    children: list[ChildSession] = field(default_factory=list)
    plan: Optional[str] = None  # For posse: the coordination plan
    completed_at: Optional[str] = None  # ISO timestamp


@dataclass
class OrchestrationRegistry:
    """Registry of all orchestrations."""

    version: int = ORCHESTRATION_VERSION
    orchestrations: dict[str, Orchestration] = field(default_factory=dict)


# --- Directory helpers ---


def get_orchestration_path() -> Path:
    """Get the path to the orchestration registry file."""
    return get_cowboy_data_dir() / "orchestration.json"


def get_tasks_dir() -> Path:
    """Get the directory for task files."""
    tasks_dir = get_cowboy_data_dir() / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return tasks_dir


def get_task_file_path(child_session_id: str) -> str:
    """Get the absolute path to a task file.

    Args:
        child_session_id: The child session's tmux session name.

    Returns:
        Absolute path to the task file.
    """
    return str(get_tasks_dir() / f"{child_session_id}.task.json")


def get_results_dir() -> Path:
    """Get the directory for result files."""
    results_dir = get_cowboy_data_dir() / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir


def get_messages_dir() -> Path:
    """Get the directory for inter-session messages."""
    messages_dir = get_cowboy_data_dir() / "messages"
    messages_dir.mkdir(parents=True, exist_ok=True)
    return messages_dir


# --- Registry I/O ---


def load_orchestrations() -> OrchestrationRegistry:
    """Load the orchestration registry from disk.

    Returns:
        OrchestrationRegistry object (empty if file doesn't exist).
    """
    path = get_orchestration_path()

    if not path.exists():
        return OrchestrationRegistry()

    try:
        with open(path) as f:
            data = json.load(f)

        # Parse orchestrations
        orchestrations = {}
        for orch_id, orch_data in data.get("orchestrations", {}).items():
            # Parse children
            children = []
            for child_data in orch_data.get("children", []):
                children.append(ChildSession(**child_data))

            orchestrations[orch_id] = Orchestration(
                id=orch_data.get("id", orch_id),
                type=orch_data.get("type", "lasso"),
                parent_session_id=orch_data.get("parent_session_id", ""),
                parent_tmux_session=orch_data.get("parent_tmux_session", ""),
                status=orch_data.get("status", "active"),
                created_at=orch_data.get("created_at", ""),
                children=children,
                plan=orch_data.get("plan"),
                completed_at=orch_data.get("completed_at"),
            )

        return OrchestrationRegistry(
            version=data.get("version", ORCHESTRATION_VERSION),
            orchestrations=orchestrations,
        )
    except (json.JSONDecodeError, OSError, TypeError) as e:
        if is_debug_enabled():
            print(f"Failed to load orchestration registry: {e}")
        return OrchestrationRegistry()


def save_orchestrations(registry: OrchestrationRegistry) -> bool:
    """Save the orchestration registry to disk.

    Args:
        registry: Registry to save.

    Returns:
        True if successful.
    """
    path = get_orchestration_path()

    try:
        # Convert to serializable format
        data = {
            "version": registry.version,
            "orchestrations": {
                orch_id: {
                    **asdict(orch),
                    "children": [asdict(child) for child in orch.children],
                }
                for orch_id, orch in registry.orchestrations.items()
            },
        }

        # Write atomically
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        tmp_path.rename(path)

        return True
    except OSError as e:
        if is_debug_enabled():
            print(f"Failed to save orchestration registry: {e}")
        return False


# --- Orchestration lifecycle ---


def generate_orchestration_id(orch_type: str) -> str:
    """Generate a unique orchestration ID.

    Args:
        orch_type: "posse" or "lasso".

    Returns:
        ID like "posse-abc123" or "lasso-def456".
    """
    short_id = secrets.token_hex(3)  # 6 hex chars
    return f"{orch_type}-{short_id}"


def create_orchestration(
    orch_type: str,
    parent_session_id: str,
    parent_tmux_session: str,
    plan: Optional[str] = None,
) -> Orchestration:
    """Create a new orchestration.

    Args:
        orch_type: "posse" or "lasso".
        parent_session_id: Parent Claude JSONL session UUID.
        parent_tmux_session: Parent tmux session name.
        plan: Optional coordination plan (for posse).

    Returns:
        The created Orchestration.
    """
    registry = load_orchestrations()

    orch = Orchestration(
        id=generate_orchestration_id(orch_type),
        type=orch_type,
        parent_session_id=parent_session_id,
        parent_tmux_session=parent_tmux_session,
        status="active",
        created_at=datetime.now(timezone.utc).isoformat(),
        plan=plan,
    )

    registry.orchestrations[orch.id] = orch
    save_orchestrations(registry)

    return orch


def add_child_to_orchestration(
    orch_id: str,
    tmux_session: str,
    role: str,
    task: str,
    session_id: str = "",
) -> Optional[ChildSession]:
    """Add a child session to an orchestration.

    Args:
        orch_id: Orchestration ID.
        tmux_session: Child tmux session name.
        role: Child's role (e.g., "frontend").
        task: Task description.
        session_id: Claude JSONL session UUID (may be empty initially).

    Returns:
        The created ChildSession, or None if orchestration not found.
    """
    registry = load_orchestrations()

    if orch_id not in registry.orchestrations:
        return None

    child = ChildSession(
        session_id=session_id,
        tmux_session=tmux_session,
        role=role,
        task=task,
        status="pending",
    )

    registry.orchestrations[orch_id].children.append(child)
    save_orchestrations(registry)

    return child


def update_child_status(
    orch_id: str,
    child_tmux_session: str,
    status: str,
    session_id: Optional[str] = None,
    result_summary: Optional[str] = None,
) -> bool:
    """Update a child session's status.

    Args:
        orch_id: Orchestration ID.
        child_tmux_session: Child's tmux session name.
        status: New status ("pending", "working", "done", "error").
        session_id: Optional Claude JSONL session UUID to set.
        result_summary: Optional result summary (when completing).

    Returns:
        True if updated.
    """
    registry = load_orchestrations()

    if orch_id not in registry.orchestrations:
        return False

    orch = registry.orchestrations[orch_id]
    for child in orch.children:
        if child.tmux_session == child_tmux_session:
            child.status = status

            if session_id:
                child.session_id = session_id

            if status == "working" and not child.started_at:
                child.started_at = datetime.now(timezone.utc).isoformat()

            if status == "done":
                child.completed_at = datetime.now(timezone.utc).isoformat()
                if result_summary:
                    child.result_summary = result_summary

            save_orchestrations(registry)
            return True

    return False


def complete_orchestration(orch_id: str) -> bool:
    """Mark an orchestration as completed.

    Args:
        orch_id: Orchestration ID.

    Returns:
        True if completed.
    """
    registry = load_orchestrations()

    if orch_id not in registry.orchestrations:
        return False

    orch = registry.orchestrations[orch_id]
    orch.status = "completed"
    orch.completed_at = datetime.now(timezone.utc).isoformat()

    save_orchestrations(registry)
    return True


def cancel_orchestration(orch_id: str) -> bool:
    """Mark an orchestration as cancelled.

    Args:
        orch_id: Orchestration ID.

    Returns:
        True if cancelled.
    """
    registry = load_orchestrations()

    if orch_id not in registry.orchestrations:
        return False

    orch = registry.orchestrations[orch_id]
    orch.status = "cancelled"
    orch.completed_at = datetime.now(timezone.utc).isoformat()

    save_orchestrations(registry)
    return True


# --- Queries ---


def get_orchestration(orch_id: str) -> Optional[Orchestration]:
    """Get an orchestration by ID.

    Args:
        orch_id: Orchestration ID.

    Returns:
        Orchestration or None.
    """
    registry = load_orchestrations()
    return registry.orchestrations.get(orch_id)


def get_active_orchestrations() -> list[Orchestration]:
    """Get all active orchestrations.

    Returns:
        List of active Orchestration objects.
    """
    registry = load_orchestrations()
    return [
        orch for orch in registry.orchestrations.values()
        if orch.status == "active"
    ]


def get_orchestrations_for_parent(parent_session_id: str) -> list[Orchestration]:
    """Get all orchestrations for a parent session.

    Args:
        parent_session_id: Parent Claude JSONL session UUID.

    Returns:
        List of Orchestration objects.
    """
    registry = load_orchestrations()
    return [
        orch for orch in registry.orchestrations.values()
        if orch.parent_session_id == parent_session_id
    ]


def get_orchestration_for_child(child_session_id: str) -> Optional[Orchestration]:
    """Get the orchestration containing a child session.

    Args:
        child_session_id: Child Claude JSONL session UUID.

    Returns:
        Orchestration or None.
    """
    registry = load_orchestrations()
    for orch in registry.orchestrations.values():
        for child in orch.children:
            if child.session_id == child_session_id:
                return orch
    return None


def get_orchestration_for_child_tmux(child_tmux_session: str) -> Optional[Orchestration]:
    """Get the orchestration containing a child tmux session.

    Args:
        child_tmux_session: Child tmux session name.

    Returns:
        Orchestration or None.
    """
    registry = load_orchestrations()
    for orch in registry.orchestrations.values():
        for child in orch.children:
            if child.tmux_session == child_tmux_session:
                return orch
    return None


def is_orchestrated_child(session_id: str) -> bool:
    """Check if a session is a child in any active orchestration.

    Args:
        session_id: Claude JSONL session UUID.

    Returns:
        True if session is an orchestrated child.
    """
    return get_orchestration_for_child(session_id) is not None


def is_orchestrated_child_tmux(tmux_session: str) -> bool:
    """Check if a tmux session is a child in any active orchestration.

    Args:
        tmux_session: tmux session name.

    Returns:
        True if session is an orchestrated child.
    """
    return get_orchestration_for_child_tmux(tmux_session) is not None


def is_orchestrating_parent(session_id: str) -> bool:
    """Check if a session is an orchestrating parent.

    Args:
        session_id: Claude JSONL session UUID.

    Returns:
        True if session is an orchestrating parent.
    """
    for orch in get_active_orchestrations():
        if orch.parent_session_id == session_id:
            return True
    return False


def get_orchestration_info_for_session(
    session_id: str, tmux_session: Optional[str] = None
) -> Optional[dict]:
    """Get orchestration info for a session (whether parent or child).

    Args:
        session_id: Claude JSONL session UUID.
        tmux_session: Optional tmux session name for child lookup.

    Returns:
        Dict with "is_parent", "orchestration", and optionally "child" keys,
        or None if session is not part of any orchestration.
    """
    # Check if parent
    for orch in get_active_orchestrations():
        if orch.parent_session_id == session_id:
            return {
                "is_parent": True,
                "orchestration": orch,
                "children": orch.children,
            }

    # Check if child by session_id
    orch = get_orchestration_for_child(session_id)
    if orch:
        for child in orch.children:
            if child.session_id == session_id:
                return {
                    "is_parent": False,
                    "orchestration": orch,
                    "child": child,
                }

    # Check if child by tmux session
    if tmux_session:
        orch = get_orchestration_for_child_tmux(tmux_session)
        if orch:
            for child in orch.children:
                if child.tmux_session == tmux_session:
                    return {
                        "is_parent": False,
                        "orchestration": orch,
                        "child": child,
                    }

    return None


# --- Task files ---


def write_task_file(
    child_session_id: str,
    orchestration_id: str,
    orchestration_type: str,
    parent_session_id: str,
    parent_tmux_session: str,
    role: str,
    task: str,
    context: Optional[dict] = None,
    siblings: Optional[list] = None,
) -> bool:
    """Write a task file for a child session.

    Args:
        child_session_id: Child's session ID (or tmux session name if not yet known).
        orchestration_id: Orchestration ID.
        orchestration_type: Type of orchestration ("lasso" or "posse").
        parent_session_id: Parent Claude JSONL session UUID.
        parent_tmux_session: Parent tmux session name.
        role: Child's role.
        task: Task description.
        context: Optional additional context (relevant files, etc.).
        siblings: Optional list of sibling sessions (for posse coordination).

    Returns:
        True if successful.
    """
    task_file = get_tasks_dir() / f"{child_session_id}.task.json"

    try:
        data = {
            "orchestration_id": orchestration_id,
            "orchestration_type": orchestration_type,
            "parent_session_id": parent_session_id,
            "parent_tmux_session": parent_tmux_session,
            "role": role,
            "task": task,
            "context": context or {},
            "siblings": siblings or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(task_file, "w") as f:
            json.dump(data, f, indent=2)

        return True
    except OSError as e:
        if is_debug_enabled():
            print(f"Failed to write task file: {e}")
        return False


def read_task_file(session_id: str) -> Optional[dict]:
    """Read the task file for a session.

    Args:
        session_id: Session ID (or tmux session name).

    Returns:
        Task data dict or None.
    """
    task_file = get_tasks_dir() / f"{session_id}.task.json"

    if not task_file.exists():
        return None

    try:
        with open(task_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def delete_task_file(session_id: str) -> bool:
    """Delete a task file.

    Args:
        session_id: Session ID (or tmux session name).

    Returns:
        True if deleted.
    """
    task_file = get_tasks_dir() / f"{session_id}.task.json"
    try:
        task_file.unlink(missing_ok=True)
        return True
    except OSError:
        return False


# --- Result files ---


def write_result_file(
    session_id: str,
    orchestration_id: str,
    status: str,
    summary: str,
    files_modified: Optional[list[str]] = None,
    notes: Optional[str] = None,
) -> bool:
    """Write a result file for a completed child session.

    Args:
        session_id: Session ID (or tmux session name).
        orchestration_id: Orchestration ID.
        status: Completion status ("completed", "error").
        summary: Brief summary of what was accomplished.
        files_modified: Optional list of modified files.
        notes: Optional additional notes.

    Returns:
        True if successful.
    """
    result_file = get_results_dir() / f"{session_id}.result.json"

    try:
        data = {
            "orchestration_id": orchestration_id,
            "session_id": session_id,
            "status": status,
            "summary": summary,
            "files_modified": files_modified or [],
            "notes": notes,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(result_file, "w") as f:
            json.dump(data, f, indent=2)

        return True
    except OSError as e:
        if is_debug_enabled():
            print(f"Failed to write result file: {e}")
        return False


def read_result_file(session_id: str) -> Optional[dict]:
    """Read the result file for a session.

    Args:
        session_id: Session ID (or tmux session name).

    Returns:
        Result data dict or None.
    """
    result_file = get_results_dir() / f"{session_id}.result.json"

    if not result_file.exists():
        return None

    try:
        with open(result_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# --- Message queue ---


def get_inbox_dir(session_id: str) -> Path:
    """Get the inbox directory for a session.

    Args:
        session_id: Session ID.

    Returns:
        Path to inbox directory.
    """
    inbox_dir = get_messages_dir() / session_id / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    return inbox_dir


def send_message(
    from_session: str,
    to_session: str,
    subject: str,
    body: str,
    msg_type: str = "notification",
    correlation_id: Optional[str] = None,
) -> str:
    """Send a message to another session's inbox.

    Args:
        from_session: Sender session ID.
        to_session: Recipient session ID.
        subject: Message subject.
        body: Message body.
        msg_type: "request", "response", or "notification".
        correlation_id: Optional correlation ID for request-response.

    Returns:
        Message ID.
    """
    inbox_dir = get_inbox_dir(to_session)
    msg_id = f"msg-{secrets.token_hex(4)}"
    timestamp = int(time.time())
    msg_file = inbox_dir / f"{timestamp}-{from_session[:8]}.json"

    data = {
        "id": msg_id,
        "from_session": from_session,
        "to_session": to_session,
        "type": msg_type,
        "subject": subject,
        "body": body,
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "read": False,
    }

    try:
        with open(msg_file, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        if is_debug_enabled():
            print(f"Failed to send message: {e}")

    return msg_id


def get_inbox_messages(session_id: str, unread_only: bool = False) -> list[dict]:
    """Get messages from a session's inbox.

    Args:
        session_id: Session ID.
        unread_only: If True, only return unread messages.

    Returns:
        List of message dicts, sorted by timestamp (oldest first).
    """
    inbox_dir = get_inbox_dir(session_id)
    messages = []

    for msg_file in sorted(inbox_dir.glob("*.json")):
        try:
            with open(msg_file) as f:
                msg = json.load(f)
                if unread_only and msg.get("read"):
                    continue
                msg["_file"] = str(msg_file)
                messages.append(msg)
        except (json.JSONDecodeError, OSError):
            continue

    return messages


def mark_message_read(session_id: str, message_file: str) -> bool:
    """Mark a message as read.

    Args:
        session_id: Session ID.
        message_file: Path to message file.

    Returns:
        True if marked.
    """
    try:
        msg_path = Path(message_file)
        if not msg_path.exists():
            return False

        with open(msg_path) as f:
            msg = json.load(f)

        msg["read"] = True

        with open(msg_path, "w") as f:
            json.dump(msg, f, indent=2)

        return True
    except (json.JSONDecodeError, OSError):
        return False


def count_unread_messages(session_id: str) -> int:
    """Count unread messages in a session's inbox.

    Args:
        session_id: Session ID.

    Returns:
        Number of unread messages.
    """
    return len(get_inbox_messages(session_id, unread_only=True))


# --- Completion detection ---


def check_orchestration_completion(orch_id: str) -> bool:
    """Check if all children in an orchestration are done.

    Args:
        orch_id: Orchestration ID.

    Returns:
        True if all children are done or error.
    """
    orch = get_orchestration(orch_id)
    if not orch:
        return False

    return all(
        child.status in ("done", "error")
        for child in orch.children
    )


def get_completed_children(orch_id: str) -> list[ChildSession]:
    """Get all completed children for an orchestration.

    Args:
        orch_id: Orchestration ID.

    Returns:
        List of completed ChildSession objects.
    """
    orch = get_orchestration(orch_id)
    if not orch:
        return []

    return [child for child in orch.children if child.status == "done"]


def get_working_children(orch_id: str) -> list[ChildSession]:
    """Get all currently working children for an orchestration.

    Args:
        orch_id: Orchestration ID.

    Returns:
        List of working ChildSession objects.
    """
    orch = get_orchestration(orch_id)
    if not orch:
        return []

    return [child for child in orch.children if child.status == "working"]


if __name__ == "__main__":
    print("Orchestration module test")
    print(f"Registry path: {get_orchestration_path()}")
    print(f"Tasks dir: {get_tasks_dir()}")
    print(f"Results dir: {get_results_dir()}")
    print(f"Messages dir: {get_messages_dir()}")

    registry = load_orchestrations()
    print(f"\nRegistry version: {registry.version}")
    print(f"Active orchestrations: {len(get_active_orchestrations())}")

    for orch_id, orch in registry.orchestrations.items():
        print(f"\n  {orch_id} ({orch.type}):")
        print(f"    Status: {orch.status}")
        print(f"    Parent: {orch.parent_tmux_session}")
        print(f"    Children: {len(orch.children)}")
        for child in orch.children:
            print(f"      - {child.role}: {child.status}")
