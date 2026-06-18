# The flywheel — grow the flow only where pain repeats

The flow starts minimal on purpose: one generalist executor, the fixed quality tail, no
specialists, no forking. It gets *better* not by guessing what to add up front, but by
feeding every run's residual findings back into the plan so the same defect can't escape
twice. Specialists and forks earn their place **only where repeated pain shows**.

## Two kinds of residual finding

Every finding the quality tail surfaces is one of:

- **Preventable** — a plan-time check *could have required* it: a missing test, an unwired
  layer, a stub left where logic was expected, a duplicate of something that already exists,
  a missing guard. **Every preventable finding that reaches audit/tidy is a plan-contract
  bug, not just a code bug.** It means the plan didn't demand the thing the code was missing.
- **Irreducible** — only knowable against the assembled diff: "this compiles but is
  obviously wrong", cross-file duplication between two *new* files, an edge the spec never
  named. These can't be prevented by a plan-time anchor; the audit/tidy phases keep catching
  them forever. That's fine — they're the floor.

The flywheel drives the **preventable** count toward zero. The irreducible floor stays.

## Route the finding to the right lever

Not every preventable finding is a plan step. Route each to the cheapest, most deterministic lever
that can *express* the check, earliest catch first:

- **hook** (a pre-write check) or **gate** (a lint rule / coverage floor / CI check) — pattern-detectable;
  fires at write or gate time, before review.
- **plan-anchor** — a plan-completeness contract row the planner must satisfy (the anchors below);
  for structural requirements a plan can enumerate.
- **rule** — a convention doc an agent reads while writing; for judgement an agent should apply.
- **agent** — a new or tightened reviewer, applied by **growing `develop-routing.json`** (add a
  route + the agent; see [routing.md](./routing.md)); last resort, for judgement-only recurrences
  nothing cheaper expresses. Once a deterministic lever subsumes a reviewer's catches, the loop may
  instead **propose reducing/merging** it — *shrinking* the routing table so a now-redundant
  reviewer stops adding run cost.

Prefer the earliest deterministic lever — a new agent is the latest catch and adds run cost. The
plan-anchor lever (next section) is the one the contract owns.

## The plan-completeness contract (stack-neutral starting anchors for the plan-anchor lever)

The contract is the set of properties the plan must *state* so the planner satisfies them by
construction. Each property has a **mechanical anchor** — a check that's true/false without
judgement — and prevents a finding class:

| Property the plan must state | Mechanical anchor | Prevents |
|---|---|---|
| Every requirement is a Requirements Inventory row | plan has the row | missing feature |
| Each requirement names how it's *verified* | a gate token / grep anchor on the row | spec-vs-impl drift |
| Tests named before impl, paired in the plan | `{test:…}` on the node + diff coverage | untested flow |
| No stub/placeholder where logic is expected | `{grep:no-todo}` over the diff | stub incompleteness |
| A reuse map (what existing code to use/extend) | `{grep:reuse:<ref>}` | duplicate-of-existing |
| Each cross-area edge is wired end to end | `{grep:<wiring-anchor>}` | unwired layer |

These six are stack-neutral and ship as the starting contract. Repo-specific anchors (a
permission verb on every mutating route, a transaction threaded through a data write, a
serialization tag on every event) get **added by the user** as the postmortem shows them
repeating — they are exactly the specialists/forks that earned their place.

## planwork-sync — keep the contract and the plan in sync, both directions

- **Plan ← contract (every run, automatic):** when `/develop:run` builds the plan, it reads
  the contract anchors and folds them into the Requirements Inventory and node gate tokens.
  The planner can't omit a contract anchor; that's the "satisfy by construction" half.
- **Contract ← runs (periodic, human-gated):** `PF` runs the **contract-gaps classifier**
  over the residual findings (one `CONTRACT_GAP` per finding — `preventable` + a proposed
  `remediation` lever + `target`; see [schemas.md](./schemas.md)) and appends them to the
  postmortem. **`/develop:flywheel`** (run periodically between feature runs) reads the
  accumulated postmortems and **promotes** any category that has appeared
  **≥ 2 times across runs — or immediately if it's a breaking-class finding** — by applying its
  lever (a hook/gate/rule/agent, or an anchor on the contract). Prefer the earliest deterministic
  lever; promote a new agent only when nothing cheaper expresses the check. **Applying** a lever
  means deferring to a workflow that builds/improves it — not hand-rolling it inline; see
  [reuse-and-defer.md](./reuse-and-defer.md).

> **Never auto-edit `.claude/` from run artifacts.** Promotion is a human edit to the lever's
> target (a hook, lint rule, contract anchor, rule doc, or agent). Auto-promotion would let one
> noisy run rewrite the rules. The classifier *proposes*; the human *promotes*.

## Where it lives

- This mechanism is bundled (portable). The **per-repo** flywheel doc — the running
  postmortem log + this repo's promoted anchors — is `.claude/develop-flywheel.md`, seeded by
  `/develop:init` from [`templates/develop-flywheel.md`](../templates/develop-flywheel.md).
- `PF` appends one postmortem block per run; the human curates the promoted-anchors list.

The loop tightens every run: a defect that escaped becomes a control at the right layer so
it can't escape again, and the flow grows (and prunes) precisely the structure the repo's
real failures call for, nothing more.
