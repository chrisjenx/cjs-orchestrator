# develop

Bootstrap a minimal, self-improving `/develop` orchestration flow fitted to your repo, then grow it via a feedback flywheel.

## Install

```text
/plugin marketplace add chrisjenx/cjs-orchestrator
/plugin install develop@cjs-orchestrator
/develop:init     # once — discover + scaffold
/develop:run      # repeatedly — spec → committed branch
/develop:flywheel # periodically — tune the flow from its postmortems
```

## How it works

The plugin ships **static, portable skills**; per-project behaviour comes from **definitions the skills discover**, not from a bespoke flow generated per repo. Its **first principle is token frugality** — every shipped token is paid on every run, so the prose is kept tight by design (`references/token-frugality.md`).

- **`skills/init`** (`/develop:init`) — detects the stack, discovers the repo's real gate commands, and writes the definitions into `.claude/` (`develop.config.json`, `develop-routing.json`, a starter `CLAUDE.md`, safe hooks, a flywheel doc). Never transplants a finished system.
- **`skills/run`** (`/develop:run`) — the portable orchestrator loop: reads those definitions and walks a per-feature plan file it creates at runtime. Static in the plugin, fitted to your repo at run time.
- **`skills/flywheel`** (`/develop:flywheel`) — the manual tuner: reads accumulated postmortems, flags recurring/breaking findings, and proposes the cheapest remediation lever + target for each (human-gated).
- **`references/`** — the portable, stack-neutral mechanism the loop relies on (plan anatomy, executor brief, gate tokens, flywheel).
- **`agents/`** — stack-agnostic subagents referenced by name from `develop-routing.json` (not copied per repo): `planner`, `executor`, diff-reading auditors (`completeness` / `stubs` / `regression`), `general-quality-reviewer`, `code-reviewer`, `tidy`, `refuter`. They read diffs and rules, not build systems, so they travel across stacks. The flow **reuses these first** and defers building anything missing to a workflow (`references/reuse-and-defer.md`).
- **`hooks/`** — safe, stack-agnostic hooks (worktree/uncommitted-work protection, generic timeouts); nothing tied to an unconfirmed stack.

See [DECISIONS.md](../../DECISIONS.md) for locked names + architecture, and the [explainer](https://chrisjenx.github.io/cjs-orchestrator/) for the full design and a worked case study.
