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
    `develop.config.json`'s `schema`** + provide a migration note (bootstrap reconciles on
    re-run; see `references/idempotency.md`).
- `marketplace.json` has no version of its own; the plugin's version is the unit users track.

## Cutting a release

1. **Green check.** Run the authoritative plugin validator (needs the `claude` CLI), then the
   same checks CI runs:
   ```
   claude plugin validate .claude-plugin/marketplace.json   # source of truth: marketplace schema
   claude plugin validate plugins/develop                   # manifest + every agent/skill
   python3 scripts/validate-manifests.py
   python3 scripts/check-install.py
   scripts/install-smoke.sh                                 # live: really installs THIS tree
   python3 scripts/check-docs-subpath.py
   python3 scripts/check-docs-leaks.py
   python3 scripts/check-docs-freshness.py
   for f in docs/*.js; do node --check "$f"; done
   ```
   `validate-manifests.py` mirrors the validator's source-shape, `agents`-field, and
   frontmatter-parse checks in CI; `claude plugin validate` is the source of truth when cutting
   locally (it caught the gh #30 install break that plain JSON validation missed).

   **`install-smoke.sh` is required for any release that touches the manifests, skills, or
   agents.** It drives a real `claude plugin marketplace add` + `install` of the working tree in
   an isolated throwaway config and asserts the plugin resolves at plugin.json's version with all
   skills, agents, and the guard hook — the gh #30 class (valid JSON, un-installable) that the
   structural checks miss. Needs the `claude` CLI (exits 2 = skip if absent, e.g. in CI). It does
   not cover the interactive trigger (see After release).
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
- The pre-release green check already ran `scripts/install-smoke.sh` (automated install). The
  part it can't automate is the interactive last mile: in a scratch Claude Code session, type
  `/develop:bootstrap` and confirm it triggers and degrades gracefully in an empty repo
  ([install e2e](evals/install-e2e.md)). Do this for any release touching manifests, skills, or
  agents.
