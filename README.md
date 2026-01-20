# Claude Cowboy

> **Note**: This project is experimental and not under active maintenance.
> Use at your own risk. Issues and PRs may not be addressed.

A tmux-based session manager for [Claude Code](https://github.com/anthropics/claude-code). Monitor, manage, and switch between multiple Claude Code sessions from the command line.

https://github.com/user-attachments/assets/1d3d8c32-05aa-4fdb-974a-086897dc9942

## Features

- **Session Browser** - fzf-based browser to view and switch between Claude sessions
- **Hook-based Status** - Real-time status detection via Claude Code hooks (working/done/wait)
- **Wait Mode** - Set timers to be notified when sessions are ready
- **Notification Sounds** - Audio alerts when Claude finishes a task
- **Tmux Integration** - Each session runs in its own tmux window for easy switching
- **Multi-Session Workflow** - Run multiple Claude Code instances across different projects
- **Session Isolation** - Git worktrees for isolated Claude state per session

## Requirements

- Python 3.12+
- [tmux](https://github.com/tmux/tmux)
- [fzf](https://github.com/junegunn/fzf) - Fuzzy finder for session browser
- [Claude Code](https://github.com/anthropics/claude-code)

## Installation

Claude Cowboy has two components that work together:

1. **CLI** (`cowboy` command) - Python package for session management
2. **Plugin** - Claude Code integration for `/sessions`, `/lasso`, `/posse` commands

**Both are required** - the plugin commands call the CLI under the hood.

### Step 1: Install the CLI

Choose one method:

**Using uv (recommended)**
```bash
uv tool install git+https://github.com/ianwsperber/claude-cowboy
```

**Using pipx**
```bash
pipx install git+https://github.com/ianwsperber/claude-cowboy
```

**Using pip**
```bash
pip install --user git+https://github.com/ianwsperber/claude-cowboy
```

> **Note**: The `--user` flag installs to `~/.local/bin`, which should be in your PATH on most systems. If `cowboy` isn't found after installation, see [Troubleshooting](#troubleshooting) below.

**From source**
```bash
git clone https://github.com/ianwsperber/claude-cowboy.git
cd claude-cowboy
uv pip install -e .  # or: pip install -e .
```

### Step 2: Install the Plugin

In Claude Code, run:

```
/plugin marketplace add ianwsperber/claude-cowboy
/plugin install cowboy@claude-cowboy
```

This enables:
- `/sessions` - List all active Claude Code sessions
- `/lasso` - Delegate tasks to new sessions asynchronously
- `/posse` - Coordinate multiple parallel sessions
- Status tracking hooks (working/done/needs attention)

### Verify Installation

```bash
# Check CLI is installed
cowboy --help
```

In Claude Code, verify the plugin is loaded:
```
/sessions
```

## Usage

```bash
# Create a new Claude Code session
cowboy new

# Create an isolated session (git worktree)
cowboy new -w

# Open the dashboard
cowboy dashboard

# List all sessions
cowboy list

# Attach to a session
cowboy attach <session-number>

# Kill a session
cowboy kill <session-number>
```

### Session Isolation

Use `-w` to run sessions in git worktrees, preventing Claude state from bleeding between sessions:

```bash
cowboy new ~/myproject -w                              # ~/.cowboy-worktrees/myproject-01
cowboy new ~/myproject -w --worktree-location sibling  # ~/myproject-01 (adjacent)
cowboy new ~/monorepo/service -w -m                    # Use monorepo root (skip prompt)
```

Idle worktrees are automatically reused. Home location worktrees are cleaned up when exceeding `maxWorktrees` (default: 3).

## Configuration

Settings are stored in `~/.claude/settings.json` under the `claudeCowboy` key:

```json
{
  "claudeCowboy": {
    "sessionDiscoveryHours": 24,
    "idleThresholdMinutes": 5,
    "hideThresholdMinutes": 15
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `sessionDiscoveryHours` | 24 | How far back to look for sessions |
| `idleThresholdMinutes` | 5 | Time before a session is marked idle |
| `hideThresholdMinutes` | 15 | Time before inactive sessions are hidden |
| `maxWorktrees` | 3 | Max idle worktrees before cleanup (home only) |
| `worktreeLocation` | `home` | Default: `home` (~/.cowboy-worktrees) or `sibling` |

## Troubleshooting

### `cowboy: command not found`

If the `cowboy` command isn't found after pip installation, the install location isn't in your PATH.

**Find where it was installed:**
```bash
python -m site --user-base  # Shows ~/.local on most systems
# The executable is in the bin/ subdirectory
```

**Add to PATH** (add to your `~/.bashrc`, `~/.zshrc`, or equivalent):
```bash
export PATH="$HOME/.local/bin:$PATH"
```

**Or reinstall with uv/pipx** (recommended - they handle PATH automatically):
```bash
pip uninstall claude-cowboy
uv tool install git+https://github.com/ianwsperber/claude-cowboy
# or: pipx install git+https://github.com/ianwsperber/claude-cowboy
```

## Acknowledgments

The hook-based status detection, session browser, wait mode, and notification
features are adapted from [tmux-claude-status](https://github.com/samleeney/tmux-claude-status)
by [@samleeney](https://github.com/samleeney), used under the MIT License.

## License

MIT
