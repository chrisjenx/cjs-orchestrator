# cjs-orchestrator — working notes

A **public** Claude Code plugin marketplace + the `develop` plugin + an interactive explainer site (`docs/`, served via GitHub Pages).

- Marketplace: `.claude-plugin/marketplace.json`
- Plugin: `plugins/develop/` (manifest in `plugins/develop/.claude-plugin/plugin.json`)
- Skills: `skills/init/SKILL.md` → `/develop:init`; `skills/run/SKILL.md` → `/develop:run`;
  `skills/flywheel/SKILL.md` → `/develop:flywheel` (manual postmortem tuner)
- Explainer: `docs/` (no-build static site: HTML + CSS + vanilla JS)

**Locked architecture (see [DECISIONS.md](DECISIONS.md)):** the plugin ships *static,
portable skills*; per-project behaviour comes from *definitions `/develop:init` discovers
and writes* into the target's `.claude/` (`develop.config.json`, `develop-routing.json`,
starter `CLAUDE.md`, safe hooks, flywheel). `/develop:run` is the static orchestrator loop
that reads those definitions. The portable mechanism (plan anatomy, executor brief, gate
tokens) lives in `plugins/develop/references/`; the stack-agnostic auditors in
`plugins/develop/agents/`. Names are locked — do not rename.

---

## Token frugality — first principle for every edit

Everything the plugin ships loads on **every run, for every user, forever** — one wasted token compounds over millions of runs. So author tight: say it once, say it short, then stop. Inline excerpts not whole files; one status line not a paragraph; fixed short return contracts; state each fact once and link rather than restate. This governs all shipped prose — skills, references, agent prompts — and this file. Canonical statement + rules: [`plugins/develop/references/token-frugality.md`](plugins/develop/references/token-frugality.md). Before committing any prose edit, re-read it and cut what doesn't earn its tokens.

---

## Keep it generic (public repo)

The explainer in `docs/` is **genericized from a real but private case study**. It has been scrubbed of project-specific data and the brand. **Keep it that way** — the tool is meant to be stack-agnostic, so the explainer must be too.

### Never add (back) — these would re-leak private info

- **Real internal agent/skill names** — use generic roles (`scaffolder`, `ui-codegen`, `ui-evaluator`, `migration-reviewer`, `domain-reviewer`, `portability-reviewer`).
- **Commit SHAs**, **internal ticket / anchor IDs** (`<PREFIX>-###`, `W##` codes).
- **Brand / product names**, **private hostnames / packages** (use `com.example.*`).
- **Stack/domain fingerprints** — name no specific framework, language, build tool, or domain. Pick neutral terms: "the UI layer", "the shared layer", "the build tool", "lint", "coverage".
- **Token/cost figures** are **representative/anonymized** — keep them framed that way, never re-attribute to private runs ("mined from our transcripts", run counts, store sizes).

### Find leaks before you commit

CI enforces this on every PR (`.github/workflows/ci.yml` → `scripts/check-docs-leaks.py`),
and you can mirror it locally: `git config core.hooksPath .githooks`. To check by hand:

```bash
python3 scripts/check-docs-leaks.py   # SHAs, TICKET-### ids, W## codes (deterministic)
# also grep docs/ for any real brand, framework, language, build-tool, or
# hostname you might have referenced — keep everything stack-neutral.
```

Each docs file carries a `PUBLIC REPO` banner pointing back here.

> **History:** the original (unscrubbed) docs were pushed in the first commit, so history was rewritten to purge them before the repo gained forks/clones (see the issues). If you ever reintroduce and then scrub private data, do the same — a working-tree scrub alone leaves it in the log.

---

## Working on it

- **`docs/`** is a no-build static site. After any change, verify it loads with **zero JS errors** (open `index.html`, or headless via jsdom) before committing.
- **Plugin manifests** are schema-valid JSON — validate `marketplace.json` + `plugin.json` before commit. Layout follows the Claude Code plugin spec (components at plugin root, only `plugin.json` inside `.claude-plugin/`).
- The plugin's guiding principle is **"discover, don't transplant"**: the bootstrapper fits a `/develop` flow to the target repo's real commands rather than copying a finished system. Keep new content aligned with that.
- Backlog lives in **GitHub issues** (labels: `mvp`, `area:plugin`, `area:docs`, `area:infra`).
