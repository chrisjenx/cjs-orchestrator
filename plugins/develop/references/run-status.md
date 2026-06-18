# Run status — the glance-readable phase stream

A `/develop:run` is meant to be **fire-and-forget**: kicked off, then left alone. So someone
who *does* drop into the session has to read where it's at in one glance — not scroll a wall
of prose. The orchestrator emits **one status line per transition**: a marker, the phase, and
the few facts that matter. Nothing else between phases.

> This is narration for the human watching — it is **not** state. State lives in the plan
> file ([plan-anatomy.md](./plan-anatomy.md)); the Execution Log is the durable record. The
> status line is the cheap, ephemeral mirror of it.

## Markers

| Marker | Means |
|---|---|
| `▸` | phase **started** / in progress — verb in `-ing`, trailing `…` while a sub-agent runs |
| `✓` | phase **done**, or a gate is green |
| `⚠` | **needs a human decision** — a between-phase gate or escalation is being surfaced |
| `✗` | **failed / blocked** — a gate failed after its budget, or a phase went `BLOCKED` |

## Line grammar

```
<marker> <phase-id?> <short name> · <fact> · <fact>
```

- One line. Lower-case. No trailing punctuation. Aim ≤ ~12 words.
- `·` separates fields. Use the **real** phase ids (`P1`, `PV`, `PA`, `PT`, `PF`) so the line
  maps straight to the plan.
- Gate tokens render **exactly as on the node** and carry their result:
  `{build}✓ {test}✓ {lint}✗ {cov>=80}✓` ([gate-tokens.md](./gate-tokens.md)).
- On entering a phase, emit a `▸ …` line; on leaving, emit the `✓` / `⚠` / `✗` outcome line.

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

The last line is always the mechanical terminal status (see the table in
[run/SKILL.md](../skills/run/SKILL.md)): `ready`, `ready-with-escalations`,
`committed-with-failures`, `commit-failed`, `planning-failed`.

## Terse everywhere (token-conscious by construction)

The status line exists to **replace** prose narration, not add to it — a glyph line is a
handful of tokens; a paragraph is hundreds. The same discipline applies to everything the
orchestrator emits and dispatches:

- **One line per transition, never a paragraph.** Don't restate what the line already says.
- **Only the orchestrator narrates.** Sub-agents emit no status lines — they write the plan
  and return their fixed short contract ([executor-brief.md](./executor-brief.md)). Two
  narrators is noise.
- **Briefs inline excerpts, not whole files** (< ~1000 tokens; [executor-brief.md](./executor-brief.md)).
- **Every return is a fixed few lines** — `STATUS:` / `NESTED:` style contracts, structured
  schemas ([schemas.md](./schemas.md)), not free prose.

If you're tempted to write a paragraph between phases, you've found the line that should have
been one marker instead.
