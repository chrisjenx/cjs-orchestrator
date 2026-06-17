# develop

Bootstrap a minimal, self-improving `/develop` orchestration flow fitted to your repo, then grow it via a feedback flywheel.

## Install

```text
/plugin marketplace add chrisjenx/cjs-orchestrator
/plugin install develop@cjs-orchestrator
/develop:init     # once — discover + scaffold
/develop:run      # repeatedly — spec → committed branch
```

## How it works

The plugin ships **static, portable skills**; per-project behaviour comes from
**definitions the skills discover**, not from generating a bespoke flow per repo.

- **`skills/init/SKILL.md`** (`/develop:init`) — detects the stack, discovers the repo's
  real gate commands, and writes the repo-specific definitions into `.claude/`
  (`develop.config.json`, `develop-routing.json`, a starter `CLAUDE.md`, safe hooks, a
  flywheel doc). Does **not** transplant a finished system.
- **`skills/run/SKILL.md`** (`/develop:run`) — the portable orchestrator loop. Static in
  the plugin, but fitted to your repo because it reads those discovered definitions and
  walks a per-feature plan file it creates at runtime.
- **`references/`** — the portable mechanism the loop relies on (plan anatomy, executor
  brief, gate tokens, flywheel). Stack-neutral.
- **`agents/`** — portable, stack-agnostic subagents available because the plugin is
  installed (referenced by name from `develop-routing.json`, not copied per repo): a
  `planner`, the generalist `executor`, diff-reading auditors (completeness / stubs /
  regression), a `general-quality-reviewer`, a `code-reviewer` (reviews against the repo's
  own rules), a `tidy` worker, and a `refuter`. They read diffs/rules, not build systems, so
  they travel across stacks. The flow **reuses these first** and defers building anything
  missing to a workflow (see `references/reuse-and-defer.md`).
- **`hooks/`** — safe, stack-agnostic hooks (worktree/uncommitted-work protection,
  generic timeouts). Nothing tied to a stack the bootstrapper didn't confirm.

See [DECISIONS.md](../../DECISIONS.md) for the locked names + architecture, and the
[explainer](https://chrisjenx.github.io/cjs-orchestrator/) for the full design and a
worked case study.
