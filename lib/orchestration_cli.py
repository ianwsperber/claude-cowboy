#!/usr/bin/env python3
"""CLI interface for orchestration management.

This script is called from command .md files to manage orchestrations.
Provides subcommands for creating, updating, and querying orchestrations.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from .orchestration import (
        create_orchestration,
        add_child_to_orchestration,
        update_child_status,
        complete_orchestration,
        cancel_orchestration,
        get_orchestration,
        get_active_orchestrations,
        get_orchestration_for_child,
        get_orchestration_for_child_tmux,
        is_orchestrated_child,
        is_orchestrated_child_tmux,
        check_orchestration_completion,
        write_task_file,
        read_task_file,
        write_result_file,
        read_result_file,
        send_message,
        get_inbox_messages,
        count_unread_messages,
        get_completed_children,
        get_working_children,
    )
    from .config import load_config
    from .notifications import play_notification
except ImportError:
    from orchestration import (
        create_orchestration,
        add_child_to_orchestration,
        update_child_status,
        complete_orchestration,
        cancel_orchestration,
        get_orchestration,
        get_active_orchestrations,
        get_orchestration_for_child,
        get_orchestration_for_child_tmux,
        is_orchestrated_child,
        is_orchestrated_child_tmux,
        check_orchestration_completion,
        write_task_file,
        read_task_file,
        write_result_file,
        read_result_file,
        send_message,
        get_inbox_messages,
        count_unread_messages,
        get_completed_children,
        get_working_children,
    )
    from config import load_config
    try:
        from notifications import play_notification
    except ImportError:
        def play_notification():
            pass


def cmd_create_lasso(args):
    """Create a new lasso (async) orchestration."""
    orch = create_orchestration(
        orch_type="lasso",
        parent_session_id=args.parent_session,
        parent_tmux_session=args.parent_tmux,
        plan=args.task,
    )
    print(json.dumps({
        "id": orch.id,
        "type": orch.type,
        "parent_session_id": orch.parent_session_id,
        "parent_tmux_session": orch.parent_tmux_session,
        "created_at": orch.created_at,
    }))


def cmd_create_posse(args):
    """Create a new posse (sync) orchestration."""
    orch = create_orchestration(
        orch_type="posse",
        parent_session_id=args.parent_session,
        parent_tmux_session=args.parent_tmux,
        plan=args.plan,
    )
    print(json.dumps({
        "id": orch.id,
        "type": orch.type,
        "parent_session_id": orch.parent_session_id,
        "parent_tmux_session": orch.parent_tmux_session,
        "created_at": orch.created_at,
    }))


def cmd_add_child(args):
    """Add a child session to an orchestration."""
    child = add_child_to_orchestration(
        orch_id=args.orchestration_id,
        tmux_session=args.tmux_session,
        role=args.role,
        task=args.task,
        session_id=args.session_id or "",
    )
    if child:
        print(json.dumps({
            "tmux_session": child.tmux_session,
            "role": child.role,
            "task": child.task,
            "status": child.status,
        }))
    else:
        print(json.dumps({"error": "Orchestration not found"}))
        sys.exit(1)


def cmd_update_status(args):
    """Update a child session's status."""
    success = update_child_status(
        orch_id=args.orchestration_id,
        child_tmux_session=args.tmux_session,
        status=args.status,
        session_id=args.session_id,
        result_summary=args.summary,
    )
    if success:
        print(json.dumps({"updated": True}))
    else:
        print(json.dumps({"error": "Child session not found"}))
        sys.exit(1)


def cmd_complete(args):
    """Mark an orchestration as completed."""
    success = complete_orchestration(args.orchestration_id)
    if success:
        print(json.dumps({"completed": True}))
    else:
        print(json.dumps({"error": "Orchestration not found"}))
        sys.exit(1)


def cmd_cancel(args):
    """Cancel an orchestration."""
    success = cancel_orchestration(args.orchestration_id)
    if success:
        print(json.dumps({"cancelled": True}))
    else:
        print(json.dumps({"error": "Orchestration not found"}))
        sys.exit(1)


