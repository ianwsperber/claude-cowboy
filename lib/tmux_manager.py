#!/usr/bin/env python3
"""tmux session and window management for Claude Cowboy.

Provides low-level tmux operations for creating and managing Claude Code sessions.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
try:
    from .config import load_config, is_debug_enabled
except ImportError:
    from config import load_config, is_debug_enabled


@dataclass
class TmuxWindow:
    """Information about a tmux window."""

    index: int
    name: str
    active: bool
    pane_pid: int | None = None
    pane_title: str | None = None
    claude_active: bool = False


@dataclass
class TmuxSession:
    """Information about a tmux session."""

    name: str
    windows: list[TmuxWindow]
    attached: bool


def _run_tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a tmux command and return the result.

    Args:
        *args: tmux command arguments.
        check: Whether to raise on non-zero exit code.

    Returns:
        CompletedProcess with stdout/stderr.
    """
    cmd = ["tmux"] + list(args)
    if is_debug_enabled():
        print(f"[tmux] {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def is_tmux_available() -> bool:
    """Check if tmux is installed and available.

    Returns:
        True if tmux is available.
    """
    try:
        result = subprocess.run(
            ["tmux", "-V"], capture_output=True, text=True, check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_session_name() -> str:
    """Get the configured tmux session name.

    Returns:
        Session name from config or default 'cowboy'.
    """
    config = load_config()
    return config.get("tmuxSessionName", "cowboy")


def configure_status_bar(session_name: str | None = None) -> bool:
    """Configure the tmux status bar for the cowboy session.

    Shows: [session] [0:Dashboard] ...window list...

    Args:
        session_name: Session name, or None to use configured name.

    Returns:
        True if successful.
    """
    name = session_name or get_session_name()
    config = load_config()

    try:
        if not config.get("statusBarShowDashboardHint", True):
            return True

        # Set status-left to call our status_line.py script
        # Use .resolve() to get absolute path from the installed package location
        lib_dir = Path(__file__).resolve().parent
        status_script = lib_dir / "status_line.py"

        # Verify the script exists before configuring
        if not status_script.exists():
            if is_debug_enabled():
                print(f"[tmux] status_line.py not found at {status_script}")
            return True  # Don't fail, just skip status bar customization

        # Pass --session #S so the script knows which session to query
        # tmux expands #S to the session name at runtime
        status_left = f"#(python3 {status_script} --session #S) "
        _run_tmux("set-option", "-t", name, "status-left", status_left, check=False)

        # Set status-left-length to accommodate session name, branch, cwd, and counts
        _run_tmux("set-option", "-t", name, "status-left-length", "100", check=False)

        # Update status more frequently (every 2 seconds)
        _run_tmux("set-option", "-t", name, "status-interval", "2", check=False)

        return True
    except subprocess.CalledProcessError:
        return False


def session_exists(session_name: str | None = None) -> bool:
    """Check if the tmux session exists.

    Args:
        session_name: Session name to check, or None to use configured name.

    Returns:
        True if session exists.
    """
    name = session_name or get_session_name()
    result = _run_tmux("has-session", "-t", name, check=False)
    return result.returncode == 0


def create_session(session_name: str | None = None, start_dir: str | None = None) -> bool:
    """Create a new tmux session with dashboard at window 0.

    The session starts with a dashboard window at index 0.

    Args:
        session_name: Session name, or None to use configured name.
        start_dir: Starting directory for the session.

    Returns:
        True if session was created successfully.
    """
    import sys
    from pathlib import Path

    name = session_name or get_session_name()

    if session_exists(name):
        if is_debug_enabled():
            print(f"Session '{name}' already exists")
        return True

    # Create session in detached mode with dashboard as window 0
    cmd = ["new-session", "-d", "-s", name, "-n", "dashboard"]
    if start_dir:
        cmd.extend(["-c", start_dir])

    try:
        _run_tmux(*cmd)

        # Run dashboard wrapper in window 0
        lib_dir = Path(__file__).parent
        wrapper_path = lib_dir / "dashboard_wrapper.py"
        python_path = sys.executable
        dashboard_cmd = f"{python_path} {wrapper_path}"
        send_keys("dashboard", dashboard_cmd, session_name=name)

        # Configure status bar
        configure_status_bar(name)

        return True
    except subprocess.CalledProcessError as e:
        if is_debug_enabled():
            print(f"Failed to create session: {e.stderr}")
        return False


def ensure_session() -> bool:
    """Ensure the cowboy tmux session exists with dashboard window.

    Returns:
        True if session exists or was created.
    """
    if session_exists():
        # Session exists, ensure dashboard window is present (migration)
        ensure_dashboard_window()
        return True
    return create_session()


def ensure_dashboard_window(session_name: str | None = None) -> bool:
    """Ensure the dashboard window exists at index 0.

    Handles migration for existing sessions that don't have a dashboard.

    Args:
        session_name: Session name, or None to use configured name.

    Returns:
        True if dashboard window exists or was created.
    """
    import sys
    from pathlib import Path

    name = session_name or get_session_name()

    if not session_exists(name):
        return False

    windows = list_windows(name)

    # Check if dashboard window already exists at index 0
    dashboard_window = next((w for w in windows if w.index == 0), None)

    if dashboard_window and dashboard_window.name == "dashboard":
        # Dashboard exists, configure status bar and we're good
        configure_status_bar(name)
        return True

    if dashboard_window:
        # Window 0 exists but isn't the dashboard - need to move it
        # First, move window 0 to a high index
        _run_tmux("move-window", "-s", f"{name}:0", "-t", f"{name}:99", check=False)

    # Create dashboard at index 0
    lib_dir = Path(__file__).parent
    wrapper_path = lib_dir / "dashboard_wrapper.py"
    python_path = sys.executable

    try:
        # Create new window at index 0 named "dashboard"
        _run_tmux("new-window", "-t", f"{name}:0", "-n", "dashboard")

        # Run dashboard wrapper
        dashboard_cmd = f"{python_path} {wrapper_path}"
        send_keys("dashboard", dashboard_cmd, session_name=name)

        # Configure status bar
        configure_status_bar(name)

        return True
    except subprocess.CalledProcessError as e:
        if is_debug_enabled():
            print(f"Failed to create dashboard window: {e}")
        return False


def list_windows(session_name: str | None = None) -> list[TmuxWindow]:
    """List all windows in the session.

    Args:
        session_name: Session name, or None to use configured name.

    Returns:
        List of TmuxWindow objects.
    """
    name = session_name or get_session_name()

    if not session_exists(name):
        return []

    # Format: index|name|active_flag|pane_pid|pane_title|pane_current_command
    result = _run_tmux(
        "list-windows", "-t", name,
        "-F", "#{window_index}|#{window_name}|#{window_active}|#{pane_pid}|#{pane_title}|#{pane_current_command}",
        check=False
    )

    if result.returncode != 0:
        return []

    windows = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 4:
            pane_title = parts[4] if len(parts) > 4 else None
            pane_pid = int(parts[3]) if parts[3] else None
            pane_command = parts[5].lower() if len(parts) > 5 else ""
            # Claude runs as node; check if foreground process is Claude-related
            claude_active = "claude" in pane_command or pane_command == "node"
            windows.append(TmuxWindow(
                index=int(parts[0]),
                name=parts[1],
                active=parts[2] == "1",
                pane_pid=pane_pid,
                pane_title=pane_title if pane_title else None,
                claude_active=claude_active,
            ))

    return windows


def create_window(
    window_name: str,
    command: str | None = None,
    start_dir: str | None = None,
    session_name: str | None = None,
) -> int | None:
    """Create a new window in the session.

    Args:
        window_name: Name for the new window.
        command: Optional command to run in the window.
        start_dir: Starting directory for the window.
        session_name: Session name, or None to use configured name.

    Returns:
        Window index if created, None on failure.
    """
    name = session_name or get_session_name()

    if not ensure_session():
        return None

    # Use "session:" format to explicitly target the session (not a window)
    # This ensures tmux creates at the next available index
    cmd = ["new-window", "-d", "-t", f"{name}:", "-n", window_name, "-P", "-F", "#{window_index}"]
    if start_dir:
        cmd.extend(["-c", start_dir])

    try:
        result = _run_tmux(*cmd)
        window_index = int(result.stdout.strip())

        if command:
            send_keys(window_name, command, session_name=name)

        return window_index
    except (subprocess.CalledProcessError, ValueError) as e:
        if is_debug_enabled():
            print(f"Failed to create window: {e}")
        return None


def send_keys(
    window: str | int,
    keys: str,
    enter: bool = True,
    session_name: str | None = None,
) -> bool:
    """Send keys to a window.

    Args:
        window: Window name or index.
        keys: Keys/command to send.
        enter: Whether to append Enter key.
        session_name: Session name, or None to use configured name.

    Returns:
        True if successful.
    """
    name = session_name or get_session_name()
    target = f"{name}:{window}"

    try:
        cmd = ["send-keys", "-t", target, keys]
        if enter:
            cmd.append("Enter")
        _run_tmux(*cmd)
        return True
    except subprocess.CalledProcessError:
        return False


def select_window(window: str | int, session_name: str | None = None) -> bool:
    """Select (focus) a window.

    Args:
        window: Window name or index.
        session_name: Session name, or None to use configured name.

    Returns:
        True if successful.
    """
    name = session_name or get_session_name()
    target = f"{name}:{window}"

    try:
        _run_tmux("select-window", "-t", target)
        return True
    except subprocess.CalledProcessError:
        return False


def kill_window(window: str | int, session_name: str | None = None) -> bool:
    """Kill a window.

    Args:
        window: Window name or index.
        session_name: Session name, or None to use configured name.

    Returns:
        True if successful.
    """
    name = session_name or get_session_name()
    target = f"{name}:{window}"

    try:
        _run_tmux("kill-window", "-t", target)
        return True
    except subprocess.CalledProcessError:
        return False


def attach_session(session_name: str | None = None) -> bool:
    """Attach to the session (replaces current terminal).

    Args:
        session_name: Session name, or None to use configured name.

    Returns:
        True if successful (note: this replaces the current process).
    """
    import os

    name = session_name or get_session_name()

    if not session_exists(name):
        if not create_session(name):
            return False

    # Use exec to replace current process
    os.execlp("tmux", "tmux", "attach-session", "-t", name)
    # Never reached
    return True


def attach_to_window(window: str | int, session_name: str | None = None) -> bool:
    """Attach to the session with independent window selection.

    Creates a grouped/linked session so this client can view a different
    window than other clients attached to the same session.

    Args:
        window: Window name or index to display.
        session_name: Session name, or None to use configured name.

    Returns:
        True if successful (note: this replaces the current process).
    """
    import os

    name = session_name or get_session_name()

    if not session_exists(name):
        if not create_session(name):
            return False

    # Use new-session -t to create a grouped session (shares windows but
    # has independent current-window selection).
    # The grouped session is destroyed automatically when we detach.
    # Use shell to chain commands: create grouped session, then select window.
    linked_name = f"{name}-{os.getpid()}"
    cmd = f"tmux new-session -t {name} -s {linked_name} \\; select-window -t {linked_name}:{window}"
    os.execlp("sh", "sh", "-c", cmd)
    # Never reached
    return True


def switch_client(window: str | int, session_name: str | None = None) -> bool:
    """Switch the attached client to a specific window.

    Args:
        window: Window name or index.
        session_name: Session name, or None to use configured name.

    Returns:
        True if successful.
    """
    name = session_name or get_session_name()
    target = f"{name}:{window}"

    try:
        _run_tmux("switch-client", "-t", target)
        return True
    except subprocess.CalledProcessError:
        return False


def capture_pane(
    window: str | int,
    lines: int = 50,
    session_name: str | None = None,
) -> str | None:
    """Capture recent output from a pane.

    Args:
        window: Window name or index.
        lines: Number of lines to capture.
        session_name: Session name, or None to use configured name.

    Returns:
        Captured text or None on failure.
    """
    name = session_name or get_session_name()
    target = f"{name}:{window}"

    try:
        result = _run_tmux(
            "capture-pane", "-t", target, "-p", "-S", f"-{lines}"
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def get_pane_pid(window: str | int, session_name: str | None = None) -> int | None:
    """Get the PID of the process running in a window's pane.

    Args:
        window: Window name or index.
        session_name: Session name, or None to use configured name.

    Returns:
        PID or None.
    """
    name = session_name or get_session_name()
    target = f"{name}:{window}"

    try:
        result = _run_tmux(
            "display-message", "-t", target, "-p", "#{pane_pid}"
        )
        return int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def is_claude_process(pid: int) -> bool:
    """Check if a PID corresponds to a Claude process.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process is Claude (or Node running Claude).
    """
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=2
        )
        comm = result.stdout.strip().lower()
        return "claude" in comm or comm == "node"
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def is_inside_tmux() -> bool:
    """Check if we're currently running inside tmux.

    Returns:
        True if inside a tmux session.
    """
    import os
    return "TMUX" in os.environ


def get_current_session() -> str | None:
    """Get the name of the current tmux session (if inside tmux).

    Returns:
        Session name or None.
    """
    if not is_inside_tmux():
        return None

    try:
        result = _run_tmux("display-message", "-p", "#{session_name}")
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def list_all_sessions() -> list[TmuxSession]:
    """List all tmux sessions.

    Returns:
        List of TmuxSession objects.
    """
    result = _run_tmux(
        "list-sessions",
        "-F", "#{session_name}|#{session_windows}|#{session_attached}",
        check=False
    )

    if result.returncode != 0:
        return []

    sessions = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            name = parts[0]
            attached = parts[2] == "1"
            # Get windows for this session
            windows = list_windows(name)
            sessions.append(TmuxSession(
                name=name,
                windows=windows,
                attached=attached,
            ))

    return sessions


def has_claude_in_session(session_name: str) -> bool:
    """Check if a tmux session has a Claude process running.

    Args:
        session_name: Name of the tmux session.

    Returns:
        True if Claude is running in any pane of the session.
    """
    import subprocess

    # Get all pane PIDs in the session
    result = _run_tmux(
        "list-panes", "-t", session_name,
        "-F", "#{pane_pid}",
        check=False
    )

    if result.returncode != 0:
        return False

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            pane_pid = int(line)
            # Check if any child of this pane is running claude
            pgrep_result = subprocess.run(
                ["pgrep", "-P", str(pane_pid), "-f", "claude"],
                capture_output=True,
                text=True,
            )
            if pgrep_result.returncode == 0:
                return True
        except (ValueError, subprocess.SubprocessError):
            continue

    return False


def get_session_cwd(session_name: str) -> str | None:
    """Get the current working directory of a tmux session.

    Args:
        session_name: Name of the tmux session.

    Returns:
        CWD path or None.
    """
    result = _run_tmux(
        "display-message", "-t", session_name,
        "-p", "#{pane_current_path}",
        check=False
    )

    if result.returncode != 0:
        return None

    cwd = result.stdout.strip()
    return cwd if cwd else None


def create_claude_session(session_name: str, start_dir: str) -> bool:
    """Create a new tmux session for Claude.

    Args:
        session_name: Name for the new session.
        start_dir: Directory to start in.

    Returns:
        True if session was created successfully.
    """
    if session_exists(session_name):
        if is_debug_enabled():
            print(f"Session '{session_name}' already exists")
        return False

    try:
        _run_tmux(
            "new-session", "-d",
            "-s", session_name,
            "-c", start_dir,
        )
        return True
    except subprocess.CalledProcessError as e:
        if is_debug_enabled():
            print(f"Failed to create session: {e.stderr}")
        return False


def switch_to_session(session_name: str) -> bool:
    """Switch the current client to a different tmux session.

    Args:
        session_name: Name of the session to switch to.

    Returns:
        True if successful.
    """
    try:
        _run_tmux("switch-client", "-t", session_name)
        return True
    except subprocess.CalledProcessError:
        return False


if __name__ == "__main__":
    print("tmux available:", is_tmux_available())
    print("Session name:", get_session_name())
    print("Session exists:", session_exists())
    print("Inside tmux:", is_inside_tmux())

    if session_exists():
        print("\nWindows:")
        for w in list_windows():
            print(f"  {w.index}: {w.name} (active={w.active}, pid={w.pane_pid}, title={w.pane_title})")
