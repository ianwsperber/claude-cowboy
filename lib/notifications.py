#!/usr/bin/env python3
"""Cross-platform notification sounds for Claude Cowboy.

Adapted from tmux-claude-status by samleeney (MIT License)
https://github.com/samleeney/tmux-claude-status
"""

import shutil
import subprocess
import sys
from pathlib import Path

try:
    from .config import load_config
except ImportError:
    from config import load_config


# Default sound files by platform
MACOS_SOUNDS = [
    "/System/Library/Sounds/Glass.aiff",
    "/System/Library/Sounds/Ping.aiff",
    "/System/Library/Sounds/Pop.aiff",
]

LINUX_SOUNDS = [
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
    "/usr/share/sounds/freedesktop/stereo/message.oga",
    "/usr/share/sounds/alsa/Front_Center.wav",
]


def _find_sound_file(custom_path: str | None = None) -> str | None:
    """Find an available sound file.

    Args:
        custom_path: Optional custom sound file path.

    Returns:
        Path to sound file or None if not found.
    """
    # Check custom path first
    if custom_path and custom_path != "default":
        path = Path(custom_path).expanduser()
        if path.exists():
            return str(path)

    # Try platform-specific defaults
    if sys.platform == "darwin":
        for sound in MACOS_SOUNDS:
            if Path(sound).exists():
                return sound
    else:
        for sound in LINUX_SOUNDS:
            if Path(sound).exists():
                return sound

    return None


def _find_player() -> tuple[str, list[str]] | None:
    """Find an available audio player.

    Returns:
        Tuple of (player_name, command_args) or None if not found.
    """
    if sys.platform == "darwin":
        # macOS: afplay
        if shutil.which("afplay"):
            return ("afplay", ["afplay"])
    else:
        # Linux: try paplay (PulseAudio), then aplay (ALSA)
        if shutil.which("paplay"):
            return ("paplay", ["paplay"])
        if shutil.which("aplay"):
            return ("aplay", ["aplay"])

    return None


def play_notification(config: dict | None = None) -> bool:
    """Play a notification sound.

    Args:
        config: Optional config dict. If not provided, loads from default.

    Returns:
        True if sound was played, False otherwise.
    """
    if config is None:
        config = load_config()

    # Check if notifications are enabled
    if not config.get("enableNotificationSound", True):
        return False

    # Find sound file
    custom_sound = config.get("notificationSound")
    sound_file = _find_sound_file(custom_sound)

    if not sound_file:
        # Fall back to terminal bell
        print("\a", end="", flush=True)
        return True

    # Find player
    player = _find_player()
    if not player:
        # Fall back to terminal bell
        print("\a", end="", flush=True)
        return True

    _, cmd = player

    try:
        # Run player in background (don't block)
        subprocess.Popen(
            cmd + [sound_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        # Fall back to terminal bell
        print("\a", end="", flush=True)
        return True


if __name__ == "__main__":
    print("Testing notification sound...")
    config = load_config()
    print(f"Notifications enabled: {config.get('enableNotificationSound', True)}")
    print(f"Custom sound: {config.get('notificationSound', 'default')}")

    sound_file = _find_sound_file(config.get("notificationSound"))
    print(f"Sound file: {sound_file or 'None (will use terminal bell)'}")

    player = _find_player()
    print(f"Player: {player[0] if player else 'None (will use terminal bell)'}")

    print("\nPlaying notification...")
    result = play_notification(config)
    print(f"Result: {'success' if result else 'failed'}")
