# Idempotent re-runs — reconcile, never clobber

`/develop:init` is meant to be re-run: when the stack changes, when CI gains a gate, when the
user wants to refresh discovery. A re-run must **never** silently overwrite work the user
customised. Same discipline the executor uses on resume: **reconcile, don't regenerate.**

> **Golden rule:** show the diff before writing anything, and default to *preserving* the
> user's version on every conflict. The user owns `.claude/`; init only proposes changes.

## Detect (Phase 0)

A re-run is any init where `.claude/develop.config.json` already exists. Inventory what's
already there: `develop.config.json`, `develop-routing.json`, `develop-flywheel.md`, the
hooks + their `settings.json` entries, and a `CLAUDE.md`.

## Classify each target file

For every file init would write, compute one of:

| State | Action |
|---|---|
| **absent** | create it (normal first-run write) |
| **present, == what init would write** | skip silently (no-op) |
| **present, user-customised** | reconcile (per-file rules below); never overwrite |
| **present, init would add new content** | propose an *additive* change; show the diff |

Then present a single consolidated diff and apply only after the user accepts. Applying
nothing on a no-change re-run is a valid, expected outcome.

## Per-file reconcile rules

- **`develop.config.json`** — *merge*, keyed by gate `id`:
  - add gates newly discovered in CI;
  - add fields introduced by a newer `schema` version;
  - **keep** the user's edits to `models`, `caps`, `intensity`, tiers, and any gate
    `command` they changed;
  - **never drop** a gate the user added or kept. If a previously-discovered gate is gone
    from CI, *flag it* for the user — don't delete it for them.
  - If `schema` bumped, migrate and note what changed.
- **`develop-routing.json`** — never overwrite user routes. Only append routes that don't
  already exist; the generalist fallback stays last (see [routing.md](./routing.md)).
- **`CLAUDE.md`** — append only the discovered sections it's missing; never rewrite existing
  prose ([claude-md-starter.md](./claude-md-starter.md)).
- **`develop-flywheel.md`** — create only if absent. It accumulates postmortems and the
  user's promoted anchors — **never** regenerate it.
- **Hooks / `settings.json`** — merge, don't overwrite; preserve existing hooks and any user
  timeout ([../hooks/README.md](../hooks/README.md)).

## Show the diff

Before writing, present the changes as a unified diff (or a per-file before/after) and a
one-line summary per file:

```
develop.config.json   + 1 gate (coverage), kept your model tiers          [will write]
develop-routing.json   no change                                           [skip]
CLAUDE.md              + Commands section (was missing)                    [will write]
develop-flywheel.md    exists — preserved                                  [skip]
settings.json          hooks already present                               [skip]
```

Only write the files marked `[will write]`, and only after the user accepts. A re-run that
changes nothing should say so and write nothing.
