# Per-version migrations — what a re-run of `/develop:init` cleans up

The single home for per-version cleanups init applies when Phase 0 detects a `pluginVersion`
gap. idempotency.md, the init SKILL, the hooks README, and the CHANGELOG carry a one-line
summary + a link here — never the procedure.

init reads the target's recorded `pluginVersion` (`config-schema.md`) vs the live plugin
(`${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`), compares with
[`scripts/version-compare.sh`](../scripts/version-compare.sh), and — **recorded version absent ⇒
treat as `0.6.0` (oldest migratable)** — runs every entry newer than the recorded version, then
stamps `pluginVersion` to current. A release that changes nothing init writes still gets a
one-line `no migration` entry below so the version is accounted for.

## v0.7.0 — retire the copied worktree-guard (order matters)

The guard is now an auto-loaded plugin hook, so a pre-0.7.0 scaffold's per-project copy is
obsolete. Clean it up **in this order**:

1. **Detect plugin-shipped vs user-customised by marker, not checksum.** If
   `.claude/hooks/worktree-guard.sh` contains `develop:worktree-guard`, it is a plugin-shipped
   copy (any historical version) and is safe to remove. Marker **absent** ⇒ the user customised
   it ⇒ **flag it, do not delete.** (Marker detection is version-robust and dependency-free — no
   `shasum`/`sha256sum` portability mess.)
2. **Remove the `settings.json` `PreToolUse(Bash)` guard entry FIRST, then delete the script
   file.** A settings entry pointing at a deleted script is exactly the fail-open bug, so the
   entry goes first. The `settings.json` edit reuses Phase 4's show-diff-then-accept JSON merge —
   not a scripted JSON editor.
3. Ensure the `.claude/worktrees/` gitignore line (via
   [`gitignore-append.sh`](../scripts/gitignore-append.sh), idempotent).
