# <feature> — plan

<!-- develop-state
{ "feature": "<feature>", "worktreeRoot": "<abs path>", "configSnapshot": {}, "agentCount": 0 }
-->

## Requirements Inventory
| # | Requirement | Area(s) | Verified by | Status |
|---|---|---|---|---|
| R1 | <requirement> | <area> | {test:<selector>} | open |

## Execution Strategy
### P1 — <description> [depends: ] [status: PENDING] [loop: max 2, commit_on_green]
- P1.a <action> [agent: executor] [status: PENDING] {build} {test:<selector>}

<!-- quality tail — appended by /develop:run before the walk; do not let the planner emit these -->
### PV — Validate [depends: P1] [status: PENDING]
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
