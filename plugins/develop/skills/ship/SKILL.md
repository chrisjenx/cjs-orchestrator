---
name: ship
description: "Push a committed branch, open its PR, then watch it through CI and review to merge — the handoff after /develop:work. Trigger on '/develop:ship', 'ship this branch', 'push and watch', 'babysit the PR', 'push and fix CI', 'watch the PR to green', 'handle the review comments', '--merge'. NOT for a plain commit/push with no watch intent. Reads the repo's `ship` config section (written by /develop:init); the bundled ship.py engine owns all mechanics."
---

# Ship — push, watch, respond, merge

You supply **judgment**; the [`ship.py`](../../scripts/ship.py) engine owns everything mechanical
(classify CI, rebase, push, reply to threads, merge) and the poll loop. The engine wakes you only
when a decision is needed. Read [ship-watch.md](../../references/ship-watch.md) once for the wake
taxonomy and cadence; [token-frugality.md](../../references/token-frugality.md) governs your
narration.

Invoke the engine as `ship` = `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ship.py"`. It reads
`.claude/develop.config.json`'s `ship` section from the main checkout; missing section → defaults +
a warning (tell the user to run `/develop:init`). All ops target the active worktree; state is
isolated per worktree.

**Entry contract:** ship expects a branch that already passed `/develop:work`'s quality tail (or
your own review) — it does not re-audit. It works on any branch except the resolved base branch /
detached HEAD.

**`--merge`:** auto-merge at `clean_exit` (CI green + approved + threads addressed + mergeable). Set
once on entry, read at exit:

```bash
ship state set merge_flag true   # only when /develop:ship --merge invoked
```

## Phase 0 — Entry

Every invocation starts here (the watch is a single Monitor process; no self-rearm). `ship status`
is cheap — call freely. Narrate state in one line (SHA, CI summary, draft/ready, mergeability).

Reset volatile counters (a fresh user entry retries from current state):

```bash
ship state set ci_fail_count '{}'
ship state set flaky_soak_round '{}'
ship state set retrigger_review_count 0
ship state set wake_ack '{}'
ship state set paused false
```

Preserve `merge_flag`, `rebase_count`, `did_rebase`. The halt caps (`ci_fail_count[*]`,
`flaky_soak_round[*]`) accumulate across events *within* a watch session; they reset only here.

## Phase 1 — Pre-push

1. **Commit + squash.** Stage the relevant files (never `git add -A`). Terse conventional subject
   matching `git log --oneline -10`, plus the `Co-Authored-By` trailer per CLAUDE.md. Squash prior
   fixups (`git rebase -i --autosquash HEAD~N`). Nothing to commit → step 2.
2. **Rebase decision.** `ship rebase-decision` → `{decision, reason, overlap_files, code_overlap, …}`.
   REBASE → `git rebase <base>` (mechanical conflict = resolve + `--continue`; semantic = `--abort` +
   halt). `code_overlap: true` → read each `overlap_files` entry for a logical conflict a clean merge
   can't catch. SKIP → continue. See [ship-watch.md](../../references/ship-watch.md).
3. **Size + local verify.** `ship size` → `{tier, files, lines, hot_touched, code_change}`. `Small` →
   skip local tests. `Medium`/`Large` → run the repo's cheap gates from `develop.config.json`
   (`build`/`types`, then the `test` gate). Failure → fix, or halt and ask. This is the only local
   test step; ship does not derive test commands itself.
4. **Push.** `ship push` (or `ship push --force-with-lease` after a rebase; clears `did_rebase` on
   success). Rejected + local≠origin tracking → halt (wrong branch); else `git pull --rebase` + retry.

## Phase 2 — PR setup

```bash
echo "<one-line summary>" | ship find-or-create-pr --draft --title "<type>(<scope>): <summary>" --summary -
```

Returns `{number, url, is_draft, branch}` (reuses an existing PR, else creates a draft + body).
Persist them. Report the PR as a clickable markdown link on the PR number, never a bare URL.

## Phase 3 — Watch (Monitor-driven)

Launch the watcher **once** — it owns the loop, performs mechanical actions itself (promote, rebase,
merge under `--merge`), and wakes you (a stdout JSON line) only for judgment. Waits and successful
auto-actions stay silent (stderr).

```
Monitor(
  description: "PR <N> state transitions",
  persistent: true,
  command: "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ship.py watch[ --merge]"
)
```

No Monitor tool on this host? Fall back to a bounded foreground loop: `ship watch --max-iters <N>`
via Bash `run_in_background`, re-launching on each wake. Carry `--merge` only when the user asked.

