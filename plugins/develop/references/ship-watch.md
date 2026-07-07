# ship-watch — the watch mechanism `/develop:ship` orchestrates

`scripts/ship.py` (Python 3 stdlib + `gh` CLI) wraps gh API calls, owns a per-PR JSON state file,
and emits compact `hint`s. The [`ship` skill](../skills/ship/SKILL.md) is a thin orchestrator that
switches on those hints. Run from inside a worktree; state lives at
`$(git rev-parse --git-dir)/ship-state-<pr>.json`.

## Hands-off by design

Launch the watch once and walk away. The engine owns every mechanical decision — classify CI,
rebase, run the flake protocol, classify threads, gate the merge — and **wakes the agent only when
human judgment is needed**: a real CI failure, a reviewer comment, a conflict, or a terminal. Waits,
throttling, and auto-actions (promote, rebase, merge under `--merge`) stay silent. A clean PR with no
review comments runs from push to the merge gate with **zero** wakes.

## Config seam

The engine reads the optional `ship` section of `.claude/develop.config.json` (from the main
checkout) and merges it over built-in defaults; a missing section logs one stderr warning and runs on
defaults. `/develop:init` writes the section; [config-schema.md](./config-schema.md) documents every
field. Repo specifics — base branch, review-bot check/comment identities + sticky format, flake
patterns, caps, cadence, rate floor, merge method, ticket route — come only from there. The engine
hardcodes nothing repo-specific; with an empty `reviewBots` it degrades gracefully (no sticky or
retrigger hints; CI + human threads + merge still work).

## Watch lifecycle

`ship watch` polls `status` and routes by hint. **stdout = WAKE the agent** (judgment); **stderr =
silent** (waits, throttle, auto-action success). A live WAKE re-emits until acked, so a dropped wake
notification can't stall the loop.

## Hint state machine

| Hint | Cadence | Handler |
|---|---:|---|
| `wait_ci` (empty check-runs → 60s) | `cadence.waitCi` (270s) | watcher, silent |
| `wait_first_review` / `wait_review_submit` | 90s | watcher, silent |
| `wait_reapproval` | 270s | watcher, silent (also while the review bot hasn't completed on current head) |
| `ci_failed` | 0 | **agent** — `ship failures` |
| `merge_conflict` | 0 | **agent** — `rebase-decision` + `rebase-attempt` |
| `fetch_threads` | 0 | **agent** — `threads`, classify, reply, resolve (only when ≥1 unaddressed) |
| `sticky_sha_stale` | 0 | **agent** — `threads --unresolved`; transient (stickyMeta bots only) |
| `promote_draft` | 0 | watcher AUTO (`gh pr ready`); wakes only on failure |
| `retrigger_review` | 0 | watcher AUTO when `reviewBots[].retrigger` + capped; else no-op |
| `behind_base` | 0 | watcher AUTO under `--merge`; else **agent** |
| `clean_exit` | 0 | **agent** — final report; merge if `--merge` |
| `halt` | 0 | **agent** — surface `reason` + `pr_url`, exit |

## Wake taxonomy (`ship watch [--merge] [--max-iters N] [--floor-core N] [--floor-graphql N]`)

- **WAKE** (stdout): `ci_failed`, `fetch_threads`, `merge_conflict`, `sticky_sha_stale`, `halt`;
  `behind_base` & `clean_exit` without `--merge`.
- **AUTO** (watcher acts, stderr): `promote_draft`, `retrigger_review`; under `--merge` also a clean
  `behind_base` (rebase) and `clean_exit` (merge) — wakes only on failure (→ `halt`) or terminal
  success (→ `done`).
- **SILENT** (stderr): all `wait_*`, rate-floor throttle, transient retries.

`--merge` merges ONLY at `clean_exit` (CI green + review approved + every thread addressed +
mergeable), so it always works reviewer comments first — unlike GitHub's `--auto`, which merges the
instant CI is green. The `_merge_gate` re-fetches live state immediately before merging; any
condition false → it emits the matching wake (`wait_ci` / `fetch_threads` / `wait_review` /
`behind_base`) instead. With empty `reviewBots` the approval sub-check is skipped (CI + threads +
mergeable still required).

## Cadence & rate headroom

`wait_ci` uses a phased fast-fail / dead-middle / landing schedule (`cadence.fastFailWindow` 120s,
`cadence.landingBuffer` 90s) so a compile error is caught in ~30s. A free `gh api rate_limit` check
runs before each poll; below `rateFloor.core` / `rateFloor.graphql` (500 each of the shared 5000/hr)
the watcher backs off.

**CI-duration baseline** — the engine self-maintains `.claude/ship-ci-durations.json` (a rolling
7-day per-job p90, rounded up to 30s): when a poll sees the suite fully green (once per sha) it
derives each check's duration from its own `started_at`/`completed_at` and merges it in (atomic
write, deduped on check-run id). No CI workflow needed. With a baseline the dead-middle sleep targets
predicted completion; empty baseline falls back to fast-fail + fixed `waitCi`. `ship ci-durations
--show` prints the map.

