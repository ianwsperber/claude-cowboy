#!/usr/bin/env python3
"""Session registry for Claude Cowboy.

Manages persistent tracking of tmux-managed Claude Code sessions.
Registry is stored at ~/.claude/cowboy/registry.json.
"""

import json
import os
import secrets
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from .config import get_cowboy_data_dir, get_claude_home, is_debug_enabled
except ImportError:
    from config import get_cowboy_data_dir, get_claude_home, is_debug_enabled


REGISTRY_VERSION = 1


@dataclass
class SessionEntry:
    """A registered Claude Code session."""

    window_name: str  # tmux window name (e.g., "claude-ad1198e4")
    tmux_window: int  # tmux window index
    cwd: str  # Working directory
    created_at: str  # ISO timestamp
    session_id: str | None = None  # JSONL session UUID (discovered after start)
    jsonl_path: str | None = None  # Path to JSONL file
    custom_name: str | None = None  # User-provided name
    git_branch: str | None = None  # Git branch at creation
    run_as_user: str | None = None  # User account running Claude (e.g., "claude")

    @property
    def display_name(self) -> str:
        """Get the display name for this session."""
        return self.custom_name or self.window_name

    @property
    def short_id(self) -> str:
        """Get the short ID (8 chars) from window name."""
        if self.window_name.startswith("claude-"):
            return self.window_name[7:15]
        return self.window_name[:8]


@dataclass
class GitInfo:
    """Git information for a session."""

    branch: str | None
    is_worktree: bool

    @property
    def display_name(self) -> str:
        """Format for display: 'branch' or 'branch (wt)'."""
        if not self.branch:
            return "-"
        if self.is_worktree:
            return f"{self.branch} (wt)"
        return self.branch


@dataclass
class Registry:
    """The session registry."""

    version: int = REGISTRY_VERSION
    tmux_session: str = "cowboy"
    sessions: dict[str, SessionEntry] = field(default_factory=dict)


def get_registry_path() -> Path:
    """Get the path to the registry file.

    Returns:
        Path to ~/.claude/cowboy/registry.json.
    """
    return get_cowboy_data_dir() / "registry.json"


def load_registry() -> Registry:
    """Load the registry from disk.

    Returns:
        Registry object (empty if file doesn't exist).
    """
    path = get_registry_path()

    if not path.exists():
        return Registry()

    try:
        with open(path) as f:
            data = json.load(f)

        # Parse sessions
        sessions = {}
        for name, entry_data in data.get("sessions", {}).items():
            sessions[name] = SessionEntry(**entry_data)

        return Registry(
            version=data.get("version", REGISTRY_VERSION),
            tmux_session=data.get("tmux_session", "cowboy"),
            sessions=sessions,
        )
    except (json.JSONDecodeError, OSError, TypeError) as e:
        if is_debug_enabled():
            print(f"Failed to load registry: {e}")
        return Registry()