def cmd_get_status(args):
    """Get orchestration status."""
    orch = get_orchestration(args.orchestration_id)
    if not orch:
        print(json.dumps({"error": "Orchestration not found"}))
        sys.exit(1)

    working = get_working_children(args.orchestration_id)
    completed = get_completed_children(args.orchestration_id)

    print(json.dumps({
        "id": orch.id,
        "type": orch.type,
        "status": orch.status,
        "total_children": len(orch.children),
        "working": len(working),
        "completed": len(completed),
        "all_done": check_orchestration_completion(args.orchestration_id),
        "children": [
            {
                "tmux_session": c.tmux_session,
                "role": c.role,
                "status": c.status,
                "result_summary": c.result_summary,
            }
            for c in orch.children
        ],
    }))


def cmd_list_active(args):
    """List all active orchestrations."""
    orchestrations = get_active_orchestrations()
    result = []
    for orch in orchestrations:
        working = len([c for c in orch.children if c.status == "working"])
        done = len([c for c in orch.children if c.status == "done"])
        result.append({
            "id": orch.id,
            "type": orch.type,
            "parent_tmux_session": orch.parent_tmux_session,
            "children": len(orch.children),
            "working": working,
            "done": done,
        })
    print(json.dumps(result))


def cmd_is_orchestrated_child(args):
    """Check if a session is an orchestrated child."""
    is_child = False
    orch = None

    if args.session_id:
        is_child = is_orchestrated_child(args.session_id)
        if is_child:
            orch = get_orchestration_for_child(args.session_id)

    if not is_child and args.tmux_session:
        is_child = is_orchestrated_child_tmux(args.tmux_session)
        if is_child:
            orch = get_orchestration_for_child_tmux(args.tmux_session)

    if is_child and orch:
        print(json.dumps({
            "is_child": True,
            "orchestration_id": orch.id,
            "type": orch.type,
            "parent_tmux_session": orch.parent_tmux_session,
        }))
    else:
        print(json.dumps({"is_child": False}))


def cmd_write_task(args):
    """Write a task file for a child session."""
    context = None
    if args.context:
        try:
            context = json.loads(args.context)
        except json.JSONDecodeError:
            pass

    success = write_task_file(
        child_session_id=args.session_id,
        orchestration_id=args.orchestration_id,
        parent_session_id=args.parent_session,
        parent_tmux_session=args.parent_tmux,
        role=args.role,
        task=args.task,
        context=context,
    )
    if success:
        print(json.dumps({"written": True}))
    else:
        print(json.dumps({"error": "Failed to write task file"}))
        sys.exit(1)


def cmd_read_task(args):
    """Read a task file."""
    task = read_task_file(args.session_id)
    if task:
        print(json.dumps(task))
    else:
        print(json.dumps({"error": "Task file not found"}))
        sys.exit(1)


def cmd_write_result(args):
    """Write a result file for a completed child."""
    files_modified = None
    if args.files:
        try:
            files_modified = json.loads(args.files)
        except json.JSONDecodeError:
            files_modified = args.files.split(",")

    success = write_result_file(
        session_id=args.session_id,
        orchestration_id=args.orchestration_id,
        status=args.status,
        summary=args.summary,
        files_modified=files_modified,
        notes=args.notes,
    )
    if success:
        print(json.dumps({"written": True}))
    else:
        print(json.dumps({"error": "Failed to write result file"}))
        sys.exit(1)


def cmd_read_result(args):
    """Read a result file."""
    result = read_result_file(args.session_id)
    if result:
        print(json.dumps(result))
    else:
        print(json.dumps({"error": "Result file not found"}))
        sys.exit(1)


