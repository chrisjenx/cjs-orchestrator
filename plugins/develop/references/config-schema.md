# `develop.config.json` — the discovered, per-repo definitions

Written by `/develop:bootstrap` into `.claude/develop.config.json`. Read by `/develop:work` at
the start of every run. This is the file that makes a *static* loop behave *fitted* to the
repo. Keep it small and human-editable; the user owns it.

## Shape

```json
{
  "schema": 1,
  "pluginVersion": "0.7.0",
  "featureDir": ".develop",
  "stack": {
    "ecosystems": ["node-ts"],
    "buildTool": "pnpm",
    "monorepo": false,
    "evidence": {
      "buildTool": "pnpm-lock.yaml",
      "test": "package.json scripts.test",
      "ci": ".github/workflows/ci.yml"
    }
  },
  "gates": [
    { "id": "types",    "kind": "types",    "tier": "cheap", "command": "pnpm -w typecheck" },
    { "id": "compile",  "kind": "build",    "tier": "cheap", "command": "pnpm -w build",
      "scopedCommand": "pnpm --filter {pkg} build" },
    { "id": "lint",     "kind": "lint",     "tier": "cheap", "command": "pnpm -w lint",
      "scopedCommand": "pnpm eslint {files}" },
    { "id": "build",    "kind": "build",    "tier": "heavy", "command": "pnpm -w build",
      "scopedCommand": "pnpm --filter {pkg} build" },
    { "id": "test",     "kind": "test",     "tier": "heavy", "command": "pnpm -w test",
      "scopedCommand": "pnpm vitest run {selector}", "fresh": true },
    { "id": "coverage", "kind": "coverage", "tier": "heavy", "command": "pnpm -w coverage",
      "threshold": 80 }
  ],
  "models": { "cheap": "default-cheap", "mid": "default-mid", "top": "default-top" },
  "caps": { "validator": 3, "audit": 2, "fork": 1, "gate": 2 },
  "intensity": { "refuters": 1, "planCandidates": 1 },
  "routingFile": ".claude/develop-routing.json",
  "flywheelFile": ".claude/develop-flywheel.md",
  "ship": {
    "baseBranch": "main",
    "reviewBots": [],
    "flakePatterns": [
      { "regex": "OutOfMemoryError", "mechanism": "memory", "hint": "shrink fixture; per-test cleanup" },
      { "regex": "(?i)connect(ion)? (refused|reset)|sockettimeout", "mechanism": "network", "hint": "stub the network dependency" },
      { "regex": "(?i)timeout", "mechanism": "timing", "hint": "bump timeout 2x or inject a test double" }
    ],
    "caps": { "ciFail": 3, "flakySoak": 3, "emptyRuns": 3, "retriggerReview": 2 },
    "ticketRoute": "gh-issue",
    "mergeMethod": "squash"
  }
}
```

## Fields

