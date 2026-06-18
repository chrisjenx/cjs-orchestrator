# Run status — the glance-readable phase stream

A `/develop:run` is fire-and-forget, so anyone who *does* drop into the session must read
where it's at in one glance. The orchestrator emits **one status line per transition** — a
marker, the phase, the few facts that matter. Nothing else between phases.

This is narration for the human watching, **not** state — state lives in the plan file
([plan-anatomy.md](./plan-anatomy.md)). The line is the cheap, ephemeral mirror of the
Execution Log.

## Markers

| Marker | Means |
|---|---|
| `▸` | phase **started** / in progress — verb in `-ing`, trailing `…` while a sub-agent runs |
| `✓` | phase **done**, or a gate is green |
| `⚠` | **needs a human decision** — a between-phase gate or escalation is surfacing |
| `✗` | **failed / blocked** — a gate failed after its budget, or a phase went `BLOCKED` |

## Line grammar

```
<marker> <phase-id?> <short name> · <fact> · <fact>
```

- One line, lower-case, no trailing punctuation, ≤ ~12 words; `·` separates fields.
- Use the **real** phase ids (`P1`, `PV`, `PA`, `PT`, `PF`) so the line maps to the plan.
- Gate tokens render **as on the node**, with their result:
  `{build}✓ {test}✓ {lint}✗ {cov>=80}✓` ([gate-tokens.md](./gate-tokens.md)).
- Emit `▸ …` on entering a phase, then the `✓` / `⚠` / `✗` outcome on leaving.

## A whole run, at a glance

```
▸ intake · spec → feature `profile-editing`
▸ worktree · develop/profile-editing
▸ assess · scope medium · areas ui,api · caps default
▸ plan · planner…
✓ plan · 5 phases · 12 reqs · 2 agents routed
▸ P1 scaffold · executor…
✓ P1 · done 3/3 · {build}✓ {lint}✓
▸ P2 wire api · executor…
⚠ P2 · blocked · 1 HIGH finding → asking
✓ P2 · resolved · done 2/2 · {types}✓
▸ PV validate · pass
▸ PA audit · 5 auditors…
✓ PA · 2 findings → fixed
▸ PT tidy · clean
▸ PF finalize · {build}✓ {test}✓ {cov>=80}✓
✓ committed `a1b2c3d` · ready
```

The last line is always the mechanical terminal status (table in
[run/SKILL.md](../skills/run/SKILL.md)): `ready`, `ready-with-escalations`,
`committed-with-failures`, `commit-failed`, `planning-failed`.

> The status line **replaces** prose narration — it doesn't add to it. Only the orchestrator
> narrates; sub-agents return their fixed contracts ([executor-brief.md](./executor-brief.md)),
> they don't. See [token-frugality.md](./token-frugality.md).