## Re-nudge until ack

A live WAKE re-emits so a dropped notification can't stall the watch; the cadence is ACK-gated
(`ship ack <hint> <sha>` on pickup):

| Tier | When | Cadence |
|---|---|---:|
| un-acked | no ack matches the live `(hint, sha)` | `cadence.unackedRewake` (120s), escalating `nudge` |
| acked | ack matches | `cadence.rewake` (600s), silent safety re-nudge |

A re-emit carries an incrementing `nudge` so the agent never dedups it against the first emit. A new
sha is a fresh wake (no `nudge`), never silenced by a stale ack.

## Subcommands

| Subcommand | Purpose |
|---|---|
| `status` | snapshot envelope (sha, ci, review, sticky, hint) |
| `failures` | failed check-runs + run id + test ids + `flaky_signal` (mechanical classification) |
| `size` | pre-push size tier `{tier, files, lines, hot_touched, code_change}` |
| `threads [--unresolved]` | review threads + `state` + sticky correlation |
| `rebase-decision [--force-rebase]` | REBASE/SKIP + reason + `overlap_files` / `code_overlap` |
| `rebase-attempt` | run `git rebase`; return conflicts on fail |
| `rerun-workflow $ID` / `extract-failed-tests $ID` | rerun failed jobs / list failed test ids |
| `promote-draft` / `find-or-create-pr […]` / `post-pr-body --summary -` | draft → ready / PR reuse-or-create / body |
| `reply-thread $ID --body -` | ONE inline reply — the only way to respond (never `gh pr review`) |
| `resolve-thread $ID` | resolve one thread (idempotent) |
| `merge-pr [--pr-number N]` | merge via `mergeMethod`; tolerates already-merged |
| `branch-name-valid` | exit 2 on the resolved base branch / detached HEAD |
| `open-flake-ticket $ID …` | write a ticket marker (routed by `ticketRoute`; see below) |
| `cleanup-worktree [<path>] [--branch B]` | remove a worktree from outside it |
| `ack $HINT $SHA` · `state get/set/inc/reset/check-caps` | ack a wake · per-PR state ops |
| `doctor` · `--selftest` | runtime preflight · offline self-check |

## Key contracts

- **Pending reviews** — inline comments on an unsubmitted review already exist as `reviewThread`s
  scoped to the author's token (which ship shares). `status` emits `wait_review_submit` and `threads`
  returns `[]` while a PENDING review is open; the set re-surfaces on submit. This is why replies go
  only through `reply-thread` — `gh pr review` would open a pending review that self-deadlocks.
- **Thread addressed** = `isResolved` AND the ship viewer authored ≥1 comment on a review-bot thread
  (a human/other-bot thread is addressed on `isResolved` alone, since the reply-only policy forbids
  the agent from touching those). `threads` never caches — a cached `[]` would hide external
  mutations.
- **Ticket route** — `open-flake-ticket` writes a PR-scoped marker and exits transient with
  `ticket_handoff_required`. The skill routes by `ship.ticketRoute`: `gh-issue` (default,
  `gh issue create`), `mcp` (a connected ticketing MCP), or `none` (record in the report).
- **Exit codes** — `0` success/no-op · `1` transient (retry next wake) · `2` halt-worthy (auth,
  malformed input, defensive gate). `status` exits 0 if JSON is valid; halt-worthiness rides in
  `hint == "halt"` + `reason`.

## Final-report format (every terminal — `clean_exit` / `done` / `halt`)

One scannable block: the PR as a clickable markdown link on the PR number, a `Status:` line (`READY` /
`MERGED` / `HALTED: <reason>`), and — when the loop needs the human — a `Needs:` line naming the one
action (e.g. "approve the PR", "resolve the semantic conflict in <file>"). Nothing else.