def save_registry(registry: Registry) -> bool:
    """Save the registry to disk.

    Args:
        registry: Registry to save.

    Returns:
        True if successful.
    """
    path = get_registry_path()

    try:
        # Convert to serializable format
        data = {
            "version": registry.version,
            "tmux_session": registry.tmux_session,
            "sessions": {
                name: asdict(entry)
                for name, entry in registry.sessions.items()
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
            print(f"Failed to save registry: {e}")
        return False


def generate_window_name() -> str:
    """Generate a unique window name.

    Returns:
        Window name like "claude-ad1198e4".
    """
    short_id = secrets.token_hex(4)  # 8 hex chars
    return f"claude-{short_id}"


def get_git_branch(cwd: str) -> str | None:
    """Get the current git branch for a directory.

    Args:
        cwd: Working directory.

    Returns:
        Branch name or None.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_git_info(cwd: str) -> tuple[str | None, bool]:
    """Get git branch and worktree status for a directory.

    Args:
        cwd: Working directory.

    Returns:
        Tuple of (branch_name, is_worktree).
        Returns (None, False) if not a git repo.
    """
    try:
        # Get branch name
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        branch = branch_result.stdout.strip()

        # Check if worktree by comparing git-dir vs git-common-dir
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        common_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )

        git_dir = os.path.abspath(os.path.join(cwd, git_dir_result.stdout.strip()))
        common_dir = os.path.abspath(os.path.join(cwd, common_dir_result.stdout.strip()))

        is_worktree = git_dir != common_dir

        return branch, is_worktree

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None, False


# Cache for git info to avoid subprocess overhead on each refresh
import time as _time

_git_info_cache: dict[str, tuple[GitInfo, float]] = {}
GIT_INFO_CACHE_TTL = 30.0  # seconds


def get_cached_git_info(cwd: str) -> GitInfo:
    """Get git info with caching.

    Args:
        cwd: Working directory.

    Returns:
        GitInfo with branch and worktree status.
    """
    now = _time.time()
    if cwd in _git_info_cache:
        info, timestamp = _git_info_cache[cwd]
        if now - timestamp < GIT_INFO_CACHE_TTL:
            return info

    branch, is_worktree = get_git_info(cwd)
    info = GitInfo(branch=branch, is_worktree=is_worktree)
    _git_info_cache[cwd] = (info, now)
    return info


# Branch safety status for determining if a worktree can be safely deleted
@dataclass
class BranchSafetyStatus:
    """Safety status for a git branch/worktree."""

    status: str  # in_remote_main, pushed, in_local_main, in_local_branch, unpushed, worktree_only
    unpushed_count: int = 0  # Number of unpushed commits (if status is "unpushed")

    @property
    def is_safe(self) -> bool:
        """Whether it's safe to delete this branch/worktree."""
        return self.status in ("in_remote_main", "pushed")

    @property
    def display_indicator(self) -> str:
        """Get the display indicator string."""
        indicators = {
            "in_remote_main": "[in remote main]",
            "pushed": "[pushed]",
            "in_local_main": "[in local main]",
            "in_local_branch": "[in local branch]",
            "worktree_only": "[worktree only]",
        }
        if self.status == "unpushed":
            return f"[+{self.unpushed_count} unpushed]"
        return indicators.get(self.status, "")


_branch_safety_cache: dict[str, tuple[BranchSafetyStatus, float]] = {}
BRANCH_SAFETY_CACHE_TTL = 60.0  # seconds (longer than git info since this changes less)


def get_branch_safety_status(cwd: str) -> BranchSafetyStatus:
    """Get the safety status of the current branch for deletion purposes.

    Checks where the current branch's commits are preserved, in priority order:
    1. In origin/main (remote default branch) - safest
    2. In any remote branch - safe
    3. In local main - mostly safe
    4. In other local branches - caution
    5. Has unpushed commits - not safe
    6. Nowhere else - unsafe (worktree only)

    Args:
        cwd: Working directory.

    Returns:
        BranchSafetyStatus with status and optional unpushed count.
    """
    now = _time.time()
    if cwd in _branch_safety_cache:
        status, timestamp = _branch_safety_cache[cwd]
        if now - timestamp < BRANCH_SAFETY_CACHE_TTL:
            return status

    result = _compute_branch_safety_status(cwd)
    _branch_safety_cache[cwd] = (result, now)
    return result


def _compute_branch_safety_status(cwd: str) -> BranchSafetyStatus:
    """Compute the branch safety status (no caching)."""
    try:
        # 1. Check if in origin/main (safest)
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
            cwd=cwd,
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return BranchSafetyStatus(status="in_remote_main")

        # Try origin/master as fallback
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "origin/master"],
            cwd=cwd,
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return BranchSafetyStatus(status="in_remote_main")

        # 2. Check if in any remote branch
        result = subprocess.run(
            ["git", "branch", "-r", "--contains", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return BranchSafetyStatus(status="pushed")

        # 3. Check if in local main
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "main"],
            cwd=cwd,
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return BranchSafetyStatus(status="in_local_main")

        # Try master as fallback
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "master"],
            cwd=cwd,
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return BranchSafetyStatus(status="in_local_main")

        # 4. Check if in other local branches (besides current)
        result = subprocess.run(
            ["git", "branch", "--contains", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Filter out current branch (marked with *)
            other_branches = [
                line.strip() for line in result.stdout.strip().split("\n")
                if line.strip() and not line.strip().startswith("*")
            ]
            if other_branches:
                return BranchSafetyStatus(status="in_local_branch")

        # 5. Check for unpushed commits (has upstream but ahead)
        upstream_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "@{upstream}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if upstream_result.returncode == 0:
            # Has upstream, check commits ahead
            ahead_result = subprocess.run(
                ["git", "rev-list", "@{upstream}..HEAD", "--count"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if ahead_result.returncode == 0:
                try:
                    ahead_count = int(ahead_result.stdout.strip())
                    if ahead_count > 0:
                        return BranchSafetyStatus(status="unpushed", unpushed_count=ahead_count)
                except ValueError:
                    pass

        # 6. Nowhere else - worktree only
        return BranchSafetyStatus(status="worktree_only")

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        # On error, assume worktree only (safest assumption)
        return BranchSafetyStatus(status="worktree_only")


def add_session(
    tmux_window: int,
    cwd: str,
    custom_name: str | None = None,
    window_name: str | None = None,
    run_as_user: str | None = None,
) -> SessionEntry:
    """Add a new session to the registry.

    Args:
        tmux_window: tmux window index.
        cwd: Working directory.
        custom_name: Optional user-provided name.
        window_name: Optional window name (generated if not provided).
        run_as_user: Optional username running Claude (e.g., "claude").

    Returns:
        The created SessionEntry.
    """
    registry = load_registry()

    if window_name is None:
        window_name = generate_window_name()

    # Resolve to absolute path
    cwd = os.path.abspath(os.path.expanduser(cwd))

    entry = SessionEntry(
        window_name=window_name,
        tmux_window=tmux_window,
        cwd=cwd,
        created_at=datetime.now(timezone.utc).isoformat(),
        custom_name=custom_name,
        git_branch=get_git_branch(cwd),
        run_as_user=run_as_user,
    )

    registry.sessions[window_name] = entry
    save_registry(registry)

    return entry


def remove_session(window_name: str) -> bool:
    """Remove a session from the registry.

    Args:
        window_name: Window name to remove.

    Returns:
        True if removed.
    """
    registry = load_registry()

    if window_name not in registry.sessions:
        return False

    del registry.sessions[window_name]
    save_registry(registry)
    return True


def get_session(window_name: str) -> SessionEntry | None:
    """Get a session by window name.

    Args:
        window_name: Window name to look up.

    Returns:
        SessionEntry or None.
    """
    registry = load_registry()
    return registry.sessions.get(window_name)


def find_session(identifier: str) -> SessionEntry | None:
    """Find a session by window name, short ID, or custom name.

    Args:
        identifier: Window name, short ID, or custom name.

    Returns:
        SessionEntry or None.
    """
    registry = load_registry()

    # Direct match
    if identifier in registry.sessions:
        return registry.sessions[identifier]

    # Search by short ID or custom name
    for entry in registry.sessions.values():
        if entry.short_id == identifier:
            return entry
        if entry.custom_name and entry.custom_name == identifier:
            return entry

    return None


def list_sessions() -> list[SessionEntry]:
    """Get all registered sessions.

    Returns:
        List of SessionEntry objects.
    """
    registry = load_registry()
    return list(registry.sessions.values())


def get_claude_home_for_user(username: str | None = None) -> Path:
    """Get the ~/.claude directory for a specific user.

    Args:
        username: Username to get home for, or None for current user.

    Returns:
        Path to the user's .claude directory.
    """
    if username is None:
        return get_claude_home()

    # Look up the user's home directory
    try:
        import pwd
        user_info = pwd.getpwnam(username)
        return Path(user_info.pw_dir) / ".claude"
    except (KeyError, ImportError):
        # Fallback: assume /Users/<username> on macOS
        return Path(f"/Users/{username}/.claude")


def get_project_dir_for_cwd(cwd: str, run_as_user: str | None = None) -> Path:
    """Get the ~/.claude/projects/ directory for a given CWD.

    Args:
        cwd: Working directory.
        run_as_user: Username running Claude, or None for current user.

    Returns:
        Path to the project's JSONL directory.
    """
    # Claude uses URL-encoded path as directory name
    # e.g., /Users/user/Code/project -> -Users-user-Code-project
    cwd = os.path.abspath(os.path.expanduser(cwd))
    encoded = cwd.replace("/", "-")
    claude_home = get_claude_home_for_user(run_as_user)
    return claude_home / "projects" / encoded


def discover_jsonl_for_session(
    entry: SessionEntry,
    exclude_paths: set[str] | None = None,
) -> str | None:
    """Try to discover the JSONL file for a session.

    Scans the project directory for JSONL files created after the session.

    Args:
        entry: Session entry to link.
        exclude_paths: Set of JSONL paths to exclude (already assigned to other sessions).

    Returns:
        Path to JSONL file or None.
    """
    project_dir = get_project_dir_for_cwd(entry.cwd, entry.run_as_user)

    try:
        if not project_dir.exists():
            return None
    except PermissionError:
        # Can't access the directory (e.g., running as different user)
        return None

    if exclude_paths is None:
        exclude_paths = set()

    # Parse session creation time
    try:
        created = datetime.fromisoformat(entry.created_at.replace("Z", "+00:00"))
    except ValueError:
        created = datetime.min.replace(tzinfo=timezone.utc)

    # Find JSONL files, sorted by modification time (newest first)
    jsonl_files = sorted(
        project_dir.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    for jsonl_path in jsonl_files:
        # Skip agent sessions
        if jsonl_path.stem.startswith("agent-"):
            continue

        # Skip already-assigned paths
        if str(jsonl_path) in exclude_paths:
            continue

        # Check if file was created after session
        mtime = datetime.fromtimestamp(
            jsonl_path.stat().st_mtime, tz=timezone.utc
        )

        # Allow some slack (file might be created slightly before registry entry)
        if mtime >= created - __import__("datetime").timedelta(seconds=30):
            # Read first line to verify CWD matches
            try:
                with open(jsonl_path) as f:
                    first_line = f.readline()
                    if first_line:
                        data = json.loads(first_line)
                        file_cwd = data.get("cwd", "")
                        # Normalize paths for comparison
                        if os.path.abspath(file_cwd) == os.path.abspath(entry.cwd):
                            return str(jsonl_path)
            except (json.JSONDecodeError, OSError):
                continue

    return None


def link_sessions_to_jsonl() -> int:
    """Link all unlinked sessions to their JSONL files.

    Returns:
        Number of sessions linked.
    """
    registry = load_registry()
    linked = 0

    # Track already-assigned JSONL paths to avoid duplicates
    assigned_jsonl_paths: set[str] = set()

    # First pass: collect already-linked paths and verify they exist
    for entry in registry.sessions.values():
        if entry.jsonl_path:
            if Path(entry.jsonl_path).exists():
                assigned_jsonl_paths.add(entry.jsonl_path)
            else:
                entry.jsonl_path = None
                entry.session_id = None

    # Second pass: link unlinked sessions, avoiding already-assigned paths
    for entry in registry.sessions.values():
        if not entry.jsonl_path:
            jsonl_path = discover_jsonl_for_session(entry, exclude_paths=assigned_jsonl_paths)
            if jsonl_path:
                entry.jsonl_path = jsonl_path
                entry.session_id = Path(jsonl_path).stem
                assigned_jsonl_paths.add(jsonl_path)
                linked += 1

    if linked > 0:
        save_registry(registry)

    return linked


def update_session(window_name: str, **kwargs) -> bool:
    """Update fields on a session entry.

    Args:
        window_name: Window name to update.
        **kwargs: Fields to update.

    Returns:
        True if updated.
    """
    registry = load_registry()

    if window_name not in registry.sessions:
        return False

    entry = registry.sessions[window_name]
    for key, value in kwargs.items():
        if hasattr(entry, key):
            setattr(entry, key, value)

    save_registry(registry)
    return True


def cleanup_stale_sessions(valid_windows: set[str]) -> int:
    """Remove sessions whose tmux windows no longer exist.

    Args:
        valid_windows: Set of window names that currently exist.

    Returns:
        Number of sessions removed.
    """
    registry = load_registry()
    removed = 0

    stale = [
        name for name in registry.sessions
        if name not in valid_windows and name != "dashboard"
    ]

    for name in stale:
        del registry.sessions[name]
        removed += 1

    if removed > 0:
        save_registry(registry)

    return removed


if __name__ == "__main__":
    print(f"Registry path: {get_registry_path()}")

    registry = load_registry()
    print(f"Registry version: {registry.version}")
    print(f"tmux session: {registry.tmux_session}")
    print(f"Sessions: {len(registry.sessions)}")

    for name, entry in registry.sessions.items():
        print(f"\n  {name}:")
        print(f"    CWD: {entry.cwd}")
        print(f"    Window: {entry.tmux_window}")
        print(f"    Session ID: {entry.session_id or 'not linked'}")
        print(f"    Created: {entry.created_at}")
