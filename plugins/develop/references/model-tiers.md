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
| `mid` | writing code AND reviewing the diff — the executor and its child writers, plus the audit/review set (separated by effort, below) | the workhorse; strong at bounded code and diff-scoped judgement |
| `top` | the highest-stakes judgement — planning (a bad plan poisons the whole run) and refutation (must catch what a same-model peer missed) | worth peak reasoning and model decorrelation; both low-volume, so it stays cheap |

## The one rule that's load-bearing: don't let review rubber-stamp the writer

A reviewer sharing the writer's blind spots confidently agrees. Two separators keep it honest:
- **Effort, at the same `mid` tier.** The executor writes at medium effort; the audit/review set
  reads the diff at **high** effort. Harder thinking on a bounded diff, plus the audit set's *lens
  diversity* (each auditor hunts a different failure), catches what the writer missed without a
  costlier model.
- **Model, at `top`.** True error-decorrelation — a different model — is spent only where it's
  decisive and cheap: the planner (one dispatch, sets up the run) and the refuters (opt-in,
  kill-on-doubt; a same-model refuter is near-worthless).

The effort split lives in each agent's `effort:` frontmatter; the tier is this map, which the
orchestrator passes as an explicit `model` per dispatch (the executor does the same for its
children — [executor-brief.md](./executor-brief.md)). A safety-critical repo can raise the
audit/review set to `top` per-repo.

## Defaults

`default-cheap` / `default-mid` / `default-top` are placeholders meaning "let the harness
pick a model of this tier." In Claude Code the natural mapping is **Haiku → cheap, Sonnet →
mid, Opus → top**; set concrete ids if you want to pin them, e.g.:

```json
"models": { "cheap": "claude-haiku-4-5", "mid": "claude-sonnet-5", "top": "claude-opus-4-8" }
```

Examples only — use whatever model ids your environment exposes. The point is the *tiering
and the writer/reviewer separation*, not specific version strings.

## Overriding

- **Per repo:** edit `models` in `develop.config.json`. `/develop:run` reads it every run, so
  changes take effect immediately.
- **Per run:** the orchestrator's Assess step may bump a tier for a high-risk change (e.g.
  plan at `top`, or raise the executor to `top` for a gnarly slice). Keep this rare and
  evidence-driven — most runs use the defaults.
- A repo that only has one model available can point all three tiers at it; you lose the
  rubber-stamp protection, so lean harder on the [refuters](./verify-by-forking.md) and the
  diff-reading auditors, which add value even at a single tier.
