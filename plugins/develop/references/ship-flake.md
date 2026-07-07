# ship-flake — the 3-round flake protocol (`ci_failed`, flaky)

Consumed by the [`ship` skill](../skills/ship/SKILL.md) when `ship failures` classifies a CI failure
`flaky_signal.is_flaky == true`. Three escalating rounds, keyed by `flaky_soak_round.$id` (the failing
test id). `ship state inc flaky_soak_round.$id`; branch on the new value: 1 → R1, 2 → R2, 3 → R3.

Classification is **config-driven**: the engine matches each failure's log against
`ship.flakePatterns` (rows `{regex, mechanism, hint}` in `develop.config.json`; defaults cover
memory / network / timing) in order, first match wins, and returns the row's `mechanism` + `hint`. No
match → `is_flaky: false`, the skill's cue to treat it as a real failure.

## R1 — free rerun (only if you did NOT touch the failing test)

```bash
ship rerun-workflow $RUN_ID
```

Narrate the rerun. **Keep the Monitor running** — do not exit the turn. The watcher re-emits the next
`ci_failed`/transition once CI settles; `flaky_soak_round.$id` persists across events within the
session, so the next entry advances to R2. Skip R1 (go straight to R2) when you changed the failing
test.

## R2 — inline fix per the matched mechanism, then a local soak

The mechanism is already chosen (`flaky_signal.mechanism`) and the row's `hint` names the fix
approach. Apply the smallest fix that addresses that mechanism (e.g. memory → shrink the fixture +
per-test cleanup; network → stub the dependency; timing → inject a test double or bump the timeout).
Commit `test(flaky): deflake <id> — <mechanism>` + the `Co-Authored-By` trailer. **Single-commit
invariant:** R2 adds exactly one commit this iteration (squash via `--autosquash` if needed).

**Local soak verdict** — before pushing, confirm the fix holds by running the failing test 10×
locally through the repo's own scoped test command (the `test` gate's `scopedCommand` in
`develop.config.json`, with the failing test substituted for `{selector}` — the same `{test:…}`
contract as [gate-tokens.md](./gate-tokens.md)):

```bash
local_fail=0
for i in $(seq 1 10); do
  <scopedCommand with {selector}=<failing test>> || { local_fail=1; break; }
done
```

All 10 pass → push. Any fail → `git reset --hard HEAD~1` → R3 this same iteration. No scoped test
gate configured → skip the soak (run the whole-repo test command once, or proceed to R3).

## R3 — quarantine + ticket

Disable the flaky test using the repo's own skip idiom — a skip/ignore annotation or a
renamed/disabled test, whatever the repo's test framework uses (look at how other skipped tests in
the suite do it; match that). Then file a tracking ticket via the engine's marker handoff:

```bash
ship open-flake-ticket "$id" --run-url <url> --frames "<excerpt>"
```

It writes a PR-scoped marker and exits transient with `ticket_handoff_required`. Route it per
`ship.ticketRoute`:

- **`gh-issue`** (default) — `gh issue create --title "flaky: <id>" --body <marker contents>`.
- **`mcp`** — create the ticket via whatever ticketing MCP is connected this session, then record its
  id.
- **`none`** — record the marker contents in the final report; no external ticket.

Commit `chore(test): disable <id> pending <ticket-or-none>`. **Ticket route unreachable** → apply the
local disable only and continue (degraded path, do NOT halt). Narrate transitions only at cap-1 /
cap; the watcher halts when `flaky_soak_round.$id` hits `caps.flakySoak`.
