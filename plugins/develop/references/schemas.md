# Structured-output schemas

The portable, stack-neutral schemas the loop and the agents exchange. Keep agents emitting
these exact shapes so the orchestrator can dedup, consolidate, and route mechanically
without parsing prose.

## FINDING — one defect

```json
{
  "file": "path/to/File.ext",
  "line": 42,
  "category": "missing-test | stub | regression | missing-guard | duplicate | ...",
  "severity": "high | medium | low | quality",
  "description": "what's wrong, in one or two sentences",
  "fix": "suggested fix (optional)"
}
```

**Fingerprint** (dedup key for the Finding Registry): `severity:file:line:slug`, where
`slug` is a short kebab of the category/description. Same fingerprint = same finding; update
the row's status instead of adding a duplicate.

## FINDINGS — an agent's report

```json
{ "findings": [ { /* FINDING */ } ], "summary": "one line" }
```

## PLAN — the planner's output ([planner](../agents/planner.md))

```json
{
  "requirements": [
    { "id": "R1", "text": "...", "areas": ["ui", "api"], "verifiedBy": "{test:...} | {grep:...}" }
  ],
  "phases": [
    {
      "id": "P1", "description": "...", "dependsOn": [],
      "nodes": [
        { "id": "P1.a", "action": "...", "agent": "executor",
          "gates": ["build", "test:<selector>"], "dependsOn": [], "reuse": "extend path/Existing" }
      ]
    }
  ],
  "gaps": ["a slice no existing agent/skill/rule covers — defer, don't invent"],
  "summary": "one line"
}
```

Domain phases only — the orchestrator appends the quality tail. `agent` on each node is an
*already-defined* agent chosen by routing; an uncovered slice goes to `executor` + a `gap`.

## VERDICT — a phase outcome (`pass` | `iterate` | `escalate`)

```json
{
  "result": "pass | iterate | escalate",
  "findings": [ { /* FINDING */ } ],
  "summary": "one line"
}
```

- `pass` — nothing blocking found.
- `iterate` — fixable in place; the loop re-dispatches with these findings.
- `escalate` — needs a human decision; surfaces at the between-phase gate.

Reviewers/auditors return `FINDINGS`; the orchestrator **derives** the VERDICT from them
(none blocking → `pass`, fixable → `iterate`, needs-a-human → `escalate`). Refuters return
`REFUTER_VERDICT`, below.

## ESCALATION reason — the tag on a `BLOCKED:<reason>` executor return

One of `context` · `reasoning` · `too-large` · `plan` — *what kind* of stuck, so the orchestrator
can route its response ([run/SKILL.md](../skills/run/SKILL.md) step 6) instead of just asking:

- `context` — the brief lacked information the slice needed.
- `reasoning` — the slice needs more capable reasoning than this tier.
- `too-large` — too big to do well as one phase.
- `plan` — the plan/spec itself is wrong here.

`DONE-CONCERNS` is a separate executor state: nodes done but correctness doubted — advances with
extra scrutiny in PV/PA, not a blocker.

## GATE_RESULT — a gate command's outcome

```json
{
  "pass": true,
  "command": "the exact command run",
  "kind": "build | test | lint | format | types | coverage",
  "failures": ["extracted failure lines"],
  "deferred": false
}
```

`deferred: true` means a heavy gate annotated `DEFERRED-PF` (run by finalize), or a gate
whose *environment* failed to run (don't loop on it — see [gate-tokens.md](./gate-tokens.md)).

## REFUTER_VERDICT — adversarial verification (opt-in, see [verify-by-forking.md](./verify-by-forking.md))

```json
{ "refuted": true, "reason": "why the claim does/doesn't hold", "confidence": "high|low" }
```

Default to `refuted: true` when uncertain — the refuter's job is to *try to kill* the claim.

## CONTRACT_GAP — flywheel classification (see [flywheel.md](./flywheel.md))

```json
{
  "category": "the finding class",
  "preventable": true,
  "remediation": "hook | gate | plan-anchor | rule | agent — the lever that should catch it",
  "target": "the concrete destination (hook id / lint rule / contract anchor / rule doc / agent + add|modify|reduce)"
}
```

## FLYWHEEL_RECORD — one line of the flywheel SSOT ([flywheel.md](./flywheel.md))

`PF` appends one line per residual finding to `.claude/develop-flywheel.jsonl` (append-only,
the machine SSOT) — a `CONTRACT_GAP` stamped with the run + the finding's fingerprint:

```json
{
  "run": "<feature>", "date": "YYYY-MM-DD",
  "fingerprint": "severity:file:line:slug",
  "category": "the finding class", "severity": "high|medium|low|quality",
  "source": "run | pr-review | ci",
  "preventable": true, "breaking": false,
  "escaped_phase": "planner | PV | PA | PT | PF",
  "remediation": "hook | gate | plan-anchor | rule | agent",
  "target": "the concrete destination"
}
```

`source` defaults to `run` (a tail residual). `source: pr-review | ci` marks a **confirmed
escape** — a finding the whole tail missed but an agreed PR review or CI caught — so it's
preventable by definition and **promotion-ready at ×1**; `escaped_phase` records which phase
should have caught it ([flywheel.md](./flywheel.md)). For an escape, `run` is the source PR id
(`date` its merge date), so distinct PRs count as distinct runs and `flywheel-ingest.py` dedups
re-ingestion on `(run, fingerprint)`. Irreducible findings carry
`preventable: false` and may omit `remediation`/`target`. The bundled
`scripts/flywheel-aggregate.py` reads this file at `/develop:flywheel` time — never in the run
loop — to count recurrences across runs; `scripts/flywheel-ingest.py` writes the escape lines.

## Conventions

- Severities: `high` blocks; `medium` should be fixed; `low`/`quality` are cleanup.
- Always include `file` + `line` when a finding is locatable — the fingerprint depends on it.
- Agents return **only** the schema object, not prose around it.
