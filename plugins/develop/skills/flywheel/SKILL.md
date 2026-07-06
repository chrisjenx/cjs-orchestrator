---
name: flywheel
description: Manually evaluate the develop flow's accumulated run records and decide what to tweak before the next run. Trigger on "/develop:flywheel", "tune the develop flow", "review the postmortems", "what should I improve before the next run", "grow the flow". Aggregates the .claude/develop-flywheel.jsonl SSOT across runs (via the bundled flywheel-aggregate.py), pulls confirmed PR-review + CI escapes into it (flywheel-ingest.py), flags recurring/breaking/escaped finding categories, and proposes the cheapest remediation lever + target for each — human-gated. Run periodically between feature runs, not per feature (PF appends a record per run).
---

# Tune the flow from its postmortems

`/develop:work` *records* each run's residual findings to the flywheel SSOT; this skill *acts*
on the accumulated records. It's the human-gated half of the
[flywheel](../../references/flywheel.md): read what keeps escaping, decide where to tighten,
and apply it. Run it once a few runs have accumulated, not after every feature.

## Read first
- `.claude/develop-flywheel.jsonl` — the machine SSOT (one record per residual finding per run,
  plus the escapes you ingest in step 1); aggregate it with the bundled
  `scripts/flywheel-aggregate.py` (step 2).
- `.claude/develop-flywheel.md` — human-curated: this repo's promoted-anchors table +
  promotion history (so you don't re-propose what's already promoted).
- `.claude/develop.config.json`, `.claude/develop-routing.json` — what gates/agents already
  exist (you reuse-first against these).
- `.claude/agents/` — the repo's own agents (to spot unwired ones — step 2b).
- `.claude/CLAUDE.md` — the repo's existing rules.
- The mechanism: [flywheel.md](../../references/flywheel.md),
  [reuse-and-defer.md](../../references/reuse-and-defer.md),
  [routing.md](../../references/routing.md), [schemas.md](../../references/schemas.md).

## Control flow

### 1. Ingest escapes (PR review + CI) — the highest-signal records
A finding the tail missed but a **human reviewer** (agreed) or **CI** caught is a *confirmed
escape* ([flywheel.md](../../references/flywheel.md)) — pull these into the SSOT before
aggregating. Mechanical, two GitHub paths; use the first available, don't improvise. The filters
below need a thread's *resolved* flag and a check's *per-commit* history, so query the endpoints
that actually carry those — not the simple ones that don't:
- **A GitHub MCP server is connected** → use its tools (structured, no parsing): recently merged
  PRs, each one's review **threads with their resolved flag**, and its **check runs per commit**.
- **else `gh` is on PATH and the remote is GitHub**:
  - merged PRs: `gh pr list --state merged --json number,mergedAt,title`
  - resolved threads (REST `/comments` omits resolution): `gh api graphql` for
    `pullRequest.reviewThreads { isResolved path line comments }`
  - failed checks (`gh pr checks` shows only the current rollup, not history): per PR commit
    (`gh pr view {n} --json commits`), `gh api repos/{owner}/{repo}/commits/{sha}/check-runs`
- **neither** → say so and skip to step 2 (aggregate existing records only).

Keep only the **agreed/real** survivors — the author *acted on* it, not just closed it
(field-based, not judgement):
- review comment: its thread `isResolved` is true **and a later commit addressed it** — a thread
  resolved as won't-fix/not-a-bug has no fix commit; drop those, plus unresolved threads, nits, praise.
- CI check: a check-run that concluded `failure` on a commit and then went **green on a _later_
  commit** (the author fixed it) — drop a same-commit rerun-green (a flake, no code change) and
  checks green throughout.

Normalise each survivor to a signal: stamp `run` with the **PR id** (e.g. `pr-123`) and `date`
with its merge date (so distinct PRs count as distinct runs); for a review give a `category` from
the FINDING enum (the agent's *only* judgement call), for CI give the `checkKind`. (severity and
breaking are derived for you; pass an explicit `fingerprint` only to split two same-kind escapes
in one PR.) Pipe the array
through the bundled mapper — it fills `escaped_phase` + the cheapest lever deterministically and
appends only records not already in the SSOT, so re-scanning the same PRs is idempotent:
```sh
echo "$signals" | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/flywheel-ingest.py" \
  --ssot .claude/develop-flywheel.jsonl
```
(No `python3`? Apply the attribution table in [flywheel.md](../../references/flywheel.md) by hand.)

### 2. Gather
Aggregate the SSOT — run the bundled aggregator (read-only, counts recurrences across runs,
cheapest lever first, irreducible floor set aside):
```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/flywheel-aggregate.py" .claude/develop-flywheel.jsonl
```
(No `python3`? The records are plain JSON lines — read the file and group by `category`
yourself.) Then read the promoted-anchors table in `.claude/develop-flywheel.md` so you don't
re-propose what's already promoted.

