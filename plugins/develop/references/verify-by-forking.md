# Verify by forking — refuters and judge panels (opt-in)

One agent checking its own (or a peer's) claim tends to rubber-stamp it. Forking replaces a
single pass with **N independent attempts to refute**, and takes the majority. It's the
highest-cost verification move, so it's **off by default** and fires only at raised
`intensity`.

> **Lean default:** `intensity` = `{ "refuters": 1, "planCandidates": 1 }` in
> `develop.config.json` → single pass, no forking. Raise these per-repo (or per-run via the
> orchestrator's Assess step) only where the cost is worth it — high-risk changes, a phase
> that keeps producing false positives, a wide design space.

## Refuters — kill the claim, or let it stand

When `intensity.refuters = N > 1`, the loop forks **N** [`refuter`](../agents/refuter.md)
agents per claim. Each is told to *try to refute* the claim and defaults to "refuted" when
uncertain. The claim survives only if **fewer than a majority** refute it.

Two places it's used:

- **Verifying a finding is real (PA):** the claim is "this finding is a true defect." If a
  majority of refuters show it isn't (false positive), drop it. This keeps the Finding
  Registry honest — noisy auditors don't get to block on imaginary bugs.
- **Verifying a correctness claim (PV / between-phase):** the claim is "requirement R is
  satisfied" or "this gate genuinely passed." If a majority refute, reopen the phase.

Use **diverse lenses** when a claim can fail more than one way: instead of N identical
skeptics, give each refuter a distinct angle (correctness, security, does-it-actually-run,
spec-conformance). Diversity catches failure modes redundancy can't. Majority still rules.

Each refuter returns `REFUTER_VERDICT` ([schemas.md](./schemas.md)); the orchestrator counts
`refuted: true` votes.

## Judge panels — N attempts, score, synthesize

When `intensity.planCandidates = M > 1`, the planning step generates **M** independent plan
candidates from different framings (e.g. MVP-first, risk-first, simplest-thing-that-works),
then runs a **judge panel**: a few graders score each candidate on the same rubric and the
orchestrator synthesizes the final plan from the winner, grafting the best ideas from the
runners-up. This beats one-plan-iterated when the solution space is wide.

Judge output (per grader, per candidate):
```json
{ "candidate": "A", "scores": { "completeness": 4, "risk": 3, "simplicity": 5 }, "note": "…" }
```
Average across graders; pick the top candidate; synthesize. Bound the whole thing by
`caps` so it can't spin.

## Cost discipline

- Forking multiplies agent count by `N` (refuters) or `M × graders` (panel). The `caps`
  bound the rounds; `intensity` bounds the width. Keep both at `1` until a real signal
  justifies raising them — that signal usually comes from the [flywheel](./flywheel.md)
  (a finding class that keeps slipping through single-pass verification).
- Forking is a *quality* lever, not a default: the lean path ships first, forks are added
  exactly where repeated pain shows — same principle as specialists.
