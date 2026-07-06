# Gate tokens — the repo's real checks, made un-skippable

`/develop:init` Phase 2. A **gate** is a check that clears *only because a command ran and
produced evidence* — never because an agent "felt done." Below: how to discover gates from
the repo and how `/develop:run` references them.

> The single most important step: extract the **actual commands** that define "correct" in
> this repo — the ones CI runs — and make each one a token a plan node can carry.

## Discovery — derive gates from CI, confirm with the user

1. **Read CI first, exhaustively.** The CI workflow(s) found in Phase 1 are canonical. For every
   job, enumerate **every gating step** — build/test/lint/format/type/coverage **and** guard-style
   `exit 1` checks (see [stack-detection.md](./stack-detection.md)). Mirror the **exact** invocation
   (flags, env, working dir, matrix). At the confirm seam (step 4) **echo the full enumerated list
   back** — one line per gating step with its `file:line` — and ask the user to confirm none was
   missed; a guard left un-enumerated is the failure this prevents.
2. **Fall back to declared scripts/tasks** only where CI is silent (`scripts.test`,
   Gradle/Maven tasks, Make targets, `pyproject` tool configs).
3. **Classify each gate** by kind and tier (below).
4. **Confirm the list with the user.** Show the commands you'll run as gates and ask: "are
   these the commands that decide green here, and did I miss any?" Write the confirmed set
   into `.claude/develop.config.json` (see [config-schema.md](./config-schema.md)).

**Build gate = whole-project, not one module.** CI often shards compile per module/target for
speed, but one module's compile is too narrow a heavy `build` gate. Use the umbrella the build
tool always provides (Gradle `build`/`assemble`, `cargo build`, `tsc -b`, `make`) for the heavy
gate. A compiled stack usually wants **two** `build`-kind gates: a **cheap** per-module compile
(inline every phase) **and** the **heavy** umbrella build (PF). Define them as two gates with
distinct ids (e.g. `id:"compile"` cheap + `id:"build"` heavy, both `kind:"build"`); the `tier`
field governs inline-vs-PF. Address a specific one with `{build:compile}` (below).

If a gate can't be derived from a real command, it is not a gate — drop it or ask. Never
invent a command.

## Gate kinds (stack-neutral)

| Kind | Proves | Typical command source |
|---|---|---|
| `build` | the code compiles / builds | CI build step |
| `test` | named tests pass | CI test step / test script |
| `lint` | linter is clean | lint script / CI |
| `format` | formatting matches | format-check / CI |
| `types` | type-checker is clean | tsc / mypy / etc. |
| `coverage` | diff/threshold coverage met | coverage report |
| `grep` | a required (or forbidden) pattern is present/absent in the diff | derived anchor, see [flywheel.md](./flywheel.md) |

Each gate stores **both** a `command` (whole-repo) and, where the tool supports it, a
`scopedCommand` template (e.g. one package, one test selector) used for the cheap inline run.

## Tiers — cheap (inline) vs heavy (final)

- **cheap** — fast and *scopeable*: single-module/package build, a single named test, a
  scoped lint/type-check on changed files. The executor runs these **in its own turn**,
  every phase. They give fast local signal.
- **heavy** — whole-repo and slow: full build, full test suite, multi-module `check`,
  whole-repo coverage. These are **deferred** to the final gate (`PF`) — the executor
  annotates them `DEFERRED-PF` and moves on; `/develop:run`'s finalize phase runs them
  locally and blocks the commit until they pass. See [quality-tail.md](./quality-tail.md).

Default tiering when unsure: `lint`, `types`, `format`, and *scoped* `build`/`test` are
cheap; whole-repo `build`/`test`/`coverage` are heavy. Let the user override per gate.

## Token grammar — how a plan node carries a gate

On a plan node (see [plan-anatomy.md](./plan-anatomy.md)), gates are space-separated tokens
in `{…}`:

```
- P2.a Implement <thing> [agent: executor] [status: PENDING] {build} {test:<selector>} {types}
- P2.b Wire <thing> [agent: executor] [status: PENDING] {lint} {cov>=80}
```

- A bare kind (`{build}`, `{lint}`, `{types}`, `{format}`) → run that gate's command. Valid only
  when **exactly one** gate of that kind exists; if several do, it is ambiguous (a planner error).
- `{<kind>:<id>}` (e.g. `{build:compile}`) → address one specific gate by its `develop.config.json`
  `id`, for the non-selector kinds (`build`/`lint`/`types`/`format`). Use this to pick the cheap
  compile vs the heavy build when both exist.
- `{test:<selector>}` → run only the named test(s); the selector is whatever the runner
  accepts (file path, test name, tag). Forces a **fresh** run (no cached results).
- `{cov>=N}` → diff coverage must be ≥ N% (a `coverage` gate must be configured).
- `{grep:<id>}` → a required/forbidden-pattern anchor: the `id` *names the pattern* (e.g.
  `no-todo`, `reuse:<ref>`, a wiring anchor), checked by grepping the diff — or the scope the
  `id` names (e.g. the test tree, for sites the diff didn't touch) — and resolved by the
  executor/flywheel layer — **not** a `develop.config.json` gate ([flywheel.md](./flywheel.md)).
- **Placement is load-bearing.** Put the gate on the node whose work it proves — a perm/
  auth test on the node that adds the guarded route, coverage on the node that adds the
  logic. An executor checks a node's gates in node order.

## Execution rules

- **Fresh test execution.** `{test:…}` must force a real run (e.g. `--rerun`, clear cached
  reports) so a stale green can't pass a node.
- **Environment failures don't loop.** If a gate command fails to *run* (toolchain/network),
  record it `DEFERRED-PF` and move on — don't burn the loop budget retrying a broken env.
- **Cheap in the executor's turn; heavy deferred.** The executor never runs heavy gates;
  it tags them `DEFERRED-PF`. Only `PF` finalize runs heavy gates, blocking until green.
- **Unrecognised or ambiguous command-token = planner error.** If a node carries a command-gate
  token (`build`/`test`/`lint`/`format`/`types`/`cov`) with no matching gate in
  `develop.config.json`, or a **bare** kind token when several gates share that kind (use
  `{kind:id}` to disambiguate), that's a bug in the plan — write a finding, don't guess.
  `{grep:<id>}` anchors are exempt: they self-resolve from the id (no config gate needed).
