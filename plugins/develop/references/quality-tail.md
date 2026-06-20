# The quality tail — controls that can't fall off the end

After the domain phases come four fixed phases: **Validate → Audit → Tidy → Finalize**
(`PV → PA → PT → PF`).

> **The orchestrator appends the tail, not the planner.** `/develop:run` writes `### PV`,
> `### PA`, `### PT`, `### PF` into the plan *before* the walk begins. A planner that forgets
> to verify, or an executor that stops early, can't drop the controls — they're structural
> nodes the walk must reach. Each depends on the previous, and `PV` depends on all domain
> phases.

All four are ordinary phases the walk processes; they just have fixed logic instead of
planner-authored nodes. Findings flow into the same Finding Registry, deduped by
fingerprint ([schemas.md](./schemas.md)). Every validate/audit/review dispatch in the tail
runs at the **top** tier — paired against the mid-tier executor so review can't rubber-stamp
([model-tiers.md](./model-tiers.md)); the `tidy` worker writes cheap, its reviewers run top.

## PV — Validate (does the diff satisfy the requirements?)

- Assemble the branch diff (`git diff <merge-base>`). Dispatch a reviewer — reuse-first, a
  bundled reviewer at **top** tier (`code-reviewer` for requirement compliance, or
  `completeness-auditor`) — with the diff + the **Requirements Inventory**; it returns
  `FINDINGS`. The orchestrator derives the outcome: none blocking → `pass`; fixable in place →
  `iterate`; a requirement needs a human call → `escalate`.
- `pass` → advance to PA.
- `iterate` → append fix-in-place subtasks (and, if a requirement was missed entirely, a
  small bounded re-plan) and re-walk. Bounded by `caps.validator` rounds; on exhaustion,
  carry the gaps as findings and advance with them recorded.
- Validation is about **completeness vs. the spec**, not style — that's PT.

## PA — Audit (deep, parallel)

- Dispatch the audit set **in parallel**: the always-on auditors plus any conditional ones
  whose trigger matches the change shape, from the `audit` rules in
  [routing.md](./routing.md). The bundled stack-agnostic auditors read *diffs*, not build
  systems, so they travel across stacks:
  - `completeness` — broadest cross-area lens (is the planned edge actually wired?)
  - `stubs` — placeholders/TODOs where real logic was required
  - `regression` — behaviour preserved when existing files were modified
  - `general-quality` — fresh-eyes "compiles but obviously wrong"
  - `code-reviewer` — requirement compliance + conformance to the repo's *own* rules
    (`CLAUDE.md`); reuses the rules that exist, doesn't invent standards
- **Consolidate**: dedup by fingerprint; promote by convergence (a finding several auditors
  independently raise is higher severity). Append the consolidated findings.
- **Audit ladder** — climb one rung per round *that finds defects* (most- to least-likely to
  surface): completeness → stubs → edge-case → regression → fresh-eyes → architecture. A
  round that finds nothing new ends the climb. Bounded by `caps.audit`; a convergence check
  (same finding count two rounds running) forces a stop → escalate. Day-one PA dispatches only
  the bundled auditors (completeness/stubs/regression/general-quality) from `routing.json`'s
  `audit` set; the `edge-case`/`architecture` rungs fill in as specialists grow via the flywheel.
- Outcome: clean → PT; fixable → append fix subtasks + re-walk; needs a human decision →
  between-phase gate.

## PT — Tidy (cleanup + reviewers)

- Dispatch the [`tidy`](../agents/tidy.md) worker: it runs the repo's own lint/format
  **autofix** (the cheap gates), removes branch leftovers (debug prints, dead code, resolved
  TODOs), and applies low-risk reviewer fixes — leaving anything behaviour-changing for a
  decision.
- Dispatch the reviewer set, path-routed from [routing.md](./routing.md)'s `reviewers` rules
  (collect *every* rule whose glob matches a changed file; `authoritative_over` suppresses
  co-listed reviewers for that path). The default reviewers are `general-quality` and
  `code-reviewer`; specialists join as the routing table grows.
- Zero "needs-decision" + clean lint → PF. Any needs-decision → between-phase gate.

## PF — Finalize (the real gates, then commit)

This is where the repo's **heavy** gates actually run and block the commit:

1. **Run every gate the executors annotated `DEFERRED-PF`**, plus all `tier: heavy` gates in
   `develop.config.json`, locally, in the worktree — whole build, full test suite, coverage,
   any multi-module check. Each returns a `GATE_RESULT`.
2. **Block until green.** A failing heavy gate is not "done": re-dispatch a fix (bounded by
   `caps.gate`), then re-run the gate. A flake (passes on rerun) is logged, not treated as a
   failure; a real failure that survives the budget → terminal status
   `committed-with-failures` (recorded, surfaced, never pushed).
3. **Classify the residual findings** — a top-tier pass (reuse a bundled reviewer, or the
   orchestrator inline; not a separate bundled agent): the flywheel **contract-gaps classifier**
   ([flywheel.md](./flywheel.md)) marks each preventable vs irreducible and, for preventable
   ones, proposes a remediation lever (hook / gate / plan-anchor / rule / agent) + its target
   (one `CONTRACT_GAP` each).
4. Write the run **report**, and **append one `FLYWHEEL_RECORD` per residual finding** to
   `.claude/develop-flywheel.jsonl` — a plain line-append, the machine SSOT
   ([schemas.md](./schemas.md)). No prose postmortem; `/develop:flywheel` aggregates the JSONL
   later. `develop-flywheel.md` is human-curated, never written from a run.
5. **Commit** the worktree (no push). Derive the terminal status mechanically from the gate
   results + finding state (see the table in [run/SKILL.md](../skills/run/SKILL.md)).

No path commits "green" without the real commands having run and produced evidence — that is
the whole point of the tail.

## Tiering recap

Cheap gates run inline in every domain phase (fast local signal); heavy gates are deferred
and run **only** here in PF, where they block the commit. See
[gate-tokens.md](./gate-tokens.md) for how each gate is tagged.
