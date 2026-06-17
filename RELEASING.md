# Releasing

How a release of the `develop` plugin is cut, and the version policy.

## Version policy

- The plugin version lives in `plugins/develop/.claude-plugin/plugin.json` (`"version"`).
- **Always set a SemVer version.** Claude Code uses it to tell users an update is available.
  If `version` is **omitted**, Claude Code falls back to the git SHA — which works, but
  doesn't signal "newer than what you have", so users won't see updates. So: never ship
  without a `version`.
- [SemVer](https://semver.org/), pre-1.0 conventions:
  - **patch** (`0.2.0 → 0.2.1`) — fixes, doc/wording, no behaviour change to the flow.
  - **minor** (`0.2.0 → 0.3.0`) — new capability (a new reference/agent/skill, a new gate
    kind, a new config field) that is backwards-compatible.
  - **major-ish for pre-1.0** — a breaking change to `develop.config.json`'s `schema`, the
    plan format, or a skill's name/contract. Bump the minor and **bump
    `develop.config.json`'s `schema`** + provide a migration note (init reconciles on re-run;
    see `references/idempotency.md`).
- `marketplace.json` has no version of its own; the plugin's version is the unit users track.

## Cutting a release

1. **Green check.** Run the same checks CI runs:
   ```
   python3 scripts/validate-manifests.py
   python3 scripts/check-install.py
   python3 scripts/check-docs-subpath.py
   python3 scripts/check-docs-leaks.py
   for f in docs/*.js; do node --check "$f"; done
   ```
2. **Bump the version** in `plugins/develop/.claude-plugin/plugin.json`.
3. **Update `CHANGELOG.md`:** move `[Unreleased]` items into a new dated version section,
   add a fresh empty `[Unreleased]`, and update the compare/tag links at the bottom.
4. **Commit** (`release: vX.Y.Z`), open a PR, merge to `main` once CI is green.
5. **Tag and push the tag:**
   ```
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
   Optionally create a GitHub Release from the tag with the CHANGELOG section as the notes.

## After release

- Users get the update via `/plugin install develop@cjs-orchestrator` (or Claude Code's
  update prompt, driven by the bumped `version`).
- Run the [install e2e](evals/install-e2e.md) in a scratch repo for any release that touches
  the manifests, skills, or agents.
