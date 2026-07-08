# End-to-end install test (scratch repo)

Verifies a real user path: add the marketplace, install the plugin, and confirm
`/develop:bootstrap` triggers — in a clean scratch repo. Closes #23.

## Automated pre-check (run in CI + locally)

```
python3 scripts/check-install.py
```
Validates everything the install resolves: the marketplace → plugin-dir mapping, the plugin
manifest, both skills' triggering frontmatter, the agents, and that **every** cross-reference
link in the plugin's docs resolves (so the loop won't hit a dead reference at runtime). This
catches the structural breakages that would make an install or a run fail.

## Live run (interactive — inside Claude Code)

The `/plugin` commands run inside Claude Code, against the repo on GitHub, so the branch must
be on the default branch first (the marketplace pulls from it).

**Prerequisite:** this work is merged to `main` (or, to test before merging, use the
local-path variant below).

1. In a **clean scratch repo** (e.g. `mkdir /tmp/scratch && cd /tmp/scratch && git init`),
   start Claude Code.
2. Add the marketplace and install:
   ```
   /plugin marketplace add chrisjenx/cjs-orchestrator
   /plugin install develop@cjs-orchestrator
   ```
   Expect: marketplace added, plugin `develop` installed, no manifest errors.
3. Confirm the skills are present and trigger:
   ```
   /develop:bootstrap
   ```
   Expect: the bootstrapper activates (Phase 0 re-run check → Phase 1 stack detection). In an
   empty repo it should detect "unknown" gracefully and ask for gate commands rather than
   erroring (see references/stacks.md). Also confirm `/develop:work` is listed.
4. Run the [triggering matrix](./triggering.md) phrases and confirm bootstrap vs work fire on the
   right intents.

### Testing before merge (local-path marketplace)

```
/plugin marketplace add /Users/<you>/git/cjs-orchestrator
/plugin install develop@cjs-orchestrator
```
Adds the marketplace from the local working tree, so you can exercise the full install +
trigger path on the current branch before pushing.

## Pass criteria
- `scripts/check-install.py` exits 0.
- Marketplace add + install complete with no manifest/JSON errors.
- `/develop:bootstrap` and `/develop:work` are both available and trigger on their intents.
- In an empty scratch repo, `/develop:bootstrap` degrades gracefully (asks for gates) rather than
  failing.
