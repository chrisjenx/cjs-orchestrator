# Triggering matrix

`/develop:bootstrap` and `/develop:work` must fire on the right intents and stay quiet on unrelated
ones. Run each phrase with a fresh agent that has the plugin installed; record whether the
expected skill activated.

## `/develop:bootstrap` — SHOULD trigger

- "bootstrap develop"
- "set up orchestration for this repo"
- "build my own develop flow"
- "scaffold an agentic pipeline here"
- "I want a spec-to-branch loop fitted to this project"
- "bootstrap the develop orchestrator"

## `/develop:bootstrap` — should NOT trigger

- "what does develop mean?" (a definition question)
- "run the tests" (a plain task)
- "develop a new feature for X" (this is run-flow / plain work, not bootstrap)
- "git init" (unrelated tooling — not to be confused with Claude Code's own built-in `/init`,
  which is also a different command)

## `/develop:work` — SHOULD trigger

- "/develop:work add pagination to the list endpoint"
- "develop this ticket: <url>"
- "run the develop flow on this spec"
- "take this spec to a committed branch"

## `/develop:work` — should NOT trigger

- "how does /develop:work work?" (a question)
- "set up the develop flow" (that's bootstrap)
- "push my branch and open a PR" (work never pushes; that's `/develop:ship`)

## `/develop:ship` — SHOULD trigger

- "/develop:ship"
- "ship this branch"
- "push and watch CI to green"
- "babysit the PR"
- "push and fix the CI failures"
- "handle the review comments and merge"

## `/develop:ship` — should NOT trigger

- "how does /develop:ship work?" (a question)
- "develop this ticket" (that's work — no push/watch intent)
- "commit these files" (a plain commit, no watch)

## Pass criteria

- Every SHOULD row activates the named skill.
- Every should-NOT row does **not** activate it.
- Pay special attention to the boundaries: "set up" → bootstrap; "develop this change" → work;
  "push/watch/babysit the PR" → ship. Question-shaped phrases should trigger neither.
