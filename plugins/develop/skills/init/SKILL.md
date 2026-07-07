---
name: init
description: Bootstrap a fitted /develop orchestration flow for THIS repo. Trigger on "init develop", "set up orchestration", "build my own develop flow", "scaffold an agentic pipeline", or any intent to stand up a spec-to-branch loop. Detects the stack, discovers the repo's real build/test/lint gates, and writes the per-repo definitions that the static /develop:work loop reads — it does NOT transplant another project's setup.
---

# Bootstrap a fitted `/develop` flow

You are standing up an agentic orchestration pipeline **fitted to the current repository**.

> **Discover, don't transplant.** Most of a good `/develop` flow is bound to one repo — its
> gate commands, its specialist registry, its conventions. Copying another project's files
> installs assumptions that misfire. Read *this* repo, then write definitions grounded in
> *its* real commands.

## How this plugin is structured (read first)

The plugin ships **static, portable skills**; per-project behaviour comes from
**definitions you discover and write**, not from generating a bespoke flow:

- **`/develop:init`** (this skill) — discovers the repo and writes the repo-specific
  definitions into `.claude/`:
  - `.claude/develop.config.json` — stack summary, the discovered gate commands (tagged
    cheap/heavy), build dir, model tiers, caps.
  - `.claude/develop-routing.json` — artifact-shape → specialist table (starts empty with a
    generalist fallback; grows via the flywheel).
  - a starter `CLAUDE.md`, safe stack-agnostic hooks, a `.claude/develop-flywheel.md`, and an
    empty `.claude/develop-flywheel.jsonl` (the append-only flywheel SSOT).
- **`/develop:work`** — the static orchestrator loop. It reads the definitions above, so it
  behaves fitted to the repo without being rewritten per repo.
- **Bundled references** — the portable mechanism in `references/`, read by `/develop:work`
  and by this skill per phase as linked below; never copied into the repo.
- **Bundled agents** (`agents/`, available because the plugin is installed — **not** copied
  into the repo): `planner`, `executor`, the diff-reading auditors (`completeness-auditor`,
  `stubs-auditor`, `regression-auditor`), `general-quality-reviewer`, `code-reviewer`, `tidy`,
  `refuter`. The
  repo's `develop-routing.json` references these by name; repo-specific specialists the user
  adds later live in the repo's own `.claude/agents/` (grown via the flywheel).

> **Reuse first, defer creation to workflows.** Both skills prefer the most specific
> *already-defined* skill / agent / rule (repo `.claude/` → bundled → available skills), and
> defer building anything missing/inadequate to a human-gated workflow rather than
> hand-rolling it ([references/reuse-and-defer.md](../../references/reuse-and-defer.md)).

Reference files in this skill are relative to the plugin root (`${CLAUDE_PLUGIN_ROOT}`).
Read them as you reach each phase; don't paste their contents into the repo.

---

## Phase pre-flight — probe worktree capability (non-blocking)

Early, run `${CLAUDE_PLUGIN_ROOT}/scripts/probe-worktree.sh <repo_root>` and record its status
(`ok` | `no-commits` | `blocked`). This is **non-blocking**: it *recommends* the worktree run
mode (the only supported mode) and its result feeds the Phase 5 gate; it does **not** hard-abort
init (a transient failure must not kill the bootstrap, and the gitignore fix is independent of
capability). The status word's meaning is defined once in the script header.

---

## Phase 0 — Re-run check + version migration (idempotent)

If `.claude/develop.config.json` already exists, this is a **re-run**. Do not clobber the user's
customisations. Follow [references/idempotency.md](../../references/idempotency.md): detect the
existing scaffold, compute a diff, and only add/update intentionally — showing the diff first.

Then check for a **plugin version gap**. Read the recorded `pluginVersion` from the config and
the live version from `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`, and compare with
`${CLAUDE_PLUGIN_ROOT}/scripts/version-compare.sh` — **absent recorded version ⇒ treat as
`0.6.0`** (the documented default, not an inference). On a gap (recorded `older` than live):
(1) run the idempotent **ensures** (Phase 3's gitignore lines; the guard is a plugin hook now, so
nothing to install); (2) run the **per-version cleanups** for every version newer than the
recorded one ([references/migrations.md](../../references/migrations.md)); (3) **stamp**
`pluginVersion` to the live version. Show the diff before writing, as always.

## Phase 1 — Detect the stack

Inspect the repo and produce a **stack summary the user confirms**, where every claim cites
a real file. Follow [references/stack-detection.md](../../references/stack-detection.md):

- Build tool / package manager, test runner, linter/formatter/type-checker, and CI — each
  with file evidence. **CI is the source of truth** for what "green" means.
- Detect per workspace in monorepos; record all matched ecosystems.
- For unrecognised ecosystems, degrade gracefully
  ([references/stacks.md](../../references/stacks.md)): detect what you can, log what you
  skipped, never block.

Output the stack summary and **ask the user to confirm or correct it before Phase 2.**

## Phase 2 — Discover the real gates

Turn the confirmed stack into the repo's **gate tokens** — checks that clear only because a
command ran and produced evidence. Follow [references/gate-tokens.md](../../references/gate-tokens.md):

- Extract the actual build / test / lint / format-check / type-check / coverage commands CI
  runs. The CI file is canonical; mirror its exact flags.
- Tag each gate `cheap` (runs inline, every phase) or `heavy` (deferred to the final gate).
- Confirm the command list with the user, then write it into `.claude/develop.config.json`
  per [references/config-schema.md](../../references/config-schema.md).

