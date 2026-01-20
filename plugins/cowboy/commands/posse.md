---
description: "Coordinate work across multiple Claude sessions synchronously"
argument-hint: "<objective>"
allowed-tools: ["Bash(cowboy:*)", "Write", "AskUserQuestion"]
---

# Posse - Synchronized Multi-Session Orchestration

Act as a product owner or engineering manager, coordinating work across multiple Claude Code sessions. Create a plan, spawn child sessions to execute it in parallel, then idle until they complete or need help.

## Arguments

- `<objective>`: The overall goal to accomplish (everything after /posse)

## Instructions

### Step 1: Analyze the objective

First, understand the objective provided. Consider:
- What distinct workstreams can be parallelized?
- What are the dependencies between tasks?
- How should work be divided (2-4 workstreams is ideal)?

### Step 2: Present plan to user for approval

Before spawning any sessions, present your plan clearly:

```
**Posse Plan for: [objective summary]**

I propose splitting this into N parallel workstreams:

1. **[Role 1]** (Session: [session-name-1])
   - [Task description]
   - [Expected deliverables]

2. **[Role 2]** (Session: [session-name-2])
   - [Task description]
   - [Expected deliverables]

Dependencies: [Note any dependencies, e.g., "Role 2 needs API from Role 1"]

Proceed with this plan? [Y/n/modify]
```

Wait for user confirmation before proceeding. Use AskUserQuestion if you need to clarify the approach.

### Step 3: Execute the plan

Once approved, write the plan to a file and call cowboy posse with the file path:

**Step 3a:** Write the plan JSON to a temporary file using the Write tool:

Write to `/tmp/posse-plan-{timestamp}.json` with content:
```json
{
  "summary": "OBJECTIVE_SUMMARY",
  "workstreams": [
    {"role": "ROLE1", "name": "SESSION_NAME1", "task": "DETAILED_TASK_DESCRIPTION_1"},
    {"role": "ROLE2", "name": "SESSION_NAME2", "task": "DETAILED_TASK_DESCRIPTION_2"}
  ]
}
```

Use `date +%s` or similar to generate a unique timestamp for the filename.

**Step 3b:** Call cowboy posse with the file path:

```bash
cowboy posse --plan-file /tmp/posse-plan-{timestamp}.json
```

If the user requested worktrees or tasks might conflict, add the `-w` flag:

```bash
cowboy posse -w --plan-file /tmp/posse-plan-{timestamp}.json
```

The command handles everything:
- Creates orchestration entry
- Spawns all child tmux sessions
- Starts Claude in each with their task
- Sets up completion notifications

### Step 4: Idle

After the command completes, display the output and idle. The hooks system will wake you when:
- A child completes (triggering review)
- All children complete (triggering summary)
- A child requests help (triggering coordination)

## Example Usage

```
User: /posse Let's tackle TECH-123, splitting frontend and backend work
Assistant: **Posse Plan for: TECH-123**

I propose splitting this into 2 parallel workstreams:

1. **Frontend** (Session: tech123-frontend)
   - Implement login form UI
   - Add form validation
   - Connect to auth API

2. **Backend** (Session: tech123-backend)
   - Create /auth/login endpoint
   - Add JWT token generation
   - Write auth middleware

Dependencies: Frontend can mock API initially; will integrate when backend ready.

Proceed with this plan?

User: Yes

[Claude writes plan to /tmp/posse-plan-1737150000.json, then runs: cowboy posse --plan-file /tmp/posse-plan-1737150000.json]
```

## Notes

- Parent session idles after spawning to avoid token usage while waiting
- The hooks system automatically wakes the parent when children complete
- Use worktrees (`-w` flag or user request) when children might edit same files
- Children can write to parent inbox if they need coordination help
- The dashboard shows orchestrated sessions with `(*)` indicator under the parent