# Executor brief — the per-phase context the orchestrator renders

`/develop:run` dispatches the [`executor`](../agents/executor.md) agent **once per phase**
with a brief built from the plan + config. The brief is the *only* context the executor
gets — keep it tight (aim < ~1000 tokens). Inline **excerpts**, never the whole plan.

## What goes in (rendered per dispatch)

- **The phase's nodes, verbatim** — copied from the plan's Execution Strategy, this phase
  only, with their gate tokens and statuses intact.
- **`worktreeRoot`** — absolute path; every shell command uses it as cwd.
- **Config slice** — `featureDir`, the `gates` table (so the executor knows each token's
  command + tier), the `models` tier map, and the phase's `[loop: …]` policy.
- **Routing slice** — the routing table (so the executor routes its own children).
- **Prior-phase handoff** — the `Notes` column of completed phases' Execution Log rows,
  concatenated. This is how phase N learns what phase N-1 decided.
- **Current Finding Registry** — so new findings dedup against existing fingerprints.

## Template

```
You are the EXECUTOR for phase {Pn} ("{description}") of feature "{feature}".
Plan file (single source of truth): {planPath}
Worktree root (cwd for every shell command): {worktreeRoot}

## Your nodes — work these and nothing else
{verbatim node bullets for this phase, with {gate tokens} and [status:] intact}

## Gates available (token → command, tier)
{the relevant rows of config.gates}
Cheap gates run in your turn; annotate heavy gates DEFERRED-PF.

## Model tiers (for any children you dispatch)
{config.models}  — reviewer tier must differ from writer tier.

## Routing (route your own child writers/reviewers)
{routing table; generalist fallback if nothing matches}

## Handoff from prior phases
{concatenated Execution Log Notes of DONE phases}

## Open findings (dedup against these)
{Finding Registry rows}

## Discipline (load-bearing)
- Worktree gate: cwd = {worktreeRoot}; hard-stop if outside a worktree or on main/master.
  Read-only git only — never checkout/reset/stash/clean.
- Resume: if a node is IN_PROGRESS, reconcile existing artifacts (git diff + status); don't
  regenerate.
- Writeback BEFORE heavy work: flip node IN_PROGRESS + append a log row, do the work, run
  cheap gates, flip DONE/BLOCKED, append a closing row, write findings (FINDING schema,
  deduped).
- Scope fence: only the files your nodes name; anything else → write a finding, don't do it.
- Test-first: a node with a {test:<selector>} gate whose test is missing — write the failing test first, then make it pass.
- Loop: honour [loop: max N]; after N attempts set [status: BLOCKED] + an ESCALATE finding stating the reason.
- Escalate honestly: BLOCKED + name the reason on an ESCALATE finding over a silent guess; done-but-unsure → DONE + a quality concern finding (schemas.md).
- No narration: the orchestrator owns the status stream ([run-status.md](./run-status.md)) —
  you write the plan and return the three lines below, nothing more.

## Return — three lines only
ASSUMPTIONS: <one line>
STATUS: DONE | BLOCKED[:context|reasoning|too-large|plan] · nodes <done>/<total>
NESTED: <children spawned> · DEFERRED-PF: <tokens left for finalize>
```

## Why excerpts, not the whole plan

A fresh executor with the whole plan is slower, costs more, and is tempted to work outside its
slice. Two exceptions warrant a full read: a **mid-flight resume** (reconcile against
everything done so far) and a **consolidation pass** (an auditor deduping across all findings).
Otherwise: excerpts only.
