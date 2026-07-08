# Multi-stack support matrix

"Supported" means something narrow here: the orchestrator, plan, executor, auditors, and
quality tail don't care about the language — they care about *gate commands*, which are
discovered. So "support" is really "how confidently can `/develop:bootstrap` auto-derive your
gates?" Everything downstream is the same across stacks.

## Support levels

- **First-class** — bootstrap recognises the marker files, knows where the gate commands usually
  live, and can propose build/test/lint/type/coverage gates with high confidence. You still
  confirm them.
- **Best-effort** — detected, gates proposed, but more likely to need correction (unusual
  toolchains, thin CI). Confirm carefully.
- **Unknown** — not recognised. The flow still works; bootstrap asks you for the gate commands
  directly and logs what it couldn't detect (see Degradation below).

## Matrix

| Ecosystem | Level | Auto-derived gates | Notes |
|---|---|---|---|
| Node / TS (npm·pnpm·yarn·bun) | first-class | build, test, lint, format, types, coverage | package manager from lockfile; gates from `scripts` + CI |
| Python (pip·poetry·uv·hatch·pdm) | first-class | test, lint, format, types, coverage | gates from `pyproject`/`tox`/CI; ruff/black/mypy common |
| Go | first-class | build, test, vet, coverage | `go build/test/vet ./...`; golangci-lint if present |
| Rust | first-class | build, test, fmt, clippy | cargo gates are uniform |
| JVM / Gradle | first-class | build, test, lint, coverage | tasks from `gradlew`; detekt/ktlint/spotless if configured |
| JVM / Maven | best-effort | build, test, lint | gates from `pom.xml` plugins + CI |
| Ruby | best-effort | test, lint | rspec/minitest + rubocop |
| PHP (composer) | best-effort | test, lint, types | phpunit/pest + phpcs/phpstan/psalm |
| .NET | best-effort | build, test, format | `dotnet build/test/format` |
| Elixir (mix) | best-effort | test, format, lint | `mix test/format`, credo |
| Swift / SPM | best-effort | build, test, lint | swiftpm or xcodebuild; swiftlint |
| C/C++ (cmake·make·meson) | best-effort | build, test | gate names vary; CI is the only reliable source |
| Dart / Flutter | best-effort | test, analyze, format | `dart`/`flutter` |
| Make / just / task | cross-cutting | whatever targets exist | a `test`/`lint`/`check`/`fmt` target maps directly to a gate |
| **anything else** | unknown | — | degrade gracefully |

> CI is always the most reliable source regardless of level. A "best-effort" repo with a
> clear CI workflow is effectively first-class; a "first-class" repo with no CI and no
> scripts may need you to supply commands. Detect from files; **confirm from CI**.

## Graceful degradation (unknown / partial stacks)

Never block on an ecosystem you don't recognise. Instead:

1. **Detect what you can.** Even an unknown stack usually has a CI file, a `Makefile`, or a
   README "how to test" — mine those for real commands.
2. **Ask for the rest.** For each gate facet you couldn't derive (build/test/lint/types/
   coverage), ask the user directly: "what command builds / tests / lints this repo?" A
   user-supplied command is a perfectly good gate.
3. **Log what was skipped.** Record every undetected facet in the stack summary and in
   `develop.config.json`'s `stack.evidence` (e.g. `"coverage": "skipped — no coverage tool
   detected"`). A skipped gate is *visible*, never silently dropped — the dry run
   ([dry-run.md](./dry-run.md)) and the user both see it.
4. **Proceed with what you have.** A flow with only a test gate and a lint gate still works;
   the quality tail runs whatever gates exist. Partial coverage of gates is fine; pretending
   to have gates you don't is not.

## Monorepos / polyglot

A repo can match several rows. Detect **per workspace** and record each workspace's gates
separately — gates may differ per package ([stack-detection.md](./stack-detection.md)). The
loop scopes cheap gates to the changed workspace and runs the union of heavy gates at PF.
