#!/usr/bin/env python3
"""Claude Cowboy CLI.

Main entry point for managing Claude Code sessions via tmux.

Usage:
    cowboy new [path] [--name NAME]   Create new Claude session
    cowboy dashboard                   Open the dashboard
    cowboy list [--json]              List all sessions
    cowboy attach <id|name>           Attach to a session
    cowboy kill <id|name>             Kill a session
    cowboy doctor                      Check dependencies
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

__version__ = "0.1.0"

try:
    from . import tmux_manager as tmux
    from . import session_registry as registry
    from . import git_worktree as worktree
    from . import orchestration
    from . import session_context
    from .config import load_config
    from .status_analyzer import analyze_session_status, get_status_emoji, SessionStatus, wait_for_session_idle
except ImportError:
    import tmux_manager as tmux
    import session_registry as registry
    import git_worktree as worktree
    import orchestration
    import session_context
    from config import load_config
    from status_analyzer import analyze_session_status, get_status_emoji, SessionStatus, wait_for_session_idle


def get_sessions_for_cwd(cwd: str) -> list[str]:
    """Get names of existing tmux sessions in the same working directory.

    Args:
        cwd: Working directory to check.

    Returns:
        List of tmux session names that are in the same directory.
    """
    cwd = os.path.abspath(os.path.expanduser(cwd))
    matching = []

    # Query tmux for all sessions and their CWDs
    all_sessions = tmux.list_all_sessions()
    for session in all_sessions:
        session_cwd = tmux.get_session_cwd(session.name)
        if session_cwd and os.path.abspath(session_cwd) == cwd:
            matching.append(session.name)

    return matching


def prompt_for_session_name(base_name: str, default_suffix: str) -> str:
    """Prompt user for a custom session name suffix.

    Args:
        base_name: Base name for the session (e.g., "claude-cowboy").
        default_suffix: Default suffix if user presses Enter (e.g., "08").

    Returns:
        Full session name (e.g., "claude-cowboy-named-sessions" or "claude-cowboy-08").

    Raises:
        KeyboardInterrupt: If user presses Ctrl+C.
        EOFError: If user presses Ctrl+D.
    """
    default_name = f"{base_name}-{default_suffix}"
    print(f"Session name: {base_name}-<suffix>")

    try:
        user_input = input(f"Enter suffix (or press Enter for '{default_suffix}'): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()  # Newline after ^C or ^D
        raise

    if not user_input:
        return default_name

    # Sanitize for tmux (no dots or colons)
    suffix = user_input.replace(".", "-").replace(":", "-")
    candidate = f"{base_name}-{suffix}"

    # Check for conflicts with existing tmux sessions
    if tmux.session_exists(candidate):
        print(f"Warning: Session '{candidate}' already exists. Appending number.")
        counter = 1
        while tmux.session_exists(f"{candidate}-{counter}"):
            counter += 1
        candidate = f"{candidate}-{counter}"

    return candidate


def generate_session_name(cwd: str, custom_suffix: str | None = None) -> str:
    """Generate a tmux session name from a directory path.

    Args:
        cwd: Working directory path.
        custom_suffix: Optional custom suffix to append to the base name.
            If provided, the session name becomes "{base_name}-{custom_suffix}".

    Returns:
        Session name (sanitized for tmux).
    """
    # Use the directory name as the base
    dir_name = os.path.basename(cwd)

    # Sanitize for tmux (no dots or colons)
    base_name = dir_name.replace(".", "-").replace(":", "-")

    if custom_suffix:
        # Use custom suffix instead of auto-generated number
        suffix = custom_suffix.replace(".", "-").replace(":", "-")
        session_name = f"{base_name}-{suffix}"
    else:
        session_name = base_name

    # If session already exists, append a number
    if tmux.session_exists(session_name):
        original_name = session_name
        counter = 1
        while tmux.session_exists(session_name):
            session_name = f"{original_name}-{counter}"
            counter += 1

    return session_name


def cmd_new(args) -> int:
    """Create a new Claude Code session in its own tmux session."""
    if not tmux.is_tmux_available():
        print("Error: tmux is not installed or not available", file=sys.stderr)
        return 1

    # Determine working directory
    cwd = args.path if args.path else os.getcwd()
    cwd = os.path.abspath(os.path.expanduser(cwd))

    if not os.path.isdir(cwd):
        print(f"Error: Directory does not exist: {cwd}", file=sys.stderr)
        return 1

    # Load config for worktree settings
    config = load_config(cwd)

    # Check for existing sessions in same directory
    existing_sessions = get_sessions_for_cwd(cwd)

    # Collect status messages to display in the new session
    status_messages = []

    # Handle worktree mode (-w flag)
    if getattr(args, "worktree", False):
        if not worktree.is_git_repo(cwd):
            print("Error: --worktree requires a git repository", file=sys.stderr)
            return 1

        repo_root = worktree.get_repo_root(cwd)

        # Monorepo detection (prompt unless -m flag)
        if worktree.is_submodule(cwd) and not getattr(args, "monorepo", False):
            parent_root = worktree.get_parent_repo_root(cwd)
            if parent_root:
                print(f"Detected submodule. Parent monorepo: {parent_root}")
                try:
                    response = input("Create worktree for monorepo instead? [y/N]: ")
                    if response.lower() == "y":
                        repo_root = parent_root
                except (EOFError, KeyboardInterrupt):
                    print()  # Newline after ^C
                    return 1

        # Determine worktree location
        location = getattr(args, "worktree_location", None) or config.get("worktreeLocation", "home")

        # Get the current branch from the source repo (for derived branch naming)
        source_branch = worktree.get_current_branch(repo_root)

        # Get active session CWDs for reuse check
        active_cwds = worktree.get_active_session_cwds()

        # Try to reuse an existing idle worktree (only for home location)
        worktree_path = worktree.find_reusable_worktree(repo_root, active_cwds, location)

        if worktree_path:
            # Prepare the reused worktree (switch to derived branch if needed)
            branch_name = worktree.prepare_reused_worktree(worktree_path, source_branch)
            if branch_name:
                status_messages.append(f"Reusing worktree: {worktree_path} (branch: {branch_name})")
            else:
                status_messages.append(f"Reusing worktree: {worktree_path}")
            cwd = worktree_path
        else:
            # Create new worktree (auto-increments number)
            try:
                cwd, branch_name = worktree.create_worktree(repo_root, location, source_branch)
                if branch_name:
                    status_messages.append(f"Created worktree: {cwd} (branch: {branch_name})")
                else:
                    status_messages.append(f"Created worktree: {cwd}")
            except subprocess.CalledProcessError as e:
                print(f"Error: Failed to create worktree: {e}", file=sys.stderr)
                return 1

        # Clean up excess worktrees (only for home location)
        if location == "home":
            max_wt = config.get("maxWorktrees", 3)
            removed = worktree.cleanup_excess_worktrees(repo_root, active_cwds, max_wt)
            if removed > 0:
                status_messages.append(f"Cleaned up {removed} old worktree(s)")

        # Generate session name for worktree mode
        # Use repo name (not worktree directory) as base
        repo_base_name = os.path.basename(repo_root).replace(".", "-").replace(":", "-")
        worktree_num = worktree.get_worktree_number(cwd)

        if args.name:
            # Use provided name as suffix (no prompt)
            suffix = args.name.replace(".", "-").replace(":", "-")
            session_name = f"{repo_base_name}-{suffix}"
            # Handle conflicts
            if tmux.session_exists(session_name):
                counter = 1
                while tmux.session_exists(f"{session_name}-{counter}"):
                    counter += 1
                session_name = f"{session_name}-{counter}"
        else:
            # Prompt for session name
            try:
                session_name = prompt_for_session_name(repo_base_name, worktree_num)
            except (EOFError, KeyboardInterrupt):
                print()
                return 1

    elif existing_sessions:
        # Collision warning (no -w flag, but other sessions exist)
        status_messages.append(f"Warning: Another session exists in this directory: {existing_sessions[0]}")
        status_messages.append("  Sessions may share history/context. Use -w for isolation.")
        # Non-worktree mode: generate session name from directory
        session_name = generate_session_name(cwd, args.name)

    else:
        # Non-worktree mode: generate session name from directory
        session_name = generate_session_name(cwd, args.name)

    # Create a new tmux session for this Claude instance
    if not tmux.create_claude_session(session_name, cwd):
        # Session might already exist
        if tmux.session_exists(session_name):
            print(f"Session '{session_name}' already exists. Switching to it.")
            if tmux.is_inside_tmux():
                tmux.switch_to_session(session_name)
            else:
                os.execlp("tmux", "tmux", "attach-session", "-t", session_name)
            return 0
        print("Error: Failed to create tmux session", file=sys.stderr)
        return 1

    # Build claude command, optionally with plugin dir for local dev
    plugin_dir = os.environ.get("COWBOY_PLUGIN_DIR")
    claude_cmd = f"claude --plugin-dir {plugin_dir}" if plugin_dir else "claude"

    # Send status messages to the new session (so user sees them after switching)
    for msg in status_messages:
        tmux.send_keys(0, f"echo '{msg}'", session_name=session_name)

    # Start Claude Code in the session
    if args.user:
        # Run as specified user with login shell
        claude_cmd = f"nocorrect sudo -u {args.user} -i zsh -c 'cd {cwd} && {claude_cmd}'"
        tmux.send_keys(0, claude_cmd, session_name=session_name)
    else:
        tmux.send_keys(0, f"cd {cwd} && {claude_cmd}", session_name=session_name)

    print(f"Created Claude session: {session_name}")
    print(f"  CWD: {cwd}")

    # Switch to the new session
    if tmux.is_inside_tmux():
        tmux.switch_to_session(session_name)
    else:
        # Attach to the new session
        os.execlp("tmux", "tmux", "attach-session", "-t", session_name)

    return 0


def cmd_dashboard(args) -> int:
    """Open the session browser (fzf-based).

    Shows tmux sessions running Claude and allows switching between them.
    Adapted from tmux-claude-status by samleeney (MIT License)
    https://github.com/samleeney/tmux-claude-status
    """
    # Trigger async cleanup on dashboard open (fire and forget)
    try:
        from .cleanup import run_all_cleanup
    except ImportError:
        from cleanup import run_all_cleanup

    try:
        run_all_cleanup(async_mode=True)
    except Exception:
        pass  # Don't block dashboard if cleanup fails

    try:
        from .session_browser import run_browser
    except ImportError:
        from session_browser import run_browser

    selected = run_browser()
    if selected:
        # Switch to the selected session
        if tmux.is_inside_tmux():
            tmux.switch_to_session(selected)
        else:
            # Attach to the session
            os.execlp("tmux", "tmux", "attach-session", "-t", selected)

    return 0


def format_age(created_at: str) -> str:
    """Format the age of a session."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - created

        if delta.total_seconds() < 60:
            return "now"
        elif delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() / 60)
            return f"{mins}m"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"{hours}h"
        else:
            days = int(delta.total_seconds() / 86400)
            return f"{days}d"
    except ValueError:
        return "?"


