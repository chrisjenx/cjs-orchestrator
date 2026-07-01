# Safe, stack-agnostic hooks

The worktree-guard is an **auto-loaded plugin hook** (`hooks.json`, command
`${CLAUDE_PLUGIN_ROOT}/hooks/worktree-guard.sh`). `/develop:init` no longer copies it or wires
it into a target's `settings.json`.

> **The rule (do not break it):** never ship a hook tied to a stack you didn't confirm. A
> build-tool timeout hook in the wrong repo misfires and erodes trust. These hooks reason only
> about git and worktrees, never a language or build tool.

## The guard

`worktree-guard.sh` is a `PreToolUse(Bash)` guard that:
- refuses destructive working-tree git (`checkout` / `switch` / `restore` / `clean` / `stash`,
  and `reset --hard|--keep|--merge`) so a run can't wipe another phase's or a sibling worktree's
  uncommitted work — the develop flow is read-only git by design;
- refuses mutating git (`commit` / `push` / `merge` / `rebase`) while on `main`/`master` or a
  detached HEAD — feature work belongs on a worktree branch (`--abort`/`--continue` are allowed).

Matching is anchored to command position and accounts for git global flags (`-C`, `--git-dir`,
`--work-tree`), so `git -C <dir> reset --hard` is caught while `echo "git commit"` is not. Exits
`2` to block, `0` to allow. Zero stack knowledge.

Because it auto-loads in **every** project, the guard **self-gates**: it enforces only when it
resolves a `.claude/develop.config.json` at the main checkout (via `git --git-common-dir`, so it
works from inside a worktree too) and fail-opens everywhere else. The self-gate rule and its
mechanics live in `worktree-guard.sh` itself; this is only a pointer.

## The command timeout (init Phase 4)

Plugin `env` does not auto-apply, so init merges a generic command timeout
(`BASH_DEFAULT_TIMEOUT_MS` / `BASH_MAX_TIMEOUT_MS`, from `hooks.json`) into the target's
`.claude/settings.json` — idempotent (present ⇒ keep the user's value; absent ⇒ add). This is
init's **only** `settings.json` write now. It is a wall-clock bound on any command, generic by
construction.

When the host **denies** the `settings.json` edit (self-modification guard), init must **emit
only the `env` snippet** for the user to paste and report it as a required manual step — it must
**never** re-emit a project-local guard copy (the guard is plugin-managed; re-emitting a copy
reintroduces the deleted fail-open bug).

## Testing the guard

```sh
echo '{"tool_input":{"command":"git reset --hard HEAD~1"}}' | ${CLAUDE_PLUGIN_ROOT}/hooks/worktree-guard.sh; echo "exit=$?"
# in a develop-managed repo -> blocked, exit=2 ; in any other repo -> allowed, exit=0 (self-gated)
```
