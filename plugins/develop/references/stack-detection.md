# Stack detection — evidence, not assumption

`/develop:init` Phase 1. The goal is a **stack summary the user confirms**, where every
claim is backed by a real file in *this* repo. Never assume an ecosystem from the repo
name, the language of a few files, or what you saw in another project.

> **Rule:** every line of the stack summary cites the file (and line/key) it came from.
> If you can't cite it, you didn't detect it — say "unknown" and ask.

## What to identify

Four facets, each with its own evidence:

1. **Build tool / package manager** — how the project is built and deps resolved.
2. **Test runner** — how tests are run.
3. **Linter / formatter / type-checker** — what defines "clean".
4. **CI** — what the project runs on every change. **CI is the source of truth** for what
   "green" means here; prefer it over inferring commands.

## Detection table (first-class ecosystems)

Match on the **marker files** (presence is the evidence). A repo may match several
(polyglot/monorepo) — record all, don't force a single winner.

| Ecosystem | Marker files | Build / package | Test runner (typical) | Lint / format / types | 
|---|---|---|---|---|
| Node / JS / TS | `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb` | npm / pnpm / yarn / bun (from lockfile) | from `scripts.test` (jest, vitest, mocha, node --test) | eslint, prettier, biome; `tsc` for types |
| Python | `pyproject.toml`, `setup.py`, `setup.cfg`, `requirements*.txt`, `tox.ini`, `Pipfile`, `poetry.lock`, `uv.lock` | pip / poetry / uv / hatch / pdm (from lock + `[build-system]`) | pytest, unittest, tox, nox | ruff, flake8, black, isort; mypy / pyright for types |
| Go | `go.mod`, `go.sum` | `go build ./...` | `go test ./...` | `gofmt`, `go vet`, golangci-lint |
| Rust | `Cargo.toml`, `Cargo.lock` | `cargo build` | `cargo test` | `cargo fmt --check`, `cargo clippy` |
| JVM / Gradle | `build.gradle`, `build.gradle.kts`, `settings.gradle(.kts)`, `gradlew` | `./gradlew` | `./gradlew test` (+ JUnit/Kotest) | detekt, ktlint, spotless, checkstyle |
| JVM / Maven | `pom.xml`, `mvnw` | `./mvnw` / `mvn` | `mvn test` (surefire) | spotless, checkstyle, spotbugs |
| Ruby | `Gemfile`, `Gemfile.lock`, `Rakefile`, `.ruby-version` | bundler | `rake test`, rspec, minitest | rubocop, standardrb |
| PHP | `composer.json`, `composer.lock` | composer | phpunit, pest | phpcs, php-cs-fixer, phpstan, psalm |
| .NET | `*.csproj`, `*.sln`, `global.json` | `dotnet build` | `dotnet test` | `dotnet format`, analyzers |
| Elixir | `mix.exs`, `mix.lock` | mix | `mix test` | `mix format`, credo, dialyzer |
| Swift | `Package.swift`, `*.xcodeproj`, `*.xcworkspace` | swiftpm / xcodebuild | `swift test`, xcodebuild test | swiftlint, swiftformat |
| C/C++ | `CMakeLists.txt`, `Makefile`, `meson.build`, `conanfile.txt` | cmake / make / meson | ctest, gtest | clang-format, clang-tidy, cppcheck |
| Dart / Flutter | `pubspec.yaml`, `pubspec.lock` | `dart`/`flutter` | `dart test`, `flutter test` | `dart analyze`, `dart format` |
| Make (cross-cutting) | `Makefile`, `justfile`, `Taskfile.yml` | `make` / `just` / `task` targets | a `test` target | a `lint`/`check`/`fmt` target |

> **Monorepos / polyglot:** detect per workspace. Look for workspace markers
> (`pnpm-workspace.yaml`, `package.json#workspaces`, Cargo workspace `[workspace]`,
> Gradle `settings.gradle` includes, Nx/Turbo/Lerna config, Bazel `WORKSPACE`/`MODULE.bazel`).
> Record each workspace's stack separately; gates may differ per package.

## How to read each facet

- **Build/package manager:** identify by lockfile first (it's unambiguous), then by config
  file. For Node, the lockfile picks the package manager (npm vs pnpm vs yarn vs bun).
- **Test runner:** read the *declared* commands, don't guess. Node → `scripts.test`;
  Python → `[tool.pytest]` / `tox.ini` / CI; Gradle/Maven → the `test` task; Make → the
  `test` target. If multiple test commands exist (unit vs integration vs e2e), list them.
- **Lint / format / type-check:** look for config files (`.eslintrc*`, `ruff.toml`,
  `detekt.yml`, `.rubocop.yml`, `clippy.toml`, `tsconfig.json`, `mypy.ini`…) AND for the
  command that runs them (a script/task/CI step). A config file with no runner is a weaker
  signal — note it as "configured but no runner found".
- **CI (do this thoroughly):** read every workflow file and extract the actual command
  lines. This is where the real, canonical gate commands live — exact flags, env, matrix.
  - GitHub Actions: `.github/workflows/*.yml|*.yaml`
  - GitLab: `.gitlab-ci.yml`
  - CircleCI: `.circleci/config.yml`
  - Azure Pipelines: `azure-pipelines.yml`
  - Jenkins: `Jenkinsfile`
  - Travis: `.travis.yml`
  - Buildkite: `.buildkite/pipeline.yml`
  - Pre-commit: `.pre-commit-config.yaml` (lint/format hooks)

## Output — the stack summary (Phase 1 deliverable)

Emit a compact, citeable summary and **ask the user to confirm or correct it before
Phase 2**. Shape:

```
Stack summary (please confirm or correct):

Ecosystem(s):   <e.g. Node + TypeScript>        ← package.json, tsconfig.json
Build / deps:   <e.g. pnpm>                      ← pnpm-lock.yaml
Test runner:    <e.g. vitest>                    ← package.json "scripts.test": "vitest run"
Lint / format:  <e.g. eslint + prettier>         ← .eslintrc.cjs, .prettierrc
Type-check:     <e.g. tsc --noEmit>              ← tsconfig.json
CI:             <e.g. GitHub Actions>            ← .github/workflows/ci.yml
Monorepo:       <yes: packages/* via pnpm | no>
Confidence:     <high | medium | low — and why>

Anything I have wrong or missed? (especially: the real commands CI runs)
```

- If a facet can't be cited, print it as `unknown — please tell me` rather than guessing.
- For unknown/unsupported ecosystems, see [stacks.md](./stacks.md): degrade gracefully —
  detect what you can, **log what was skipped**, and proceed with whatever gates the user
  confirms. Never block on an ecosystem you don't recognise.

The confirmed facts here feed Phase 2 ([gate discovery](./gate-tokens.md)), which turns the
CI command lines into the repo's gate tokens.
