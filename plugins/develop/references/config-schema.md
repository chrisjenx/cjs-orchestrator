# `develop.config.json` — the discovered, per-repo definitions

Written by `/develop:init` into `.claude/develop.config.json`. Read by `/develop:work` at
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
  "flywheelFile": ".claude/develop-flywheel.md"
}
```

## Fields

| Field | Set by | Meaning |
|---|---|---|
| `schema` | init | Config schema version (currently `1`). Bump on breaking changes. |
| `pluginVersion` | init | The plugin version that last wrote this scaffold. **Managed by init, not user-editable** — init overwrites it with the live plugin version and uses the gap vs current to drive Phase 0 migrations ([migrations.md](./migrations.md)). Absent ⇒ treated as `0.6.0`. Additive; no `schema` bump. |
| `featureDir` | init | Where per-feature plan files live (`<featureDir>/<feature>.plan.md`). Default `.develop` (init adds it to `.gitignore` if absent). Must be git-ignored (so plan artifacts never land in the feature commit) and must **not** sit under a build-output dir (`build/`, `target/`, `out/`, `dist/`, `bin/`) a `clean` task wipes mid-run. |
| `stack` | init Phase 1 | The confirmed stack summary + file evidence. Informational + drives scoped-command templates. |
| `gates` | init Phase 2 | The discovered gate commands. See [gate-tokens.md](./gate-tokens.md). |
| `gates[].kind` | init | `build` \| `test` \| `lint` \| `format` \| `types` \| `coverage` \| `grep`. **Multiple gates may share a kind** (e.g. a cheap `compile` + a heavy `build`); address a specific one with `{kind:id}` ([gate-tokens.md](./gate-tokens.md)). |
| `gates[].tier` | init | `cheap` (inline every phase) or `heavy` (deferred to `PF`). |
| `gates[].command` | init | The exact whole-repo command (from CI). |
| `gates[].scopedCommand` | init | **Optional** template for the cheap inline run; placeholders `{files}`, `{pkg}`, `{selector}`. **Omit it when no uniform per-module command exists** (some multi-target build tools expose per-target task names with no single per-module compile task) — fall back to the whole-repo `command`, or to a per-module umbrella task that is valid everywhere. |
| `gates[].fresh` | init | `true` for test gates that must force a non-cached run. |
| `gates[].threshold` | init | For `coverage` gates: minimum diff coverage %. |
| `models` | init / [model-tiers.md](./model-tiers.md) | The cheap/mid/top model ids `/develop:work` dispatches with. |
| `caps` | init / run | Loop bounds: validator rounds, audit rounds, fork rounds, between-phase gate rounds. |
| `intensity` | [verify-by-forking.md](./verify-by-forking.md) | `refuters` and `planCandidates` counts. `1` = lean default (no forking). |
| `routingFile` | init | Path to the routing table ([routing.md](./routing.md)). |
| `flywheelFile` | init | Path to the **human-curated** flywheel doc ([flywheel.md](./flywheel.md)). The machine SSOT is its sibling `.claude/develop-flywheel.jsonl`, which `PF` appends to; the `.md` is never written from a run. |

## Rules

- **Only commands the user confirmed go in `gates`.** No invented commands.
- The config is the contract between `/develop:init` (writer) and `/develop:work` (reader).
  A *command-gate* token on a plan node with no matching `gates[].id`/`kind` — **or a bare
  `{kind}` when several gates share that kind** (disambiguate with `{kind:id}`) — is a planner
  error; `{grep:<id>}` anchors self-resolve ([gate-tokens.md](./gate-tokens.md)).
- Defaults shown for `models`, `caps`, `intensity` are the lean starting point; the user
  edits them. `/develop:work` reads them every run, so edits take effect immediately.
- On a re-run, `/develop:init` reconciles this file rather than overwriting it (see
  [idempotency.md](./idempotency.md)).
