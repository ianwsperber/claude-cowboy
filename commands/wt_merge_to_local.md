---
description: "Merge current worktree branch into the main local repo"
argument-hint: "[--no-delete]"
allowed-tools: ["Bash(git:*)"]
---

# Merge Worktree Branch to Local Main

Merges the current worktree's branch into the main repository's branch locally, without pushing to remote.

## Arguments

- `--no-delete`: Keep the branch after merging (by default, the branch is deleted after successful merge)

## Instructions

### Step 1: Verify we're in a worktree

```bash
git rev-parse --is-inside-work-tree && git worktree list
```

Check that the current directory is NOT the main worktree (first line of `git worktree list`). If this IS the main worktree, inform the user this command is for merging FROM a worktree TO the main repo.

### Step 2: Get current branch

```bash
git branch --show-current
```

If the output is empty, the worktree is in detached HEAD state. Create a branch from the current HEAD:

```bash
git checkout -b <branch-name>
```

Ask the user what they'd like to name the branch, or suggest a name based on context (e.g., `worktree-merge-<short-sha>`).

### Step 3: Check for uncommitted changes

```bash
git status --porcelain
```

If there are uncommitted changes, ask the user if they want to commit them first or stash them.

### Step 4: Get main worktree info

Parse the first line of `git worktree list` to get the main worktree path. Then check what branch it's on:

```bash
git --git-dir=/path/to/main/.git branch --show-current
```

### Step 5: Perform the merge

```bash
cd /path/to/main/worktree && git merge <branch-name>
```

### Step 6: Clean up (unless --no-delete)

If merge succeeded and `--no-delete` was NOT passed:

First, check if this is the only branch in the worktree:

```bash
git branch --list | wc -l
```

If the count is 1, skip branch deletion - inform the user that the branch cannot be deleted because it's the only branch in the worktree. The worktree itself would need to be removed to fully clean up.

If there are multiple branches, delete the merged branch:

```bash
git branch -d <branch-name>
```

Report the result to the user, showing:

- The merge commit (if any)
- Whether the branch was deleted
- Reminder that changes are local only (not pushed)

## Example Usage

```
$ /cowboy_wt_merge_to_local
Merging branch 'feature-x' into main at ~/Code/claude-cowboy...

Merge successful:
  Commit: abc1234 Merge branch 'feature-x'
  Branch 'feature-x' deleted.

Changes are local only. Use 'git push' in the main repo to publish.
```

## Notes

- This command performs a LOCAL merge only - nothing is pushed to remote
- The main worktree must not have uncommitted changes that conflict
- If merge conflicts occur, you'll need to resolve them in the main worktree
