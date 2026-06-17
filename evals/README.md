# Evals for `/develop:init`

These evals are the **tests** for the bootstrapper skill: they pin down that `/develop:init`
(1) **triggers** on the right intents and not the wrong ones, and (2) **behaves** correctly —
detects the stack and discovers the real gates — across sample repos of different stacks.
Their job is to catch regressions in detection/discovery when the skill or references change.

This mirrors the superpowers `writing-skills` methodology (skill evals = TDD for skills):
fixtures are application scenarios; `expected.json` is the assertion. A change that breaks
detection makes an eval fail.

## What's here

```
evals/
  README.md            # this file
  triggering.md        # should-trigger / should-NOT-trigger phrase matrix
  fixtures/
    node-ts/           # a realistic minimal repo per stack
    python-uv/
    go-mod/
    unknown-stack/     # exercises graceful degradation
  fixtures/<stack>/expected.json   # the detection/discovery the run must produce
```

## How to run (subagent-per-fixture)

For each fixture, dispatch a subagent with the `develop` plugin available, cwd set to the
fixture, and the task: *"Run the `/develop:init` Phase 1–2 discovery (stack detection + gate
discovery) and report the stack summary + the gate commands you'd write to
develop.config.json."* Do **not** let it write files — this is a read-only detection eval.

Then compare the subagent's report to `expected.json`:

- `stack.ecosystems`, `stack.buildTool` — must match.
- `gates[].kind` set — must include every `expected.gates[].kind` (extra cheap gates are OK;
  a missing kind is a regression).
- `gates[].command` — must match the CI command (substring match on the canonical command is
  enough; flags may be normalised).
- `skipped` — for partial/unknown stacks, the named facets must be reported as skipped, not
  silently passed.

Score each fixture pass/fail and report the matrix. A red fixture = a detection regression to
fix in the skill/references, not in the eval.

## Triggering evals

See [triggering.md](./triggering.md). For each should-trigger phrase, a fresh agent with the
plugin installed should invoke `/develop:init`; for each should-NOT-trigger phrase, it should
not. Over-triggering (firing on unrelated intents) is as much a failure as under-triggering.

## Adding a fixture

1. Make `fixtures/<stack>/` a minimal but **realistic** repo: the real marker file(s), a
   `.github/workflows/ci.yml` (or other CI) with the real command lines, and any lint/type
   config.
2. Write `fixtures/<stack>/expected.json` with the stack + gate kinds/commands the run must
   produce (and `skipped` for any facet that legitimately can't be detected).
3. Keep it tiny — detection reads marker files and CI, not a full build. No real dependencies
   needed.

## Note on the Iron Law

These evals are infrastructure added for an already-shipped skill. If an eval surfaces a
detection gap, that drives an edit to the skill/references (with the eval as the failing test
that edit must turn green) — never a tweak to the eval to make a bad result "pass".
