---
name: run
description: Run the fitted /develop orchestration loop for THIS repo — turn a spec, ticket, or rough idea into a reviewed, committed branch. Trigger on "/develop:run", "develop this", "run the develop flow", "spec to branch", or handing this skill a spec/ticket/description. Requires /develop:init to have written .claude/develop.config.json. Walks a per-feature plan file, dispatches one executor per phase, and runs a fixed quality tail wired to the repo's real gates. Static loop; behaviour is fitted because it reads the repo's discovered definitions.
---

# Run the `/develop` loop

You are the **orchestrator**. You hold only "which phase am I on"; everything durable lives
in the plan file. You dispatch one [`executor`](../../agents/executor.md) per phase and you
never write feature code yourself.

## Read first (every run)

- `.claude/develop.config.json` — the repo's gates, stack, model tiers, caps
  ([config-schema.md](../../references/config-schema.md)). Read it from the **main checkout**
  (the `--git-common-dir` parent), since it may be uncommitted and so absent on a fresh worktree
  branch. **If it's genuinely missing there, stop and tell the user to run `/develop:init` first.**
- `.claude/develop-routing.json` — artifact-shape → specialist routing
  ([routing.md](../../references/routing.md)).
- The portable mechanism: [plan-anatomy.md](../../references/plan-anatomy.md),
  [executor-brief.md](../../references/executor-brief.md),
  [gate-tokens.md](../../references/gate-tokens.md),
  [quality-tail.md](../../references/quality-tail.md),
  [schemas.md](../../references/schemas.md),
  [run-status.md](../../references/run-status.md),
  [reuse-and-defer.md](../../references/reuse-and-defer.md).

**Reuse first, defer creation to workflows.** At every step that needs a capability — plan,
write, review, audit, enforce a rule — use the most specific *already-defined* skill / agent /
rule (repo `.claude/` → bundled agents → available skills). When nothing fits or an existing
one is inadequate, **don't hand-roll it inline** — record the gap and defer creation/
improvement to a human-gated workflow. See
[reuse-and-defer.md](../../references/reuse-and-defer.md).

## Status output (what someone dropping in sees)

A run is fire-and-forget, so make it glance-readable: emit **one status line per transition**
— `▸` started · `✓` done/green · `⚠` needs a decision · `✗` failed/blocked — with the real
phase ids and gate tokens ([run-status.md](../../references/run-status.md)). The line
**replaces** prose narration; only the orchestrator narrates. The `say:` cues below give the
exact line. Keep everything you write and dispatch terse —
[token-frugality.md](../../references/token-frugality.md) is the first principle.

## Control flow

### 1. Intake
Resolve the argument into a spec brief: a spec file/dir → read it; a ticket id/URL → fetch
it; an inline description → use it as-is. Derive a kebab `feature` name. Write the brief to
`<featureDir>/<feature>.spec.md`.
_say:_ `▸ intake · spec → feature <feature>` (feature name in backticks)

### 2. Worktree (isolation)
Work in an isolated git worktree so a run can't corrupt the user's workspace.

**First, detect an already-isolated session.** If cwd is already inside a worktree under
`.claude/worktrees/` (host `EnterWorktree` / a background job pins cwd there), **reuse it** as
`worktreeRoot` — do not create a nested worktree. Otherwise create one, resolving the path
against the **main repo root** (never cwd, which would nest):
```
root=$(git rev-parse --path-format=absolute --git-common-dir)/..   # main checkout, not this worktree
git -C "$root" worktree add "$root/.claude/worktrees/<feature>" -b develop/<feature>
worktreeRoot=$(git -C "$root/.claude/worktrees/<feature>" rev-parse --show-toplevel)   # clean canonical path
```
Either way, `worktreeRoot` is the worktree's **canonical absolute** path (on reuse, the current
worktree; on create, the line above). **Hard-stop** if the resolved cwd is on `main`/`master` (and
not in a worktree). If `origin/main` has advanced past the branch base,
rebase onto it first (a stale base poisons every diff). To resume an interrupted run, reuse the
existing worktree instead of creating one.
_say:_ `▸ worktree · develop/<feature>`

### 3. Assess
Read `develop.config.json`. Build the run config: classify scope (small/medium/large by
*new* work, not surface area), list touched areas, set `caps` and `intensity` from config
(lean defaults — no forking unless raised; see
[verify-by-forking.md](../../references/verify-by-forking.md)). Collect every blocking
unknown into `ambiguities`.
_say:_ `▸ assess · scope <s> · areas <list> · caps <profile>`

### 4. Clarify
If the spec is thin or `ambiguities` is non-empty, ask the user the blocking questions now
(`AskUserQuestion`) — this is the main human-in-the-loop seam. Fold answers into the brief.
Skip only when the spec is genuinely unambiguous.
_say:_ `⚠ clarify · <n> questions` (only when asking; skip the line when the spec is clear)

### 5. Plan
Dispatch the [`planner`](../../agents/planner.md) agent (top tier) with the spec brief +
config + routing — so the spec-and-repo planning context stays out of *your* head. It runs a
reuse survey (reuse existing code, route nodes to already-defined agents, fold in the repo's
rules + contract anchors) and returns a structured `PLAN`
([schemas.md](../../references/schemas.md)). Render it into the plan file per
[plan-anatomy.md](../../references/plan-anatomy.md):
- A **Requirements Inventory** — every requirement a row, each with how it's *verified*.
- An **Execution Strategy** — the planner's domain phases `### P1..Pn` with subtask nodes,
  `[agent:]`, `[depends:]`, `[loop:]`, and gate tokens on the node whose work they prove.