def shorten_path(path: str, max_len: int = 30) -> str:
    """Shorten a path for display."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home):]

    if len(path) <= max_len:
        return path

    parts = path.split(os.sep)
    if len(parts) <= 2:
        return path[:max_len - 3] + "..."

    # Keep first and last two components
    return os.sep.join(parts[:1] + ["..."] + parts[-2:])


def cmd_list(args) -> int:
    """List all sessions (same sessions as dashboard)."""
    try:
        from .session_browser import get_all_sessions
    except ImportError:
        from session_browser import get_all_sessions

    all_sessions = get_all_sessions()

    # Filter to Claude sessions by default, show all with --all flag
    show_all = getattr(args, "all", False)
    if show_all:
        sessions = all_sessions
    else:
        sessions = [s for s in all_sessions if s.has_claude]

    if not sessions:
        if args.json:
            print("[]")
        else:
            if show_all:
                print("No tmux sessions found.")
            else:
                non_claude = len(all_sessions) - len(sessions)
                print("No Claude sessions found.")
                if non_claude > 0:
                    print(f"\n{non_claude} non-Claude tmux session(s) hidden. Use --all to see them.")
            print("\nCreate one with: cowboy new [path]")
        return 0

    # Determine path display mode
    show_full_paths = getattr(args, "full_paths", False)
    max_cwd_len = 30 if not show_full_paths else 60

    if args.json:
        output = []
        for s in sessions:
            output.append({
                "session_name": s.session_name,
                "cwd": s.cwd,
                "status": s.status or "unknown",
                "wait_remaining": s.wait_remaining,
                "attached": s.attached,
                "has_claude": s.has_claude,
                "git_branch": s.git_branch,
                "is_worktree": s.is_worktree,
                "safety_status": s.safety_status,
            })
        print(json.dumps(output, indent=2))
        return 0

    # Table output
    print(f"{'Session':<20} {'Status':<14} {'Branch':<15} {'CWD':<{max_cwd_len}} {'Attached'}")
    print("-" * (20 + 14 + 15 + max_cwd_len + 10))

    for s in sessions:
        # Format status
        if not s.has_claude:
            status_str = "(no claude)"
        elif s.status == "needs_attention":
            status_str = "! ATTENTION"
        elif s.status == "working":
            status_str = "* working"
        elif s.status == "wait":
            status_str = f"~ wait{s.wait_remaining}"
        elif s.status == "done":
            status_str = "  done"
        else:
            status_str = "? unknown"

        # Format branch
        branch = s.git_branch or "-"
        if len(branch) > 15:
            branch = branch[:12] + "..."

        # Format CWD
        cwd = s.cwd or "?"
        if not show_full_paths:
            cwd = shorten_path(cwd, max_cwd_len)

        # Attached indicator
        attached = "(attached)" if s.attached else ""

        print(
            f"{s.session_name:<20} "
            f"{status_str:<14} "
            f"{branch:<15} "
            f"{cwd:<{max_cwd_len}} "
            f"{attached}"
        )

    # Footer
    claude_count = sum(1 for s in sessions if s.has_claude)
    non_claude_count = len(sessions) - claude_count
    hidden_count = len(all_sessions) - len(sessions)

    print()
    parts = []
    if claude_count:
        parts.append(f"{claude_count} Claude session(s)")
    if non_claude_count:
        parts.append(f"{non_claude_count} other tmux session(s)")
    if parts:
        print(", ".join(parts))
    if hidden_count > 0 and not show_all:
        print(f"{hidden_count} non-Claude session(s) hidden. Use --all to see them.")

    return 0


def cmd_attach(args) -> int:
    """Attach to a session."""
    entry = registry.find_session(args.identifier)

    if not entry:
        print(f"Error: Session not found: {args.identifier}", file=sys.stderr)
        return 1

    # Check if window exists
    windows = tmux.list_windows()
    if not any(w.name == entry.window_name for w in windows):
        print(f"Error: Window no longer exists: {entry.window_name}", file=sys.stderr)
        print("Remove with: cowboy kill " + entry.short_id)
        return 1

    if tmux.is_inside_tmux():
        # Use switch-client to only affect THIS client, not all attached clients
        tmux.switch_client(entry.window_name)
    else:
        # Create a grouped session for independent window selection
        tmux.attach_to_window(entry.window_name)

    return 0


def cmd_kill(args) -> int:
    """Kill a session."""
    entry = registry.find_session(args.identifier)

    if not entry:
        print(f"Error: Session not found: {args.identifier}", file=sys.stderr)
        return 1

    # Kill the tmux window
    window_killed = tmux.kill_window(entry.window_name)

    # Remove from registry
    registry.remove_session(entry.window_name)

    if window_killed:
        print(f"Killed session: {entry.display_name}")
    else:
        print(f"Removed session from registry: {entry.display_name}")
        print("(Window was already closed)")

    return 0


def cmd_cleanup(args) -> int:
    """Clean up stale sessions, orchestrations, and worktrees."""
    try:
        from .cleanup import run_all_cleanup
    except ImportError:
        from cleanup import run_all_cleanup

    results = run_all_cleanup(async_mode=False)  # Sync for explicit command

    total = sum(results.values())
    if total > 0:
        print("Cleanup complete:")
        labels = {
            "orchestrations_removed": "orchestration children",
            "worktrees_removed": "worktrees",
            "registry_entries_removed": "registry entries",
        }
        for key, count in results.items():
            if count > 0:
                label = labels.get(key, key.replace("_", " "))
                print(f"  - {label}: {count}")
    else:
        print("Nothing to clean up.")

    return 0


def cmd_tmux(args) -> int:
    """Attach to the cowboy tmux session."""
    if not tmux.is_tmux_available():
        print("Error: tmux is not installed or not available", file=sys.stderr)
        return 1

    if not tmux.session_exists():
        print("No cowboy tmux session exists yet.")
        print("Create one with: cowboy new [path]")
        return 1

    session_name = tmux.get_session_name()
    print(f"Attaching to {session_name}...")
    os.execlp("tmux", "tmux", "attach-session", "-t", session_name)
    return 0


def cmd_configure_status(args) -> int:
    """Configure status bar for tmux sessions."""
    if not tmux.is_tmux_available():
        print("Error: tmux is not installed or not available", file=sys.stderr)
        return 1

    # Get all tmux sessions
    all_sessions = tmux.list_all_sessions()
    if not all_sessions:
        print("No tmux sessions found")
        return 0

    configured = 0
    for session in all_sessions:
        # Only configure sessions that have Claude running
        if tmux.has_claude_in_session(session.name):
            if tmux.configure_status_bar(session.name):
                print(f"Configured: {session.name}")
                configured += 1
            else:
                print(f"Failed to configure: {session.name}", file=sys.stderr)

    if configured == 0:
        print("No Claude sessions found to configure")
    else:
        print(f"\nConfigured {configured} session(s)")

    return 0


def cmd_lasso(args) -> int:
    """Query another Claude session synchronously.

    Resumes the target session with a prompt and waits for the response.
    """
    # Get target and prompt from args
    target = args.target or ""
    prompt_parts = args.prompt or []
    prompt = " ".join(prompt_parts) if prompt_parts else ""

    if not prompt:
        print("Error: No query provided", file=sys.stderr)
        print("Usage: cowboy lasso [target] <query>", file=sys.stderr)
        return 1

    # Load config for timeout settings
    config = load_config()
    timeout_minutes = getattr(args, "timeout", None) or config.get("lassoTimeoutMinutes", 8)
    timeout_seconds = timeout_minutes * 60

    # Handle clean mode (new session instead of resume)
    if getattr(args, "clean", False):
        cwd = args.cwd if args.cwd else os.getcwd()
        cwd = os.path.abspath(os.path.expanduser(cwd))

        if not os.path.isdir(cwd):
            print(f"Error: Directory does not exist: {cwd}", file=sys.stderr)
            return 1

        # Build /lassoed prompt with flags
        parent_cwd = os.getcwd()
        parent_session = os.environ.get("TMUX_PANE", "unknown")
        lassoed_prompt = _build_lassoed_prompt(parent_cwd, parent_session, prompt)

        # Run headless claude in clean mode
        plugin_dir = os.environ.get("COWBOY_PLUGIN_DIR")
        cmd = ["claude"]
        if plugin_dir:
            cmd.extend(["--plugin-dir", plugin_dir])
        cmd.extend(["-p", lassoed_prompt])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=cwd,
            )
            print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return result.returncode
        except subprocess.TimeoutExpired:
            print(f"Error: Lasso timed out after {timeout_minutes} minutes", file=sys.stderr)
            return 1
        except FileNotFoundError:
            print("Error: claude CLI not found", file=sys.stderr)
            return 1

    # Resolve target to session UUID and CWD
    try:
        session_uuid, cwd = session_context.resolve_lasso_target(target)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("\nAvailable sessions:")
        subprocess.run(["cowboy", "list"], check=False)
        return 1

    # Wait for session to be idle
    poll_interval = config.get("lassoPollIntervalSeconds", 2.0)
    max_poll_interval = config.get("lassoMaxPollIntervalSeconds", 10.0)

    ok, msg = wait_for_session_idle(
        session_uuid,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
        max_poll_interval=max_poll_interval,
    )
    if not ok:
        print(f"Error: {msg}", file=sys.stderr)
        return 1
    if msg:
        print(msg, file=sys.stderr)

    # Build /lassoed prompt with flags
    parent_cwd = os.getcwd()
    parent_session = os.environ.get("TMUX_PANE", tmux.get_current_session() or "unknown")
    lassoed_prompt = _build_lassoed_prompt(parent_cwd, parent_session, prompt)

    # Build and execute claude command
    plugin_dir = os.environ.get("COWBOY_PLUGIN_DIR")
    cmd = ["claude", "--resume", session_uuid]
    if plugin_dir:
        cmd.extend(["--plugin-dir", plugin_dir])
    cmd.extend(["-p", lassoed_prompt])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=cwd,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode
    except subprocess.TimeoutExpired:
        print(f"Error: Lasso timed out after {timeout_minutes} minutes", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("Error: claude CLI not found", file=sys.stderr)
        return 1


def _build_lassoed_prompt(parent_cwd: str, parent_session: str, query: str) -> str:
    """Build the /lassoed prompt with flags.

    Uses flags instead of JSON to avoid shell escaping issues.

    Args:
        parent_cwd: Parent session's working directory.
        parent_session: Parent's tmux session name.
        query: The actual query.

    Returns:
        Formatted prompt string for /lassoed skill.
    """
    # Escape double quotes in query
    escaped_query = query.replace('"', '\\"')
    # Build prompt with flags
    return f'/claude-cowboy:lassoed --parent-cwd "{parent_cwd}" --parent-session "{parent_session}" "{escaped_query}"'


def cmd_posse(args) -> int:
    """Coordinate work across multiple Claude sessions synchronously.

    This command is meant to be called from the /posse command with a JSON plan.
    It creates the orchestration and spawns child sessions according to the plan.
    """
    if not tmux.is_tmux_available():
        print("Error: tmux is not installed or not available", file=sys.stderr)
        return 1

    # Load plan from file or inline argument
    plan = None
    plan_file = getattr(args, "plan_file", None)
    if plan_file:
        try:
            with open(plan_file, "r") as f:
                plan = json.load(f)
        except FileNotFoundError:
            print(f"Error: Plan file not found: {plan_file}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in plan file: {e}", file=sys.stderr)
            return 1
        except OSError as e:
            print(f"Error reading plan file: {e}", file=sys.stderr)
            return 1
    elif args.plan:
        try:
            plan = json.loads(args.plan)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid plan JSON: {e}", file=sys.stderr)
            return 1
    else:
        print("Error: No plan provided (use --plan or --plan-file)", file=sys.stderr)
        return 1

    # Determine working directory
    cwd = args.cwd if args.cwd else os.getcwd()
    cwd = os.path.abspath(os.path.expanduser(cwd))

    if not os.path.isdir(cwd):
        print(f"Error: Directory does not exist: {cwd}", file=sys.stderr)
        return 1

    # Get parent session info
    parent_tmux = os.environ.get("CLAUDE_SESSION_ID", tmux.get_current_session() or "unknown")
    parent_session_id = os.environ.get("CLAUDE_SESSION_UUID", parent_tmux)

    # Create orchestration
    orch = orchestration.create_orchestration(
        orch_type="posse",
        parent_session_id=parent_session_id,
        parent_tmux_session=parent_tmux,
        plan=plan.get("summary", ""),
    )

    config = load_config(cwd)
    children_info = []

    # First pass: generate all child names and info (needed for siblings list)
    children_plan = []
    for workstream in plan.get("workstreams", []):
        role = workstream.get("role", "worker")
        task = workstream.get("task", "")
        use_worktree = workstream.get("worktree", False) or getattr(args, "worktree", False)

        # Generate child name
        child_name = workstream.get("name")
        if not child_name:
            import secrets
            child_name = f"{parent_tmux}-{role}-{secrets.token_hex(2)}"
        child_name = child_name.replace(".", "-").replace(":", "-")

        # Ensure unique
        while tmux.session_exists(child_name):
            import secrets
            child_name = f"{child_name}-{secrets.token_hex(2)}"

        children_plan.append({
            "name": child_name,
            "role": role,
            "task": task,
            "use_worktree": use_worktree,
            "context": workstream.get("context"),
        })

    # Second pass: spawn children with siblings info
    for i, child_info in enumerate(children_plan):
        child_name = child_info["name"]
        role = child_info["role"]
        task = child_info["task"]
        use_worktree = child_info["use_worktree"]

        child_cwd = cwd

        # Handle worktree for this child
        if use_worktree and worktree.is_git_repo(cwd):
            repo_root = worktree.get_repo_root(cwd)
            location = config.get("worktreeLocation", "home")
            source_branch = worktree.get_current_branch(repo_root)
            active_cwds = worktree.get_active_session_cwds()

            worktree_path = worktree.find_reusable_worktree(repo_root, active_cwds, location)
            if worktree_path:
                worktree.prepare_reused_worktree(worktree_path, source_branch)
                child_cwd = worktree_path
            else:
                try:
                    child_cwd, _ = worktree.create_worktree(repo_root, location, source_branch)
                except subprocess.CalledProcessError:
                    pass  # Fall back to regular cwd

        # Create tmux session
        if not tmux.create_claude_session(child_name, child_cwd):
            print(f"Warning: Failed to create session {child_name}", file=sys.stderr)
            continue

        # Add to orchestration
        orchestration.add_child_to_orchestration(
            orch_id=orch.id,
            tmux_session=child_name,
            role=role,
            task=task,
        )

        # Build siblings list (all other children)
        siblings = [
            {"role": c["role"], "tmux_session": c["name"]}
            for j, c in enumerate(children_plan) if j != i
        ]

        # Write task file with full posse context
        orchestration.write_task_file(
            child_session_id=child_name,
            orchestration_id=orch.id,
            orchestration_type="posse",
            parent_session_id=parent_session_id,
            parent_tmux_session=parent_tmux,
            role=role,
            task=task,
            context=child_info.get("context"),
            siblings=siblings,
        )

        # Build claude command - interactive session with /deputized command
        # Use -- to pass initial prompt to interactive session (not -p which is headless)
        plugin_dir = os.environ.get("COWBOY_PLUGIN_DIR")
        base_cmd = f"claude --plugin-dir {plugin_dir}" if plugin_dir else "claude"
        task_file_path = orchestration.get_task_file_path(child_name)
        claude_cmd = f'{base_cmd} -- "/claude-cowboy:deputized {task_file_path}"'
        tmux.send_keys(0, claude_cmd, session_name=child_name)

        # Update status
        orchestration.update_child_status(
            orch_id=orch.id,
            child_tmux_session=child_name,
            status="working",
        )

        children_info.append(f"  - {role} ({child_name}): {task[:50]}...")

    # Output result
    children_list = "\n".join(children_info) if children_info else "  (no children spawned)"
    print(f"""**Posse Active** (ID: {orch.id})

