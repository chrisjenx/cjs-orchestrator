# cjs-orchestrator

**Fire one prompt. Walk away. Get back a branch that already passed your own review.**

Stop babysitting your agent at every handoff. `/develop` plans the change, builds it, audits the diff against your repo's own rules, and clears your gates before it hands the branch back. It's a **self-improving, agentic flow fitted to *your* repo**, not transplanted from someone else's.

This repo is both a **Claude Code plugin marketplace** and the home of the **`develop`** plugin, plus an interactive explainer of how the underlying orchestration works.

- **Explainer site:** https://chrisjenx.github.io/cjs-orchestrator/
- **Plugin:** `develop` bootstraps a minimal orchestration flow and grows it via a feedback flywheel.

> **Status: early (v0).** The bootstrapper skill guides you through setup today; the deeper automation is tracked in [issues](https://github.com/chrisjenx/cjs-orchestrator/issues).

## Why "grow", not "transplant"

An agentic `/develop` pipeline *looks* like a pile of files, but most of its value is bound to one repo: the gate commands (`./gradlew test`, `npm test`, `cargo test`…), the specialist registry, the conventions. Copying another project's setup installs assumptions that misfire.

So the plugin doesn't copy a finished system. It **discovers your repo's real commands**, generates a *minimal* orchestrator (one generalist executor, a plan file, your actual gates), and gives you a **flywheel** that grows specialists and parallel verification only where repeated pain shows.

The portable part is a small set of moves: state in a file, narrow context per agent, structural gates, close the loop. Everything else is fitted to you.

## Install

```text
/plugin marketplace add chrisjenx/cjs-orchestrator
/plugin install develop@cjs-orchestrator
```

Then, in the repo you want to set up:

```text
/develop:init     # once: detect your stack, confirm gates, scaffold the config
/develop:work      # per feature: spec → reviewed, committed branch
/develop:ship      # per branch: push, watch CI + review, merge
/develop:flywheel # periodically: review postmortems, tune the flow for next run
```

`/develop:init` detects your stack, confirms the real gate commands with you, and writes
the repo-specific definitions (gates, conventions, routing, safe hooks) into `.claude/`.
`/develop:work` is the portable orchestrator loop: it ships **static** in the plugin but
behaves **fitted to your repo** because it reads those discovered definitions, and hands off a
committed branch (it never pushes). `/develop:ship` takes it from there — push, open the PR, and a
Monitor-driven watcher babysits CI and review to merge, waking you only for judgment. See
[DECISIONS.md](DECISIONS.md) for the locked names and architecture.

## Layout

```
cjs-orchestrator/
├── .claude-plugin/marketplace.json   # marketplace catalog
├── plugins/develop/                  # the plugin
│   ├── .claude-plugin/plugin.json
│   ├── skills/init/SKILL.md          # the /develop:init bootstrapper
│   ├── skills/work/SKILL.md           # the /develop:work orchestrator loop
│   ├── skills/ship/SKILL.md           # the /develop:ship CI watcher
│   ├── skills/flywheel/SKILL.md      # the /develop:flywheel tuner
│   ├── scripts/                      # bundled engines (ship.py, flywheel-*.py)
│   ├── references/                   # portable mechanism (plan anatomy, briefs, gates)
│   ├── agents/                       # portable, stack-agnostic auditor agents
│   └── hooks/                        # safe, stack-agnostic hooks
└── docs/                             # the explainer site (GitHub Pages)
```

## Releases

Changes are in [CHANGELOG.md](CHANGELOG.md); the release flow and SemVer version policy are in
[RELEASING.md](RELEASING.md). The plugin version (`plugins/develop/.claude-plugin/plugin.json`)
is what Claude Code uses to surface updates; it's always set, never omitted.

## License

MIT © Chris Jenkins. See [LICENSE](LICENSE).

Pattern lineage cross-references Anthropic's [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents).