def cmd_handle_child_completion(args):
    """Handle a child session completion (called from hook)."""
    # Find the orchestration for this child
    orch = None
    if args.session_id:
        orch = get_orchestration_for_child(args.session_id)
    if not orch and args.tmux_session:
        orch = get_orchestration_for_child_tmux(args.tmux_session)

    if not orch:
        print(json.dumps({"handled": False, "reason": "Not an orchestrated child"}))
        return

    # Read result file if it exists
    child_id = args.session_id or args.tmux_session
    result = read_result_file(child_id)
    result_summary = result.get("summary") if result else None

    # Update child status
    update_child_status(
        orch_id=orch.id,
        child_tmux_session=args.tmux_session or args.session_id,
        status="done",
        result_summary=result_summary,
    )

    # Notify parent via tmux display-message
    try:
        child_role = "child"
        for child in orch.children:
            if child.tmux_session == args.tmux_session or child.session_id == args.session_id:
                child_role = child.role
                break

        subprocess.run(
            ["tmux", "display-message", "-t", orch.parent_tmux_session,
             f"Orchestration: {child_role} completed"],
            capture_output=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Play notification sound
    config = load_config()
    if config.get("enableNotificationSound", True):
        play_notification()

    # Check if all children are done
    all_done = check_orchestration_completion(orch.id)

    if all_done and orch.type == "posse":
        # Wake parent Claude via tmux send-keys
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", orch.parent_tmux_session,
                 f"claude --resume {orch.parent_session_id} 'All child sessions have completed. Review results and summarize.'",
                 "Enter"],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    print(json.dumps({
        "handled": True,
        "orchestration_id": orch.id,
        "all_done": all_done,
    }))


def cmd_count_unread(args):
    """Count unread messages for a session."""
    count = count_unread_messages(args.session_id)
    print(json.dumps({"count": count}))


def cmd_send_message(args):
    """Send a message to another session."""
    msg_id = send_message(
        from_session=args.from_session,
        to_session=args.to_session,
        subject=args.subject,
        body=args.body,
        msg_type=args.type,
    )
    print(json.dumps({"message_id": msg_id}))


def cmd_get_inbox(args):
    """Get inbox messages for a session."""
    messages = get_inbox_messages(args.session_id, unread_only=args.unread)
    print(json.dumps(messages))


def cmd_get_current_session(args):
    """Get current session info from environment."""
    # Try to get from Claude Code environment variables
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    tmux_session = ""

    # Try to get tmux session name
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            tmux_session = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Try to get CWD
    cwd = os.getcwd()

    print(json.dumps({
        "session_id": session_id,
        "tmux_session": tmux_session,
        "cwd": cwd,
    }))


