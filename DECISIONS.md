# Decisions

Short, append-only record of decisions that are painful to reverse once there are
users. Newest first.

---

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

- The plugin namespace is `develop:`, so every plugin skill is invoked `develop:<skill>`.
- `/develop:run` is a **plugin** skill (not a generated project `/develop`). That is
  the only way the `develop:run` invocation works, and it keeps the run-loop versioned
  and upgradeable centrally.
- Avoid a third top-level verb unless it earns its place; prefer arguments/flags on the
  two existing skills.

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
