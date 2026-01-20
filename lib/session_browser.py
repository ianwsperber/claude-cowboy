#!/usr/bin/env python3
"""Session browser for Claude Cowboy.

fzf-based browser showing tmux sessions running Claude.
Adapted from tmux-claude-status by samleeney (MIT License)
https://github.com/samleeney/tmux-claude-status
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from .config import load_config
    from .status_analyzer import get_hook_status_dir, get_wait_dir
    from .session_registry import get_cached_git_info, get_branch_safety_status
    from . import tmux_manager as tmux
    from .orchestration import (
        get_active_orchestrations,
        get_orchestration_info_for_session,
    )
except ImportError:
    from config import load_config
    from status_analyzer import get_hook_status_dir, get_wait_dir
    from session_registry import get_cached_git_info, get_branch_safety_status
    import tmux_manager as tmux
    from orchestration import (
        get_active_orchestrations,
        get_orchestration_info_for_session,
    )


# ANSI color codes
YELLOW = "\033[1;33m"
GREEN = "\033[1;32m"
CYAN = "\033[1;36m"
DIM = "\033[2m"  # Dim/faint - respects terminal theme for "inactive" look
MAGENTA = "\033[1;35m"
RED = "\033[1;31m"
RESET = "\033[0m"

# Regex to strip ANSI escape codes for width calculation
import re
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')


@dataclass
class ClaudeSession:
    """A tmux session (may or may not have Claude running)."""

    session_name: str
    cwd: str | None
    status: str  # "needs_attention", "working", "done", "wait", or ""
    wait_remaining: str  # e.g., "(5m)" or ""
    attached: bool
    window_count: int
    has_claude: bool = True  # Whether Claude is running in this session
    git_branch: str | None = None  # Git branch name
    is_worktree: bool = False  # Whether this is a git worktree
    safety_status: str = ""  # Safety status: in_remote_main, pushed, etc.
    safety_indicator: str = ""  # Display indicator: [pushed], [worktree only], etc.
    # Orchestration info
    is_orchestrated_child: bool = False  # Is this a child in an orchestration?
    is_orchestrating_parent: bool = False  # Is this a parent orchestrating children?
    orchestration_id: str | None = None  # Orchestration ID if orchestrated
    orchestration_type: str | None = None  # "posse" or "lasso"
    orchestration_role: str | None = None  # Child role (e.g., "frontend")
    orchestration_working: int = 0  # Number of working children (for parent)
    orchestration_total: int = 0  # Total children (for parent)


def get_session_status(session_name: str) -> tuple[str, str]:
    """Get status for a session from hook status files.

    Args:
        session_name: tmux session name.

    Returns:
        Tuple of (status, wait_remaining).
        Status is "needs_attention", "working", "done", "wait", or "".
        wait_remaining is e.g., "(5m)" or "".
    """
    import time

    status_dir = get_hook_status_dir()
    wait_dir = get_wait_dir()

    # Check for wait timer first
    wait_file = wait_dir / f"{session_name}.wait"
    if wait_file.exists():
        try:
            expires = int(wait_file.read_text().strip())
            remaining = expires - int(time.time())
            if remaining > 0:
                minutes = remaining // 60
                wait_str = f"({minutes}m)" if minutes > 0 else "(<1m)"
                return "wait", wait_str
            else:
                # Timer expired
                wait_file.unlink(missing_ok=True)
        except (ValueError, OSError):
            pass

    # Check status file
    status_file = status_dir / f"{session_name}.status"
    if status_file.exists():
        try:
            status = status_file.read_text().strip().lower()
            if status in ("working", "done", "wait", "needs_attention"):
                return status, ""
        except OSError:
            pass

    return "", ""


def get_all_sessions() -> list[ClaudeSession]:
    """Get all tmux sessions, marking which ones have Claude running.

    Returns:
        List of ClaudeSession objects for all tmux sessions.
    """
    sessions = []

    # Build orchestration lookup maps
    orchestration_map = {}  # tmux_session -> orchestration info
    try:
        for orch in get_active_orchestrations():
            # Map parent
            orchestration_map[orch.parent_tmux_session] = {
                "is_parent": True,
                "orchestration": orch,
                "working": len([c for c in orch.children if c.status == "working"]),
                "total": len(orch.children),
            }
            # Map children
            for child in orch.children:
                orchestration_map[child.tmux_session] = {
                    "is_parent": False,
                    "orchestration": orch,
                    "child": child,
                }
    except Exception:
        pass  # Orchestration module may not be available

    for tmux_session in tmux.list_all_sessions():
        # Check if this session has Claude running
        has_claude = tmux.has_claude_in_session(tmux_session.name)

        # Get CWD
        cwd = tmux.get_session_cwd(tmux_session.name)

        # Check if this is an orchestrated session (child or parent)
        is_orchestrated = tmux_session.name in orchestration_map

        # Get status from hook files
        # - Always check for Claude sessions
        # - Also check for orchestrated sessions (even if Claude exited, to show completion status)
        status, wait_remaining = "", ""
        if has_claude or is_orchestrated:
            status, wait_remaining = get_session_status(tmux_session.name)
            # Default to "done" if no status file (Claude is running but no recent hook)
            if not status:
                status = "done"

        # Get git info and safety status (only for worktrees)
        git_branch = None
        is_worktree = False
        safety_status = ""
        safety_indicator = ""
        if cwd:
            git_info = get_cached_git_info(cwd)
            git_branch = git_info.branch
            is_worktree = git_info.is_worktree
            # Only compute safety status for worktrees (main repos don't need deletion warnings)
            # Include orchestrated children even if Claude has exited
            if is_worktree and (has_claude or is_orchestrated):
                branch_safety = get_branch_safety_status(cwd)
                safety_status = branch_safety.status
                safety_indicator = branch_safety.display_indicator

        # Get orchestration info
        is_orchestrated_child = False
        is_orchestrating_parent = False
        orchestration_id = None
        orchestration_type = None
        orchestration_role = None
        orchestration_working = 0
        orchestration_total = 0

        orch_info = orchestration_map.get(tmux_session.name)
        if orch_info:
            orch = orch_info["orchestration"]
            orchestration_id = orch.id
            orchestration_type = orch.type
            if orch_info["is_parent"]:
                is_orchestrating_parent = True
                orchestration_working = orch_info["working"]
                orchestration_total = orch_info["total"]
            else:
                is_orchestrated_child = True
                orchestration_role = orch_info["child"].role

        # Treat orchestrated children as "Claude sessions" for display purposes
        # even if Claude has exited (so completed tasks still show in dashboard)
        effective_has_claude = has_claude or is_orchestrated_child

        sessions.append(ClaudeSession(
            session_name=tmux_session.name,
            cwd=cwd,
            status=status,
            wait_remaining=wait_remaining,
            attached=tmux_session.attached,
            window_count=len(tmux_session.windows),
            has_claude=effective_has_claude,
            git_branch=git_branch,
            is_worktree=is_worktree,
            safety_status=safety_status,
            safety_indicator=safety_indicator,
            is_orchestrated_child=is_orchestrated_child,
            is_orchestrating_parent=is_orchestrating_parent,
            orchestration_id=orchestration_id,
            orchestration_type=orchestration_type,
            orchestration_role=orchestration_role,
            orchestration_working=orchestration_working,
            orchestration_total=orchestration_total,
        ))

    return sessions


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text for width calculation."""
    return ANSI_ESCAPE.sub('', text)


