---
description: "List all active Claude Code sessions with status"
argument-hint: "[--json] [--all] [--full-paths]"
allowed-tools: ["Bash(cowboy:*)"]
---

# List Active Claude Code Sessions

Display a table of all tmux sessions running Claude Code with their current status.

## Arguments

- `--json`: Output in JSON format for programmatic use
- `--all`: Show all tmux sessions, not just those running Claude
- `--full-paths`: Show full paths instead of shortened versions

## Instructions

Run the cowboy list command to display active sessions:

```bash
cowboy list $ARGUMENTS
```

Display the output to the user exactly as returned by the command.

## Status Legend

- **working**: Claude is actively processing input or executing tools
- **ATTENTION**: Claude asked a question and is waiting for user response
- **done**: Claude has finished and is waiting for user input
- **wait**: User set a wait timer on this session

## Example Output

```
$ /sessions
Session              Status         Branch          CWD                            Attached
--------------------------------------------------------------------------------------------
my-project           * working      main            ~/Code/my-project
claude-cowboy        ! ATTENTION    feature-x       ~/.cowboy-worktrees/...        (attached)
api-server             done         develop         ~/Code/api-server

3 Claude session(s)
```

```
$ /sessions --all
Session              Status         Branch          CWD                            Attached
--------------------------------------------------------------------------------------------
my-project           * working      main            ~/Code/my-project
claude-cowboy        ! ATTENTION    feature-x       ~/.cowboy-worktrees/...        (attached)
api-server             done         develop         ~/Code/api-server
random-tmux          (no claude)    -               ~/

3 Claude session(s), 1 other tmux session(s)
```

## Notes

- Sessions are identified by their tmux session name
- The dashboard (`cowboy dash`) shows the same sessions
- Use `cowboy dash` for an interactive fzf-based browser
