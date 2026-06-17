---
name: init
description: Bootstrap a minimal, self-improving /develop orchestration flow fitted to THIS repo. Trigger on "init develop", "set up orchestration", "build my own develop flow", "scaffold an agentic pipeline", or any intent to stand up a spec-to-branch loop. Detects the stack, discovers the repo's real build/test/lint gates, and generates a minimal orchestrator that grows over time — it does NOT transplant another project's setup.
---

# Bootstrap a fitted `/develop` flow

You are standing up an agentic orchestration pipeline **fitted to the current repository**. The single most important rule:

> **Discover, don't transplant.** Most of a good `/develop` flow is bound to one repo — its gate commands, its specialist registry, its conventions. Copying another project's files installs assumptions that misfire. Read *this* repo, then generate a minimal flow grounded in *its* real commands.

The portable part is a small set of moves (below). Everything stack-specific must be discovered. Start minimal; let a feedback loop grow it.

Philosophy and a worked case study: https://chrisjenx.github.io/cjs-orchestrator/

---

## Phase 1 — Detect the stack

Inspect the repo (do not assume). Identify, with evidence from real files:

- **Build tool / package manager** — `package.json`, `build.gradle(.kts)`, `Cargo.toml`, `go.mod`, `pyproject.toml`, `Makefile`, etc.
- **Test runner** — from the same config + any `test`/`spec` scripts or tasks.
- **Linter / formatter** — eslint, ruff, detekt, golangci-lint, clippy, etc.
- **CI** — `.github/workflows/*`, `.gitlab-ci.yml`, etc. The CI file is the best source of truth for what "green" means here.

Output a short stack summary and ask the user to confirm or correct it before continuing.

## Phase 2 — Discover the real gates

This is the step a naive copy skips, and the one that matters most. Extract the **actual commands** that define "correct" in this repo — the ones CI runs:

- build, test, lint/format-check, type-check, coverage (if any).

Each becomes a **gate token**: a check that clears only because a command ran and produced evidence — never because an agent "felt done." Tag each gate `cheap` (run inline, every phase) or `heavy` (deferred to a final gate). Confirm the command list with the user.

## Phase 3 — Draft minimal

Generate the smallest thing that works. **Do not** scaffold specialists, routing tables, or parallel forking yet.

- **A plan file as the system of record** — phase nodes with statuses, an append-only log, a findings registry. Crash-resume = re-read it (skip DONE, re-enter the first IN_PROGRESS).
- **One generalist executor** — a single subagent that takes a phase brief and does the work for that slice. No registry of specialists on day one.
- **An orchestrator loop (this is the `/develop` skill it generates)** — walks the plan, dispatches one executor per phase, holds only phase status.
- **A fixed quality tail** — validate → audit → the repo's real gate commands → finalize, appended structurally so controls can't fall off the end.
- **A starter `CLAUDE.md`** — the repo's conventions as discovered, kept short.

Write these into the target repo's `.claude/` (skill + a single agent + a plan-anatomy doc). Show the user the diff before writing.

## Phase 4 — Install safe hooks only

Only stack-agnostic safety: worktree/uncommitted-work protection and generic command timeouts. **Never** install a hook tied to a stack you didn't confirm (e.g. a Gradle timeout hook in a Node repo).

## Phase 5 — Dry run, then close the loop

- **Dry run** the generated flow on a trivial change; confirm the gates actually execute and block on failure.
- **Write the flywheel doc.** After each real run, classify every audit/review finding as *preventable* (a plan-time check could have required it) or *irreducible*. Each preventable one becomes a new plan-time anchor the planner satisfies next run. This is how the flow grows specialists and forks **only where repeated pain shows** — not by guessing up front.

---

## The portable moves (the only things you may carry in)

1. **State lives in a file** — durable artifact, not in-memory context. Crash-resume comes free.
2. **Narrow the context** — hand each agent its slice verbatim; the orchestrator holds only status.
3. **Route to specialists** — *later*: map artifact shape → the right writer/reviewer. Start with one generalist.
4. **Tier the models** — cheap for mechanical, mid for code, top only for hard judgement; pair writer vs reviewer.
5. **Verify by forking** — *later*: per claim, fork N skeptics to refute; N judged beats one iterated.
6. **Gates that can't be skipped** — machine-checkable commands with evidence, appended structurally.
7. **Close the loop** — feed review findings back into the planner; the line tightens every run.

## Start minimal — a checklist

- [ ] Stack detected and confirmed by the user
- [ ] Real gate commands discovered from CI, tagged cheap/heavy
- [ ] Plan file + one generalist executor + orchestrator loop generated
- [ ] Quality tail wired to the repo's real gates
- [ ] Safe hooks only
- [ ] Dry run passes and a gate failure actually blocks
- [ ] Flywheel doc written for the user to grow it over time

> This skill is an early v0. The deeper per-phase automation (gate auto-discovery, registry generation, idempotent re-runs, multi-stack matrix) is tracked in the repo's issues. For now it guides you through the bootstrap; deepen it as the backlog lands.
