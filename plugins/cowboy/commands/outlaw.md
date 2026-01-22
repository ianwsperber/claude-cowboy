---
description: "Get external code review from Gemini (the outlaw)"
argument-hint: "@<file> [@file...] [prompt]"
allowed-tools: Read, Bash(gemini:*)
---

# Outlaw - External Code Review via Gemini

Get a second opinion on your code from Gemini CLI. The "outlaw" is our external consultant for a different perspective.

## Arguments

- `@file` (required): One or more file paths prefixed with `@`
- `prompt` (optional): Custom review prompt (everything after the file paths)

## Instructions

### 1. Parse Arguments

Extract from `$ARGUMENTS`:

- **Files**: All tokens starting with `@` are file paths (remove the `@` prefix to get the path)
- **Prompt**: Any remaining text after extracting file paths

If no `@` prefixed files are found, tell the user to specify at least one file using the `@` prefix.

### 2. Read the Files

Use the **Read** tool to get the contents of each specified file.

If a file cannot be read:

- Show the error to the user
- Continue with the remaining files if there are any
- If no files could be read, stop and report the error

### 3. Construct the Prompt

Build a prompt combining:

1. The user's custom prompt, OR if none provided, use this default:
   ```
   Review the following code for potential issues, bugs, and improvements.
   ```
2. Each file's contents, formatted as:
   ```
   === File: <filepath> ===
   <file contents>
   ```

### 4. Call Gemini

Execute the gemini CLI with the constructed prompt:

```bash
gemini -p "<constructed prompt>"
```

**Important**: The prompt may contain quotes and special characters. Use proper escaping or a heredoc approach if needed.

### 5. Display the Response

Show Gemini's response to the user. If gemini fails (not installed, API error, etc.), display the error message.

## Examples

```
# Review a single file with default prompt
User: /outlaw @src/api.py
Assistant: [Reads src/api.py]
          [Runs: gemini -p "Review the following code..."]
          [Shows Gemini's review]

# Review multiple files with custom prompt
User: /outlaw @lib/auth.py @lib/session.py Check for security vulnerabilities
Assistant: [Reads lib/auth.py and lib/session.py]
          [Runs: gemini -p "Check for security vulnerabilities..."]
          [Shows Gemini's analysis]

# Get specific feedback
User: /outlaw @model.py Are there any tensor shape mismatches?
Assistant: [Reads model.py]
          [Runs: gemini -p "Are there any tensor shape mismatches?..."]
          [Shows Gemini's response]
```

## Notes

- Gemini CLI must be installed and configured for this command to work
- Large files may hit token limits - consider reviewing smaller chunks if needed
- The response is from Gemini, not Claude - it's an external perspective
