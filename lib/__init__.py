"""Claude Cowboy library modules."""

from .config import (
    load_config,
    get_anthropic_api_key,
    get_github_token,
    get_claude_home,
    get_cowboy_data_dir,
    is_debug_enabled,
)

from .session_discovery import (
    SessionInfo,
    discover_sessions,
    discover_all_sessions,
    get_session_by_id,
    get_session_by_pid,
)

from .status_analyzer import (
    SessionStatus,
    StatusResult,
    analyze_session_status,
    get_status_emoji,
)

from .session_registry import (
    SessionEntry,
    Registry,
    load_registry,
    save_registry,
    add_session,
    remove_session,
    get_session,
    find_session,
    list_sessions,
    link_sessions_to_jsonl,
)

from .tmux_manager import (
    is_tmux_available,
    get_session_name,
    session_exists,
    create_session,
    ensure_session,
    list_windows,
    create_window,
    send_keys,
    select_window,
    kill_window,
    attach_session,
    capture_pane,
    is_inside_tmux,
)

__all__ = [
    # Config
    "load_config",
    "get_anthropic_api_key",
    "get_github_token",
    "get_claude_home",
    "get_cowboy_data_dir",
    "is_debug_enabled",
    # Session discovery (legacy)
    "SessionInfo",
    "discover_sessions",
    "discover_all_sessions",
    "get_session_by_id",
    "get_session_by_pid",
    # Status analyzer
    "SessionStatus",
    "StatusResult",
    "analyze_session_status",
    "get_status_emoji",
    # Session registry (tmux-based)
    "SessionEntry",
    "Registry",
    "load_registry",
    "save_registry",
    "add_session",
    "remove_session",
    "get_session",
    "find_session",
    "list_sessions",
    "link_sessions_to_jsonl",
    # tmux manager
    "is_tmux_available",
    "get_session_name",
    "session_exists",
    "create_session",
    "ensure_session",
    "list_windows",
    "create_window",
    "send_keys",
    "select_window",
    "kill_window",
    "attach_session",
    "capture_pane",
    "is_inside_tmux",
]