def visible_width(text: str) -> int:
    """Get the visible width of text (excluding ANSI codes)."""
    return len(strip_ansi(text))


def pad_to_width(text: str, width: int) -> str:
    """Pad text to a specific visible width, accounting for ANSI codes."""
    current_width = visible_width(text)
    if current_width < width:
        return text + " " * (width - current_width)
    return text


@dataclass
class SessionColumns:
    """Column data for a session, used for aligned formatting."""
    name: str
    status: str
    branch: str
    attached: str
    cwd: str
    safety: str
    is_claude: bool


def get_session_columns(session: ClaudeSession) -> SessionColumns:
    """Extract column data from a session.

    Args:
        session: ClaudeSession object.

    Returns:
        SessionColumns with formatted column values.
    """
    # Shorten CWD
    cwd = session.cwd or "?"
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]
    if len(cwd) > 50:
        cwd = "..." + cwd[-47:]

    # For non-Claude sessions
    if not session.has_claude:
        attached_str = "(attached)" if session.attached else ""
        return SessionColumns(
            name=session.session_name,
            status="",
            branch="",
            attached=attached_str,
            cwd=cwd,
            safety="",
            is_claude=False,
        )

    # Session name - add (*) prefix for orchestrated children
    name_str = session.session_name
    if session.is_orchestrated_child:
        name_str = f"{MAGENTA}(*){RESET} {session.session_name}"

    # Status indicator
    if session.is_orchestrating_parent:
        # Parent: show orchestration status [posse:2/3] or [lasso:1]
        if session.orchestration_type == "posse":
            status_str = f"{MAGENTA}[posse:{session.orchestration_working}/{session.orchestration_total}]{RESET}"
        else:
            status_str = f"{MAGENTA}[lasso:{session.orchestration_total}]{RESET}"
    elif session.status == "needs_attention":
        status_str = "[ATTENTION]"
    elif session.status == "working":
        status_str = "[working]"
    elif session.status == "wait":
        status_str = f"[wait]{session.wait_remaining}"
    else:
        status_str = "[done]"

    # Attached indicator
    attached_str = "(attached)" if session.attached else ""

    # Git branch (truncate if too long, color cyan)
    branch_str = ""
    if session.git_branch:
        branch = session.git_branch
        if len(branch) > 20:
            branch = branch[:17] + "..."
        branch_str = f"{CYAN}{branch}{RESET}"

    # Safety indicator (only for worktrees)
    safety_str = ""
    if session.safety_indicator:
        # Color based on safety status
        if session.safety_status in ("in_remote_main", "pushed"):
            safety_str = f"{GREEN}{session.safety_indicator}{RESET}"
        elif session.safety_status in ("in_local_main", "in_local_branch", "unpushed"):
            safety_str = f"{YELLOW}{session.safety_indicator}{RESET}"
        else:  # worktree_only
            safety_str = f"{RED}{session.safety_indicator}{RESET}"

    return SessionColumns(
        name=name_str,
        status=status_str,
        branch=branch_str,
        attached=attached_str,
        cwd=cwd,
        safety=safety_str,
        is_claude=True,
    )


