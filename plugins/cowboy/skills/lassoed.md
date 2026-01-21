---
description: Handle incoming lasso query from another Claude session
---

# Lassoed - Incoming Context Query Handler

You've been lassoed by another Claude session that needs context from your work. Your job is to answer their query concisely using your existing context.

## Arguments

The query includes flags followed by the actual question:

- `--parent-cwd <path>`: The parent session's working directory
- `--parent-session <name>`: The parent's tmux session name
- The final argument is the query itself

## Instructions

1. **Parse the arguments** to extract:
   - Parent CWD (where the calling session is working)
   - Parent session name (who is asking)
   - The actual query/question

2. **Answer the query** using your existing context:
   - You already have the full conversation history
   - Draw on what you know from your work
   - Be concise but thorough

3. **Consider the parent's context**:
   - They may be working in a different directory
   - They may need information relevant to their work location
   - If they ask about files, consider both your CWD and theirs

4. **Keep responses focused**:
   - Answer the specific question asked
   - Include relevant details but avoid unnecessary tangents
   - If you need to reference files, include relative paths

## Response Format

Provide a direct, concise answer to the query. No need for elaborate formatting - the response will be displayed directly to the parent session's user.

If you don't have relevant context to answer the query, say so clearly and explain what context you do have.

## Examples

**Query:** "What files did you modify?"
**Good response:** "I modified 3 files: lib/auth.py (added login validation), lib/session.py (fixed session timeout), and tests/test_auth.py (new test cases)."

**Query:** "What's the status of the API implementation?"
**Good response:** "Completed the /users and /auth endpoints. Still working on /orders - need to add validation. Blocked on database schema for order items."

**Query:** "Can you help debug an error in src/app.py?"
**Good response:** "I haven't worked on src/app.py in this session. My work has been focused on lib/ and tests/. You may want to share the error details if you need help."
