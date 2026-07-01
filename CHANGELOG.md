# Changelog

All notable changes to the `develop` plugin are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the plugin version is in
`plugins/develop/.claude-plugin/plugin.json` and follows [SemVer](https://semver.org/).
See [RELEASING.md](RELEASING.md) for how releases are cut and the version policy.

## [Unreleased]

## [0.7.0] - 2026-06-30

Hardens how `/develop:init` provisions and upgrades a repo for the worktree run loop, and gives
existing projects a version-anchored upgrade path. Unlike 0.6.0, this changes what init writes,
so existing projects pick up the fixes by re-running `/develop:init` (see Notes).

### Added
- **Worktree capability probe + worktree-cache gitignore.** init now runs a non-blocking
  `probe-worktree.sh` (live add/remove oracle, no git-version parsing, zero-commit aware, trap
  cleanup in system temp) and gitignores `.claude/worktrees/` as well as `<featureDir>` via a new
  idempotent, parent-dir-aware `gitignore-append.sh`. The Phase 5 dry run gates on the probe.
- **Version-anchored migrations.** A new init-managed `pluginVersion` config field plus
  `version-compare.sh` (POSIX) let Phase 0 detect a plugin gap (absent => treated as 0.6.0), run
  per-version cleanups from a single `references/migrations.md`, and stamp the version.
- **CI determinism + coherence guards.** `validate-manifests.py` gains a POSIX-bashism lint over
  all shipped `plugins/develop/**/*.sh`, a guard-contract check, and an init-coherence check, each
  selftested.

### Changed
- **Worktree-guard is now an auto-loaded plugin hook** (`${CLAUDE_PLUGIN_ROOT}`) that **self-gates**
  to develop-managed repos via `git --git-common-dir`, so it enforces from inside a worktree too
  and is inert elsewhere. init no longer copies the guard or wires it into `settings.json`; Phase 4
  now only merges the command-timeout env (with an env-only manual-paste fallback on host denial).

### Fixed
- **Guard could fail open.** A guard installed at project scope with a `$CLAUDE_PROJECT_DIR` path
  misfired in every project and, from inside a worktree, did not enforce at all. The plugin-hook +
  self-gate fixes both.
- **Worktree cache leaked as untracked.** init never gitignored `.claude/worktrees/`, so a run's
  worktree showed up as untracked in the main checkout.

### Notes
- **Re-run `/develop:init` to upgrade.** v0.7.0 changes what init writes, so existing projects pick
  up the fixes by re-running init: Phase 0 detects the `pluginVersion` gap (or its absence => 0.6.0),
  removes an obsolete copied `.claude/hooks/worktree-guard.sh` + its `settings.json` entry when it is
  plugin-shipped (marker-detected; a user-customised guard is flagged, not deleted), ensures the
  `.claude/worktrees/` gitignore line, and stamps `pluginVersion`. The guard runs as an auto-loaded
  plugin hook (takes effect on next session or `/reload-plugins`).

## [0.6.0] - 2026-06-24

Sharpens three parts of the run loop: how the executor escalates when stuck, when tests get
written, and what review catches. The plugin changes are static prose (existing init'd projects
pick them up on plugin update, see Notes); the only non-prose change is a CI validator.

### Added
- **Executor escalates with a classified reason.** When a phase blocks, the executor records the
  reason (`context`, `reasoning`, `too-large`, or `plan`) on its `ESCALATE` finding, so the
  between-phase gate can show you *why* and you decide knowingly instead of seeing a bare
  "blocked". A new `check_status_contract` in `validate-manifests.py` keeps the executor's STATUS
  line in sync across `executor.md` and `executor-brief.md` and its reason set aligned with
  `schemas.md`, so the grammar cannot drift in CI.
- **Test-first discipline for test-verified requirements.** A node carrying a
  `{test:<selector>}` gate is worked test-first: the executor writes the failing test before the
  implementation, then makes it pass. The planner places a test-verified requirement's gate on
  the implementing node. Scoped to test-gated nodes, so scaffold and config phases are
  unaffected.
- **Over-build (YAGNI) review lens.** `code-reviewer` now flags substantial unrequested behavior
  or abstraction as a finding, the complement to the requirement-compliance check (which only
  catches under-building).

### Notes
- **No re-init required.** The shipped skills, references, and agents changed, but nothing
  `/develop:init` writes into a target repo did. Existing projects get the new behavior on the
  next `/develop:run` after the plugin updates, with no migration. (The `validate-manifests.py`
  change is a CI check for this repo only; it does not touch target repos.)

## [0.5.0] - 2026-06-23

Fixes the gaps a real init + dry run on a multi-target monorepo surfaced, and hardens the gate
contract so they cannot silently recur.

### Added
- **Multiple gates per kind + addressable tokens.** A compiled stack can define both a cheap
  per-module compile and a heavy umbrella build as two `build`-kind gates; a node addresses one
  with `{kind:id}` (e.g. `{build:compile}`). Backwards-compatible: bare `{kind}` still works when
  a kind has a single gate. `scopedCommand` is now explicitly optional with a multi-target
  umbrella fallback. (#31, #34)

### Fixed
- **init `featureDir` default** is now `.develop` (hidden, git-ignored by init) instead of
  `build/develop`, which a build `clean` wipes mid-run; a validate-manifests guard blocks any
  build-output featureDir. (#2)
- **Phase 4 hook install** degrades gracefully when the host denies the `settings.json` merge:
  it emits the exact snippet to paste and reports a required manual step instead of leaving the
  guard silently inert. (#32)
- **`/develop:run` worktree step** reuses an already-isolated worktree instead of nesting, resolves
  the new worktree against the main repo root, and reads config from the main checkout. (#33)
- **CI gate discovery** is now an enforced per-job/per-step exhaustiveness contract that counts
  guard-style `exit 1` checks as gating and echoes the list back at the confirm seam, with a
  dry-run completeness re-check. Prevents a guard being missed. (#3)
- **planner** emits the canonical gate-token grammar; a validate-manifests guard lints gate-token
  examples in the references. (#34)

## [0.4.1] - 2026-06-23

Makes the plugin installable. v0.4.0 could not be installed at all; three separate schema
problems each blocked `claude plugin install develop@cjs-orchestrator`, and CI did not catch any
of them.

### Fixed
- **Install was broken (#30), three causes, all now gated in CI:**
  - `marketplace.json` gave the plugin `source` as a bare name (`"develop"`) and relied on
    `metadata.pluginRoot` to prefix it. Claude Code does not honor `pluginRoot` for a string
    source, so install failed with "this plugin uses a source type your Claude Code version does
    not support." The source is now a full relative path (`"./plugins/develop"`) and the unused
    `metadata` block is removed.
  - `plugin.json` declared `"agents": "./agents/"`. The schema rejects a directory string for
    `agents` (it expects a file-path array). The field is dropped so the `agents/` directory is
    auto-discovered; all 9 agents still load.
  - Six of the nine agent files had an unquoted `: ` (colon-space) inside their `description`
    frontmatter, which fails YAML parsing. Each affected agent loaded with empty metadata, so
    routing by agent name broke even once install succeeded. All agent descriptions are now
    quoted.
- `validate-manifests.py` now also checks the marketplace source shape, the `agents` field type,
  and that every shipped agent/skill frontmatter parses as YAML with a name and description, with
  a selftest wired into CI, so this class of install break cannot ship again.

## [0.4.0] - 2026-06-23

The flywheel learns from downstream signal (PR review + CI), and the quality tail protects the
orchestrator's own context.

### Added
- **Flywheel escape ingestion.** `/develop:flywheel` now pulls confirmed escapes (PR-review
  comments you agreed to, and CI failures) into the SSOT over two mechanical GitHub paths (a
  connected MCP server, else the `gh` CLI, using GraphQL resolved-thread + per-commit check-run
  data), attributes each to the phase that should have caught it (`escaped_phase`), and treats it
  as promotion-ready at x1 (a proven miss, versus >=2 recurrences for an internal residual).
  Ingestion is idempotent: each escape is stamped with its source PR id and `flywheel-ingest.py`
  dedups against the SSOT on `(run, fingerprint)`, so re-scanning the same PRs is safe. A new
  bundled `scripts/flywheel-ingest.py` fills the phase/lever mapping deterministically (selftested
  in CI), and `flywheel-aggregate.py` flags escapes distinctly.

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

[Unreleased]: https://github.com/chrisjenx/cjs-orchestrator/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.7.0
[0.6.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.6.0
[0.5.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.5.0
[0.4.1]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.4.1
[0.4.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.4.0
[0.3.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.3.0
[0.2.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.2.0
[0.1.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.1.0
