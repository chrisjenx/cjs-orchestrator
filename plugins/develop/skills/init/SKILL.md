---
name: init
description: Bootstrap a fitted /develop orchestration flow for THIS repo. Trigger on "init develop", "set up orchestration", "build my own develop flow", "scaffold an agentic pipeline", or any intent to stand up a spec-to-branch loop. Detects the stack, discovers the repo's real build/test/lint gates, and writes the per-repo definitions that the static /develop:run loop reads — it does NOT transplant another project's setup.
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
  - a starter `CLAUDE.md`, safe stack-agnostic hooks, and a `.claude/develop-flywheel.md`.
- **`/develop:run`** — the static orchestrator loop. It reads the definitions above, so it
  behaves fitted to the repo without being rewritten per repo.
- **Bundled references** (the portable mechanism, read by `/develop:run`, never copied into
  the repo): `references/plan-anatomy.md`, `references/executor-brief.md`,
  `references/gate-tokens.md`, `references/flywheel.md`, `references/routing.md`,
  `references/config-schema.md`, `references/schemas.md`, `references/stacks.md`.
- **Bundled agents** — portable, diff-reading auditors under `agents/`.

Reference files in this skill are relative to the plugin root (`${CLAUDE_PLUGIN_ROOT}`).
Read them as you reach each phase; don't paste their contents into the repo.

---

## Phase 0 — Re-run check (idempotent)

If `.claude/develop.config.json` already exists, this is a **re-run**. Do not clobber the
user's customisations. Follow [references/idempotency.md](../../references/idempotency.md):
detect the existing scaffold, compute a diff, and only add/update intentionally — showing
the diff before writing.

## Phase 1 — Detect the stack

Inspect the repo and produce a **stack summary the user confirms**, where every claim cites
a real file. Follow [references/stack-detection.md](../../references/stack-detection.md):

- Build tool / package manager, test runner, linter/formatter/type-checker, and CI — each
  with file evidence. **CI is the source of truth** for what "green" means.
- Detect per workspace in monorepos; record all matched ecosystems.
- For unrecognised ecosystems, degrade gracefully (see
  [references/stacks.md](../../references/stacks.md)): detect what you can, log what you
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
  ([references/flywheel.md](../../references/flywheel.md)).

The plan file, plan-anatomy, executor brief, and quality tail are **not** written here —
they live in the plugin and are used by `/develop:run` at runtime.

## Phase 4 — Install safe hooks only

Only stack-agnostic safety: worktree/uncommitted-work protection and generic command
timeouts. **Never** install a hook tied to a stack you didn't confirm. Follow
[hooks/README.md](../../hooks/README.md).

## Phase 5 — Dry run, then close the loop

- **Dry run** `/develop:run` on a trivial change; confirm the gates actually execute and a
  gate failure blocks. Report results to the user
  ([references/dry-run.md](../../references/dry-run.md)).
- Point the user at `.claude/develop-flywheel.md`: after each real run, classify every
  audit/review finding *preventable* vs *irreducible*; promote preventable ones to
  plan-time anchors. This is how the flow grows specialists and forks **only where repeated
  pain shows** — not by guessing up front.

---

## The portable moves (the only things carried in)

1. **State lives in a file** — the per-feature plan; crash-resume comes free.
2. **Narrow the context** — hand each agent its slice; the orchestrator holds only status.
3. **Route to specialists** — *later*: artifact shape → the right writer/reviewer. Start
   with one generalist.
4. **Tier the models** — cheap for mechanical, mid for code, top for hard judgement; pair
   writer vs reviewer.
5. **Verify by forking** — *later*: per claim, fork N skeptics to refute; N judged beats
   one iterated.
6. **Gates that can't be skipped** — machine-checkable commands with evidence, appended
   structurally.
7. **Close the loop** — feed review findings back into the planner; the line tightens every
   run.

## Start-minimal checklist

- [ ] Re-run check done (Phase 0)
- [ ] Stack detected and confirmed by the user
- [ ] Real gate commands discovered from CI, tagged cheap/heavy
- [ ] `develop.config.json` + `develop-routing.json` written
- [ ] Starter `CLAUDE.md` written
- [ ] Safe hooks only
- [ ] Dry run passes and a gate failure actually blocks
- [ ] Flywheel doc in place for the user to grow it over time

Philosophy and a worked case study: https://chrisjenx.github.io/cjs-orchestrator/
