# Plan anatomy — the plan file IS the system of record

`/develop:run` keeps **all** durable state in one markdown file per feature:
`<featureDir>/<feature>.plan.md` (default `build/develop/<feature>.plan.md`). Context is
volatile; the plan is not. Everything the loop needs to resume after a crash is in this
file — the orchestrator holds only "which phase am I on" in working memory.

> **Why a file, not memory:** crash-resume comes free. Re-reading the plan reconstructs the
> entire run: skip `DONE`, re-enter the first `IN_PROGRESS`, continue. No separate state
> store, no lost work.

## Section order

```markdown
# <feature> — plan

<!-- develop-state
{ "feature": "...", "worktreeRoot": "...", "configSnapshot": {...}, "agentCount": 0 }
-->

## Requirements Inventory
| # | Requirement | Area(s) | Verified by | Status |
|---|---|---|---|---|
| R1 | ... | ui / api / data | {test:...} or {grep:...} | open |

## Execution Strategy
### P1 — <description> [depends: ] [status: PENDING] [loop: max 2, commit_on_green]
- P1.a <action> [agent: executor] [status: PENDING] {build} {test:<selector>}
- P1.b <action> [agent: executor] [status: PENDING] [depends: P1.a] {types}

### P2 — <description> [depends: P1] [status: PENDING] [loop: max 2]
- P2.a ...

### PV — Validate [depends: <all domain phases>] [status: PENDING]
### PA — Audit [depends: PV] [status: PENDING]
### PT — Tidy [depends: PA] [status: PENDING]
### PF — Finalize [depends: PT] [status: PENDING]

## Execution Log
| Phase | Subtask | Status | When | Notes |
|---|---|---|---|---|

## Finding Registry
| Fingerprint | Phase | Severity | Status | Note |
|---|---|---|---|---|

## Decisions
| Gate id | Kind | Round | Resolution | Note |
|---|---|---|---|---|
```

## Phase nodes

- A **phase** is a `### P<n> — <description>` heading carrying machine-readable tags:
  - `[status: PENDING | IN_PROGRESS | DONE | BLOCKED]` — the single source of phase truth.
  - `[depends: P1, P2]` — phase is *ready* only when not DONE/BLOCKED and every listed
    dependency is `DONE`. A terminal `BLOCKED` dependency blocks its dependents.
  - `[loop: max <N>, commit_on_green]` — loop policy (see below).
- A phase contains **subtask bullets** `- P<n>.<x> <action>` carrying their own
  `[agent: ...]`, `[status: ...]`, optional `[depends: ...]`, and gate tokens `{…}` (see
  [gate-tokens.md](./gate-tokens.md)).
- The **planner** emits the domain phases (P1..Pn). The **orchestrator** appends the fixed
  quality tail (PV, PA, PT, PF) *before* the walk begins, so controls can't fall off the
  end — see [quality-tail.md](./quality-tail.md).

### Status lifecycle

```
PENDING ──▶ IN_PROGRESS ──▶ DONE        (all node gates pass / deferred to PF)
                   │
                   └──────▶ BLOCKED      (cheap gate fails after loop exhausted,
                                          or a dependency is terminally BLOCKED)
```

### Loop policy

`[loop: max N, commit_on_green]` on a phase:
- A failed **cheap** gate re-dispatches the phase with the gate's evidence, up to `N` times.
- After `N` attempts still failing → `BLOCKED` + an `ESCALATE` finding.
- `commit_on_green` → when all the phase's nodes are `DONE` with cheap gates green, the
  executor records a green commit (no push) as a resume checkpoint.

## Append-only journals

These are **never rewritten**, only appended — that's what makes resume safe:

- **Execution Log** — one row per dispatch. The orchestrator appends a row *before*
  dispatching a phase (the breadcrumb that survives a crash) and the executor appends a
  closing row with results. The `Notes` column carries the handoff a later phase needs.
- **Finding Registry** — one row per unique finding, deduped by **fingerprint**
  `severity:file:line:slug` (see [schemas.md](./schemas.md)). Repeated detections update the
  existing row's status rather than adding a duplicate.
- **Decisions** — between-phase gate outcomes (user answers or fallthrough defaults).

Phase `[status:]` tags ARE rewritten in place (PENDING→IN_PROGRESS→DONE/BLOCKED); the
journals are not. Telemetry in the `develop-state` comment (agent count, spend) is *derived*
from the journals — never read back as source of truth.

## Crash-resume contract

Re-invoking `/develop:run` on an existing plan:
1. Read the plan.
2. Skip every `DONE` phase.
3. Re-enter the **first** `IN_PROGRESS` phase. Its executor must **reconcile, not
   regenerate**: detect existing artifacts (`git diff` against the merge-base + `git status`),
   verify them against the node, fill gaps — never rewrite completed work. See
   [executor-brief.md](./executor-brief.md).
4. Continue the walk from there.

Because the breadcrumb row is appended *before* dispatch, a crash mid-phase still leaves a
record that the phase was entered, so resume re-enters exactly one phase — no double-work,
no skipped work.