Children spawned:
{children_list}

I'll be woken when:
  - All children complete
  - A child needs help
  - You message me

Check status: /sessions
Check dashboard: cowboy dashboard

I'm now idling to save tokens. The orchestration system will wake me when needed.""")

    return 0


def cmd_doctor(args) -> int:
    """Check system dependencies and configuration."""
    print(f"Claude Cowboy v{__version__}\n")
    print("Checking dependencies...\n")

    all_ok = True

    # Required dependencies
    required = [
        ("tmux", "tmux", "Session management"),
        ("claude", "Claude Code", "AI assistant"),
    ]

    # Optional dependencies
    optional = [
        ("fzf", "fzf", "Session browser (optional)"),
        ("jq", "jq", "JSON parsing in hooks (optional)"),
        ("git", "git", "Worktree support (optional)"),
    ]

    print("Required:")
    for cmd, name, desc in required:
        path = shutil.which(cmd)
        if path:
            # Try to get version
            version = ""
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                version = result.stdout.strip().split("\n")[0][:40]
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
            print(f"  [OK] {name}: {version or path}")
        else:
            print(f"  [MISSING] {name}: {desc}")
            all_ok = False

    print("\nOptional:")
    for cmd, name, desc in optional:
        path = shutil.which(cmd)
        if path:
            version = ""
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                version = result.stdout.strip().split("\n")[0][:40]
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
            print(f"  [OK] {name}: {version or path}")
        else:
            print(f"  [--] {name}: {desc}")

    # Check Python version
    print(f"\nPython: {sys.version.split()[0]}")
    if sys.version_info < (3, 12):
        print("  [WARNING] Python 3.12+ recommended")
        all_ok = False

    # Check config
    try:
        config = load_config()
        print(f"\nConfiguration loaded from ~/.claude/settings.json")
        print(f"  Session discovery: {config.get('sessionDiscoveryHours', 24)}h")
        print(f"  Worktree location: {config.get('worktreeLocation', 'home')}")
    except Exception as e:
        print(f"\nConfiguration: Error loading - {e}")

    print()
    if all_ok:
        print("All required dependencies are installed.")
        return 0
    else:
        print("Some required dependencies are missing.")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Claude Cowboy - tmux-based Claude Code session manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", "-V", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # new
    new_parser = subparsers.add_parser("new", help="Create a new Claude session")
    new_parser.add_argument("path", nargs="?", help="Working directory (default: cwd)")
    new_parser.add_argument("--name", "-n", help="Custom suffix for session name (e.g., --name feat creates dir-feat)")
    new_parser.add_argument("--user", "-u", help="Run as specified user (e.g., 'claude')")
    new_parser.add_argument("--worktree", "-w", action="store_true",
        help="Create session in a git worktree for isolation")
    new_parser.add_argument("--worktree-location", choices=["home", "sibling"],
        help="Where to create worktrees (default: home = ~/.cowboy-worktrees)")
    new_parser.add_argument("--monorepo", "-m", action="store_true",
        help="Use parent monorepo for worktree (skip submodule prompt)")

    # dashboard
    subparsers.add_parser("dashboard", aliases=["dash"], help="Open the dashboard")

    # list
    list_parser = subparsers.add_parser("list", aliases=["ls"], help="List sessions")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")
    list_parser.add_argument("--all", "-a", action="store_true", help="Show all tmux sessions, not just Claude")
    list_parser.add_argument("--full-paths", action="store_true", help="Show full paths instead of shortened")

    # attach
    attach_parser = subparsers.add_parser("attach", aliases=["a"], help="Attach to session")
    attach_parser.add_argument("identifier", help="Window name, short ID, or custom name")

    # kill
    kill_parser = subparsers.add_parser("kill", aliases=["k"], help="Kill a session")
    kill_parser.add_argument("identifier", help="Window name, short ID, or custom name")

    # cleanup
    subparsers.add_parser("cleanup", help="Remove stale sessions from registry")

    # tmux - attach to the tmux session
    subparsers.add_parser("tmux", aliases=["t"], help="Attach to cowboy tmux session")

    # configure-status - apply status bar to all Claude sessions
    subparsers.add_parser("configure-status", help="Configure status bar for all Claude sessions")

    # lasso - query another Claude session synchronously
    lasso_parser = subparsers.add_parser("lasso", help="Query another Claude session synchronously")
    lasso_parser.add_argument("target", nargs="?", help="Target session (tmux name or UUID)")
    lasso_parser.add_argument("prompt", nargs="*", help="Query/task for the session")
    lasso_parser.add_argument("--clean", "-c", action="store_true",
        help="Create new session instead of resuming existing")
    lasso_parser.add_argument("--cwd", help="Working directory for clean mode (default: current)")
    lasso_parser.add_argument("--timeout", "-t", type=int,
        help="Timeout in minutes (default: 8)")

    # posse - coordinate multiple sessions
    posse_parser = subparsers.add_parser("posse", help="Coordinate work across multiple Claude sessions")
    posse_parser.add_argument("--plan", "-p", help="JSON plan with workstreams (inline)")
    posse_parser.add_argument("--plan-file", "-f", help="Path to JSON file containing plan")
    posse_parser.add_argument("--cwd", "-c", help="Working directory (default: current)")
    posse_parser.add_argument("--worktree", "-w", action="store_true",
        help="Create children in git worktrees for isolation")

    # doctor - check dependencies
    subparsers.add_parser("doctor", help="Check system dependencies and configuration")

    args = parser.parse_args()

    if args.command is None:
        # Default to "new" in current directory when called without arguments
        args.command = "new"
        args.path = None
        args.name = None
        args.user = None
        args.worktree = False
        args.worktree_location = None
        args.monorepo = False

    commands = {
        "new": cmd_new,
        "dashboard": cmd_dashboard,
        "dash": cmd_dashboard,
        "list": cmd_list,
        "ls": cmd_list,
        "attach": cmd_attach,
        "a": cmd_attach,
        "kill": cmd_kill,
        "k": cmd_kill,
        "cleanup": cmd_cleanup,
        "tmux": cmd_tmux,
        "t": cmd_tmux,
        "configure-status": cmd_configure_status,
        "lasso": cmd_lasso,
        "posse": cmd_posse,
        "doctor": cmd_doctor,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
