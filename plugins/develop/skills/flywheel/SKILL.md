---
name: flywheel
description: Manually evaluate the develop flow's accumulated postmortems and decide what to tweak before the next run. Trigger on "/develop:flywheel", "tune the develop flow", "review the postmortems", "what should I improve before the next run", "grow the flow". Reads .claude/develop-flywheel.md across runs, flags recurring/breaking finding categories, and proposes the cheapest remediation lever + target for each — human-gated. Run periodically between feature runs, not per feature (PF already logs each run).
---

# Tune the flow from its postmortems

`/develop:run` *logs* a postmortem after every run; this skill *acts* on the accumulated
logs. It's the human-gated half of the [flywheel](../../references/flywheel.md): read what
keeps escaping, decide where to tighten, and apply it — so the next run is stronger. Run it
periodically once a few runs have accumulated, not after every feature.

## Read first
- `.claude/develop-flywheel.md` — the postmortem log + this repo's promoted-anchors table.
- `.claude/develop.config.json`, `.claude/develop-routing.json` — what gates/agents already
  exist (you reuse-first against these).
- `.claude/agents/` — the repo's own agents (to spot unwired ones — step 1b).
- `.claude/CLAUDE.md` — the repo's existing rules.
- The mechanism: [flywheel.md](../../references/flywheel.md),
  [reuse-and-defer.md](../../references/reuse-and-defer.md),
  [routing.md](../../references/routing.md), [schemas.md](../../references/schemas.md).

## Control flow

### 1. Gather
Read every postmortem block in `.claude/develop-flywheel.md` and the promoted-anchors table
(so you don't re-propose what's already promoted).

### 1b. Detect unwired agents (quick grep)
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

(If `comm` isn't available, just read both files and diff the name sets — it's a tiny list.)
Carry the unwired list into step 4: for each, ask **"should this have caught one of the
recurring findings?"** If yes, wiring it is the cheapest possible fix — it already exists.
Group the **preventable** escaped findings by category across runs; count recurrences and
flag any **breaking-class** ones. Set the **irreducible** floor aside — those aren't
preventable; don't try to "fix" them, just confirm they're staying flat.

### 3. Flag promotion-ready
A category is promotion-ready when it has appeared **≥ 2 times across runs** *or* is
**breaking-class**. A category already promoted but **still recurring** is a signal its
existing lever is **inadequate** → mark it for *strengthening*, not a duplicate.

### 4. Evaluate each (reuse first)
For each flagged category, pick the remediation per
[reuse-and-defer.md](../../references/reuse-and-defer.md):
- **Does something already target this?** A rule in `CLAUDE.md`, a gate, a hook, a reviewer?
  If it exists and the finding still escapes, propose **strengthening that** — never add a
  duplicate alongside it.
- **Is there an unwired agent (step 1b) that already covers this?** If one exists but nothing
  routes to it, the fix is to **wire it in** — add a route in `develop-routing.json`. That's a
  cheap, direct edit, not a build: an existing agent that should have been used beats authoring
  a new one.
- **Otherwise pick the cheapest, earliest deterministic lever** that can express the check:
  `hook` → `gate` → `plan-anchor` → `rule` → `agent` (building a *new* reviewer is the last
  resort). Name the **concrete target** (which file / anchor / route / rule line).
- **Pruning:** if a cheaper lever now subsumes a reviewer's catches, propose **reducing or
  merging** that routing entry — removing run cost is as valid an outcome as adding.

### 5. Propose (prioritized)
Present a report, cheapest/earliest lever first:

```
Tweaks before next run (you approve which to apply):
  1. <category>  ×<n> runs [breaking?]  → <lever>: <target>
     edit: <the exact change>            apply: direct | defer-to-workflow
  2. ...
  Irreducible floor: <n> (unchanged — expected)
  Unwired: <agent> exists but isn't routed — should have caught <category>? → wire it  (cheap)
  Prune: <reviewer> — subsumed by <lever>  (optional)
```

### 6. Human-gate
Ask the user which proposals to apply (`AskUserQuestion`, or an explicit approve list).
**Nothing is applied without approval** — this is the promotion gate.

### 7. Apply
- **Simple deterministic levers — edit directly (after approval, show the diff):** a
  contract-anchor row in `.claude/develop-flywheel.md`; a `gates[]` entry in
  `develop.config.json`; a route added/pruned in `develop-routing.json`; a rule line in
  `CLAUDE.md`; a hook in `.claude/hooks/` + settings.
- **Building/improving an agent, skill, or rule (judgement work) — defer to a workflow:**
  don't hand-author it here. Kick off (or instruct the user to run) a workflow that authors
  it eval-first ([reuse-and-defer.md](../../references/reuse-and-defer.md)); its output lands
  in the repo's `.claude/` for review.

### 8. Record
Update the promoted-anchors table (date / runs seen / lever applied), mark deferred items as
pending-workflow, and annotate the postmortem entries you addressed. Next `/develop:run`
reads the strengthened definitions automatically.

## Invariants
- **Never auto-edit `.claude/` without approval.** The classifier proposes; the human
  promotes.
- **Reuse first** — strengthen what exists before adding anything new.
- **Cheapest, earliest lever first**; a new agent is the last resort.
- Drives the **preventable** count toward zero; the **irreducible** floor stays.
