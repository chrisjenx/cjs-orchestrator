# develop

Bootstrap a minimal, self-improving `/develop` orchestration flow fitted to your repo, then grow it via a feedback flywheel.

## Install

```text
/plugin marketplace add chrisjenx/cjs-orchestrator
/plugin install develop@cjs-orchestrator
/develop:init
```

## What ships today (v0)

- **`skills/init/SKILL.md`** — the `/develop:init` bootstrapper. Detects the stack, discovers the repo's real gate commands, and scaffolds a *minimal* orchestrator (one generalist executor + a plan file + your actual gates). Guides you through it; does not transplant a finished system.

## What's coming (tracked in issues)

- **`agents/`** — portable, stack-agnostic subagents (diff-reading completeness / regression / stubs auditors, a general-quality reviewer) the bootstrapper can drop in.
- **`hooks/`** — safe, stack-agnostic hooks (worktree/uncommitted-work protection, generic timeouts). Nothing tied to a stack the bootstrapper didn't confirm.
- Gate auto-discovery, registry generation, idempotent re-runs, a multi-stack support matrix.

See the [explainer](https://chrisjenx.github.io/cjs-orchestrator/) for the full design and a worked case study.
