# Reuse first, defer creation to workflows

Two rules govern how the flow gets the capabilities it needs (a planner, a reviewer, a rule,
a skill) — keeping it lean and stopping it from hand-rolling one-off helpers nobody maintains.

> **1. Reuse first.** Before doing a job, find the most specific *already-defined*
> skill / agent / rule and use it. Don't reinvent what exists.
>
> **2. Defer creation to a workflow.** When nothing suitable exists, or an existing one is
> inadequate, **don't hand-roll a fix inline** — defer to a workflow that builds / creates /
> improves the artifact properly. Human-gated.

## Reuse-first lookup order

When the flow needs a capability (plan this, write this slice, review this file, enforce
this convention), resolve it against existing definitions, **most specific first**:

1. **The repo's own `.claude/`** — its skills, its `agents/`, its rules in `CLAUDE.md`, and
   `develop-routing.json`. Repo-owned and most specific; always wins.
2. **The plugin's bundled agents** — `executor`, `planner`, the auditors, `code-reviewer`,
   `tidy`, `general-quality-reviewer`, `refuter`.
3. **Skills available in the environment** — e.g. a code-review skill, a skill-authoring
   skill. Use them rather than re-implementing their behaviour.

Use the most specific match; only fall back to a generalist when nothing more specific fits
(see [routing.md](./routing.md)). **Never skip the lookup** and default straight to a
generalist or to writing something new — that's how existing capabilities stop being used.

## When nothing fits: defer to a workflow (don't hand-roll)

Two triggers:

- **Missing** — the planner or router finds a slice that no existing skill/agent/rule covers.
- **Inadequate** — the [flywheel](./flywheel.md) shows an existing capability keeps letting a
  finding class escape (a reviewer that misses it, a rule too vague to apply).

In both cases the flow **records the gap and defers** — it does not inline-author a quick
agent or rule. Creation/improvement is a *workflow*: a deliberate, multi-step, human-gated
build using the canonical authoring method (for skills/agents, the skill-authoring discipline —
write the failing eval first, then the agent; for rules, the repo's rule-doc conventions). The
heavy authoring + verification happens there, not in the middle of a feature run.

## How this maps onto the flywheel levers

The flywheel routes a preventable finding to the cheapest remediation lever
([flywheel.md](./flywheel.md)). **Applying** a lever follows the defer rule:

| Lever | Apply by deferring to a workflow that… |
|---|---|
| hook / gate | authors + tests the hook or wires the lint/coverage/CI gate |
| plan-anchor | adds + validates the contract row (and the grep/token that checks it) |
| rule | writes the convention into `CLAUDE.md` / a rule doc, with an example |
| agent | builds a new reviewer (eval-first) **or** prunes a now-redundant one, updating `develop-routing.json` |

Promotion stays **human-gated** (recurs ≥ 2 runs, or breaking-class) and the workflow's
output lands in the repo's `.claude/` for review — then reuse-first picks it up next run, and
the loop tightens. Never auto-edit `.claude/` from a run artifact; the workflow proposes, the
human accepts.
