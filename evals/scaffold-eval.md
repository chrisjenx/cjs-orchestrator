# Scaffold eval — run `/develop:bootstrap` for real and validate what it writes

The detection eval ([README](./README.md)) is **read-only**: it checks Phase 1–2 discovery and
forbids writes. This is the **write** eval: it runs bootstrap's full Phase 0–4 in a sandbox, captures
the `.claude/` scaffold it writes, and asserts the whole artifact — then measures run-to-run
variance and, for an existing repo, diffs against that repo's hand-built `.claude/` golden.

`/develop:bootstrap` is LLM-driven, so its output is never bit-identical. Only the parts sourced
deterministically are asserted; prose is not:

| Layer | Deterministic? | Asserted by |
|---|---|---|
| required files present, `develop.config.json` schema-shaped | yes | `check-scaffold.py` validate |
| gate set + commands (mirror CI) | yes | validate, from `expected.json` |
| stack, routing generalist fallback, safe hook, empty flywheel `.jsonl` | yes | validate |
| `CLAUDE.md` prose, config `evidence`, `notes`, gate `id` naming, `scopedCommand` | no | not asserted |

Tooling: [`scripts/check-scaffold.py`](../scripts/check-scaffold.py) — `validate` and `--compare`.

## Protocol

1. **Sandbox** — copy the target repo to a temp dir *outside* this repo, `git init`, drop any
   eval metadata:
   ```sh
   d=/tmp/develop-bootstrap-eval/run1
   mkdir -p "$d" && cp -R <target>/. "$d/" && ( cd "$d" && git init -q && git add -A && git commit -qm init )
   ```
2. **Run** — dispatch one in-session subagent (general-purpose) per sandbox with the contract
   below. For the variance probe, run N≥2 in parallel with the *same* prompt (only the target
   path differs).
3. **Validate** each run against the stack's expected discovery:
   ```sh
   python3 scripts/check-scaffold.py /tmp/develop-bootstrap-eval/run1 evals/fixtures/<stack>/expected.json
   ```
4. **Variance** — the deterministic core must be identical across runs:
   ```sh
   python3 scripts/check-scaffold.py --compare /tmp/develop-bootstrap-eval/run1 /tmp/develop-bootstrap-eval/run2
   ```
5. **Cleanup** — `rm -rf /tmp/develop-bootstrap-eval`.

### Subagent contract (the run step)

Point it at the plugin (read-only) and the sandbox (write target):

- Plugin `plugins/develop`: execute `skills/bootstrap/SKILL.md`, reading the references it cites as
  you reach each phase (stack-detection, gate-tokens, config-schema, model-tiers, routing,
  claude-md-starter, idempotency) plus `templates/` and `hooks/`.
- Target = the sandbox dir: **every** file bootstrap writes (`.claude/...`, `CLAUDE.md`) goes there
  and nowhere else; never touch the plugin repo.
- Non-interactive: where the skill says confirm the stack/gates, AUTO-CONFIRM and proceed. Base
  every gate strictly on the target's CI — mirror it exactly; no aspirational gates. Skip Phase 5
  (no toolchain). Write real files.
- Report: the `.claude/` tree, `develop.config.json`, `develop-routing.json`, the `CLAUDE.md`,
  the merged `settings.json` hooks/env, and any judgment calls.

## Validating against an existing repo's golden

To check bootstrap *recreates* a repo you already set up by hand, run **from inside that repo's own
checkout** so nothing private ever leaves it:

1. Sandbox a copy with `.claude/` and `CLAUDE.md` removed; run bootstrap into it (steps 1–2).
2. `check-scaffold.py validate <sandbox> <that repo's expected.json>` — does a fresh bootstrap produce
   a correct day-one scaffold?
3. `check-scaffold.py --compare <repo-with-its-real-.claude> <sandbox>` — where do they differ?

Read the `--compare` output with the flywheel in mind:

- **Should match:** gates, stack, config shape, model/cap defaults, the safe hook, the empty
  flywheel seed. A divergence here is a **bootstrap bug** — fix the skill.
- **Will differ, expected:** routing specialists, promoted `CLAUDE.md` anchors, anything in
  `.claude/agents/`. That is growth the flywheel added over many runs, not bootstrap's day-one job.

## Fixing failures (Iron Law)

A red check drives a fix in `skills/bootstrap/SKILL.md` or the references it reads — never a tweak to
the validator or `expected.json` to make a bad result pass. The skill is the code under test.
