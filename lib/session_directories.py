#!/usr/bin/env python3
"""Session directories helper for Claude Cowboy.

Provides list of unique directories from recent Claude sessions
for the new session directory picker.
"""

import os

try:
    from .session_discovery import discover_all_sessions
except ImportError:
    from session_discovery import discover_all_sessions


def get_unique_directories() -> list[str]:
    """Get unique directories from recent Claude sessions.

    Returns:
        List of unique CWDs that still exist, sorted alphabetically (case-insensitive).
    """
    sessions = discover_all_sessions()
    cwds = set(s.cwd for s in sessions if s.cwd and os.path.isdir(s.cwd))
    return sorted(cwds, key=str.lower)


def shorten_path(path: str) -> str:
    """Shorten a path for display by replacing home with ~.

    Args:
        path: Full path to shorten.

    Returns:
        Shortened path with ~ for home directory.
    """
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def main():
    """Print unique directories for use by shell scripts."""
    directories = get_unique_directories()
    for d in directories:
        print(shorten_path(d))


if __name__ == "__main__":
    main()