Each event: `{"event":"transition","hint":"…","sha":"…","reason":"…","pr_url":"…"}` or
`{"event":"done",…}`.

**ACK every WAKE first:** `ship ack <hint> <sha>` before handling (stops the re-nudge; skip only for
terminal `done`/`halt`). Then switch on `hint`:

### `ci_failed`
Re-verify current (`ship status`; never act while the latest attempt is `in_progress`), then:

```bash
ship failures
```

Per non-empty row: `flaky_signal.is_flaky == true` → [ship-flake.md](../../references/ship-flake.md).
Else dispatch the [`ci-failure-extractor`](../../agents/ci-failure-extractor.md) agent → classify
**Real** (fix + commit + `ship state inc ci_fail_count.$root_cause`, no push — the watcher re-emits
after your push lands) vs **Flaky** (flake protocol). The watcher enforces the caps each poll and
emits `halt` when one hits; you must still `ship state inc` the counter so the gate can fire.

### `fetch_threads`
```bash
ship threads
```

Reply **only** via `ship reply-thread` (one inline reply) — never `gh pr review` / the "Start a
review" UI, which opens a pending review that self-deadlocks the watcher. Act per row:

| Type | Action |
|---|---|
| Code change | fix + commit + reply `Fixed in <short-sha>. <brief>` + resolve |
| Question / Nit / FYI | reply + resolve (fix the nit if trivial) |
| Disagreement | reply with reasoning; **do NOT resolve** |
| Bot false-positive | reply briefly + resolve |
| Large refactor / user interjects | halt + ask |

### `merge_conflict` / `behind_base` (without `--merge`)
```bash
ship rebase-decision
ship rebase-attempt            # did_rebase=true on success
ship push --force-with-lease   # clears did_rebase on success
```
Mechanical conflict → resolve inline + `git add` + `--continue` + push. Semantic → halt with the file
list. Under `--merge` the watcher handles `behind_base` itself; you only see a conflict as a `halt`.

### `sticky_sha_stale`
The review sticky is on an older SHA than HEAD. `ship threads --unresolved`; new actionable threads →
handle per `fetch_threads`; none → transient, no action (the next poll re-emits). Don't re-request
review.

### `clean_exit` (only without `--merge`)
PR green. Emit the final report ([ship-watch.md](../../references/ship-watch.md)), `TaskStop` the
monitor, exit.

### `event: done` (merged under `--merge`)
The watcher merged. `cd` to the main checkout, `ship cleanup-worktree --branch <branch>`, emit the
final report, `TaskStop`.

### `halt`
`ship state set paused true`, emit the final report (`Status: HALTED: <reason>`), `TaskStop`, exit. A
halt is the only early end besides `clean_exit`/`done`.

### User interruption
Any mid-flow message that isn't a `/develop:ship` restart → `ship state set paused true`, `TaskStop`,
surface the PR link, address it. Never auto-resume; restart only on explicit re-invocation.

**Event hygiene:** dedup a *fresh* event (no `nudge`) by `(hint, sha)` — already handling that pair →
ignore. A re-nudge (`nudge ≥ 1`) is live: re-ack and confirm you're actually changing PR state.

## Narration — concise
**Narrate:** per-wake hint + reason; size tier (first iter); rebase decision; counters at cap-1/cap;
per-thread action; flake transitions; merge enable. **Silent:** cache-skip iters, no-op pushes.

## Per-wake cost — human levers
`ship watch` keeps wakes cheap; the agent-side work each wake triggers grows context. Between wakes
the human can `/compact` after a heavy `ci_failed` fix, and set `/effort` to the `ship size` tier.
State lives in the state file, so neither loses progress.

## Halt conditions
**Halt:** a cap at/over limit (`ci_fail_count[*]`, `flaky_soak_round[*]`, `empty_runs`,
`retriggerReview`); flake R2+R3 both fail; push divergence + wrong branch; rate-limited repeatedly;
reviewer wants a large refactor or the user interjects; gh auth failure; semantic rebase conflict; on
the base branch / detached HEAD. **Degraded-continue:** ticket route unreachable → local quarantine
only; mechanical rebase conflict → resolve + push; ambiguous comment → reply for clarity + continue.

## See also
- [ship-watch.md](../../references/ship-watch.md) — wake taxonomy, cadence, rate floor, sticky/merge gate, config seam, final-report format
- [ship-flake.md](../../references/ship-flake.md) — the 3-round flake protocol
- [flywheel.md](../../references/flywheel.md) — a fixed CI failure is a confirmed escape; how it feeds back
