# Claude Cowboy - Development Guidelines

## Project Overview

Claude Cowboy is a Claude Code plugin that monitors and displays all active Claude Code sessions. It provides visibility into session status, working directories, and activity across multiple concurrent sessions.

## Architecture

```
claude-cowboy/
├── .claude-plugin/
│   └── plugin.json          # Plugin manifest
├── commands/
│   ├── sessions.md          # /sessions command definition
│   ├── lasso.md             # /lasso synchronous session query
│   ├── posse.md             # /posse multi-session orchestration
│   └── deputized.md         # Child session bootstrapping
├── skills/
│   └── lassoed.md           # Handler for incoming lasso queries
├── hooks/
│   └── status-hook.sh       # Claude Code hook for status tracking
├── lib/
│   ├── __init__.py          # Package exports
│   ├── config.py            # Configuration loader
│   ├── cleanup.py           # Unified cleanup module
│   ├── session_discovery.py # Session-ID centric discovery
│   ├── status_analyzer.py   # Hook-based status detection
│   ├── session_browser.py   # fzf-based session browser
│   ├── wait_mode.py         # Wait timer management
│   ├── notifications.py     # Cross-platform notification sounds
│   ├── status_line.py       # tmux status bar output
│   ├── sessions_cli.py      # CLI output formatting
│   ├── orchestration.py     # Parent-child session coordination
│   └── cowboy_cli.py        # Main CLI entry point
└── .thoughts/
    └── PLAN.md              # Detailed implementation plan
```

## Key Concepts

### Session-ID Centric Approach

Sessions are identified by UUID (from JSONL filenames), not by PID. This allows:

- Multiple sessions per directory
- IDE sessions (VS Code) detection
- Proper tracking even when process can't be found

### Status Detection