**Ship discovery (optional — for `/develop:ship`).** Seed the config's `ship` section
([config-schema.md](../../references/config-schema.md), [ship-watch.md](../../references/ship-watch.md)):
resolve `baseBranch` from `git symbolic-ref refs/remotes/origin/HEAD`; scan recent PR check-runs
(`gh pr checks` / recent runs) for a review-bot check name to offer as a `reviewBots[]` entry (leave
`[]` if none — it degrades fine); keep the neutral default `flakePatterns` and `caps`. Ask only the
one or two questions that need a human (which check is the review bot; the sticky beacon, if any);
default the rest. A repo that won't use `/develop:ship` can skip this entirely.

## Phase 3 — Write the per-repo definitions

Write (showing the diff first):

- `.claude/develop.config.json` — gates + stack + build dir + model tiers
  ([references/config-schema.md](../../references/config-schema.md),
  [references/model-tiers.md](../../references/model-tiers.md)).
- `.claude/develop-routing.json` — starts with a generalist fallback only
  ([references/routing.md](../../references/routing.md)).
- a starter `CLAUDE.md` from the discovered conventions, kept short
  ([references/claude-md-starter.md](../../references/claude-md-starter.md)).
- `.claude/develop-flywheel.md` — how the flow grows
  ([references/flywheel.md](../../references/flywheel.md)) — plus an **empty**
  `.claude/develop-flywheel.jsonl`, the append-only SSOT `PF` appends records to (create it
  empty so the first run can append).
- ensure the plugin-owned gitignore lines via `${CLAUDE_PLUGIN_ROOT}/scripts/gitignore-append.sh
  <repo_root> <pattern>` (idempotent, parent-dir aware — a re-run shows no spurious diff), called
  for **both** `<featureDir>` (default `.develop/`, so plan artifacts stay out of commits and out
  of any build-output dir a `clean` wipes) **and** `.claude/worktrees/` (the run-loop worktree
  cache, which `/develop:work` creates under `.claude/` — otherwise it leaks as untracked), plus
  `ship.durationsFile` (default `.claude/ship-ci-durations.json`) when the `ship` section was
  written. This is the only place init touches `.gitignore`; Phase 0's re-run references this ensure.

The plan file, plan-anatomy, executor brief, and quality tail are **not** written here —
they live in the plugin and are used by `/develop:work` at runtime.

## Phase 4 — Merge the command timeout only

The worktree-guard is an auto-loaded, self-gating plugin hook now — init does **not** copy it or
wire it into `settings.json`. Phase 4's only `settings.json` write is the generic command timeout
(`BASH_DEFAULT_TIMEOUT_MS` / `BASH_MAX_TIMEOUT_MS`): idempotent merge (present ⇒ keep the user's
value; absent ⇒ add), per [hooks/README.md](../../hooks/README.md). If the host **denies** the
merge (self-modification guard), emit **only** the `env` snippet for the user to paste and report
it as a required manual step — **never** re-emit a project-local guard copy.

**Prove the guard actually fires.** The guard is inert unless the plugin is enabled in this
context. Exercise it through the **live host** (not just by piping JSON into the script) as part
of the Phase 5 dry run; if the plugin is not enabled here, WARN as a hard Phase 5 report line
(marker present + plugin disabled = guard inactive; re-enable the plugin).

## Phase 5 — Dry run, then close the loop

- **Probe gate:** if the pre-flight worktree probe was `blocked` (or `no-commits`), the dry run
  cannot proceed — surface it as a hard report line (mirroring the v0.5.0 "required manual step"
  discipline), not a silent pass.
- **Dry run** `/develop:work` on a trivial change; confirm the gates actually execute, a gate
  failure blocks, and — through the live host — the guard **blocks destructive git from inside
  `.claude/worktrees/<feature>`**. Report results
  ([references/dry-run.md](../../references/dry-run.md)).
- Point the user at `.claude/develop-flywheel.md`: after each real run, classify every
  audit/review finding *preventable* vs *irreducible*; promote preventable ones to
  plan-time anchors. This is how the flow grows specialists and forks **only where repeated
  pain shows**, not by guessing up front.

---

## The portable moves (the only things carried in)

1. **State lives in a file** — the per-feature plan; crash-resume comes free.
2. **Narrow the context** — hand each agent its slice; the orchestrator holds only status.
3. **Route to specialists** — *later*: artifact shape → the right writer/reviewer. Start
   with one generalist.
4. **Tier the models** — cheap for mechanical, mid for code + diff review (writer vs reviewer
   split by effort), top reserved for planning/refutation.
5. **Verify by forking** — *later*: per claim, fork N skeptics to refute; N judged beats
   one iterated.
6. **Gates that can't be skipped** — machine-checkable commands with evidence, appended
   structurally.
7. **Close the loop** — feed review findings back into the planner; the line tightens every
   run.
8. **Reuse first, defer creation to workflows** — use the most specific already-defined
   skill/agent/rule; build anything missing/inadequate in a human-gated workflow, never
   inline ([references/reuse-and-defer.md](../../references/reuse-and-defer.md)).

## Start-minimal checklist

- [ ] Re-run check done (Phase 0)
- [ ] Stack detected and confirmed by the user
- [ ] Real gate commands discovered from CI, tagged cheap/heavy
- [ ] `develop.config.json` + `develop-routing.json` written
- [ ] Starter `CLAUDE.md` written
- [ ] Worktree probed (non-blocking); `.claude/worktrees/` + `<featureDir>` gitignored
- [ ] Command-timeout env merged; guard runs as the plugin hook (proved firing, incl. in-worktree)
- [ ] `pluginVersion` stamped; a version gap migrated per migrations.md
- [ ] Dry run passes and a gate failure actually blocks
- [ ] Flywheel doc + empty `.jsonl` SSOT in place for the flow to grow over time

Philosophy and a worked case study: https://chrisjenx.github.io/cjs-orchestrator/
