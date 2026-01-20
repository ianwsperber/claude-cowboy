#!/usr/bin/env python3
"""Configuration loader for Claude Cowboy plugin.

Loads settings from:
1. Default values
2. ~/.claude/settings.json (claudeCowboy namespace)
3. {project}/.claude/settings.json (claudeCowboy namespace)
4. Environment variables (highest precedence)
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "summaryModel": "haiku",
    "sessionDiscoveryHours": 24,  # How far back to scan for JSONL files
    "idleThresholdMinutes": 5,  # When to mark session as idle (with PID)
    "inactiveThresholdMinutes": 5,  # When to mark as inactive (no PID)
    "hideThresholdMinutes": 15,  # When to hide sessions without PID
    "waitingThresholdMinutes": 10,  # When "Waiting" becomes "Idle" in display
    "prPollingIntervalMinutes": 5,
    "notificationMethod": "both",  # "hook", "file", or "both"
    "prFeedbackAction": "ask",  # "inject", "spawn", or "ask"
    "enablePrMonitoring": True,
    "maxSummaryLength": 100,
    # tmux-based session management
    "tmuxSessionName": "cowboy",  # Name of the tmux session
    "dashboardRefreshSeconds": 1,  # Dashboard auto-refresh interval
    "dashboardRestartDelay": 2,  # Seconds between dashboard restart attempts
    "statusBarShowDashboardHint": True,  # Show [0:Dash] in status bar
    "autoCloseOnExit": False,  # Auto-close window when Claude exits
    # Hook-based status detection (adapted from tmux-claude-status)
    "enableNotificationSound": True,  # Play sound when Claude finishes
    "notificationSound": "default",  # "default" or path to custom sound file
    # Session browser settings
    "browserHeight": "70%",  # fzf popup height
    "browserWidth": "80%",  # fzf popup width
    "showPreview": True,  # Show pane preview in browser
    # SSH monitoring (optional)
    "sshHosts": [],  # List of SSH hosts to poll for status
    "sshPollIntervalSeconds": 60,  # How often to poll SSH hosts
    # Git worktree settings for session isolation
    "maxWorktrees": 3,  # Max permanent worktrees per repo (oldest idle ones are cleaned up)
    "worktreeLocation": "home",  # "home" for ~/.cowboy-worktrees/, "sibling" for adjacent dirs
    # Status detection patterns (for tmux pane content matching)
    # These are brittle and may need updating if Claude Code UI changes
    "statusPatterns": {
        "planMode": "plan mode on",
        "waitingForInput": "Do you want to proceed?",
    },
}


def load_config(project_path: str | None = None) -> dict[str, Any]:
    """Load configuration with cascading precedence.

    Args:
        project_path: Optional project directory for project-level overrides.

    Returns:
        Merged configuration dictionary.
    """
    config = DEFAULT_CONFIG.copy()

    # Load global settings from ~/.claude/settings.json
    global_settings_path = Path.home() / ".claude" / "settings.json"
    if global_settings_path.exists():
        try:
            with open(global_settings_path) as f:
                settings = json.load(f)
                if "claudeCowboy" in settings:
                    config.update(settings["claudeCowboy"])
        except (json.JSONDecodeError, OSError) as e:
            if os.environ.get("CLAUDE_COWBOY_DEBUG"):
                print(f"Warning: Failed to load global settings: {e}")

    # Load project-level overrides if project_path provided
    if project_path:
        project_settings_path = Path(project_path) / ".claude" / "settings.json"
        if project_settings_path.exists():
            try:
                with open(project_settings_path) as f:
                    settings = json.load(f)
                    if "claudeCowboy" in settings:
                        config.update(settings["claudeCowboy"])
            except (json.JSONDecodeError, OSError) as e:
                if os.environ.get("CLAUDE_COWBOY_DEBUG"):
                    print(f"Warning: Failed to load project settings: {e}")

    # Environment variable overrides
    env_mappings = {
        "CLAUDE_COWBOY_SUMMARY_MODEL": ("summaryModel", str),
        "CLAUDE_COWBOY_DISCOVERY_HOURS": ("sessionDiscoveryHours", int),
        "CLAUDE_COWBOY_IDLE_THRESHOLD": ("idleThresholdMinutes", int),
        "CLAUDE_COWBOY_INACTIVE_THRESHOLD": ("inactiveThresholdMinutes", int),
        "CLAUDE_COWBOY_HIDE_THRESHOLD": ("hideThresholdMinutes", int),
        "CLAUDE_COWBOY_WAITING_THRESHOLD": ("waitingThresholdMinutes", int),
        "CLAUDE_COWBOY_PR_INTERVAL": ("prPollingIntervalMinutes", int),
        "CLAUDE_COWBOY_NOTIFICATION_METHOD": ("notificationMethod", str),
        "CLAUDE_COWBOY_PR_ACTION": ("prFeedbackAction", str),
        "CLAUDE_COWBOY_PR_MONITORING": ("enablePrMonitoring", lambda x: x.lower() == "true"),
        "CLAUDE_COWBOY_MAX_SUMMARY_LENGTH": ("maxSummaryLength", int),
        "CLAUDE_COWBOY_TMUX_SESSION": ("tmuxSessionName", str),
        "CLAUDE_COWBOY_DASHBOARD_REFRESH": ("dashboardRefreshSeconds", int),
        "CLAUDE_COWBOY_AUTO_CLOSE": ("autoCloseOnExit", lambda x: x.lower() == "true"),
        # New hook-based settings
        "CLAUDE_COWBOY_NOTIFICATION_SOUND": ("enableNotificationSound", lambda x: x.lower() == "true"),
        "CLAUDE_COWBOY_SHOW_PREVIEW": ("showPreview", lambda x: x.lower() == "true"),
        "CLAUDE_COWBOY_SSH_POLL_INTERVAL": ("sshPollIntervalSeconds", int),
        # Worktree settings
        "CLAUDE_COWBOY_MAX_WORKTREES": ("maxWorktrees", int),
        "CLAUDE_COWBOY_WORKTREE_LOCATION": ("worktreeLocation", str),
    }

    for env_var, (config_key, converter) in env_mappings.items():
        if env_var in os.environ:
            try:
                config[config_key] = converter(os.environ[env_var])
            except (ValueError, TypeError) as e:
                if os.environ.get("CLAUDE_COWBOY_DEBUG"):
                    print(f"Warning: Invalid value for {env_var}: {e}")

    return config


def get_anthropic_api_key() -> str | None:
    """Get Anthropic API key from environment.

    Returns:
        API key string or None if not found.
    """
    return os.environ.get("ANTHROPIC_API_KEY")


def get_github_token() -> str | None:
    """Get GitHub token, falling back to gh CLI if not set.

    Returns:
        GitHub token string or None if not available.
    """
    # Check environment first
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token

    # Try to get from gh CLI
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return None


def get_claude_home() -> Path:
    """Get the Claude home directory path.

    Returns:
        Path to ~/.claude directory.
    """
    return Path.home() / ".claude"


def get_cowboy_data_dir() -> Path:
    """Get the Claude Cowboy data directory, creating if needed.

    Returns:
        Path to ~/.claude/cowboy directory.
    """
    data_dir = get_claude_home() / "cowboy"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def is_debug_enabled() -> bool:
    """Check if debug mode is enabled.

    Returns:
        True if CLAUDE_COWBOY_DEBUG is set to a truthy value.
    """
    debug = os.environ.get("CLAUDE_COWBOY_DEBUG", "").lower()
    return debug in ("1", "true", "yes", "on")


if __name__ == "__main__":
    # Test the configuration loader
    config = load_config()
    print("Current configuration:")
    for key, value in config.items():
        print(f"  {key}: {value}")

    print(f"\nAnthropic API key: {'set' if get_anthropic_api_key() else 'not set'}")
    print(f"GitHub token: {'set' if get_github_token() else 'not set'}")
    print(f"Claude home: {get_claude_home()}")
    print(f"Cowboy data dir: {get_cowboy_data_dir()}")
    print(f"Debug enabled: {is_debug_enabled()}")
