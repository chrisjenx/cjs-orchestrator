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

## v0.9.0 — new `ship` config section (additive)

`/develop:ship` (the 4th skill) reads an optional top-level `ship` section of `develop.config.json`
([config-schema.md](./config-schema.md)); no `schema` bump (additive optional key). On re-run, init
*proposes* adding the `ship` block (base branch from remote HEAD, empty `reviewBots`, the neutral
default `flakePatterns`, caps) — idempotency reconcile: present-and-customised ⇒ preserve, absent ⇒
additive diff shown before write. It also ensures the `ship.durationsFile` path is git-ignored (via
`gitignore-append.sh`) and re-stamps `pluginVersion`. A repo that never runs `/develop:ship` is
unaffected — the engine falls back to defaults.

## v0.8.0 — the run skill is now `/develop:work` (breaking)

`/develop:run` was renamed to `/develop:work`; the old invocation no longer works. Nothing init writes into `.claude/` is keyed on the command name, so
a re-run just re-stamps `pluginVersion`. **Flag, don't auto-edit:** the target repo's
`CLAUDE.md` (user-managed prose — [idempotency.md](./idempotency.md)) or any local scripts may
still say `/develop:run`; tell the user to update those to `/develop:work` by hand.

## v0.7.2 — no migration

The stack-neutral starting contract grew to eight ([flywheel.md](./flywheel.md)); `/develop:work`
reads the anchors from the shipped reference, so existing repos pick them up on plugin update with
no init action. The repo's human-curated `.claude/develop-flywheel.md` is left untouched — its
promoted-anchors table is only ever edited by `/develop:flywheel` on approval, never by init
([idempotency.md](./idempotency.md)). A re-run only re-stamps `pluginVersion`.

## v0.7.1 — no migration

Behaviour tuning only: the audit/review set moved from the `top` tier to `mid` + high effort, and
every bundled agent gained an `effort:` frontmatter. Nothing `/develop:init` writes into a target
repo changed, so a re-run only re-stamps `pluginVersion`.

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
