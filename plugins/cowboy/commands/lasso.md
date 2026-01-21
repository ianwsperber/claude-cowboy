---
description: "Query another Claude session's context synchronously"
argument-hint: "[@session] <query>"
allowed-tools: Bash(cowboy:*), AskUserQuestion
---

# Lasso - Synchronous Session Query

Query another Claude Code session for context or information. The target session is resumed with a headless prompt, and results are returned synchronously.

## Arguments

- `@session` (optional): Target session name or UUID, prefixed with @
- `<query>`: Your question or task for that session

## Instructions

### 1. Parse Arguments

Extract from the user's input:
- **Target**: If the input starts with `@`, extract the session name (without the `@`)
- **Query**: The remaining text is the query

### 2. Session Discovery (if no target specified)

If no `@session` was provided, help the user select a session:

```bash
cowboy list --json
```

Use **AskUserQuestion** to present the available sessions and let the user pick one:
- Show session name, status, and CWD for each
- Filter out the current session (don't lasso yourself)

### 3. Execute the Lasso

Run the synchronous lasso command:

```bash
cowboy lasso <target> "<query>"
```

**Examples:**
```bash
# Query a specific session
cowboy lasso my-backend-work "What files did you modify?"

# Query by UUID
cowboy lasso abc123-def456 "Summarize your changes"
```

### 4. Return the Response

The command will:
1. Wait for the target session to become idle (if busy)
2. Resume the session with the query
3. Return the response

Display the response to the user.

## Clean Mode

For querying without resuming an existing session (starts fresh):

```bash
cowboy lasso --clean --cwd /path/to/project "Review the codebase"
```

## Examples

```
User: /lasso @backend-work What API endpoints did you implement?
Assistant: [Runs: cowboy lasso backend-work "What API endpoints did you implement?"]
Response: "I implemented 3 endpoints: /api/users, /api/auth/login, and /api/auth/logout..."

User: /lasso What was the last thing you did?
Assistant: [Runs: cowboy list --json]
         [AskUserQuestion to select session]
         [Runs: cowboy lasso <selected> "What was the last thing you did?"]
Response: "I was working on the authentication module..."
```

## Notes

- The target session is **resumed** with your query - it has full context of its prior work
- If the target is busy, lasso waits for it to become idle (up to 8 minutes by default)
- Use `--timeout N` to set a custom timeout in minutes
- For async task delegation, use: `cowboy lasso --async "task description"`
