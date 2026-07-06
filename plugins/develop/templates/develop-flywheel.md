# develop flywheel — <repo name>

How this repo's `/develop` flow grows. Each run, `PF` appends one record per residual finding
to the companion **`develop-flywheel.jsonl`** (the machine SSOT). Run **`/develop:flywheel`**
periodically to aggregate that SSOT and promote tweaks for the next run. This doc is
**human-curated** — never written from a run; only `/develop:flywheel` edits it, on your
approval. See the mechanism in the plugin's `references/flywheel.md`. Start minimal; promote a
remediation only when a finding category recurs (≥ 2 runs), is breaking-class, **or** is a
confirmed escape (a PR review you agreed to, or a CI failure), which `/develop:flywheel` pulls in
and promotes at ×1 (a proven miss).

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

Starts with the stack-neutral defaults. Add a row only after the SSOT shows a category
repeating. Each anchor must be *mechanical* (true/false without judgement).

| Anchor | Prevents | Promoted on (date / runs seen) |
|---|---|---|
| Requirements Inventory: every requirement a row | missing feature | default |
| Each requirement names its verification (gate/grep) | spec-vs-impl drift | default |
| Tests named before impl + diff coverage | untested flow | default |
| `{grep:no-todo}` over the diff | stub incompleteness | default |
| Reuse map stated | duplicate-of-existing | default |
| Cross-area edges wired end to end | unwired layer | default |
| Signature widening lists every mock/stub site (even a defaulted param) | run-time matcher-arity break | default |
| One named test per equivalence class of a branching predicate (incl. negative + exception paths) | untested negative branch | default |

## Promotion history (curated by `/develop:flywheel` on approval; newest first)

<!-- one line per promotion: <date> — <category> ×<n> runs → <lever>: <target> -->