def format_session_line(cols: SessionColumns, widths: dict[str, int]) -> str:
    """Format a session line with aligned columns.

    Args:
        cols: SessionColumns with column data.
        widths: Dict of column name to max width.

    Returns:
        Formatted string with aligned columns.
    """
    if not cols.is_claude:
        # Non-Claude sessions: dim, simpler format
        parts = [pad_to_width(cols.name, widths["name"])]
        # Add empty status column for alignment
        parts.append(" " * widths["status"])
        if widths["branch"] > 0:
            parts.append(" " * widths["branch"])
        parts.append(pad_to_width(cols.attached, widths["attached"]))
        parts.append(cols.cwd)
        return f"{DIM}{'  '.join(parts)}{RESET}"

    # Claude sessions with full formatting
    parts = [
        pad_to_width(cols.name, widths["name"]),
        pad_to_width(cols.status, widths["status"]),
    ]
    if widths["branch"] > 0:
        parts.append(pad_to_width(cols.branch, widths["branch"]))
    parts.append(pad_to_width(cols.attached, widths["attached"]))
    parts.append(cols.cwd)
    if cols.safety:
        parts.append(cols.safety)

    return "  ".join(parts)


def generate_fzf_input() -> str:
    """Generate input for fzf with Claude sessions first, then other tmux sessions.

    Orchestrated sessions are grouped hierarchically:
    - Non-orchestrated Claude sessions first
    - Then orchestration groups (parent followed by indented children)
    - Then other tmux sessions

    Returns:
        Formatted string with Claude sessions sorted alphabetically,
        followed by other tmux sessions in a separate section.
    """
    all_sessions = get_all_sessions()

    if not all_sessions:
        return f"{DIM}No tmux sessions found. Use 'cowboy new' to create one.{RESET}"

    # Build session lookup
    session_by_name = {s.session_name: s for s in all_sessions}

    # Separate sessions into categories
    claude_sessions = [s for s in all_sessions if s.has_claude]
    other_sessions = [s for s in all_sessions if not s.has_claude]

    # Further separate orchestrated from non-orchestrated Claude sessions
    non_orchestrated = [s for s in claude_sessions
                       if not s.is_orchestrated_child and not s.is_orchestrating_parent]
    orchestrating_parents = [s for s in claude_sessions if s.is_orchestrating_parent]
    orchestrated_children = {s.session_name: s for s in claude_sessions if s.is_orchestrated_child}

    # Find orphaned children (children whose parent session doesn't exist)
    # These should be shown in the main list since there's no parent to nest them under
    parent_session_names = {s.session_name for s in orchestrating_parents}
    orphaned_children = []
    for child_name, child_session in orchestrated_children.items():
        # Check if any active orchestration's parent exists in our session list
        try:
            orchestrations = get_active_orchestrations()
            child_parent_exists = False
            for orch in orchestrations:
                if child_name in [c.tmux_session for c in orch.children]:
                    if orch.parent_tmux_session in parent_session_names:
                        child_parent_exists = True
                        break
            if not child_parent_exists:
                orphaned_children.append(child_session)
        except Exception:
            orphaned_children.append(child_session)

    # Add orphaned children to non_orchestrated so they get shown
    non_orchestrated.extend(orphaned_children)

    # Sort non-orchestrated alphabetically
    non_orchestrated.sort(key=lambda s: s.session_name.lower())
    orchestrating_parents.sort(key=lambda s: s.session_name.lower())
    other_sessions.sort(key=lambda s: s.session_name.lower())

    # Convert all sessions to column data for width calculation
    all_cols: list[tuple[ClaudeSession, SessionColumns]] = []
    for session in all_sessions:
        all_cols.append((session, get_session_columns(session)))

    # Calculate max widths for each column (across ALL sessions for alignment)
    widths = {
        "name": max((visible_width(c.name) for _, c in all_cols), default=0),
        "status": max((visible_width(c.status) for _, c in all_cols), default=0),
        "branch": max((visible_width(c.branch) for _, c in all_cols), default=0),
        "attached": max((visible_width(c.attached) for _, c in all_cols), default=0),
    }

    lines = []

    # Non-orchestrated Claude sessions first
    for session in non_orchestrated:
        cols = get_session_columns(session)
        lines.append(format_session_line(cols, widths))

    # Orchestration groups
    if orchestrating_parents:
        if lines:
            lines.append("")
        lines.append(f"{MAGENTA}━━━ ORCHESTRATIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")

        for parent in orchestrating_parents:
            # Parent line
            cols = get_session_columns(parent)
            lines.append(format_session_line(cols, widths))

            # Find and display children for this parent (indented)
            # Get orchestration info to find children
            try:
                orchestrations = get_active_orchestrations()
                shown_children = set()  # Track shown children to avoid duplicates
                for orch in orchestrations:
                    if orch.parent_tmux_session == parent.session_name:
                        for child in orch.children:
                            # Skip if already shown (from another orchestration)
                            if child.tmux_session in shown_children:
                                continue
                            child_session = session_by_name.get(child.tmux_session)
                            if child_session:
                                cols = get_session_columns(child_session)
                                # Add indentation for child
                                line = format_session_line(cols, widths)
                                lines.append(f"  {line}")
                                shown_children.add(child.tmux_session)
            except Exception:
                pass

    # Other tmux sessions in a separate section
    if other_sessions:
        if lines:
            lines.append("")
        lines.append(f"{DIM}━━━ OTHER TMUX SESSIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
        for session in other_sessions:
            cols = get_session_columns(session)
            lines.append(format_session_line(cols, widths))

    if not lines:
        return f"{DIM}No sessions found. Use 'cowboy new' to create one.{RESET}"

    return "\n".join(lines)


def get_script_path() -> str:
    """Get the path to this module for reload commands."""
    return os.path.abspath(__file__)


def get_browse_script_path() -> str:
    """Get the path to the browse.sh script for auto-refresh."""
    module_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(module_dir), "scripts", "browse.sh")