def main():
    parser = argparse.ArgumentParser(description="Orchestration CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-lasso
    p = subparsers.add_parser("create-lasso", help="Create lasso orchestration")
    p.add_argument("--parent-session", required=True, help="Parent session ID")
    p.add_argument("--parent-tmux", required=True, help="Parent tmux session")
    p.add_argument("--task", required=True, help="Task description")
    p.set_defaults(func=cmd_create_lasso)

    # create-posse
    p = subparsers.add_parser("create-posse", help="Create posse orchestration")
    p.add_argument("--parent-session", required=True, help="Parent session ID")
    p.add_argument("--parent-tmux", required=True, help="Parent tmux session")
    p.add_argument("--plan", required=True, help="Coordination plan")
    p.set_defaults(func=cmd_create_posse)

    # add-child
    p = subparsers.add_parser("add-child", help="Add child to orchestration")
    p.add_argument("--orchestration-id", required=True, help="Orchestration ID")
    p.add_argument("--tmux-session", required=True, help="Child tmux session")
    p.add_argument("--role", required=True, help="Child role")
    p.add_argument("--task", required=True, help="Task description")
    p.add_argument("--session-id", help="Child Claude session ID")
    p.set_defaults(func=cmd_add_child)

    # update-status
    p = subparsers.add_parser("update-status", help="Update child status")
    p.add_argument("--orchestration-id", required=True, help="Orchestration ID")
    p.add_argument("--tmux-session", required=True, help="Child tmux session")
    p.add_argument("--status", required=True, help="New status")
    p.add_argument("--session-id", help="Child Claude session ID")
    p.add_argument("--summary", help="Result summary")
    p.set_defaults(func=cmd_update_status)

    # complete
    p = subparsers.add_parser("complete", help="Complete orchestration")
    p.add_argument("orchestration_id", help="Orchestration ID")
    p.set_defaults(func=cmd_complete)

    # cancel
    p = subparsers.add_parser("cancel", help="Cancel orchestration")
    p.add_argument("orchestration_id", help="Orchestration ID")
    p.set_defaults(func=cmd_cancel)

    # get-status
    p = subparsers.add_parser("get-status", help="Get orchestration status")
    p.add_argument("orchestration_id", help="Orchestration ID")
    p.set_defaults(func=cmd_get_status)

    # list-active
    p = subparsers.add_parser("list-active", help="List active orchestrations")
    p.set_defaults(func=cmd_list_active)

    # is-orchestrated-child
    p = subparsers.add_parser("is-orchestrated-child", help="Check if child")
    p.add_argument("--session-id", help="Claude session ID")
    p.add_argument("--tmux-session", help="tmux session name")
    p.set_defaults(func=cmd_is_orchestrated_child)

    # write-task
    p = subparsers.add_parser("write-task", help="Write task file")
    p.add_argument("--session-id", required=True, help="Child session ID")
    p.add_argument("--orchestration-id", required=True, help="Orchestration ID")
    p.add_argument("--parent-session", required=True, help="Parent session ID")
    p.add_argument("--parent-tmux", required=True, help="Parent tmux session")
    p.add_argument("--role", required=True, help="Child role")
    p.add_argument("--task", required=True, help="Task description")
    p.add_argument("--context", help="JSON context")
    p.set_defaults(func=cmd_write_task)

    # read-task
    p = subparsers.add_parser("read-task", help="Read task file")
    p.add_argument("session_id", help="Session ID")
    p.set_defaults(func=cmd_read_task)

    # write-result
    p = subparsers.add_parser("write-result", help="Write result file")
    p.add_argument("--session-id", required=True, help="Session ID")
    p.add_argument("--orchestration-id", required=True, help="Orchestration ID")
    p.add_argument("--status", required=True, help="Completion status")
    p.add_argument("--summary", required=True, help="Result summary")
    p.add_argument("--files", help="Files modified (JSON array or comma-sep)")
    p.add_argument("--notes", help="Additional notes")
    p.set_defaults(func=cmd_write_result)

    # read-result
    p = subparsers.add_parser("read-result", help="Read result file")
    p.add_argument("session_id", help="Session ID")
    p.set_defaults(func=cmd_read_result)

    # handle-child-completion
    p = subparsers.add_parser("handle-child-completion",
                               help="Handle child completion (from hook)")
    p.add_argument("--session-id", help="Claude session ID")
    p.add_argument("--tmux-session", help="tmux session name")
    p.set_defaults(func=cmd_handle_child_completion)

    # count-unread
    p = subparsers.add_parser("count-unread", help="Count unread messages")
    p.add_argument("session_id", help="Session ID")
    p.set_defaults(func=cmd_count_unread)

    # send-message
    p = subparsers.add_parser("send-message", help="Send message")
    p.add_argument("--from-session", required=True, help="Sender session ID")
    p.add_argument("--to-session", required=True, help="Recipient session ID")
    p.add_argument("--subject", required=True, help="Message subject")
    p.add_argument("--body", required=True, help="Message body")
    p.add_argument("--type", default="notification",
                   choices=["request", "response", "notification"])
    p.set_defaults(func=cmd_send_message)

    # get-inbox
    p = subparsers.add_parser("get-inbox", help="Get inbox messages")
    p.add_argument("session_id", help="Session ID")
    p.add_argument("--unread", action="store_true", help="Only unread")
    p.set_defaults(func=cmd_get_inbox)

    # get-current-session
    p = subparsers.add_parser("get-current-session", help="Get current session info")
    p.set_defaults(func=cmd_get_current_session)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
