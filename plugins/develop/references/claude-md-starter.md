# Starter `CLAUDE.md` from discovered conventions

`/develop:bootstrap` Phase 3 writes a **short** starter `CLAUDE.md` capturing what it discovered,
so Claude (and the develop loop) has the repo's commands and layout in context. Keep it
minimal — a few lines per section. It's a seed, not a manual; let it grow as the repo
teaches you more.

## Rules

- **Only what you discovered with evidence.** Every command must be a real command from
  Phase 1/2 (the same ones in `develop.config.json`). No aspirational conventions.
- **Don't duplicate the config.** `develop.config.json` is the machine-readable gate source;
  `CLAUDE.md` is the human-readable orientation. The commands appear in both, but `CLAUDE.md`
  adds the *why/where* a human needs.
- **If a `CLAUDE.md` already exists, do not overwrite it.** Propose an *append* of any
  discovered sections it's missing, and show the diff (see [idempotency.md](./idempotency.md)).
- Keep it under ~40 lines. A long generated `CLAUDE.md` is noise.

## What to capture

1. **One-line what-this-repo-is** — from README / package metadata.
2. **Build / test / lint commands** — the real ones, with a word on when to use each
   (cheap vs full).
3. **Layout** — the handful of top-level dirs that matter (where source, tests, CI live).
4. **Conventions worth stating** — only ones you have evidence for (formatter enforced in
   CI, a test-naming pattern, a monorepo workspace rule). Skip if you're guessing.
5. **A pointer** to `.claude/develop.config.json`, `/develop:work`, and `/develop:ship`.

## Template

The companion skeleton is [`templates/CLAUDE.md.template`](../templates/CLAUDE.md.template).
Fill the `<…>` placeholders from discovery; **delete** any section you have no evidence for
rather than leaving a guess.
