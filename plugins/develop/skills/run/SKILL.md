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
  ([config-schema.md](../../references/config-schema.md)). **If it's missing, stop and tell
  the user to run `/develop:init` first.**
- `.claude/develop-routing.json` — artifact-shape → specialist routing
  ([routing.md](../../references/routing.md)).
- The portable mechanism: [plan-anatomy.md](../../references/plan-anatomy.md),
  [executor-brief.md](../../references/executor-brief.md),
  [gate-tokens.md](../../references/gate-tokens.md),
  [quality-tail.md](../../references/quality-tail.md),
  [schemas.md](../../references/schemas.md).

## Control flow

### 1. Intake
Resolve the argument into a spec brief: a spec file/dir → read it; a ticket id/URL → fetch
it; an inline description → use it as-is. Derive a kebab `feature` name. Write the brief to
`<featureDir>/<feature>.spec.md`.

### 2. Worktree (isolation)
Work in an isolated git worktree so a run can't corrupt the user's workspace:
```
git worktree add .claude/worktrees/<feature> -b develop/<feature>
```
Capture its **absolute** path as `worktreeRoot`. **Hard-stop** if the resolved cwd is on
`main`/`master` or outside the worktree. If `origin/main` has advanced past the branch base,
rebase onto it first (a stale base poisons every diff). To resume an interrupted run, reuse
the existing worktree instead of creating one.

### 3. Assess
Read `develop.config.json`. Build the run config: classify scope (small/medium/large by
*new* work, not surface area), list touched areas, set `caps` and `intensity` from config
(lean defaults — no forking unless raised; see
[verify-by-forking.md](../../references/verify-by-forking.md)). Collect every blocking
unknown into `ambiguities`.

### 4. Clarify
If the spec is thin or `ambiguities` is non-empty, ask the user the blocking questions now
(`AskUserQuestion`) — this is the main human-in-the-loop seam. Fold answers into the brief.
Skip only when the spec is genuinely unambiguous.

### 5. Plan
Produce the plan file `<featureDir>/<feature>.plan.md` per
[plan-anatomy.md](../../references/plan-anatomy.md):
- A **Requirements Inventory** — every requirement a row, each with how it's *verified*
  (a gate token or grep anchor).
- An **Execution Strategy** — domain phases `### P1..Pn` with subtask nodes, `[agent:]`,
  `[depends:]`, `[loop:]`, and gate tokens placed on the node whose work they prove.
- Then **append the fixed quality tail** (`### PV`, `### PA`, `### PT`, `### PF`) — *you*
  append these, not the planner, so controls can't fall off the end
  ([quality-tail.md](../../references/quality-tail.md)).

**Pre-walk gate:** the plan must contain `### P` nodes and a Requirements Inventory. If not,
terminate `planning-failed` (no code written).

### 6. Walk the plan
Loop until no phase is ready:
1. Read the plan. Find the **first** phase that is not `DONE`/`BLOCKED` and whose
   `[depends:]` are all `DONE`.
2. Flip it `[status: IN_PROGRESS]` and append an Execution Log breadcrumb row **before**
   dispatching (survives a crash).
3. Render the [executor brief](../../references/executor-brief.md) — this phase's nodes
   verbatim, `worktreeRoot`, the config/routing slices, prior-phase handoff Notes, the
   Finding Registry. Inline excerpts, not the whole plan.
4. Dispatch **one** executor (`Agent`, `subagent_type: executor`, model = mid tier).
5. **Re-read the plan** to confirm the phase reached `DONE`/`BLOCKED` — trust the file, not
   the executor's reply message.
6. **Between-phase gate:** if the phase ended `BLOCKED` with unresolved HIGH findings or an
   `ESCALATE`, surface one `AskUserQuestion` (options include the tentative default) and
   fold the answer into the plan's `## Decisions`. Bounded by `caps.gate`; beyond that, fall
   through to the tentative default (logged). The phase may re-open.
7. Advance.

**Resume on crash:** re-invoking re-reads the plan, skips `DONE`, re-enters the first
`IN_PROGRESS` phase; its executor reconciles existing artifacts rather than regenerating.

### 7. Quality tail
PV → PA → PT → PF are ordinary phases in the walk, but with fixed logic — see
[quality-tail.md](../../references/quality-tail.md). In short: **Validate** the diff against
the Requirements Inventory, deep **Audit** (parallel auditors from [routing](../../references/routing.md)),
**Tidy** (reviewers + lint), **Finalize** (run every `DEFERRED-PF` heavy gate locally,
blocking until green, then commit — no push — and write the report + flywheel postmortem).

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

## Invariants
- The plan file is the only source of truth. Phase `[status:]` is rewritten in place;
  Execution Log / Finding Registry / Decisions are append-only.
- One executor per phase; the orchestrator never writes feature code.
- The quality tail is appended structurally before the walk; it cannot be skipped.
- Heavy gates run only in PF, blocking the commit until green.
