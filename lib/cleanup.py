#!/usr/bin/env python3
"""Unified cleanup module for Claude Cowboy.

Consolidates all cleanup logic in one place. Can be invoked:
- Automatically (async) when the dashboard opens
- Manually (sync) via `cowboy cleanup`

Cleans up:
1. Stale orchestration children (tmux sessions that no longer exist)
2. Excess worktrees (LRU eviction for home location)
3. Stale session registry entries (tmux windows that no longer exist)
"""

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import tmux_manager as tmux
    from . import session_registry as registry
    from . import git_worktree as worktree
    from . import orchestration
    from .config import load_config, is_debug_enabled
except ImportError:
    import tmux_manager as tmux
    import session_registry as registry
    import git_worktree as worktree
    import orchestration
    from config import load_config, is_debug_enabled


def run_all_cleanup(async_mode: bool = True) -> dict:
    """Run all cleanup tasks.

    Args:
        async_mode: If True, spawns a background process and returns immediately.
                    If False, runs synchronously and returns results.

    Returns:
        If sync: dict with cleanup results
        If async: empty dict (results not available, runs in background)
    """
    if async_mode:
        # Spawn background process running this module with --run flag
        subprocess.Popen(
            [sys.executable, __file__, "--run"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent process group
        )
        return {}
    else:
        return _run_cleanup_sync()


def _run_cleanup_sync() -> dict:
    """Run all cleanup tasks synchronously.

    Returns:
        Dict with counts of removed items.
    """
    results = {
        "orchestrations_removed": cleanup_stale_orchestrations(),
        "worktrees_removed": cleanup_stale_worktrees(),
        "registry_entries_removed": cleanup_stale_registry(),
    }
    return results


def cleanup_stale_orchestrations() -> int:
    """Remove orchestration children whose tmux sessions don't exist.

    For each active orchestration:
    - Removes children whose tmux_session no longer exists
    - Marks orchestration as "completed" if all children are gone

    Returns:
        Number of child entries removed.
    """
    removed = 0

    try:
        # Get all existing tmux session names
        all_tmux_sessions = tmux.list_all_sessions()
        existing_sessions = {s.name for s in all_tmux_sessions}

        # Load orchestration registry
        orch_registry = orchestration.load_orchestrations()

        modified = False

        for orch_id, orch in list(orch_registry.orchestrations.items()):
            if orch.status != "active":
                continue

            # Filter children to only those with existing tmux sessions
            original_count = len(orch.children)
            valid_children = [
                child for child in orch.children
                if child.tmux_session in existing_sessions
            ]

            children_removed = original_count - len(valid_children)
            if children_removed > 0:
                removed += children_removed
                orch.children = valid_children
                modified = True

                if is_debug_enabled():
                    print(f"[cleanup] Removed {children_removed} stale children from {orch_id}")

            # If all children are gone, mark orchestration as completed
            if len(valid_children) == 0 and original_count > 0:
                orch.status = "completed"
                orch.completed_at = datetime.now(timezone.utc).isoformat()

                if is_debug_enabled():
                    print(f"[cleanup] Marked orchestration {orch_id} as completed (no children)")

        if modified:
            orchestration.save_orchestrations(orch_registry)

    except Exception as e:
        if is_debug_enabled():
            print(f"[cleanup] Error cleaning orchestrations: {e}")

    return removed


def cleanup_stale_worktrees() -> int:
    """Clean up excess worktrees using LRU eviction.

    Finds all repos with worktrees in ~/.cowboy-worktrees/ and runs
    cleanup for each, respecting the maxWorktrees config.

    Returns:
        Number of worktrees removed.
    """
    removed = 0

    try:
        worktrees_base = worktree.get_worktrees_base_dir()
        if not worktrees_base.exists():
            return 0

        # Get active session CWDs to avoid cleaning active worktrees
        active_cwds = {
            os.path.realpath(cwd) for cwd in worktree.get_active_session_cwds().values() if cwd
        }

        # Load config for max worktrees
        config = load_config()
        max_wt = config.get("maxWorktrees", 3)

        # Find all worktree directories in ~/.cowboy-worktrees/
        # Group by repo name (prefix before the -NN suffix)
        repo_worktrees: dict[str, list[str]] = {}

        for item in worktrees_base.iterdir():
            if not item.is_dir():
                continue

            # Parse repo name from worktree name (e.g., "myrepo-01" -> "myrepo")
            name = item.name
            # Find the last dash followed by digits
            parts = name.rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit():
                repo_name = parts[0]
            else:
                repo_name = name

            if repo_name not in repo_worktrees:
                repo_worktrees[repo_name] = []
            repo_worktrees[repo_name].append(str(item))

        # For each repo, clean excess idle worktrees
        for repo_name, wt_paths in repo_worktrees.items():
            # Sort by modification time (oldest first)
            wt_with_mtime = []
            for wt_path in wt_paths:
                # Skip if this worktree has an active session (compare by CWD)
                wt_realpath = os.path.realpath(wt_path)
                if wt_realpath in active_cwds:
                    continue
                try:
                    mtime = os.path.getmtime(wt_path)
                    wt_with_mtime.append((mtime, wt_path))
                except OSError:
                    continue

            wt_with_mtime.sort()  # Oldest first

            # Remove excess (keep max_wt idle worktrees per repo)
            while len(wt_with_mtime) > max_wt:
                _, oldest_path = wt_with_mtime.pop(0)
                if worktree.remove_worktree(oldest_path):
                    removed += 1
                    if is_debug_enabled():
                        print(f"[cleanup] Removed worktree: {oldest_path}")

    except Exception as e:
        if is_debug_enabled():
            print(f"[cleanup] Error cleaning worktrees: {e}")

    return removed


def cleanup_stale_registry() -> int:
    """Remove registry entries for non-existent tmux windows.

    Returns:
        Number of registry entries removed.
    """
    removed = 0

    try:
        # Get all existing tmux windows in the cowboy session
        windows = tmux.list_windows()
        valid_names = {w.name for w in windows}

        # Use the registry's cleanup function
        removed = registry.cleanup_stale_sessions(valid_names)

        if is_debug_enabled() and removed > 0:
            print(f"[cleanup] Removed {removed} stale registry entries")

    except Exception as e:
        if is_debug_enabled():
            print(f"[cleanup] Error cleaning registry: {e}")

    return removed


if __name__ == "__main__":
    # When run directly with --run, execute cleanup synchronously
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Run cleanup")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    if args.run:
        results = _run_cleanup_sync()
        if args.verbose:
            print(f"Cleanup complete: {results}")
    else:
        # Print help if called without --run
        parser.print_help()