| Field | Set by | Meaning |
|---|---|---|
| `schema` | bootstrap | Config schema version (currently `1`). Bump on breaking changes. |
| `pluginVersion` | bootstrap | The plugin version that last wrote this scaffold. **Managed by bootstrap, not user-editable** — bootstrap overwrites it with the live plugin version and uses the gap vs current to drive Phase 0 migrations ([migrations.md](./migrations.md)). Absent ⇒ treated as `0.6.0`. Additive; no `schema` bump. |
| `featureDir` | bootstrap | Where per-feature plan files live (`<featureDir>/<feature>.plan.md`). Default `.develop` (bootstrap adds it to `.gitignore` if absent). Must be git-ignored (so plan artifacts never land in the feature commit) and must **not** sit under a build-output dir (`build/`, `target/`, `out/`, `dist/`, `bin/`) a `clean` task wipes mid-run. |
| `stack` | bootstrap Phase 1 | The confirmed stack summary + file evidence. Informational + drives scoped-command templates. |
| `gates` | bootstrap Phase 2 | The discovered gate commands. See [gate-tokens.md](./gate-tokens.md). |
| `gates[].kind` | bootstrap | `build` \| `test` \| `lint` \| `format` \| `types` \| `coverage` \| `grep`. **Multiple gates may share a kind** (e.g. a cheap `compile` + a heavy `build`); address a specific one with `{kind:id}` ([gate-tokens.md](./gate-tokens.md)). |
| `gates[].tier` | bootstrap | `cheap` (inline every phase) or `heavy` (deferred to `PF`). |
| `gates[].command` | bootstrap | The exact whole-repo command (from CI). |
| `gates[].scopedCommand` | bootstrap | **Optional** template for the cheap inline run; placeholders `{files}`, `{pkg}`, `{selector}`. **Omit it when no uniform per-module command exists** (some multi-target build tools expose per-target task names with no single per-module compile task) — fall back to the whole-repo `command`, or to a per-module umbrella task that is valid everywhere. |
| `gates[].fresh` | bootstrap | `true` for test gates that must force a non-cached run. |
| `gates[].threshold` | bootstrap | For `coverage` gates: minimum diff coverage %. |
| `models` | bootstrap / [model-tiers.md](./model-tiers.md) | The cheap/mid/top model ids `/develop:work` dispatches with. |
| `caps` | bootstrap / run | Loop bounds: validator rounds, audit rounds, fork rounds, between-phase gate rounds. |
| `intensity` | [verify-by-forking.md](./verify-by-forking.md) | `refuters` and `planCandidates` counts. `1` = lean default (no forking). |
| `routingFile` | bootstrap | Path to the routing table ([routing.md](./routing.md)). |
| `flywheelFile` | bootstrap | Path to the **human-curated** flywheel doc ([flywheel.md](./flywheel.md)). The machine SSOT is its sibling `.claude/develop-flywheel.jsonl`, which `PF` appends to; the `.md` is never written from a run. |
| `ship` | bootstrap (optional) | Config for `/develop:ship` ([ship-watch.md](./ship-watch.md)). Absent ⇒ the engine runs on built-in defaults. All fields optional, merged over defaults. |
| `ship.baseBranch` | bootstrap | Fallback base branch for rebase/merge; resolution prefers `SHIP_BASE_REF`, then the PR's live base, then this, then `origin/HEAD`. |
| `ship.reviewBots[]` | bootstrap / user | Per-bot review identities: `checkNames[]` (review check-runs, excluded from CI classification), `commentLogins[]` + `commentSignature` (classify a thread's author as the review bot), `stickyBeacon` + `stickyMeta` (a summary comment; `stickyMeta:true` parses an embedded `{sha,status,findings}` JSON), `retrigger` (draft→ready toggle to force re-review; **default false** — it re-fires every `ready_for_review` workflow). Empty ⇒ CI + human threads + merge still work; no sticky/retrigger hints. |
| `ship.checkExclusions[]` | user | Extra check-run names to exclude from CI pass/fail (unioned with every `reviewBots[].checkNames`). |
| `ship.skipLogins[]` | bootstrap | Comment authors to ignore entirely (bots like `dependabot[bot]`). |
| `ship.flakePatterns[]` | bootstrap / flywheel | Ordered `{regex, mechanism, hint}` rows; first regex matching a failed log marks the failure flaky with that mechanism ([ship-flake.md](./ship-flake.md)). Defaults cover memory/network/timing; add stack rows as flakes recur. |
| `ship.failedTestRegex` | bootstrap | Optional regex extracting failing test ids from a log (named groups joined, else whole match). Empty ⇒ the extractor agent supplies location instead. |
| `ship.caps` | user | Halt caps: `ciFail`, `flakySoak`, `emptyRuns`, `retriggerReview`. |
| `ship.cadence` | user | Poll cadence seconds: `waitCi`, `fastFailWindow`, `landingBuffer`, `rewake`, `unackedRewake`. |
| `ship.rateFloor` | user | `core`/`graphql` gh-token reserve floors; the watcher backs off below them. |
| `ship.durationsFile` | bootstrap | Path to the self-maintained CI-duration baseline (git-ignored). |
| `ship.hotPaths[]` | bootstrap / user | Regexes for high-conflict paths (lockfiles, generated code); a rebase touching one wakes the agent. Default `[]`. |
| `ship.ticketRoute` | bootstrap | Where a flake ticket goes: `gh-issue` (default), `mcp`, or `none` ([ship-flake.md](./ship-flake.md)). |
| `ship.mergeMethod` | bootstrap | `squash` \| `merge` \| `rebase` for the auto-merge under `--merge`. |

## Rules

- **Only commands the user confirmed go in `gates`.** No invented commands.
- The config is the contract between `/develop:bootstrap` (writer) and `/develop:work` (reader).
  A *command-gate* token on a plan node with no matching `gates[].id`/`kind` — **or a bare
  `{kind}` when several gates share that kind** (disambiguate with `{kind:id}`) — is a planner
  error; `{grep:<id>}` anchors self-resolve ([gate-tokens.md](./gate-tokens.md)).
- Defaults shown for `models`, `caps`, `intensity` are the lean starting point; the user
  edits them. `/develop:work` reads them every run, so edits take effect immediately.
- On a re-run, `/develop:bootstrap` reconciles this file rather than overwriting it (see
  [idempotency.md](./idempotency.md)).
