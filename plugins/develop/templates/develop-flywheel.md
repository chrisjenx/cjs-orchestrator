# develop flywheel — <repo name>

How this repo's `/develop` flow grows. See the mechanism in the plugin's
`references/flywheel.md`. Start minimal; promote an anchor only when a finding category has
recurred (≥ 2 runs).

## Promoted anchors (this repo's plan-completeness contract)

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
  - <category> → proposed anchor: <anchor>  (seen <count>x total)
- Irreducible findings (floor): <n>
- Promotion candidates (≥2 runs): <list, or none>
