#!/usr/bin/env python3
"""Git worktree helpers for Claude Cowboy.

Provides isolation for multiple Claude sessions in the same repository
by creating separate git worktrees for each session.
"""

import os
import re
import subprocess
from pathlib import Path
try:
    from .config import load_config, is_debug_enabled
except ImportError:
    from config import load_config, is_debug_enabled


def is_git_repo(path: str) -> bool:
    """Check if path is inside a git repository.

    Args:
        path: Directory path to check.

    Returns:
        True if path is inside a git repo.
    """
    result = subprocess.run(
        ["git", "-C", path, "rev-parse", "--git-dir"],
        capture_output=True,
    )
    return result.returncode == 0


def get_repo_root(path: str) -> str | None:
    """Get the root directory of the git repository.

    Args:
        path: Any path inside a git repo.

    Returns:
        Absolute path to repo root, or None if not a git repo.
    """
    result = subprocess.run(
        ["git", "-C", path, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def get_current_branch(repo_path: str) -> str | None:
    """Get the current branch name, or None if HEAD is detached.

    Args:
        repo_path: Path to the git repository.

    Returns:
        Branch name, or None if HEAD is detached.
    """
    result = subprocess.run(
        ["git", "-C", repo_path, "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None  # Detached HEAD


def is_submodule(path: str) -> bool:
    """Check if the repo at path is a git submodule.

    Submodules have .git as a file (not a directory) pointing to the parent.

    Args:
        path: Path to check.

    Returns:
        True if path is inside a git submodule.
    """
    repo_root = get_repo_root(path)
    if not repo_root:
        return False
    git_path = os.path.join(repo_root, ".git")
    return os.path.isfile(git_path)


def get_parent_repo_root(submodule_path: str) -> str | None:
    """Get the root of the parent repo containing a submodule.

    Args:
        submodule_path: Path inside a submodule.

    Returns:
        Path to parent repo root, or None if not found.
    """
    repo_root = get_repo_root(submodule_path)
    if not repo_root:
        return None

    # Go up from repo root and find the parent git repo
    parent_dir = os.path.dirname(repo_root)
    while parent_dir != "/":
        if is_git_repo(parent_dir):
            return get_repo_root(parent_dir)
        parent_dir = os.path.dirname(parent_dir)
    return None


def get_worktrees_base_dir() -> Path:
    """Get the base directory for cowboy-managed worktrees.

    Returns:
        Path to ~/.cowboy-worktrees/
    """
    return Path.home() / ".cowboy-worktrees"


def get_next_worktree_number(repo_path: str, location: str = "home") -> int:
    """Find the next available worktree number for a repo in a specific location.

    Args:
        repo_path: Path to the git repository.
        location: "home" or "sibling" to determine where to look.

    Returns:
        Next available number (1, 2, 3, etc.)
    """
    existing = list_worktrees_for_repo(repo_path)
    repo_name = os.path.basename(repo_path)

    if location == "sibling":
        # Look for sibling directories like ~/code/my-repo-01, ~/code/my-repo-02
        # These are in the same parent directory as repo_path
        location_prefix = os.path.dirname(repo_path)
    else:
        # Look in ~/.cowboy-worktrees/ for directories like my-repo-01, my-repo-02
        location_prefix = str(get_worktrees_base_dir())

    used_numbers = set()
    for wt in existing:
        # Skip the main worktree
        if wt == repo_path:
            continue

        # Only count worktrees in the target location
        if not wt.startswith(location_prefix):
            continue

        wt_name = os.path.basename(wt)
        # Check if this worktree matches our naming pattern
        if wt_name.startswith(repo_name + "-"):
            suffix = wt_name[len(repo_name) + 1:]
            # Handle both "1" and "01" formats
            if suffix.isdigit():
                used_numbers.add(int(suffix))

    # Find next available number
    num = 1
    while num in used_numbers:
        num += 1
    return num


def get_worktree_path(
    repo_path: str,
    location: str = "home",
) -> str:
    """Calculate worktree path based on location preference.

    Auto-increments based on existing worktrees (01, 02, etc.)

    Args:
        repo_path: Path to the git repository.
        location: "home" for ~/.cowboy-worktrees/, "sibling" for adjacent directory.

    Returns:
        Path where worktree should be created.
    """
    repo_name = os.path.basename(repo_path)
    num = get_next_worktree_number(repo_path, location)

    if location == "sibling":
        # ~/code/my-repo -> ~/code/my-repo-01
        return f"{repo_path}-{num:02d}"
    else:
        # Default: ~/.cowboy-worktrees/my-repo-01
        return str(get_worktrees_base_dir() / f"{repo_name}-{num:02d}")


def get_worktree_number(worktree_path: str) -> str:
    """Extract the number suffix from a worktree path.

    Args:
        worktree_path: Path to a worktree (e.g., "~/.cowboy-worktrees/repo-name-03")

    Returns:
        The number suffix as a string (e.g., "03"), or "01" if not found.
    """
    basename = os.path.basename(worktree_path)
    match = re.search(r'-(\d+)$', basename)
    return match.group(1) if match else "01"


def list_worktrees_for_repo(repo_path: str) -> list[str]:
    """List all worktrees for a repository.

    Args:
        repo_path: Path to the git repository (main worktree or any worktree).

    Returns:
        List of worktree paths.
    """
    result = subprocess.run(
        ["git", "-C", repo_path, "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    worktrees = []
    for line in result.stdout.split("\n"):
        if line.startswith("worktree "):
            worktrees.append(line[9:])  # Strip "worktree " prefix
    return worktrees


def find_reusable_worktree(
    repo_path: str,
    active_session_cwds: dict[str, str | None],
    location: str = "home",
) -> str | None:
    """Find an existing idle worktree that can be reused.

    Looks in the specified location (home or sibling) for idle worktrees.

    Args:
        repo_path: Path to the git repository.
        active_session_cwds: Dict mapping session names to their CWDs.
        location: "home" or "sibling".

    Returns:
        Path to reusable worktree, or None if none available.
    """
    worktrees = list_worktrees_for_repo(repo_path)
    repo_name = os.path.basename(repo_path)

    # Determine where to look based on location
    if location == "sibling":
        location_prefix = os.path.dirname(repo_path)
    else:
        location_prefix = str(get_worktrees_base_dir())

    # Build set of normalized CWDs for quick lookup
    active_cwds = {
        os.path.realpath(cwd) for cwd in active_session_cwds.values() if cwd
    }

    for wt in worktrees:
        # Skip the main worktree
        if wt == repo_path:
            continue

        # Only consider worktrees in the target location
        if not wt.startswith(location_prefix):
            continue

        # Only consider worktrees matching our naming pattern (repo-name-NN)
        wt_name = os.path.basename(wt)
        if not wt_name.startswith(repo_name + "-"):
            continue

        # Skip worktrees that no longer exist on disk (stale git references)
        if not os.path.isdir(wt):
            continue

        # Check if this worktree has an active tmux session by comparing CWDs
        wt_realpath = os.path.realpath(wt)
        if wt_realpath not in active_cwds:
            return wt

    return None


def create_worktree(
    repo_path: str,
    location: str = "home",
    source_branch: str | None = None,
) -> tuple[str, str | None]:
    """Create a git worktree for a session.

    Auto-increments worktree number based on existing worktrees.
    If source_branch is provided, creates a derived branch (e.g., feature-x-wt-03).

    Args:
        repo_path: Path to the git repository.
        location: "home" or "sibling".
        source_branch: Branch name from source repo, or None if detached.

    Returns:
        Tuple of (worktree_path, branch_name). branch_name is None if detached.

    Raises:
        subprocess.CalledProcessError: If worktree creation fails.
    """
    worktree_dir = get_worktree_path(repo_path, location)

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(worktree_dir), exist_ok=True)

    branch_name = None
    if source_branch:
        # Create derived branch name: {source_branch}-wt-{NN}
        wt_num = get_worktree_number(worktree_dir)
        branch_name = f"{source_branch}-wt-{wt_num}"

        # Check if branch already exists
        check_result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", branch_name],
            capture_output=True,
        )

        if check_result.returncode == 0:
            # Branch exists - create worktree with existing branch
            subprocess.run(
                ["git", "-C", repo_path, "worktree", "add", worktree_dir, branch_name],
                check=True,
                capture_output=True,
            )
        else:
            # Create worktree with new branch
            subprocess.run(
                ["git", "-C", repo_path, "worktree", "add", "-b", branch_name, worktree_dir, "HEAD"],
                check=True,
                capture_output=True,
            )
    else:
        # No source branch (detached HEAD) - create worktree detached at HEAD
        subprocess.run(
            ["git", "-C", repo_path, "worktree", "add", "-d", worktree_dir, "HEAD"],
            check=True,
            capture_output=True,
        )

    if is_debug_enabled():
        if branch_name:
            print(f"[worktree] Created worktree at {worktree_dir} (branch: {branch_name})")
        else:
            print(f"[worktree] Created worktree at {worktree_dir} (detached)")

    return worktree_dir, branch_name


def prepare_reused_worktree(
    worktree_path: str,
    source_branch: str | None = None,
) -> str | None:
    """Prepare a reused worktree, optionally switching to a derived branch.

    When reusing a worktree, if source_branch is provided, this function will:
    1. Create or checkout the derived branch (e.g., feature-x-wt-03)
    2. Reset it to the source branch's current commit

    Args:
        worktree_path: Path to the existing worktree.
        source_branch: Branch name from source repo, or None to stay detached.

    Returns:
        The branch name if on a branch, or None if detached.
    """
    if not source_branch:
        # No source branch - checkout detached at HEAD of main repo
        # First, get the main repo path
        result = subprocess.run(
            ["git", "-C", worktree_path, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            # git-common-dir gives us the .git directory of the main repo
            git_dir = result.stdout.strip()
            # Get HEAD commit from main repo
            head_result = subprocess.run(
                ["git", "--git-dir", git_dir, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            )
            if head_result.returncode == 0:
                commit = head_result.stdout.strip()
                subprocess.run(
                    ["git", "-C", worktree_path, "checkout", "--detach", commit],
                    capture_output=True,
                )
        return None

    # Create derived branch name: {source_branch}-wt-{NN}
    wt_num = get_worktree_number(worktree_path)
    branch_name = f"{source_branch}-wt-{wt_num}"

    # Check if branch already exists
    check_result = subprocess.run(
        ["git", "-C", worktree_path, "rev-parse", "--verify", branch_name],
        capture_output=True,
    )

    if check_result.returncode == 0:
        # Branch exists - checkout and reset to source branch
        subprocess.run(
            ["git", "-C", worktree_path, "checkout", branch_name],
            capture_output=True,
        )
        # Reset to source branch's current commit
        subprocess.run(
            ["git", "-C", worktree_path, "reset", "--hard", source_branch],
            capture_output=True,
        )
    else:
        # Create new branch at source branch's HEAD
        subprocess.run(
            ["git", "-C", worktree_path, "checkout", "-b", branch_name, source_branch],
            capture_output=True,
        )

    if is_debug_enabled():
        print(f"[worktree] Prepared reused worktree on branch: {branch_name}")

    return branch_name


def remove_worktree(worktree_path: str) -> bool:
    """Remove a worktree.

    Args:
        worktree_path: Path to the worktree to remove.

    Returns:
        True if removal succeeded.
    """
    if not os.path.exists(worktree_path):
        return True

    result = subprocess.run(
        ["git", "-C", worktree_path, "worktree", "remove", worktree_path],
        capture_output=True,
    )

    if is_debug_enabled():
        if result.returncode == 0:
            print(f"[worktree] Removed worktree at {worktree_path}")
        else:
            print(f"[worktree] Failed to remove worktree: {result.stderr.decode()}")

    return result.returncode == 0


def cleanup_excess_worktrees(
    repo_path: str,
    active_session_cwds: dict[str, str | None],
    max_worktrees: int = 3,
) -> int:
    """Remove oldest idle worktrees if over the limit.

    Only cleans up worktrees in ~/.cowboy-worktrees/ (home location).
    Sibling worktrees are never automatically cleaned up.
    Removes oldest by modification time (least recently used).

    Args:
        repo_path: Path to the git repository.
        active_session_cwds: Dict mapping session names to their CWDs.
        max_worktrees: Maximum number of idle worktrees to keep in home location.

    Returns:
        Number of worktrees removed.
    """
    worktrees = list_worktrees_for_repo(repo_path)
    cowboy_worktrees_dir = str(get_worktrees_base_dir())

    # Build set of normalized CWDs for quick lookup
    active_cwds = {
        os.path.realpath(cwd) for cwd in active_session_cwds.values() if cwd
    }

    # Filter to managed worktrees (home location only) without active sessions
    idle_worktrees = []
    for wt in worktrees:
        # Only manage worktrees in ~/.cowboy-worktrees/
        if not wt.startswith(cowboy_worktrees_dir):
            continue
        # Check if this worktree has an active tmux session by comparing CWDs
        wt_realpath = os.path.realpath(wt)
        if wt_realpath not in active_cwds:
            try:
                mtime = os.path.getmtime(wt)
                idle_worktrees.append((mtime, wt))
            except OSError:
                continue

    # Sort by mtime (oldest first = smallest mtime) and remove excess
    idle_worktrees.sort()  # Sorts by mtime ascending (oldest first)
    removed = 0
    while len(idle_worktrees) > max_worktrees:
        _, oldest = idle_worktrees.pop(0)  # Remove oldest (first in sorted list)
        if remove_worktree(oldest):
            removed += 1

    return removed


def get_active_session_names() -> set[str]:
    """Get names of all active tmux sessions.

    This is used to determine which worktrees are in use.

    Returns:
        Set of tmux session names.
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return set(result.stdout.strip().split("\n"))
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return set()


def _get_session_cwd(session_name: str) -> str | None:
    """Get the current working directory of a tmux session.

    Args:
        session_name: Name of the tmux session.

    Returns:
        CWD path or None if unavailable.
    """
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-t", session_name, "-p", "#{pane_current_path}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            cwd = result.stdout.strip()
            return cwd if cwd else None
    except subprocess.SubprocessError:
        pass
    return None


def get_active_session_cwds() -> dict[str, str | None]:
    """Get current working directories for all active tmux sessions.

    This is used to determine which worktrees are in use by checking
    actual session CWDs rather than comparing names.

    Returns:
        Dict mapping session name to CWD (or None if unavailable).
    """
    result = {}
    for session_name in get_active_session_names():
        cwd = _get_session_cwd(session_name)
        result[session_name] = cwd
    return result


if __name__ == "__main__":
    # Test the module
    import sys

    test_path = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

    print(f"Testing with path: {test_path}")
    print(f"Is git repo: {is_git_repo(test_path)}")

    if is_git_repo(test_path):
        root = get_repo_root(test_path)
        print(f"Repo root: {root}")
        print(f"Is submodule: {is_submodule(test_path)}")

        if is_submodule(test_path):
            parent = get_parent_repo_root(test_path)
            print(f"Parent repo root: {parent}")

        worktrees = list_worktrees_for_repo(test_path)
        print(f"Existing worktrees: {worktrees}")

        active = get_active_session_names()
        print(f"Active tmux sessions: {active}")
