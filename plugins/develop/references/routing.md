# Routing — artifact shape → the right agent

`.claude/develop-routing.json` maps the *shape* of a file (by path glob) to the agent that
should write or review it. `/develop:init` generates it with **only a generalist fallback**;
it grows specialist rows over time as the [flywheel](./flywheel.md) shows where a generalist
keeps missing things. Day one has no specialists — and that's correct.

## Structure

```json
{
  "writers": [
    { "glob": ["**/*"], "agent": "executor" }
  ],
  "reviewers": [
    { "glob": ["**/*"], "agent": "general-quality-reviewer" }
  ],
  "audit": [
    { "always": true, "agents": ["completeness-auditor", "stubs-auditor", "general-quality-reviewer"] },
    { "when": "pre-existing files modified", "agents": ["regression-auditor"] }
  ]
}
```

- **`writers`** — used by the executor when it nests child writers. Route each file to be
  written by its glob.
- **`reviewers`** — used by `PT` (Tidy). Per changed file, the reviewers that should look at
  it.
- **`audit`** — used by `PA` (Audit). `always: true` agents run every time; `when: <signal>`
  agents run only when the change shape matches.

## Matching rules (they differ by section — this matters)

- **Writers — first match wins.** Walk the list top to bottom; the first rule whose glob
  matches the file routes it. The generalist fallback (`"glob": ["**/*"]`) is **last**, so a
  specialist row added above it takes precedence. If nothing else matches, the fallback
  catches it. **Never skip the lookup** and default straight to the generalist — that's how
  specialists stop getting used.
- **Reviewers — collect ALL matches.** A changed file gets *every* reviewer whose glob
  matches it, not just the first. An optional `"authoritative_over": ["other-reviewer"]` on a
  rule suppresses the listed reviewers for that path (use when a specialist subsumes the
  generalist for its files).
- **Audit — union of always + matching when.** Start with the `always` agents, add every
  `when` rule whose signal fires (e.g. `pre-existing files modified`, `diff touches <area>`).
  `PA` then climbs the [audit ladder](./quality-tail.md) one rung per round that finds
  defects.

## Generation (what init writes)

Init writes the starting table above: the bundled auditors wired into `audit`, and
generalist fallbacks for `writers`/`reviewers`. No stack-specific routes — those aren't
guessed up front. On a re-run, init only **appends** routes that don't already exist and
keeps the fallback last ([idempotency.md](./idempotency.md)).

## Growing the table (the flywheel pays out here)

When the postmortem shows a finding category clustering on one artifact shape — say,
data-migration files repeatedly get a defect class the generalist misses — that's the signal
to add a specialist:

1. Write a specialist agent under the repo's `.claude/agents/` (or reuse a bundled one).
2. Add a route **above** the fallback:
   ```json
   { "glob": ["**/migrations/**"], "agent": "migration-reviewer" }
   ```
3. For reviewers that fully own their files, add `"authoritative_over"` to suppress the
   generalist there.

A specialist earns its row by repeated pain, never by speculation. The table you don't need
yet, you don't write.

## Shrinking the table (the agent lever, in reverse)

Routes also come **out**. When a cheaper, deterministic lever — a hook, a gate, a lint rule —
starts catching what a reviewer was added for, that reviewer is now redundant run cost. The
[flywheel](./flywheel.md)'s agent lever covers both directions: grow a route when judgement is
the only thing that catches a recurring class, and **reduce or merge** a route once something
earlier subsumes its catches. Removing a now-redundant reviewer is as much a flywheel outcome
as adding one — keep the table only as large as the pain requires.
