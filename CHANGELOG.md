# Changelog

All notable changes to the `develop` plugin are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the plugin version is in
`plugins/develop/.claude-plugin/plugin.json` and follows [SemVer](https://semver.org/).
See [RELEASING.md](RELEASING.md) for how releases are cut and the version policy.

## [Unreleased]

### Added
- **Flywheel escape ingestion.** `/develop:flywheel` now pulls confirmed escapes (PR-review
  comments you agreed to, and CI failures) into the SSOT over two mechanical GitHub paths (a
  connected MCP server, else the `gh` CLI), attributes each to the phase that should have caught
  it (`escaped_phase`), and treats it as promotion-ready at x1 (a proven miss, versus >=2
  recurrences for an internal residual). A new bundled `scripts/flywheel-ingest.py` fills the
  phase/lever mapping deterministically (selftested in CI), and `flywheel-aggregate.py` flags
  escapes distinctly.

### Changed
- `references/quality-tail.md` (PF step 2, PT): run any long fix/review loop (coverage tuning,
  flaky-test soak, a lint cluster, reviewer-finding validation) in its own nested subagent group
  that returns only the conclusion, protecting the orchestrator's context. Agent spend can stay
  well under budget while the orchestrator's own context exhausts on inline gate churn; the two
  metrics decouple. (#29)
- `references/quality-tail.md` (PF): document two diff-coverage gate traps: commit before the
  coverage gate (an uncommitted tree shows zero changed files and passes vacuously), plus a
  scoped-coverage fallback when an environmental flake blocks the full suite. (#28)

## [0.3.0] - 2026-06-19

First tagged release. The orchestration system from `[0.2.0]` plus its third skill and the
reuse-first planner/reviewer/tidy agents, hardened by a full validation sweep and code review.

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

### Fixed
- **Build gate** now uses the build tool's whole-project umbrella (e.g. `gradle assemble`)
  rather than a single module's compile, so it catches breakage anywhere a change touches.
- **`/develop:run` loop coherence**: `{grep:<id>}` anchors self-resolve (no longer tripping
  the unrecognised-token rule); the flywheel machine SSOT (`.jsonl`) and human doc (`.md`) are
  unambiguous; `PV` derives its verdict from a reviewer's `FINDINGS`; the quality tail states
  its model tiers; locked auditor names are used consistently.
- **`worktree-guard.sh`** hardened with command-position matching that closes the
  `git -C <dir>` / `--git-dir` and detached-HEAD bypasses and stops false positives like a
  command that merely mentions `git commit` in a string.
- **Eval harness** (`evals/scaffold-eval.md`, `scripts/check-scaffold.py`): validates the full
  `.claude/` scaffold init writes, with a deterministic `--selftest` wired into CI.

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

[Unreleased]: https://github.com/chrisjenx/cjs-orchestrator/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.3.0
[0.2.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.2.0
[0.1.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.1.0