def run_browser(auto_refresh: bool = True) -> str | None:
    """Run the fzf-based session browser.

    Args:
        auto_refresh: If True, use shell script with fzf --listen for auto-refresh.
                     Falls back gracefully for older fzf versions.

    Returns:
        Selected session name or None if cancelled.
    """
    # Check if fzf is available
    if subprocess.run(["which", "fzf"], capture_output=True).returncode != 0:
        print("Error: fzf is not installed. Please install it first.", file=sys.stderr)
        print("  macOS: brew install fzf", file=sys.stderr)
        print("  Linux: apt install fzf / dnf install fzf", file=sys.stderr)
        return None

    if auto_refresh:
        # Use shell script for auto-refresh (uses fzf --listen)
        browse_script = get_browse_script_path()
        if os.path.exists(browse_script):
            # Run the shell script - it handles everything including switching
            result = subprocess.run([browse_script])
            # Shell script handles the switch, so return None
            return None

    # Fallback: run fzf directly without auto-refresh
    script_path = get_script_path()
    reload_cmd = f"python3 {script_path} --no-fzf"
    preview_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "preview.sh")

    fzf_cmd = [
        "fzf",
        "--ansi",
        "--no-sort",
        "--color=bg+:#D87757,fg+:#000000",
        "--header=Sessions | Enter: actions | Esc: cancel | Ctrl-K: kill | Ctrl-R: refresh",
        "--prompt=Session> ",
        "--layout=reverse",
        "--info=inline",
        "--bind=ctrl-j:preview-down",
        f"--bind=ctrl-r:reload({reload_cmd})",
        f"--bind=ctrl-k:execute-silent(echo {{}} | grep -v '━━━' | awk '{{print $1}}' | xargs -I{{s}} tmux kill-session -t {{s}} 2>/dev/null)+reload({reload_cmd})",
        f"--preview={preview_script} {{}}",
        "--preview-window=right:50%:wrap:~9:follow",
    ]

    try:
        fzf_input = generate_fzf_input()

        result = subprocess.run(
            fzf_cmd,
            input=fzf_input,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0 and result.stdout.strip():
            selected = result.stdout.strip()
            if "━━━" in selected or not selected:
                return None
            return selected.split()[0]
        return None

    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"Error running fzf: {e}", file=sys.stderr)
        return None