### 2b. Detect unwired agents (quick grep)
A repo agent that exists but nothing routes to is a missed reuse — it *should have been
used*. A quick light grep finds them: list the repo's agents, list the names referenced in
routing, and report the difference.

```sh
# repo-local agents that exist
for f in .claude/agents/*.md; do basename "$f" .md; done | sort -u > /tmp/have
# agent names referenced by any route (agent: "x" / agents: ["x", …])
grep -oE '"agents?"[[:space:]]*:[[:space:]]*(\[[^]]*\]|"[^"]*")' .claude/develop-routing.json \
  | grep -oE '"[a-z0-9][a-z0-9-]*"' | tr -d '"' | grep -vE '^(agent|agents)$' | sort -u > /tmp/routed
# UNWIRED = exists but not routed
comm -23 /tmp/have /tmp/routed
```

(If `comm` isn't available, read both files and diff the name sets — it's a tiny list.)
Carry the unwired list into step 5: for each, ask **"should this have caught one of the
recurring findings?"** If yes, wiring it is the cheapest possible fix — it already exists.

### 3. Categorize
Group the **preventable** escaped findings by category across runs; count recurrences and
flag any **breaking-class** ones. Set the **irreducible** floor aside — those aren't
preventable; don't try to "fix" them, just confirm they're staying flat.

### 4. Flag promotion-ready
A category is promotion-ready when it has appeared **≥ 2 times across runs**, is
**breaking-class**, *or* includes a **confirmed escape** (`source: pr-review|ci`) — an escape is
a proven miss, so it promotes at ×1 (the aggregator flags it and names the `escaped_phase`). A
category already promoted but **still recurring or escaping** signals its existing lever is
**inadequate** → mark it for *strengthening*, not a duplicate.

### 5. Evaluate each (reuse first)
For each flagged category, pick the remediation per
[reuse-and-defer.md](../../references/reuse-and-defer.md):
- **Does something already target this?** A rule in `CLAUDE.md`, a gate, a hook, a reviewer?
  If it exists and the finding still escapes, propose **strengthening that** — never add a
  duplicate alongside it.
- **Is there an unwired agent (step 2b) that already covers this?** If one exists but nothing
  routes to it, **wire it in** — add a route in `develop-routing.json`. A cheap, direct edit,
  not a build: an existing agent that should have been used beats authoring a new one.
- **Otherwise pick the cheapest, earliest deterministic lever** that can express the check:
  `hook` → `gate` → `plan-anchor` → `rule` → `agent` (building a *new* reviewer is the last
  resort). Name the **concrete target** (which file / anchor / route / rule line).
- **Pruning:** if a cheaper lever now subsumes a reviewer's catches, propose **reducing or
  merging** that routing entry — removing run cost is as valid an outcome as adding.

### 6. Propose (prioritized)
Present a report, escaped (proven) then cheapest/earliest lever first:

```
Tweaks before next run (you approve which to apply):
  1. <category>  ×<n> runs · ESCAPED→<phase>  → <lever>: <target>   (proven miss, x1)
     edit: <the exact change>            apply: direct | defer-to-workflow
  2. <category>  ×<n> runs [breaking?]  → <lever>: <target>
  3. ...
  Irreducible floor: <n> (unchanged — expected)
  Unwired: <agent> exists but isn't routed — should have caught <category>? → wire it  (cheap)
  Prune: <reviewer> — subsumed by <lever>  (optional)
```

### 7. Human-gate
Ask the user which proposals to apply (`AskUserQuestion`, or an explicit approve list).
**Nothing is applied without approval** — this is the promotion gate.

### 8. Apply
- **Simple deterministic levers — edit directly (after approval, show the diff):** a
  contract-anchor row in `.claude/develop-flywheel.md`; a `gates[]` entry in
  `develop.config.json`; a route added/pruned in `develop-routing.json`; a rule line in
  `CLAUDE.md`; a hook in `.claude/hooks/` + settings.
- **Building/improving an agent, skill, or rule (judgement work) — defer to a workflow:**
  don't hand-author it here. Kick off (or instruct the user to run) a workflow that authors
  it eval-first ([reuse-and-defer.md](../../references/reuse-and-defer.md)); its output lands
  in the repo's `.claude/` for review.

### 9. Record
Update the promoted-anchors table (date / runs seen / lever applied), mark deferred items as
pending-workflow, and annotate the postmortem entries you addressed. Next `/develop:work`
reads the strengthened definitions automatically.

## Invariants
- **Never auto-edit `.claude/` without approval.** The classifier proposes; the human
  promotes. (Ingest *appends* escape records to the SSOT — a log write, not a `.claude/` edit.)
- **A confirmed escape (PR/CI) promotes at ×1** — a proven miss; internal residuals still need ≥2.
- **Reuse first** — strengthen what exists before adding anything new.
- **Cheapest, earliest lever first**; a new agent is the last resort.
- Drives the **preventable** count toward zero; the **irreducible** floor stays.
