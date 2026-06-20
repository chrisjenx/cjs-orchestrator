# Gate tokens — the repo's real checks, made un-skippable

`/develop:init` Phase 2. A **gate** is a check that clears *only because a command ran and
produced evidence* — never because an agent "felt done." Below: how to discover gates from
the repo and how `/develop:run` references them.

> The single most important step: extract the **actual commands** that define "correct" in
> this repo — the ones CI runs — and make each one a token a plan node can carry.

## Discovery — derive gates from CI, confirm with the user

1. **Read CI first.** The CI workflow(s) found in Phase 1 are canonical. Extract each
   command line that gates a merge: build, test, lint, format-check, type-check, coverage.
   Mirror the **exact** invocation (flags, env, working dir, matrix).
2. **Fall back to declared scripts/tasks** only where CI is silent (`scripts.test`,
   Gradle/Maven tasks, Make targets, `pyproject` tool configs).
3. **Classify each gate** by kind and tier (below).
4. **Confirm the list with the user.** Show the commands you'll run as gates and ask: "are
   these the commands that decide green here, and did I miss any?" Write the confirmed set
   into `.claude/develop.config.json` (see [config-schema.md](./config-schema.md)).

**Build gate = whole-project, not one module.** CI often shards compile per module/target for
speed, but one module's compile is too narrow a `build` gate. Use the umbrella the build tool
always provides (Gradle `build`/`assemble`, `cargo build`, `tsc -b`, `make`); scope only the
*cheap* run to changed modules. The gate must catch compile breakage anywhere the change touches.

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
`scoped_command` template (e.g. one package, one test selector) used for the cheap inline run.

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

- A bare kind (`{build}`, `{lint}`, `{types}`, `{format}`) → run that gate's command.
- `{test:<selector>}` → run only the named test(s); the selector is whatever the runner
  accepts (file path, test name, tag). Forces a **fresh** run (no cached results).
- `{cov>=N}` → diff coverage must be ≥ N% (a `coverage` gate must be configured).
- `{grep:<id>}` → a required-pattern anchor from the routing/flywheel layer.
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
- **Unrecognised token = planner error.** If a node carries a token with no matching gate
  in `develop.config.json`, that's a bug in the plan — write a finding, don't guess.
