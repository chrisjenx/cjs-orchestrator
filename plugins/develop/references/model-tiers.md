# Model tiers — match the model to the job, pair writer vs reviewer

Three tiers in `develop.config.json`'s `models`, dispatched explicitly per agent. Spending a
top model on a mechanical edit is waste; spending a cheap model on hard judgement is risk.

```json
"models": { "cheap": "default-cheap", "mid": "default-mid", "top": "default-top" }
```

## The tiers

| Tier | Use for | Why |
|---|---|---|
| `cheap` | mechanical work — formatting, renames, boilerplate, log/breadcrumb writes, simple greps | fast and inexpensive; the task has one right answer |
| `mid` | writing code — the executor and its child writers, straightforward implementation | the default workhorse; good code at reasonable cost |
| `top` | hard judgement — planning, audit/review verdicts, refuters, between-phase decisions | where being wrong is expensive and reasoning matters |

## The one rule that's load-bearing: pair writer vs reviewer across tiers

**A reviewer must not be the same tier as the writer it checks.** Same-tier review
rubber-stamps — the reviewer shares the writer's blind spots and confidently agrees.
- Executor writes at `mid` → audit/tidy review at `top`.
- A `cheap` mechanical write → review at `mid` or `top`.
- Refuters run at `top` (their whole value is catching what a peer missed).

The orchestrator passes an explicit `model` on every dispatch from this map; the executor
does the same for its children (see [executor-brief.md](./executor-brief.md)).

## Defaults

`default-cheap` / `default-mid` / `default-top` are placeholders meaning "let the harness
pick a model of this tier." In Claude Code the natural mapping is **Haiku → cheap, Sonnet →
mid, Opus → top**; set concrete ids if you want to pin them, e.g.:

```json
"models": { "cheap": "claude-haiku-4-5", "mid": "claude-sonnet-4-6", "top": "claude-opus-4-8" }
```

These are examples — use whatever model ids your environment exposes. The point is the
*tiering and the writer/reviewer pairing*, not specific version strings.

## Overriding

- **Per repo:** edit `models` in `develop.config.json`. `/develop:run` reads it every run, so
  changes take effect immediately.
- **Per run:** the orchestrator's Assess step may bump a tier for a high-risk change (e.g.
  plan at `top`, or raise the executor to `top` for a gnarly slice). Keep this rare and
  evidence-driven — most runs use the defaults.
- A repo that only has one model available can point all three tiers at it; you lose the
  rubber-stamp protection, so lean harder on the [refuters](./verify-by-forking.md) and the
  diff-reading auditors, which add value even at a single tier.
