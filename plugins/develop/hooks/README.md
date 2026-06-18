# Safe, stack-agnostic hooks

`/develop:init` Phase 4 installs **only** hooks that are safe in *any* repo because they
reason about git and worktrees, never about a language or build tool.

> **The rule (do not break it):** never install a hook tied to a stack you didn't confirm.
> A Gradle timeout hook in a Node repo, a pytest guard in a Go repo — these misfire and
> erode trust. If a protection would need to know the stack, it doesn't belong here; it
> belongs in the repo's own config, added by the user.

## What gets installed

1. **`worktree-guard.sh`** — a `PreToolUse(Bash)` guard that:
   - refuses destructive git (`checkout` / `restore` / `reset --hard` / `clean` / `stash`)
     so a run can't wipe another phase's uncommitted work — the develop flow is read-only
     git by design;
   - refuses mutating git (`commit` / `push` / `merge` / `rebase`) while on `main`/`master`
     — feature work belongs on a worktree branch.
   It exits `2` with a reason to block, `0` to allow. It has zero stack knowledge.

2. **A generic command timeout** — set via env in `settings.json`
   (`BASH_DEFAULT_TIMEOUT_MS` / `BASH_MAX_TIMEOUT_MS`): a wall-clock bound on *any* command,
   so a hung command can't stall a run forever. Generic by construction — it knows nothing
   about your build tool.

## How init installs them (idempotent, non-destructive)

- Copy `worktree-guard.sh` → `.claude/hooks/worktree-guard.sh` and `chmod +x` it.
- **Merge** the `hooks` and `env` blocks from `hooks.json` into `.claude/settings.json` —
  never overwrite. If the user already has a `PreToolUse(Bash)` hook, append to its list; if
  they already set a bash timeout, leave theirs. Show the diff before writing
  ([../references/idempotency.md](../references/idempotency.md)).

## Testing the guard

```sh
echo '{"tool_input":{"command":"git reset --hard HEAD~1"}}' | .claude/hooks/worktree-guard.sh; echo "exit=$?"
# → blocked, exit=2
echo '{"tool_input":{"command":"git status"}}' | .claude/hooks/worktree-guard.sh; echo "exit=$?"
# → allowed, exit=0
```
