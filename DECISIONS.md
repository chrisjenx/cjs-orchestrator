# Decisions

Short, append-only record of decisions that are painful to reverse once there are
users. Newest first.

---

## 2026-07-07 — Lock a 4th public verb: `/develop:ship` (push → watch → merge)

The plugin ended at a committed branch by design (`/develop:work` never pushes). `/develop:ship`
adds the missing half: push, open the PR, then a mechanical watcher (`scripts/ship.py`, a
genericized port of our private babysit/commit-push-watch engine) babysits CI + review — waking the
agent only for judgment — and merges at green + approved + threads addressed.

- **Locked name/paths:** `/develop:ship`, `plugins/develop/skills/ship/`, engine
  `plugins/develop/scripts/ship.py`, agent `agents/ci-failure-extractor.md`.
- **Why `ship`:** it names the outcome (get the change merged) without over-claiming — and it was
  rejected for the *work* rename precisely because work never pushes, which is exactly why it fits
  the skill that does. Rejected `build` (collides with the build gates the plugin talks about) and
  `watch` (undersells that it commits/fixes/merges too).
- **Earns its place** by the same test `/develop:flywheel` passed: distinct **cadence** (per branch,
  after work — not per feature) and distinct **action** (remote CI/review babysitting + merge, not a
  local build). Overloading `work` with it would muddy work's "hands off a committed branch" contract.
- **Static + discovered:** the engine is stack-neutral; all repo specifics (base branch, review-bot
  identities, flake patterns, caps, ticket route) come from the init-written `ship` config section —
  the locked discover-don't-transplant doctrine, not a transplant of the private engine's config.

## 2026-07-06 — Rename the run skill `/develop:run` → `/develop:work` (reverses the 2026-06-17 lock)

Deliberately overturning the "Public names locked" entry below for one name. `/develop:run`
read ambiguously against "run the application" — a newcomer can't tell the orchestrator loop
from executing the built software. The trio is now **`/develop:init` · `/develop:work` ·
`/develop:flywheel`**. `work` names the action (turn a spec into a reviewed, committed branch)
without over-claiming: rejected `build` (collides with the build gates/tooling the plugin talks
about) and `ship` (the skill pointedly **never** pushes or opens a PR — it hands off a committed
branch).

- **Breaking, no alias.** `/develop:run` stops working; users re-learn one verb. Taken now
  because the user base is still small enough to absorb it — the same "while there are ~zero
  users" bet the original lock made, cashed in one direction.
- The common noun **"run"** (a single execution of the flow — "every run", "per-run state",
  "the run loop", "dry run") is unchanged; only the command/skill name moved.
- Current locked name: **Run skill → `/develop:work`**, `plugins/develop/skills/work/`. The
  2026-06-17 table below is left as the historical record of the original lock.

## 2026-06-17 — Per-run state stays markdown; flywheel gets a structured SSOT

Where durable state lives, decided per layer because the two layers have opposite needs.

- **Per-run plan/phase/gate state → the markdown plan file, unchanged.** Reject SQLite here:
  it's single-writer-per-feature (no concurrency for transactions to solve), and a binary in
  the hot loop trades away the plan's zero-dependency portability, git-diffability, hand-
  editability, and its role as the explainer's teaching artifact — for a marginal token win
  the executor brief already captures by inlining *excerpts, not the whole plan*. Resume is
  already solved by re-reading the file. If the orchestrator's between-phase read needs to be
  cheaper, lean on the existing `<!-- develop-state {…} -->` header (plan-anatomy.md) as the
  authoritative quick-read — zero new dependency.
- **Cross-run flywheel → add a structured SSOT.** This *is* the real multi-session problem
  (append-heavy, aggregated across many runs; recurrence counting is a `GROUP BY` on the
  `FINDING` fingerprint / `CONTRACT_GAP` records that already exist in schemas.md). Add an
  append-only `develop-flywheel.jsonl` (one record per run, fingerprinted) + a read-time
  aggregator (jq or a small bundled script) run **only** at `/develop:flywheel`.
  `develop-flywheel.md` stays the human-curated promoted-anchors narrative; the `.jsonl` is
  the machine SSOT that feeds it.
- **Defer SQLite** until JSONL aggregation actually hurts (hundreds of runs, real query/index
  needs) — the flywheel's own "earn the structure by repeated pain, never speculation" rule,
  applied to its own storage.

**Boundary principle (locked):** no new runtime dependency in the hot loop. Per-feature state
is plain-text append-only journals; any shared script lives at read/aggregate time only.

## 2026-06-17 — Public names locked

Renaming after install is painful (users have to re-add the marketplace, re-install,
and relearn the commands), so the public surface is locked **now**, while there are
zero users. Closes #1.

| Surface | Locked name | Where it lives |
|---|---|---|
| Marketplace | `cjs-orchestrator` | `.claude-plugin/marketplace.json` |
| Plugin | `develop` | `plugins/develop/.claude-plugin/plugin.json` |
| Bootstrap skill | `/develop:init` | `plugins/develop/skills/init/` |
| Run skill | `/develop:run` | `plugins/develop/skills/run/` |
| Flywheel skill | `/develop:flywheel` | `plugins/develop/skills/flywheel/` |

- The plugin namespace is `develop:`, so every plugin skill is invoked `develop:<skill>`.
- `/develop:run` is a **plugin** skill (not a generated project `/develop`). That is
  the only way the `develop:run` invocation works, and it keeps the run-loop versioned
  and upgradeable centrally.
- A third verb must earn its place. `/develop:flywheel` earned it: distinct **cadence**
  (periodic, between feature runs — not per feature, which `PF` already logs) and distinct
  **action** (cross-run postmortem evaluation + human-gated promotion). It is not a feature
  build, so overloading `/develop:run` with it would muddy that skill's contract.

## 2026-06-17 — Run-flow architecture: static skills, discovered definitions

The plugin ships **static, portable skills**; per-project behaviour comes from
**definitions the skills discover and read**, not from generating a bespoke skill per
repo. Resolves the #4–#7 architecture fork.

- **`/develop:init`** — *discovers* the repo (stack, real gate commands, conventions)
  and writes the repo-specific pieces into the target's `.claude/`:
  - `develop.config.json` — discovered gates (tagged cheap/heavy), build dir, stack
    summary, model tiers, caps.
  - `develop-routing.json` — artifact-shape → specialist table (starts empty, generalist
    fallback; grows via the flywheel).
  - starter `CLAUDE.md`, safe stack-agnostic hooks, a `flywheel.md`.
- **`/develop:run`** — the portable orchestrator loop. It is *static* (same for every
  repo) but *behaves tailored* because it reads `develop.config.json` + `develop-routing.json`
  and walks a per-feature `build/develop/<feature>.plan.md` it creates at runtime.
- **Bundled in the plugin** (portable mechanism, not copied per repo): the plan-anatomy,
  executor-brief, and gate-token references, plus the stack-agnostic auditor agents.

Why this over "generate a self-contained `.claude/skills/develop/` into the repo":
the orchestration *mechanism* is the same everywhere and benefits from central upgrades;
only the stack-specific *definitions* differ, and those are exactly what we discover.
This is "discover, don't transplant" applied precisely — we transplant only the portable
moves and discover everything bound to the repo.