- Then **append the fixed quality tail** (`### PV`, `### PA`, `### PT`, `### PF`) — *you*
  append these, not the planner, so controls can't fall off the end
  ([quality-tail.md](../../references/quality-tail.md)).
- If the planner returns `gaps` (a slice no existing agent/skill/rule covers), surface them:
  route the slice to the generalist `executor` for now and offer to **defer** building the
  missing capability to a workflow ([reuse-and-defer.md](../../references/reuse-and-defer.md)).

_say:_ `▸ plan · planner…` then `✓ plan · <p> phases · <r> reqs · <a> agents routed`

**Pre-walk gate:** the plan must contain `### P` nodes and a Requirements Inventory. If not,
terminate `planning-failed` (no code written).

### 6. Walk the plan
Loop until no phase is ready:
1. Read the plan. Find the **first** phase that is not `DONE`/`BLOCKED` and whose
   `[depends:]` are all `DONE`.
2. Flip it `[status: IN_PROGRESS]` and append an Execution Log breadcrumb row **before**
   dispatching (survives a crash). _say:_ `▸ <Pn> <short name> · <agent>…`
3. Render the [executor brief](../../references/executor-brief.md) — this phase's nodes
   verbatim, `worktreeRoot`, the config/routing slices, prior-phase handoff Notes, the
   Finding Registry. Inline excerpts, not the whole plan.
4. Dispatch **one** executor (`Agent`, `subagent_type: executor`, model = mid tier).
5. **Re-read the plan** to confirm the phase reached `DONE`/`BLOCKED` — trust the file, not the
   executor's reply message. _say:_ `✓ <Pn> · done <x>/<y> · {gate}✓ …` (or
   `✗ <Pn> · blocked · <reason>`).
6. **Between-phase gate:** if the phase ended `BLOCKED` with unresolved HIGH findings or an
   `ESCALATE`, surface one `AskUserQuestion` (options include the tentative default) and fold
   the answer into the plan's `## Decisions`. When an `ESCALATE` finding carries an
   `escalate:<reason>` ([schemas.md](../../references/schemas.md)), show that reason so the human
   chooses knowingly. Bounded by `caps.gate`; beyond that, fall through to the tentative default
   (logged). The phase may re-open. _say:_ `⚠ <Pn> · <reason or finding> → asking`.
7. Advance.

**Resume on crash:** re-invoking re-reads the plan, skips `DONE`, re-enters the first
`IN_PROGRESS` phase; its executor reconciles existing artifacts rather than regenerating.
All phases `DONE` + new scope → new run: new plan file, `Continuation of:` header — never
append to a discharged plan ([plan-anatomy.md](../../references/plan-anatomy.md)).

### 7. Quality tail
PV → PA → PT → PF are ordinary phases in the walk, but with fixed logic — see
[quality-tail.md](../../references/quality-tail.md). In short: **Validate** the diff against
the Requirements Inventory, deep **Audit** (parallel auditors + `code-reviewer` from
[routing](../../references/routing.md)), **Tidy** (the [`tidy`](../../agents/tidy.md) worker +
reviewers), **Finalize** (run every `DEFERRED-PF` heavy gate locally, blocking until green,
then commit — no push — write the report, and append one `FLYWHEEL_RECORD` per residual
finding to `.claude/develop-flywheel.jsonl`, the machine SSOT).
_say:_ one line per tail phase — `▸ PV validate · pass`, `✓ PA · <n> findings → fixed`,
`▸ PT tidy · clean`, `▸ PF finalize · {build}✓ {test}✓ {cov>=80}✓`.

### 8. Relay
Derive the terminal status **mechanically** from the plan's Decisions/finding state and the
finalize result — never from prose:

| Status | Meaning |
|---|---|
| `ready` | all phases DONE, every gate green |
| `ready-with-escalations` | phases DONE, unresolved escalations surfaced |
| `committed-with-failures` | committed, but a heavy gate failed (a real defect) |
| `commit-failed` | finalize blocked the commit (unresolved finalize escalations) |
| `planning-failed` | no code written (plan missing `### P` nodes) |

Report status, the commit SHA, open findings, and escalations. **Never push and never open a
PR** — `/develop:run` hands off a committed branch; the user (or a separate push/PR flow)
takes it from there.
_say:_ the final line is the mechanical status — `✓ committed <sha> · ready` (or
`⚠ … · ready-with-escalations`, `✗ … · committed-with-failures` / `commit-failed` /
`planning-failed`).

## Invariants
- The plan file is the only source of truth. Phase `[status:]` is rewritten in place;
  Execution Log / Finding Registry / Decisions are append-only.
- One executor per phase; the orchestrator never writes feature code (and never plans in its
  own head — the `planner` does that).
- Reuse first; defer creation of any missing/inadequate skill/agent/rule to a human-gated
  workflow — never hand-roll it inline ([reuse-and-defer.md](../../references/reuse-and-defer.md)).
- The quality tail is appended structurally before the walk; it cannot be skipped.
- Heavy gates run only in PF, blocking the commit until green.
- **Token frugality is the first principle** ([token-frugality.md](../../references/token-frugality.md)):
  one status line per transition (never a paragraph; only the orchestrator narrates), excerpts
  not whole files in briefs, fixed short return contracts. A wasted token compounds every run.
