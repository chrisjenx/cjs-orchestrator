# Dry run — prove the gates are real before trusting them

`/develop:init` Phase 5. A scaffold that *looks* wired but whose gates don't actually run (or
run but don't block) is worse than none — it gives false confidence. Before declaring the
flow ready, prove two things on a throwaway change:

1. **The gates execute.** The real commands from `develop.config.json` run and produce
   evidence.
2. **A gate failure blocks.** When a gate fails, the flow does **not** reach a clean commit —
   it relays a failure status instead.

The second is the one that matters. Anyone can make a green pipeline; the test of a gate is
that it can say *no*.

## Protocol

Run both halves in a disposable worktree so nothing touches the user's tree.

### A. Positive run — gates execute
- Make a **trivial, safe** change (e.g. a comment, or a tiny passing test).
- Run `/develop:work` on it.
- Confirm it walks to `PF` and the heavy gates **actually ran** — capture the real command
  lines and their exit status as evidence (not "the agent said it built").
- Confirm the **guard blocks destructive git when invoked from inside** `.claude/worktrees/<feature>`
  through the live host (not just via a piped JSON test) — proving the self-gate enforces in the
  worktree, not only at the main checkout.
- Expect terminal status `ready`.
- **Completeness re-check.** Audit the Phase-1/2 enumeration, not your memory: confirm it accounts
  for **every** step in the CI files — each is a confirmed gate or carries an explicit non-gating
  reason. A CI step absent from that enumeration (or one marked non-gating without a sound reason)
  is a silent under-discovery — surface it as a dry-run finding, don't let it pass.

### B. Negative run — a failure blocks (the load-bearing test)
- Introduce a **deliberate, obvious** gate failure — pick the cheapest gate to trip:
  - a `test` gate → add a test that asserts `false`;
  - else a `lint`/`format`/`types` gate → introduce one obvious violation;
  - else a `build` gate → introduce a syntax error in a throwaway file.
- Run `/develop:work` again.
- **Confirm the flow refuses to land it:** `PF` blocks the commit and the terminal status is
  `committed-with-failures` (or the commit is withheld) — never `ready`. If a deliberately
  broken gate produces a clean `ready`, the gate is **not wired** — fix the config/tail and
  repeat. This is a hard failure of the dry run.

### C. Cleanup
- Remove the dry-run worktree/branch and every throwaway file/test. Leave the tree exactly as
  it was. Verify with `git status` in the main working tree.

## Report to the user

Emit a short, evidence-backed summary:

```
Dry run results:
  Gates executed:   <build ✓ (cmd)> <test ✓ (cmd)> <lint ✓ (cmd)> <coverage — skipped: reason>
  Failure blocks:   PASS — a deliberately failing <gate> produced status
                    'committed-with-failures', commit withheld.
  Skipped:          <any gate that couldn't run in this env, and why>
  Verdict:          flow is wired and gates are load-bearing  |  NOT READY — <what to fix>
```

- If a gate could not run in this environment (missing toolchain, needs network/secrets),
  **say so explicitly** and mark it skipped — don't silently pass it. A skipped gate is an
  unverified gate.
- Only declare the flow ready when at least one gate's *failure* was observed to block.
