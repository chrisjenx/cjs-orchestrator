# develop flywheel — <repo name>

How this repo's `/develop` flow grows. `/develop:run`'s `PF` appends a postmortem block
below after each run; run **`/develop:flywheel`** periodically to evaluate the accumulated
log and promote tweaks for the next run. See the mechanism in the plugin's
`references/flywheel.md`. Start minimal; promote a remediation only when a finding category
recurs (≥ 2 runs) **or** is breaking-class. Promotion is always a human-gated edit — never
auto-edited from a run.

## Remediation levers (route each preventable finding to the cheapest, earliest one)

| Lever | Catches at | Where it lands in this repo |
|---|---|---|
| hook | write time | `.claude/hooks/` + `.claude/settings.json` |
| gate | gate/CI time | a `gates[]` entry in `.claude/develop.config.json` (lint rule / coverage floor / CI check) |
| plan-anchor | plan time | a row in the contract table below |
| rule | while writing | a convention line in `CLAUDE.md` (or a referenced rule doc) |
| agent | review time | a route in `.claude/develop-routing.json` (add a reviewer; or *shrink* a now-redundant one) |

Prefer the earliest deterministic lever; a new agent is the last resort (latest catch, adds
run cost).

## Promoted anchors (this repo's plan-completeness contract — the plan-anchor lever)

Starts with the stack-neutral defaults. Add a row only after the postmortem shows a category
repeating. Each anchor must be *mechanical* (true/false without judgement).

| Anchor | Prevents | Promoted on (date / runs seen) |
|---|---|---|
| Requirements Inventory: every requirement a row | missing feature | default |
| Each requirement names its verification (gate/grep) | spec-vs-impl drift | default |
| Tests named before impl + diff coverage | untested flow | default |
| `{grep:no-todo}` over the diff | stub incompleteness | default |
| Reuse map stated | duplicate-of-existing | default |
| Cross-area edges wired end to end | unwired layer | default |

## Postmortem log (append one block per run; newest first)

<!-- PF appends a block like this after each run -->
### <feature> — <date>
- Terminal status: <ready | ...>
- Preventable findings that escaped to audit/tidy: <n>
  - <category> → proposed remediation: <hook|gate|plan-anchor|rule|agent> → <target>  (seen <count>x total)
- Irreducible findings (floor): <n>
- Promotion candidates (≥2 runs or breaking-class): <list, or none>
