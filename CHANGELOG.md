# Changelog

All notable changes to the `develop` plugin are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the plugin version is in
`plugins/develop/.claude-plugin/plugin.json` and follows [SemVer](https://semver.org/).
See [RELEASING.md](RELEASING.md) for how releases are cut and the version policy.

## [Unreleased]

### Added
- **`/develop:flywheel` skill**: the manually-triggered tuner (third plugin skill). Reads
  the accumulated postmortems in `.claude/develop-flywheel.md`, flags recurring (≥2 runs) or
  breaking-class finding categories, and proposes the cheapest remediation lever and concrete
  target for each (reuse-first), human-gated. It applies simple deterministic levers directly
  and defers agent/skill/rule builds to a workflow. This is the act-on-the-postmortems half
  that was previously only described, not scaffolded.
- **`planner` agent**: `/develop:run` now dispatches a planner (reuse survey → Requirements
  Inventory and Execution Strategy as structured `PLAN`) instead of planning inline, which
  keeps the orchestrator thin.
- **`code-reviewer` agent**: reviews the diff against the repo's *own* rules (`CLAUDE.md`) plus
  requirement compliance; the default PT reviewer alongside `general-quality`.
- **`tidy` agent**: the PT cleanup worker (repo's own lint/format autofix, removes
  leftovers, applies low-risk fixes).
- **`references/reuse-and-defer.md`**: the reuse-first and defer-creation-to-workflows
  principle (and the 8th portable move). Prefer already-defined skills/agents/rules; build
  anything missing or inadequate in a human-gated workflow, never inline. Wired through the
  planner, routing (growth *and* pruning), the flywheel levers, and both skills.

### Changed
- `develop-routing.json` default reviewers now include `code-reviewer`.

## [0.2.0] - 2026-06-17

First full build of the orchestration system. The plugin grew from a single high-level
bootstrapper into static, portable skills that read per-repo discovered definitions.

### Added
- **`/develop:run`**: the static orchestrator loop (Intake → Worktree → Assess → Clarify →
  Plan → Walk → quality tail → Relay), dispatching one executor per phase and holding only
  phase status.
- **Portable mechanism references** (`plugins/develop/references/`): plan anatomy, executor
  brief, gate tokens, the quality tail (PV/PA/PT/PF), schemas, the flywheel and planwork-sync,
  routing, the config schema, model tiers, the multi-stack matrix, stack detection,
  CLAUDE.md starter, the dry-run protocol, idempotency, and verify-by-forking.
- **Bundled stack-agnostic agents** (`plugins/develop/agents/`): the generalist `executor`,
  diff-reading `completeness` / `stubs` / `regression` auditors, a `general-quality`
  reviewer, and the adversarial `refuter`.
- **Safe hooks** (`plugins/develop/hooks/`): a worktree/destructive-git guard plus a generic
  command timeout, installed by merge (never overwrite), nothing stack-tied.
- **Templates** (`plugins/develop/templates/`): `develop.config.json`, `develop-routing.json`,
  the plan skeleton, `CLAUDE.md`, and the flywheel doc.
- **Eval harness** (`evals/`): triggering matrix plus stack fixtures (node-ts, python-uv,
  go-mod, unknown-stack) with `expected.json`, plus the install e2e checklist.
- **CI and verification scripts** (`.github/workflows/ci.yml`, `scripts/`): manifest and
  install-structure validation, docs subpath check, and a deterministic docs leak scan;
  optional `.githooks/pre-commit`.
- **DECISIONS.md**: locked public names and the static-skills/discovered-definitions
  architecture.

### Changed
- **`/develop:init`** rebuilt around the locked architecture: detailed stack detection,
  gate-command discovery, writing per-repo definitions, safe-hook install, dry-run
  verification, and idempotent (reconcile-not-clobber) re-runs.
- Explainer "build your own" now points at `/develop:init` and gained a `#ship` install
  section (replacing the "coming soon" placeholder).
- READMEs and CLAUDE.md updated to the two-skill UX and locked architecture.

## [0.1.0] - initial

- Marketplace and `develop` plugin (v0): the `/develop:init` bootstrapper skill and the
  genericized explainer site.

[Unreleased]: https://github.com/chrisjenx/cjs-orchestrator/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.2.0
[0.1.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.1.0