def show_action_menu(session_name: str) -> str | None:
    """Show action menu for a selected session.

    Args:
        session_name: The name of the selected session.

    Returns:
        Selected action: "switch", "open", "editor", "lasso", "kill", "cancel", or None if cancelled.
    """
    fzf_cmd = [
        "fzf",
        f"--header=Action for: {session_name}  [s]witch [o]pen [t]erminal [e]ditor [l]asso [k]ill [c]ancel",
        "--height=10",
        "--layout=reverse",
        "--no-info",
        "--prompt=Action> ",
        "--bind=s:become(echo switch)",
        "--bind=o:become(echo open)",
        "--bind=t:become(echo terminal)",
        "--bind=e:become(echo editor)",
        "--bind=l:become(echo lasso)",
        "--bind=k:become(echo kill)",
        "--bind=c:become(echo cancel)",
    ]

    try:
        result = subprocess.run(
            fzf_cmd,
            input="switch\nopen\nterminal\neditor\nlasso\nkill\ncancel",
            capture_output=True,
            text=True,
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None

    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def main():
    """Main entry point for session browser."""
    import argparse

    parser = argparse.ArgumentParser(description="Claude Cowboy session browser")
    parser.add_argument(
        "--no-fzf",
        action="store_true",
        help="Print sessions without fzf (for scripting/reload)",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Disable auto-refresh (use Ctrl-R for manual refresh)",
    )
    parser.add_argument(
        "--switch",
        action="store_true",
        help="Switch to selected session (default when run interactively)",
    )
    args = parser.parse_args()

    if args.no_fzf:
        print(generate_fzf_input())
        return

    auto_refresh = not args.no_refresh
    selected = run_browser(auto_refresh=auto_refresh)

    # If auto_refresh=True, the shell script handles switching
    # Only handle switching when auto_refresh=False
    if selected:
        # Show action menu
        action = show_action_menu(selected)

        # Get session CWD for open/editor actions
        session_cwd = tmux.get_session_cwd(selected)

        if action == "switch":
            if tmux.is_inside_tmux():
                if tmux.switch_to_session(selected):
                    pass  # Successfully switched
                else:
                    print(f"Failed to switch to session: {selected}", file=sys.stderr)
                    sys.exit(1)
            else:
                # Attach to the session
                os.execlp("tmux", "tmux", "attach-session", "-t", selected)
        elif action == "open":
            if session_cwd:
                # macOS: open, Linux: xdg-open
                subprocess.run(["open", session_cwd], capture_output=True) or \
                    subprocess.run(["xdg-open", session_cwd], capture_output=True)
            # Re-run the browser
            os.execlp(sys.executable, sys.executable, *sys.argv)
        elif action == "terminal":
            if session_cwd:
                # Use $TERMINAL if set, otherwise try iTerm, then Terminal.app, then Linux terminals
                terminal = os.environ.get("TERMINAL")
                if terminal:
                    result = subprocess.run(["open", "-a", terminal, session_cwd], capture_output=True)
                    if result.returncode != 0:
                        subprocess.run([terminal, session_cwd], capture_output=True)
                else:
                    result = subprocess.run(["open", "-a", "iTerm", session_cwd], capture_output=True)
                    if result.returncode != 0:
                        result = subprocess.run(["open", "-a", "Terminal", session_cwd], capture_output=True)
                    if result.returncode != 0:
                        result = subprocess.run(["gnome-terminal", f"--working-directory={session_cwd}"], capture_output=True)
                    if result.returncode != 0:
                        subprocess.run(["x-terminal-emulator", "--workdir", session_cwd], capture_output=True)
            # Re-run the browser
            os.execlp(sys.executable, sys.executable, *sys.argv)
        elif action == "editor":
            if session_cwd:
                # Try VS Code first, then fall back to $EDITOR
                result = subprocess.run(["code", session_cwd], capture_output=True)
                if result.returncode != 0:
                    editor = os.environ.get("EDITOR", "vim")
                    subprocess.run([editor, session_cwd], capture_output=True)
            # Re-run the browser
            os.execlp(sys.executable, sys.executable, *sys.argv)
        elif action == "lasso":
            # Placeholder - does nothing for now
            os.execlp(sys.executable, sys.executable, *sys.argv)
        elif action == "kill":
            subprocess.run(["tmux", "kill-session", "-t", selected], capture_output=True)
            # Re-run the browser
            os.execlp(sys.executable, sys.executable, *sys.argv)
        # cancel or None: just exit


if __name__ == "__main__":
    main()
