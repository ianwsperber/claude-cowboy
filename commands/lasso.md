---
description: "Query another Claude session's context synchronously"
argument-hint: "[@session] <query>"
allowed-tools: Task
---

# Lasso - Cross-Session Context Query

Query another Claude Code session for context or information. Results are returned synchronously via a subagent that loads the target session's full conversation history.

## Arguments

- `@session` (optional): Target session name, prefixed with @
- `<query>`: Your question about that session's work

## Instructions

Use the Task tool to spawn a `claude-cowboy:lasso` subagent with this prompt format:

```
Target session: [SESSION_NAME or "pick from list"]
Query: [USER'S QUESTION]
```

**If a session name was provided** (starts with @):
- Extract the session name (remove the @ prefix)
- Include it in the prompt as the target session

**If no session specified**:
- Set target session to "pick from list"
- The subagent will use `cowboy list` and AskUserQuestion to help the user select

## Examples

```
User: /lasso @example-claude-monorepo Where are the posse sessions you created?
Assistant: [Spawns lasso subagent with prompt: "Target session: example-claude-monorepo\nQuery: Where are the posse sessions you created?"]

User: /lasso What was the last session working on?
Assistant: [Spawns lasso subagent with prompt: "Target session: pick from list\nQuery: What was the last session working on?"]
→ Subagent lists sessions, asks user to pick, then answers the query

User: /lasso @backend-work What API endpoints did you implement?
Assistant: [Spawns lasso subagent targeting backend-work session]
```

## Notes

- The subagent loads the target session's **full conversation transcript**
- Results are returned inline (synchronous, not async notifications)
- Multiple /lasso commands can run in parallel via Task tool
- The subagent can explore the codebase if needed to answer the query
- For advanced use cases, the subagent can search tmux sessions or old JSONL files