Status is determined via Claude Code's hook system. This approach is adapted from
[tmux-claude-status](https://github.com/samleeney/tmux-claude-status) by @samleeney (MIT License).

**How it works:**
1. Claude Code fires hooks on events: `PreToolUse`, `Stop`, `Notification`
2. Our hook script (`hooks/status-hook.sh`) writes status to files
3. Status files are stored at `~/.claude/cowboy/status/{session-id}.status`

**Hook events:**
- `PreToolUse` → writes "working" (Claude is processing), or "needs_attention" if using AskUserQuestion or permission_mode=ask
- `Stop` → writes "done" (Claude has finished)
- `Notification` → ignored (fires for completion alerts, not reliable for status)

**Display statuses:**

| Display Status    | Condition                                              |
| ----------------- | ------------------------------------------------------ |
| `Needs Attention` | Hook wrote "needs_attention" (AskUserQuestion/permission) |
| `Working`         | Hook wrote "working" (Claude is processing)            |
| `Done`            | Hook wrote "done" (Claude finished)                    |
| `Wait (Nm)`       | User set wait timer, N minutes remaining               |
| `Unknown`         | No status file found                                   |

**Wait mode:**
Users can set a wait timer on a session. The timer file is stored at
`~/.claude/cowboy/wait/{session-id}.wait` containing a Unix timestamp.
When the timer expires, the session status becomes "done".

### Git Branch Display

The dashboard shows the current git branch for each session with worktree detection:
- Regular repos show the branch name (e.g., `main`)
- Git worktrees show branch with indicator (e.g., `feature-x (wt)`)
- Git info is cached for 30 seconds to minimize subprocess overhead

### Session Isolation (Worktrees)

Multiple Claude sessions in the same directory share `~/.claude/projects/{path}/` state. Use git worktrees for isolation:

```bash
cowboy new ~/myproject -w                              # Isolated session
cowboy new ~/myproject -w --worktree-location sibling  # Adjacent directory
```

- `-w` creates/reuses a git worktree, giving Claude a separate CWD
- Idle worktrees are reused; home location auto-cleans when exceeding `maxWorktrees`
- Sibling worktrees persist (never auto-cleaned)
- Submodules prompt for monorepo worktree; use `-m` to skip

### Automatic Cleanup

Cleanup runs automatically in the background when the dashboard opens:

1. **Stale orchestrations** - Removes child entries for tmux sessions that no longer exist
2. **Excess worktrees** - LRU eviction of worktrees exceeding `maxWorktrees` (default: 3)
3. **Stale registry** - Removes session registry entries for non-existent tmux windows

Manual cleanup: `cowboy cleanup`

Cleanup is async and non-blocking - the dashboard opens immediately while cleanup runs in the background.

### Cross-Session Communication (/lasso)

The `/lasso` command enables synchronous querying of other Claude sessions. It resumes
the target session with a headless prompt and returns the response.

**How it works:**

1. Parent session runs `/lasso @target-session "What files did you modify?"`
2. CLI resolves target to session UUID and CWD
3. CLI waits for target session to become idle (if busy)
4. CLI runs `claude --resume <uuid> -p "/lassoed ..."` to query the target
5. Target session answers using its full context
6. Response is returned synchronously to the parent

**Usage:**
```bash
# Query a specific session
/lasso @backend-work What API endpoints did you implement?

# Query with session discovery (prompts for selection)
/lasso What was the last thing you did?

# Clean mode (new session, no resume)
cowboy lasso --clean --cwd /project "Review the codebase"
```

### Orchestration (/posse)

The `/posse` command enables coordination of multiple parallel Claude sessions.

| Command  | Purpose                              | Child Count |
| -------- | ------------------------------------ | ----------- |
| `/posse` | Coordinate parallel workstreams      | 2-4         |

**How it works:**

1. Parent session runs `/posse <objective>`
2. Parent calls `cowboy posse` CLI command
3. CLI creates orchestration entry in `~/.claude/cowboy/orchestration.json`
4. CLI writes task file(s) to `~/.claude/cowboy/tasks/{child-name}.task.json`
5. CLI spawns tmux session(s) and starts Claude with `/claude-cowboy:deputized`
6. Child reads its task file and executes the assigned work
7. Parent is notified when children complete (via hooks)

**Task file structure:**
```json
{
  "orchestration_id": "posse-abc123",
  "orchestration_type": "posse",
  "parent_session_id": "uuid",
  "parent_tmux_session": "parent-session-name",
  "role": "backend",
  "task": "Implement the auth API endpoints",
  "siblings": [{"role": "frontend", "name": "tech123-frontend"}],
  "context": {}
}
```

**Plan handoff (for /posse):**

To avoid shell escaping issues with complex plans, `/posse` writes the plan JSON
to a temporary file and passes the file path:

```bash
# Claude writes plan to file using Write tool
/tmp/posse-plan-{timestamp}.json

# Then calls cowboy with file path
cowboy posse --plan-file /tmp/posse-plan-{timestamp}.json
```

**Child session bootstrapping:**

Children are started in **interactive mode** (not headless) with an initial prompt:

```bash
claude --plugin-dir /path/to/plugin -- "/claude-cowboy:deputized /path/to/task.json"
```

The `--` flag starts an interactive session with an initial prompt (vs `-p` which
is headless). This allows users to interact with child sessions if needed.

**Dashboard integration:**

Orchestrated children show `(*)` indicator under their parent in the dashboard.
Completed children remain visible until the orchestration is marked complete.

### Visibility Rules (Hybrid PID + Recency)

- **Has PID** → Always show
- **No PID, < 15 min activity** → Show
- **No PID, > 15 min activity** → Hidden (use `--all`)

## Configuration

Settings in `~/.claude/settings.json` under `claudeCowboy`:

```json
{
  "claudeCowboy": {
    "sessionDiscoveryHours": 24,
    "hideThresholdMinutes": 15,
    "enableNotificationSound": true,
    "showPreview": true
  }
}
```

| Setting                   | Default | Description                                      |
| ------------------------- | ------- | ------------------------------------------------ |
| `sessionDiscoveryHours`   | 24      | How far back to scan for JSONL files             |
| `hideThresholdMinutes`    | 15      | Minutes before hiding sessions without PID       |
| `enableNotificationSound` | true    | Play sound when Claude finishes                  |
| `showPreview`             | true    | Show pane preview in session browser             |
| `maxWorktrees`            | 3       | Max idle worktrees before cleanup (home only)    |
| `worktreeLocation`        | home    | Default location: `home` or `sibling`            |
| `lassoTimeoutMinutes`     | 8       | Max time to wait for target session to become idle |
| `lassoPollIntervalSeconds`| 2       | Initial polling interval when waiting            |
| `lassoMaxPollIntervalSeconds`| 10   | Max polling interval (exponential backoff cap)   |

## Testing

Run the sessions CLI directly:

```bash
python3 lib/sessions_cli.py
python3 lib/sessions_cli.py --json
python3 lib/sessions_cli.py --all
```

## CLI Commands

The `cowboy` CLI provides session management:

| Command            | Alias | Description                              |
| ------------------ | ----- | ---------------------------------------- |
| `cowboy new`       |       | Create a new Claude session              |
| `cowboy dashboard` | dash  | Open the fzf-based session browser       |
| `cowboy list`      | ls    | List all sessions                        |
| `cowboy attach`    | a     | Attach to a session                      |
| `cowboy kill`      | k     | Kill a session                           |
| `cowboy cleanup`   |       | Clean up stale data (orchestrations, worktrees, registry) |
| `cowboy tmux`      | t     | Attach to the cowboy tmux session        |
| `cowboy lasso`     |       | Query another session synchronously      |
| `cowboy posse`     |       | Coordinate multiple sessions (parallel)  |
| `cowboy doctor`    |       | Check system dependencies                |

**Key flags:**

```bash
cowboy new ~/project -w              # Use worktree for isolation
cowboy new ~/project --name myname   # Custom session name
cowboy lasso my-session "query"      # Query another session
cowboy lasso --clean --cwd /path "q" # Query in new session
cowboy posse --plan-file plan.json   # Start posse from plan file
```

## Data Sources

| Source             | Location                                          | Purpose                    |
| ------------------ | ------------------------------------------------- | -------------------------- |
| Session JSONL      | `~/.claude/projects/{path}/{session-id}.jsonl`    | Primary session data       |
| IDE locks          | `~/.claude/ide/*.lock`                            | VS Code session PIDs       |
| Processes          | `ps aux \| grep claude`                           | Running CLI PIDs           |
| Status files       | `~/.claude/cowboy/status/{session-id}.status`     | Hook-based status tracking |
| Wait timers        | `~/.claude/cowboy/wait/{session-id}.wait`         | User-set wait timers       |
| Orchestration      | `~/.claude/cowboy/orchestration.json`             | Parent-child relationships |
| Task files         | `~/.claude/cowboy/tasks/{child-name}.task.json`   | Child session assignments  |
| Result files       | `~/.claude/cowboy/results/{child-name}.result.json`| Completed child summaries |
| Messages           | `~/.claude/cowboy/messages/{session-id}/inbox/`   | Inter-session messaging    |

## Implementation Notes

### Plugin File Formats

**Agent files** (`agents/*.md`) must follow this exact frontmatter format:

```yaml
---
name: agent-name
description: Description without quotes
model: sonnet
tools: Tool1, Tool2, Bash(pattern:*)
color: yellow
---
```

Key requirements:
- `name:` field is **required** (filename without extension)
- `tools:` must be **comma-separated**, not a JSON array
- `description:` should not have quotes
- Invalid agent format will break the **entire plugin** from loading

**Command files** (`commands/*.md`) frontmatter:

```yaml
---
description: "Description with quotes is fine"
argument-hint: "<args>"
allowed-tools: Tool1, Tool2, Bash(pattern:*)
---
```

Key requirements:
- `allowed-tools:` should be comma-separated or single tool name
- Do not use `Tool(subagent:type)` syntax - just use `Tool`

**Plugin manifest** (`.claude-plugin/plugin.json`) should be minimal:

```json
{
  "name": "plugin-name",
  "description": "...",
  "author": {"name": "..."}
}
```

Commands, agents, skills, and hooks are **auto-discovered** from their directories.
Do not explicitly list them in plugin.json.

### Filtering Subagents

Sessions starting with `agent-` are subagent sessions and are filtered out. Only top-level sessions are shown.

### PID Assignment

When multiple sessions exist for the same CWD:

1. PIDs are stored as `dict[str, list[int]]` (CWD → list of PIDs)
2. Sessions are sorted by last activity (most recent first)
3. Each PID is assigned to at most one session (most recent gets priority)
4. Parent directory matching: if session CWD is under a process CWD, they match

### Warmup Messages

Messages with `isSidechain: true` or content "Warmup" are background initialization messages and are ignored when determining session status.

## Future Work

See `.thoughts/PLAN.md` for:

- Conversation summaries (using Haiku)
- PR feedback monitoring
- Enhanced cross-session messaging (beyond current orchestration)
