# develop

**Fire one prompt. Walk away. Get back a branch that already passed your own review.**

`/develop` plans the change, builds it, audits the diff against your repo's own rules, and clears your gates before it hands the branch back. It bootstraps a minimal orchestration flow fitted to your repo, then grows it via a feedback flywheel.

## Install

```text
/plugin marketplace add chrisjenx/cjs-orchestrator
/plugin install develop@cjs-orchestrator
/develop:init     # once: discover + scaffold
/develop:work      # per feature: spec → reviewed, committed branch
/develop:ship      # per branch: push, watch CI + review, merge
/develop:flywheel # periodically: tune the flow from its postmortems
```

## How it works

The plugin ships **static, portable skills**; per-project behaviour comes from **definitions the skills discover**, not from a bespoke flow generated per repo. Its **first principle is token frugality**: every shipped token is paid on every run, so the prose is kept tight by design (`references/token-frugality.md`).

- **`skills/init`** (`/develop:init`) detects the stack, discovers the repo's real gate commands, and writes the definitions into `.claude/` (`develop.config.json`, `develop-routing.json`, a starter `CLAUDE.md`, safe hooks, a flywheel doc). It never transplants a finished system.
- **`skills/work`** (`/develop:work`) is the portable orchestrator loop. It reads those definitions and walks a per-feature plan file it creates at runtime: static in the plugin, fitted to your repo at run time. It hands off a committed branch (it never pushes).
- **`skills/ship`** (`/develop:ship`) takes that branch the rest of the way: push, open the PR, then a mechanical watcher (`scripts/ship.py`, Monitor-driven, waking the agent only for judgment: a real CI failure, a review thread, a conflict) fixes/replies/rebases and merges at green + approved + threads addressed. Repo specifics come from the config's `ship` section.
- **`skills/flywheel`** (`/develop:flywheel`) is the manual tuner. It reads accumulated postmortems, flags recurring or breaking findings, and proposes the cheapest remediation lever and target for each (human-gated).
- **`references/`** hold the portable, stack-neutral mechanism the loop relies on (plan anatomy, executor brief, gate tokens, flywheel).
- **`agents/`** are stack-agnostic subagents referenced by name from `develop-routing.json` (not copied per repo): `planner`, `executor`, the diff-reading auditors (`completeness` / `stubs` / `regression`), `general-quality-reviewer`, `code-reviewer`, `tidy`, `refuter`. They read diffs and rules, not build systems, so they travel across stacks. The flow **reuses these first** and defers building anything missing to a workflow (`references/reuse-and-defer.md`).
- **`hooks/`** are safe, stack-agnostic hooks (worktree/uncommitted-work protection, generic timeouts); nothing is tied to an unconfirmed stack.

See [DECISIONS.md](../../DECISIONS.md) for locked names and architecture, and the [explainer](https://chrisjenx.github.io/cjs-orchestrator/) for the full design and a worked case study.
