# cjs-orchestrator

Build a **self-improving, agentic `/develop` flow** — fitted to *your* repo, not transplanted from someone else's.

This repo is both a **Claude Code plugin marketplace** and the home of the **`develop`** plugin, plus an interactive explainer of how the underlying orchestration works.

- 📖 **Explainer site:** https://chrisjenx.github.io/cjs-orchestrator/
- 🧩 **Plugin:** `develop` — bootstraps a minimal orchestration flow and grows it via a feedback flywheel.

> **Status: early (v0).** The bootstrapper skill guides you through the setup today; the deeper automation is tracked in [issues](https://github.com/chrisjenx/cjs-orchestrator/issues).

## Why "grow", not "transplant"

An agentic `/develop` pipeline *looks* like a pile of files, but ~80% of its value is bound to one repo — the gate commands (`./gradlew test`, `npm test`, `cargo test`…), the specialist registry, the conventions. Copying another project's setup installs assumptions that misfire.

So the plugin doesn't copy a finished system. It **discovers your repo's real commands**, generates a *minimal* orchestrator (one generalist executor, a plan file, your actual gates), and gives you a **flywheel** that grows specialists and parallel verification only where repeated pain shows.

The portable part is a small set of moves — state in a file, narrow context per agent, structural gates, close the loop. Everything else is fitted to you.

## Install

```text
/plugin marketplace add chrisjenx/cjs-orchestrator
/plugin install develop@cjs-orchestrator
```

Then, in the repo you want to set up:

```text
/develop:init
```

It will detect your stack, confirm the real gate commands with you, and scaffold a minimal flow.

## Layout

```
cjs-orchestrator/
├── .claude-plugin/marketplace.json   # marketplace catalog
├── plugins/develop/                  # the plugin
│   ├── .claude-plugin/plugin.json
│   ├── skills/init/SKILL.md          # the /develop:init bootstrapper
│   ├── agents/                       # portable, stack-agnostic agents (WIP)
│   └── hooks/                        # safe, stack-agnostic hooks (WIP)
└── docs/                             # the explainer site (GitHub Pages)
```

## License

MIT © Chris Jenkins. See [LICENSE](LICENSE).

Pattern lineage cross-references [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents).
