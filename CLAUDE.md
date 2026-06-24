# cjs-orchestrator — working notes

A **public** Claude Code plugin marketplace + the `develop` plugin + an interactive explainer (`docs/`, GitHub Pages).

- Marketplace: `.claude-plugin/marketplace.json`
- Plugin: `plugins/develop/` (manifest in its `.claude-plugin/plugin.json`)
- Skills → commands: `skills/init` → `/develop:init`, `skills/run` → `/develop:run`, `skills/flywheel` → `/develop:flywheel`
- Explainer: `docs/` — no-build static site (HTML + CSS + vanilla JS)

**Locked architecture ([DECISIONS.md](DECISIONS.md)):** the plugin ships *static, portable skills*; per-project behaviour comes from *definitions `/develop:init` writes* into the target's `.claude/` (`develop.config.json`, `develop-routing.json`, starter `CLAUDE.md`, hooks, flywheel). `/develop:run` is the static orchestrator that reads them. Mechanism → `plugins/develop/references/`; stack-agnostic auditors → `plugins/develop/agents/`. **Names are locked — don't rename.**

## Token frugality — first principle for every edit

Everything the plugin ships loads on **every run, for every user, forever** — one wasted token compounds over millions of runs. Author tight: say it once, say it short, stop. Inline excerpts not whole files; one status line not a paragraph; fixed short return contracts; state each fact once and link, don't restate. Governs all shipped prose (skills, references, agent prompts) and this file. Rules: [`references/token-frugality.md`](plugins/develop/references/token-frugality.md) — re-read before any prose edit and cut what doesn't earn its tokens.

## Keep it generic (public repo)

`docs/` is **genericized from a real but private case study** — keep it stack-neutral and brand-free. **Never re-add** (each re-leaks private info):

- **Real internal agent/skill names** — use generic roles (`scaffolder`, `ui-codegen`, `ui-evaluator`, `migration-reviewer`, `domain-reviewer`, `portability-reviewer`).
- **Commit SHAs**, **internal ticket/anchor IDs** (`<PREFIX>-###`, `W##`).
- **Brand/product names**, **private hostnames/packages** (use `com.example.*`).
- **Stack/domain fingerprints** — no specific framework, language, build tool, or domain; use neutral terms ("the UI layer", "the build tool", "lint", "coverage").
- **Token/cost figures** — keep framed as representative/anonymized; never re-attribute to private runs.

**Before committing:** CI runs two leak scanners on every PR — `scripts/check-docs-leaks.py` (brand / framework / language / build-tool fingerprints in `docs/`) and `scripts/check-private-leaks.py` (case-study product / org / package identifiers, hashed denylist, everywhere *outside* `docs/` — the gap that let a stack fingerprint reach `plugins/`). Mirror locally (`git config core.hooksPath .githooks`), run both by hand, and grep `docs/` for any real brand / hostname. Each docs file carries a `PUBLIC REPO` banner.

> **History:** unscrubbed docs were purged by a history rewrite before the repo gained forks (see issues). If you reintroduce then scrub private data, do the same — a working-tree scrub leaves it in the log.

## Working on it

- **`docs/`** — after any change, verify it loads with **zero JS errors** before committing.
- **Manifests** — `marketplace.json` + `plugin.json` must be schema-valid JSON; layout per the plugin spec (components at plugin root, only `plugin.json` in `.claude-plugin/`).
- **"Discover, don't transplant"** — the bootstrapper fits `/develop` to the target repo's real commands, never copies a finished system. Keep new content aligned.
- Backlog: GitHub issues (labels `mvp`, `area:plugin`, `area:docs`, `area:infra`).
