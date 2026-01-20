# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2025-01-17

### Added

- Initial release of Claude Cowboy
- Session browser with fzf integration for managing multiple Claude Code sessions
- Hook-based status detection (Working, Done, Wait, Needs Attention)
- Wait mode for setting session timers
- Notification sounds when Claude finishes tasks
- Tmux integration for session management
- Git worktree support for session isolation
- Multi-session workflow support
- Dashboard view with real-time status updates
- CLI commands: `new`, `list`, `attach`, `kill`, `cleanup`, `dashboard`
- Configuration via `~/.claude/settings.json`
- Support for both CLI and IDE (VS Code) sessions

### Credits

- Status detection approach adapted from [tmux-claude-status](https://github.com/samleeney/tmux-claude-status) by @samleeney (MIT License)
