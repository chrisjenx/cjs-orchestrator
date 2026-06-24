# `/develop` init + run discovery fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five real defects a real `/develop:init` + dry run on a Kotlin Multiplatform monorepo surfaced (tickets #31–#34 plus the `featureDir`/`clean` hazard), and harden the contract so they cannot silently recur.

**Architecture:** These are edits to the `develop` plugin's shipped *prose contract* (skill instructions, reference docs, one agent prompt) plus two mechanical guards added to `scripts/validate-manifests.py` (the CI-mirrored validator). The plugin ships static skills; behaviour is fitted by the definitions init writes, so most fixes live in the references/skills, not in code. We deliberately do **not** shard init discovery into per-module sub-agents (only ~1 of 6 issues is discovery-breadth-bound, and it was depth within one CI job, not cross-module breadth); any `ci-gates` discovery scout is deferred to the flywheel's own earn-it rule until a genuinely large monorepo's init actually saturates and misses gates.

**Tech Stack:** Markdown reference docs + skill `SKILL.md` files + JSON manifests/templates under `plugins/develop/`; Python 3 validator (`scripts/validate-manifests.py`, stdlib + PyYAML) with a `--selftest`; the authoritative checker is the `claude plugin validate` CLI.

**Conventions for every edit in this plan:**
- Token frugality is the plugin's first principle: when strengthening a line, *replace* the soft version rather than adding alongside it; say it once, short.
- Shipped reference/skill prose is LLM-read payload; the existing em-dash style there is fine to match. (The repo-root README/CHANGELOG/`docs/` site are the human-reading surfaces that must stay em-dash-free; none of those are touched here except CHANGELOG in Task 6, which is ASCII.)
- After any prose edit, the authoritative check is `claude plugin validate plugins/develop` (and `.claude-plugin/marketplace.json`); the CI mirror is `python3 scripts/validate-manifests.py` + `python3 scripts/check-install.py` (cross-links).
- Do not rename any locked name (skills, agents, config keys, gate kinds, token forms).

---

## File structure (what each task touches)

| File | Responsibility | Task |
|---|---|---|
| `plugins/develop/references/config-schema.md` | `develop.config.json` shape + field rules (incl. `featureDir` default, gate model) | 1, 5 |
| `plugins/develop/templates/develop.config.json` | the starter config init writes | 1 |
| `scripts/validate-manifests.py` | CI-mirrored validator + selftest (new `featureDir` + token-grammar guards) | 1, 5 |
| `plugins/develop/hooks/README.md` | how init installs the safe hooks (Phase 4) | 2 |
| `plugins/develop/skills/init/SKILL.md` | init phase walk (Phase 4 hook step) | 2 |
| `plugins/develop/skills/run/SKILL.md` | run loop (step 2 Worktree; Read-first config) | 3 |
| `plugins/develop/references/stack-detection.md` | Phase 1 CI reading (exhaustiveness contract) | 4 |
| `plugins/develop/references/gate-tokens.md` | gate discovery + token grammar | 4, 5 |
| `plugins/develop/references/dry-run.md` | Phase 5 dry run (completeness re-check) | 4 |
| `plugins/develop/agents/planner.md` | planner output (emit canonical token grammar) | 5 |
| `CHANGELOG.md` | release notes | 6 |
| `plugins/develop/.claude-plugin/plugin.json` | version bump | 6 |

Each task is independent and leaves the plugin valid (`claude plugin validate` green) on its own. Recommended order: 1 → 2 → 3 → 4 → 5 → 6.

---

## Task 1: `featureDir` default must not sit where `clean` wipes it (#2 / MY-#2)

**Why:** init defaulted `featureDir` to `build/develop`; `**/build/` is gitignored *and* a build tool's `clean` task (e.g. `gradle clean`) wipes `build/`, destroying the in-flight plan/resume state mid-run. The worktree-guard blocks `git clean` but not `gradle clean`. Fix the documented default and add a mechanical guard so the shipped template can never regress to a build-output dir.

**Files:**
- Modify: `plugins/develop/references/config-schema.md` (example line 12; field row line 47)
- Modify: `plugins/develop/templates/develop.config.json` (line 3)
- Modify: `scripts/validate-manifests.py` (add guard + selftest)

- [ ] **Step 1: Add the failing guard + selftest to `validate-manifests.py` first**

In `scripts/validate-manifests.py`, add this pure predicate and check function (place near the other `check_*` functions):

```python
BUILD_OUTPUT_SEGMENTS = ("build", "target", "out", "dist", "bin")


def feature_dir_unsafe(fd):
    """Return a reason string if featureDir sits under a build-output dir a 'clean' wipes, else None."""
    parts = [s for s in str(fd).split("/") if s]
    if parts and parts[0] in BUILD_OUTPUT_SEGMENTS:
        return f"featureDir {fd!r} sits under build-output dir {parts[0]!r}/ which a 'clean' task wipes mid-run"
    return None


def check_template_feature_dir(problems):
    tmpl = ROOT + "/plugins/develop/templates/develop.config.json"
    try:
        fd = json.load(open(tmpl, encoding="utf-8")).get("featureDir", "")
    except Exception as e:  # noqa: BLE001
        problems.append(f"templates/develop.config.json: {e}")
        return
    reason = feature_dir_unsafe(fd)
    if reason:
        problems.append("templates/develop.config.json: " + reason + " — use a stack-neutral hidden path like '.develop'")
```

Call it from `main()` right after `check_plugin_fields(pl, problems)`:

```python
    # 5) Template featureDir must not be wiped by a build 'clean'.
    check_template_feature_dir(problems)
```

Add to `selftest()` (before the final `if fails:` block):

```python
    # featureDir safety
    expect(feature_dir_unsafe("build/develop"), "build/develop should be flagged")
    expect(feature_dir_unsafe("target/x"), "target/ should be flagged")
    expect(not feature_dir_unsafe(".develop"), ".develop should pass")
    expect(not feature_dir_unsafe(".claude/develop"), ".claude/develop should pass")
```

- [ ] **Step 2: Run the guard and watch it FAIL against the current template**

Run: `python3 scripts/validate-manifests.py`
Expected: FAIL with `templates/develop.config.json: featureDir 'build/develop' sits under build-output dir 'build'/ ...` (the template still says `build/develop`).

Also run: `python3 scripts/validate-manifests.py --selftest`
Expected: PASS (the predicate selftest asserts the right behaviour).

- [ ] **Step 3: Fix the template default**

In `plugins/develop/templates/develop.config.json`, change line 3:

```
  "featureDir": "build/develop",
```
to:
```
  "featureDir": ".develop",
```

- [ ] **Step 4: Fix the documented default + rule in `config-schema.md`**

In `plugins/develop/references/config-schema.md`, change the example (line 12):

```
  "featureDir": "build/develop",
```
to:
```
  "featureDir": ".develop",
```

Then change the `featureDir` field row (line 47):

```
| `featureDir` | init | Where per-feature plan files live (`<featureDir>/<feature>.plan.md`). Default `build/develop`; must be git-ignored or a build dir. |
```
to:
```
| `featureDir` | init | Where per-feature plan files live (`<featureDir>/<feature>.plan.md`). Default `.develop` (init adds it to `.gitignore` if absent). Must be git-ignored (so plan artifacts never land in the feature commit) and must **not** sit under a build-output dir (`build/`, `target/`, `out/`, `dist/`, `bin/`) a `clean` task wipes mid-run. |
```

- [ ] **Step 5: Have init ensure `.develop/` is git-ignored**

In `plugins/develop/skills/init/SKILL.md`, Phase 3 (the "Write the per-repo definitions" list), append one bullet after the `develop-flywheel` bullet (currently lines 92-95):

```
- ensure `<featureDir>` (default `.develop/`) is in `.gitignore` — append the line if missing
  (merge, never rewrite the file), so per-feature plan artifacts stay out of commits and out of
  any build-output dir a `clean` would wipe.
```

- [ ] **Step 6: Verify**

Run:
```
python3 scripts/validate-manifests.py
python3 scripts/validate-manifests.py --selftest
python3 scripts/check-install.py
claude plugin validate plugins/develop
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/validate-manifests.py plugins/develop/templates/develop.config.json plugins/develop/references/config-schema.md plugins/develop/skills/init/SKILL.md
git commit -m "fix(init): default featureDir to .develop (outside build/), guard it in CI (#2)

A build-output featureDir (build/develop) is wiped by 'gradle clean' mid-run,
destroying plan/resume state. Default to a hidden gitignored .develop/, have init
add it to .gitignore, and add a validate-manifests guard + selftest so the template
can never regress to a clean-wiped path.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Phase 4 hook install needs a fallback when the host denies the `settings.json` edit (#32)

**Why:** In auto/background mode the host self-modification guard *denies* editing `.claude/settings.json` when it carries a permissions/hooks block. init copied `worktree-guard.sh` but the merge was rejected, leaving the guard inert with no fallback (and no `BASH_*_TIMEOUT_MS` env). The fix: detect the denial, emit the exact snippet for the user to paste, and report it as a clean manual step instead of an opaque failure.

**Files:**
- Modify: `plugins/develop/hooks/README.md` (after the install section, lines 29-35)
- Modify: `plugins/develop/skills/init/SKILL.md` (Phase 4, lines 100-104)

- [ ] **Step 1: Read the exact blocks the fallback must emit**

Run: `cat plugins/develop/hooks/hooks.json`
Note the `env` block and the `PreToolUse(Bash)` entry it defines — those are what the fallback tells the user to paste.

- [ ] **Step 2: Add the fallback section to `hooks/README.md`**

In `plugins/develop/hooks/README.md`, after the "How init installs them" list (which currently ends at line 35 with the `idempotency.md` link), add:

```markdown

## When the host blocks the `settings.json` edit

Some hosts (Claude Code auto/background mode) run a self-modification guard that **denies**
editing `.claude/settings.json` when it contains a `permissions`/`hooks` block. The hook
*script* still installs into `.claude/hooks/`, but the merge is rejected, so the guard would be
left **inert**. Never accept that silently. On a denied write, init must:

1. Confirm the script is in place: `.claude/hooks/worktree-guard.sh` (and `chmod +x`).
2. **Emit the exact merge for the user to paste** into `.claude/settings.json` — the `env` block
   and the `PreToolUse(Bash)` entry from this directory's `hooks.json`, verbatim, with a one-line
   note to append (not replace) any existing `PreToolUse(Bash)` list.
3. Report it in the Phase 5 summary as a **required manual step** (`hook: installed; settings
   merge needs manual paste — denied by host`), so the user knows the guard is not yet active.

A copied-but-unwired guard is worse than none; treat the denial as a reported manual step, never
a clean pass.
```

- [ ] **Step 3: Wire the fallback into init Phase 4**

In `plugins/develop/skills/init/SKILL.md`, Phase 4 (lines 100-104), replace:

```
## Phase 4 — Install safe hooks only

Only stack-agnostic safety: worktree/uncommitted-work protection and generic command
timeouts. **Never** install a hook tied to a stack you didn't confirm. Follow
[hooks/README.md](../../hooks/README.md).
```
with:
```
## Phase 4 — Install safe hooks only

Only stack-agnostic safety: worktree/uncommitted-work protection and generic command
timeouts. **Never** install a hook tied to a stack you didn't confirm. Follow
[hooks/README.md](../../hooks/README.md). If the host **denies** the `settings.json` merge
(self-modification guard), don't fail silently: emit the exact snippet for the user to paste and
report it as a required manual step, per that README's fallback section.
```

- [ ] **Step 4: Verify**

Run:
```
python3 scripts/check-install.py
claude plugin validate plugins/develop
```
Expected: both PASS (cross-links resolve; manifest + agents valid). `check-install.py` reports the plugin doc cross-links resolve.

- [ ] **Step 5: Commit**

```bash
git add plugins/develop/hooks/README.md plugins/develop/skills/init/SKILL.md
git commit -m "fix(init): Phase 4 hook fallback when host denies settings.json edit (#32)

Auto/background mode denies editing a settings.json with a hooks/permissions block, so
the worktree-guard was copied but never wired in. Document + wire a fallback: emit the
exact env + PreToolUse snippet for manual paste and report it as a required manual step,
never a silent inert hook.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `/develop:run` worktree step must reuse an already-isolated worktree, not nest (#33)

**Why:** When `/develop:run` runs from a session already isolated to a worktree (host `EnterWorktree` / background job), step 2's `git worktree add .claude/worktrees/<feature>` resolves the **relative** path against cwd and nests under the current worktree; the host then blocks edits in the new sibling worktree; and a worktree branched off `main` lacks the uncommitted branch-local `develop.config.json`. Fix: resolve against the main repo root, detect an already-isolated session and reuse it, and read config from the main checkout.

**Files:**
- Modify: `plugins/develop/skills/run/SKILL.md` (step 2, lines 51-60; Read-first config bullet, lines 14-16)

- [ ] **Step 1: Replace step 2 (Worktree) prose**

In `plugins/develop/skills/run/SKILL.md`, replace the entire `### 2. Worktree (isolation)` block (lines 51-60):

```
### 2. Worktree (isolation)
Work in an isolated git worktree so a run can't corrupt the user's workspace:
```
git worktree add .claude/worktrees/<feature> -b develop/<feature>
```
Capture its **absolute** path as `worktreeRoot`. **Hard-stop** if the resolved cwd is on
`main`/`master` or outside the worktree. If `origin/main` has advanced past the branch base,
rebase onto it first (a stale base poisons every diff). To resume an interrupted run, reuse
the existing worktree instead of creating one.
_say:_ `▸ worktree · develop/<feature>`
```
with:
```
### 2. Worktree (isolation)
Work in an isolated git worktree so a run can't corrupt the user's workspace.

**First, detect an already-isolated session.** If cwd is already inside a worktree under
`.claude/worktrees/` (host `EnterWorktree` / a background job pins cwd there), **reuse it** as
`worktreeRoot` — do not create a nested worktree. Otherwise create one, resolving the path
against the **main repo root** (never cwd, which would nest):
```
root=$(git rev-parse --path-format=absolute --git-common-dir)/..   # main checkout, not this worktree
git -C "$root" worktree add "$root/.claude/worktrees/<feature>" -b develop/<feature>
```
Capture the worktree's **absolute** path as `worktreeRoot`. **Hard-stop** if the resolved cwd is
on `main`/`master` (and not in a worktree). If `origin/main` has advanced past the branch base,
rebase onto it first (a stale base poisons every diff). To resume an interrupted run, reuse the
existing worktree instead of creating one.
_say:_ `▸ worktree · develop/<feature>`
```

- [ ] **Step 2: Make Read-first tolerate branch-local config**

In `plugins/develop/skills/run/SKILL.md`, replace the first Read-first bullet (lines 14-16):

```
- `.claude/develop.config.json` — the repo's gates, stack, model tiers, caps
  ([config-schema.md](../../references/config-schema.md)). **If it's missing, stop and tell
  the user to run `/develop:init` first.**
```
with:
```
- `.claude/develop.config.json` — the repo's gates, stack, model tiers, caps
  ([config-schema.md](../../references/config-schema.md)). Read it from the **main checkout**
  (the `--git-common-dir` parent), since it may be uncommitted and so absent on a fresh worktree
  branch. **If it's genuinely missing there, stop and tell the user to run `/develop:init` first.**
```

- [ ] **Step 3: Verify**

Run:
```
python3 scripts/check-install.py
claude plugin validate plugins/develop
```
Expected: both PASS.

- [ ] **Step 4: Commit**

```bash
git add plugins/develop/skills/run/SKILL.md
git commit -m "fix(run): reuse an already-isolated worktree instead of nesting (#33)

When cwd is already a worktree (host EnterWorktree / background job), the relative
'git worktree add' nested and the host blocked edits in the sibling. Detect the
isolated session and reuse it; otherwise resolve the new worktree against the main
repo root via --git-common-dir; read config from the main checkout (may be uncommitted).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: CI-exhaustiveness contract + dry-run completeness re-check (#3 / MY-#3)

**Why:** init read the CI file but anchored only the easy path-guard and missed the breaking-class wire/format-compat guard in the *same* CI job. The fix is depth/exhaustiveness, not fan-out: make "read CI thoroughly" an enforced per-job/per-step contract that explicitly counts guard-style jobs (conditional `exit 1` steps) as gating, echoes the enumerated list back at the Phase-2 confirm seam, and re-checks completeness in the dry run. Heed two cautions: phrase it **semantically** (what *gates a merge* — #3 was a recognition miss, not a "missed a line" miss), and **do not** enumerate setup/checkout/cache steps as gates (that would regress the "no hallucinated gates" positive).

**Files:**
- Modify: `plugins/develop/references/stack-detection.md` (CI bullet, lines 58-67)
- Modify: `plugins/develop/references/gate-tokens.md` (discovery step 1, lines 12-14)
- Modify: `plugins/develop/references/dry-run.md` (positive run, section A)

- [ ] **Step 1: Strengthen the CI-reading contract in `stack-detection.md`**

In `plugins/develop/references/stack-detection.md`, replace the `**CI (do this thoroughly):**` bullet and its provider sub-list (lines 58-67):

```
- **CI (do this thoroughly):** read every workflow file and extract the actual command
  lines — the canonical gate commands, with exact flags, env, matrix.
  - GitHub Actions: `.github/workflows/*.yml|*.yaml`
  - GitLab: `.gitlab-ci.yml`
  - CircleCI: `.circleci/config.yml`
  - Azure Pipelines: `azure-pipelines.yml`
  - Jenkins: `Jenkinsfile`
  - Travis: `.travis.yml`
  - Buildkite: `.buildkite/pipeline.yml`
  - Pre-commit: `.pre-commit-config.yaml` (lint/format hooks)
```
with:
```
- **CI (enumerate exhaustively, per job, per step):** for **every** CI file, **every** job, list
  **every step that can fail a merge** with its exact command and `file:line`. A step is gating
  if it can `exit 1` and block: build/test/lint/format/type/coverage steps **and** guard-style
  steps (a conditional check that rejects a PR, e.g. "fail if file X changed", a wire/format-compat
  check, a required-label gate). Flag breaking-class guards explicitly — the flywheel promotes
  them at x1. A job is not done until every step is either captured as a gate or **explicitly
  marked non-gating with a reason**. Do **not** count setup/checkout/cache/upload steps as gates
  (no over-discovery — a hallucinated gate erodes trust as much as a missed one).
  - GitHub Actions: `.github/workflows/*.yml|*.yaml`
  - GitLab: `.gitlab-ci.yml`
  - CircleCI: `.circleci/config.yml`
  - Azure Pipelines: `azure-pipelines.yml`
  - Jenkins: `Jenkinsfile`
  - Travis: `.travis.yml`
  - Buildkite: `.buildkite/pipeline.yml`
  - Pre-commit: `.pre-commit-config.yaml` (lint/format hooks)
```

- [ ] **Step 2: Add the echo-back to the Phase-2 confirm seam in `gate-tokens.md`**

In `plugins/develop/references/gate-tokens.md`, replace discovery step 1 (lines 12-14):

```
1. **Read CI first.** The CI workflow(s) found in Phase 1 are canonical. Extract each
   command line that gates a merge: build, test, lint, format-check, type-check, coverage.
   Mirror the **exact** invocation (flags, env, working dir, matrix).
```
with:
```
1. **Read CI first, exhaustively.** The CI workflow(s) found in Phase 1 are canonical. For every
   job, enumerate **every gating step** (per [stack-detection.md](./stack-detection.md)) —
   build/test/lint/format/type/coverage **and** guard-style `exit 1` checks (file-change guards,
   wire/format-compat, required-label gates). Mirror the **exact** invocation (flags, env, working
   dir, matrix). At the confirm seam (step 4) **echo the full enumerated list back** — one line per
   gating step with its `file:line` — and ask the user to confirm none was missed; a guard left
   un-enumerated is the failure this prevents.
```

- [ ] **Step 3: Add the completeness re-check to the dry run in `dry-run.md`**

In `plugins/develop/references/dry-run.md`, in section `### A. Positive run — gates execute`, append a final bullet after the existing "Expect terminal status `ready`." line (line 24):

```
- **Completeness re-check.** Re-scan the CI files for command-shaped and `exit 1`/guard-style
  gating steps; flag any that map to **no** confirmed gate and carry **no** explicit non-gating
  note. A gating-looking step that is neither a configured gate nor an annotated exception is a
  silent under-discovery — surface it as a dry-run finding, don't let it pass.
```

- [ ] **Step 4: Verify**

Run:
```
python3 scripts/check-install.py
claude plugin validate plugins/develop
```
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/develop/references/stack-detection.md plugins/develop/references/gate-tokens.md plugins/develop/references/dry-run.md
git commit -m "fix(init): enforce CI-exhaustiveness discovery + dry-run completeness re-check (#3)

init anchored the easy CI guard but missed the breaking-class wire-compat guard in the
same job. Make 'read CI thoroughly' a per-job/per-step contract that counts guard-style
exit-1 checks as gating, echo the enumerated list back at the confirm seam, and re-check
completeness in the dry run. Phrased semantically (what gates a merge) and bounded against
over-discovery (no setup/cache steps as gates).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Gate model allows N gates per kind + addressable token grammar; planner emits canonical tokens (#31 + #34)

**Why:** Two coupled spec/schema defects. (#31) `config-schema.md` modeled one gate per kind with one `scopedCommand` template, so a compiled stack needing **cheap per-module compile + heavy full build** (two `build`-kind gates) made the bare `{build}` token ambiguous, and the `:{pkg}:<task>` template is invalid on multi-target stacks (KMP) where no uniform per-module task exists. (#34) the planner emitted `build:compile`/`test:server` (a `kind:id` form) that `gate-tokens.md`'s grammar (`{build}`, `{test:<selector>}`) doesn't define, risking a false "planner error". Fix: sanction multiple gates per kind, add an addressable `{kind:id}` token form for the non-selector kinds, make `scopedCommand` explicitly optional with a multi-target fallback, and make the planner emit the canonical grammar.

**This change is additive and backwards-compatible** (old single-gate-per-kind configs and bare `{kind}` tokens still work), so **`schema` stays `1`** — no migration. (If the reviewer decides it warrants signalling, bump per RELEASING.md; default here is no bump.)

**Files:**
- Modify: `plugins/develop/references/config-schema.md` (example gates; field rows 50, 53; Rules)
- Modify: `plugins/develop/references/gate-tokens.md` (build-umbrella note 22-26; grammar 68-74; planner-error rule 87-90)
- Modify: `plugins/develop/agents/planner.md` (output grammar)
- Modify: `scripts/validate-manifests.py` (token-grammar guard + selftest)

- [ ] **Step 1: Add the token-grammar guard + selftest to `validate-manifests.py` first**

In `scripts/validate-manifests.py`, add (near the other checks; add `import re` at the top if not present):

```python
TOKEN_KIND_HEADS = ("build", "test", "lint", "format", "types", "coverage", "cov", "grep")


def valid_gate_token(tok):
    """tok includes braces. Canonical grammar (gate-tokens.md)."""
    if re.fullmatch(r"\{(build|lint|types|format)(:[A-Za-z0-9_.\-]+)?\}", tok):
        return True   # bare kind, or {kind:id} to disambiguate multiple same-kind gates
    if re.fullmatch(r"\{test:[^}]+\}", tok):
        return True   # test always carries a selector
    if re.fullmatch(r"\{cov(>=|<=|=)\d+\}", tok):
        return True
    if re.fullmatch(r"\{grep:[^}]+\}", tok):
        return True
    return False


def _looks_like_gate_token(tok):
    head = re.split(r"[:<>=}]", tok[1:], 1)[0]
    return head in TOKEN_KIND_HEADS


def check_gate_token_grammar(problems):
    # Validate every gate-token-shaped {...} in the docs that carry token examples.
    # scopedCommand placeholders ({files},{pkg},{selector}) are skipped: their head is not a kind.
    for rel in ("plugins/develop/references/gate-tokens.md",
                "plugins/develop/references/plan-anatomy.md"):
        path = ROOT + "/" + rel
        try:
            text = open(path, encoding="utf-8").read()
        except Exception as e:  # noqa: BLE001
            problems.append(f"{rel}: {e}")
            continue
        for tok in re.findall(r"\{[^}\s]+\}", text):
            if _looks_like_gate_token(tok) and not valid_gate_token(tok):
                problems.append(f"{rel}: malformed gate token {tok!r} (see gate-tokens.md grammar)")
```

Call it from `main()` after `check_template_feature_dir(problems)`:

```python
    # 6) Gate-token examples in the docs match the canonical grammar.
    check_gate_token_grammar(problems)
```

Add to `selftest()`:

```python
    # gate-token grammar
    for good in ("{build}", "{build:compile}", "{lint}", "{types}", "{format}", "{test:server}", "{cov>=80}", "{grep:no-todo}"):
        expect(valid_gate_token(good), f"{good} should be valid")
    for bad in ("{build:}", "{frobnicate}", "{cov>=}", "{test}", "{grep}"):
        expect(not valid_gate_token(bad), f"{bad} should be rejected")
    expect(_looks_like_gate_token("{build:compile}") and not _looks_like_gate_token("{pkg}"), "placeholder {pkg} must not look like a gate token")
```

- [ ] **Step 2: Run the guard + selftest (selftest must pass; doc scan passes today since `{build:compile}` isn't yet in the docs)**

Run: `python3 scripts/validate-manifests.py --selftest`
Expected: PASS.
Run: `python3 scripts/validate-manifests.py`
Expected: PASS (no malformed gate tokens currently in the docs). This guard now *protects* the grammar we are about to document.

- [ ] **Step 3: Sanction multiple gates per kind + addressable tokens in `gate-tokens.md`**

In `plugins/develop/references/gate-tokens.md`, replace the "Build gate = whole-project" paragraph (lines 22-26):

```
**Build gate = whole-project, not one module.** CI often shards compile per module/target for
speed, but one module's compile is too narrow a `build` gate. Use the umbrella the build tool
always provides (Gradle `build`/`assemble`, `cargo build`, `tsc -b`, `make`); scope only the
*cheap* run to changed modules. The gate must catch compile breakage anywhere the change touches.
```
with:
```
**Build gate = whole-project, not one module.** CI often shards compile per module/target for
speed, but one module's compile is too narrow a heavy `build` gate. Use the umbrella the build
tool always provides (Gradle `build`/`assemble`, `cargo build`, `tsc -b`, `make`) for the heavy
gate. A compiled stack usually wants **two** `build`-kind gates: a **cheap** per-module compile
(inline every phase) **and** the **heavy** umbrella build (PF). Define them as two gates with
distinct ids (e.g. `id:"compile"` cheap + `id:"build"` heavy, both `kind:"build"`); the `tier`
field governs inline-vs-PF. Address a specific one with `{build:compile}` (below).
```

Then replace the token grammar bullets (lines 68-74), which currently read:

```
- A bare kind (`{build}`, `{lint}`, `{types}`, `{format}`) → run that gate's command.
- `{test:<selector>}` → run only the named test(s); the selector is whatever the runner
  accepts (file path, test name, tag). Forces a **fresh** run (no cached results).
- `{cov>=N}` → diff coverage must be ≥ N% (a `coverage` gate must be configured).
- `{grep:<id>}` → a required/forbidden-pattern anchor: the `id` *names the pattern* (e.g.
  `no-todo`, `reuse:<ref>`, a wiring anchor), checked by grepping the diff and resolved by the
  executor/flywheel layer — **not** a `develop.config.json` gate ([flywheel.md](./flywheel.md)).
```
with:
```
- A bare kind (`{build}`, `{lint}`, `{types}`, `{format}`) → run that gate's command. Valid only
  when **exactly one** gate of that kind exists; if several do, it is ambiguous (a planner error).
- `{<kind>:<id>}` (e.g. `{build:compile}`) → address one specific gate by its `develop.config.json`
  `id`, for the non-selector kinds (`build`/`lint`/`types`/`format`). Use this to pick the cheap
  compile vs the heavy build when both exist.
- `{test:<selector>}` → run only the named test(s); the selector is whatever the runner
  accepts (file path, test name, tag). Forces a **fresh** run (no cached results).
- `{cov>=N}` → diff coverage must be ≥ N% (a `coverage` gate must be configured).
- `{grep:<id>}` → a required/forbidden-pattern anchor: the `id` *names the pattern* (e.g.
  `no-todo`, `reuse:<ref>`, a wiring anchor), checked by grepping the diff and resolved by the
  executor/flywheel layer — **not** a `develop.config.json` gate ([flywheel.md](./flywheel.md)).
```

Then update the planner-error execution rule (lines 87-90):

```
- **Unrecognised command-token = planner error.** If a node carries a command-gate token
  (`build`/`test`/`lint`/`format`/`types`/`cov`) with no matching gate in
  `develop.config.json`, that's a bug in the plan — write a finding, don't guess. `{grep:<id>}`
  anchors are exempt: they self-resolve from the id (no config gate needed).
```
with:
```
- **Unrecognised or ambiguous command-token = planner error.** If a node carries a command-gate
  token (`build`/`test`/`lint`/`format`/`types`/`cov`) with no matching gate in
  `develop.config.json`, or a **bare** kind token when several gates share that kind (use
  `{kind:id}` to disambiguate), that's a bug in the plan — write a finding, don't guess.
  `{grep:<id>}` anchors are exempt: they self-resolve from the id (no config gate needed).
```

- [ ] **Step 4: Update `config-schema.md` — example, field rows, rules**

In `plugins/develop/references/config-schema.md`, in the example `gates` array (lines 23-33), add a cheap `compile` build-kind gate so the multi-gate-per-kind shape is shown. Change:

```
  "gates": [
    { "id": "types",    "kind": "types",    "tier": "cheap", "command": "pnpm -w typecheck" },
```
to:
```
  "gates": [
    { "id": "types",    "kind": "types",    "tier": "cheap", "command": "pnpm -w typecheck" },
    { "id": "compile",  "kind": "build",    "tier": "cheap", "command": "pnpm -w build",
      "scopedCommand": "pnpm --filter {pkg} build" },
```

(Now `build` kind has two gates: cheap `compile` and the existing heavy `build` — addressed as `{build:compile}` and `{build:build}` or, since one is heavy/PF-only, `{build}` on a node is ambiguous and must use the id.)

Change the `gates[].kind` row (line 50):

```
| `gates[].kind` | init | `build` \| `test` \| `lint` \| `format` \| `types` \| `coverage` \| `grep`. |
```
to:
```
| `gates[].kind` | init | `build` \| `test` \| `lint` \| `format` \| `types` \| `coverage` \| `grep`. **Multiple gates may share a kind** (e.g. a cheap `compile` + a heavy `build`); address a specific one with `{kind:id}` ([gate-tokens.md](./gate-tokens.md)). |
```

Change the `gates[].scopedCommand` row (line 53):

```
| `gates[].scopedCommand` | init | Optional template for the cheap inline run; placeholders `{files}`, `{pkg}`, `{selector}`. |
```
to:
```
| `gates[].scopedCommand` | init | **Optional** template for the cheap inline run; placeholders `{files}`, `{pkg}`, `{selector}`. **Omit it when no uniform per-module command exists** (multi-target stacks like KMP have no single `:{pkg}:compile` task) — fall back to the whole-repo `command`, or use a universally-valid umbrella per module (e.g. `:{pkg}:assemble`). |
```

Update the Rules bullet about the contract (lines 65-68):

```
- The config is the contract between `/develop:init` (writer) and `/develop:run` (reader).
  A *command-gate* token (`build`/`test`/`lint`/`format`/`types`/`cov`) on a plan node with no
  matching `gates[].id`/`kind` is a planner error; `{grep:<id>}` anchors self-resolve
  ([gate-tokens.md](./gate-tokens.md)).
```
with:
```
- The config is the contract between `/develop:init` (writer) and `/develop:run` (reader).
  A *command-gate* token on a plan node with no matching `gates[].id`/`kind` — **or a bare
  `{kind}` when several gates share that kind** (disambiguate with `{kind:id}`) — is a planner
  error; `{grep:<id>}` anchors self-resolve ([gate-tokens.md](./gate-tokens.md)).
```

- [ ] **Step 5: Make the planner emit the canonical grammar (`planner.md`)**

In `plugins/develop/agents/planner.md`, in the "Fold in the plan-completeness contract" section, append a sentence after the existing line about placing gate tokens (currently ends line 32 "Place each gate token ... on the node whose work it proves."):

```
Emit tokens **exactly** as [gate-tokens.md](../references/gate-tokens.md) defines: bare `build`/
`lint`/`types`/`format`, `test:<selector>` for tests, `cov>=N` for coverage, and `kind:id` (e.g.
`build:compile`) **only** to disambiguate when several gates share a kind. Do not invent a
`kind:id` form for a kind that has a single gate, and do not use a bare kind when it is ambiguous.
```

- [ ] **Step 6: Verify (the doc scan now sees `{build:compile}` and must accept it)**

Run:
```
python3 scripts/validate-manifests.py --selftest
python3 scripts/validate-manifests.py
python3 scripts/check-install.py
claude plugin validate plugins/develop
```
Expected: all PASS. In particular `validate-manifests.py` must PASS now that `{build:compile}` appears in `gate-tokens.md` (the guard recognizes it as valid). If it fails on a token, the grammar regex and the doc disagree — fix whichever is wrong.

- [ ] **Step 7: Commit**

```bash
git add scripts/validate-manifests.py plugins/develop/references/gate-tokens.md plugins/develop/references/config-schema.md plugins/develop/agents/planner.md
git commit -m "feat(gates): allow N gates per kind + addressable {kind:id} tokens; align planner grammar (#31,#34)

Compiled stacks need a cheap per-module compile AND a heavy umbrella build (two build-kind
gates); sanction multiple gates per kind and add an addressable {kind:id} token to pick one,
make scopedCommand optional with a multi-target umbrella fallback, and make the planner emit
the canonical token grammar (no ad-hoc kind:id). Additive + backwards-compatible: schema stays
1. New validate-manifests guard lints gate-token examples against the grammar.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: CHANGELOG, version bump, release, tickets

**Why:** Ship the batch. These are fixes plus one backwards-compatible new capability (multiple gates per kind + addressable tokens), so per RELEASING.md this is a **minor** bump (0.4.1 → 0.5.0), no `schema` change.

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `plugins/develop/.claude-plugin/plugin.json`

- [ ] **Step 1: Bump the version**

In `plugins/develop/.claude-plugin/plugin.json`, change `"version": "0.4.1",` to `"version": "0.5.0",`.

- [ ] **Step 2: Write the CHANGELOG entry (ASCII, no em dashes — human-reading surface)**

In `CHANGELOG.md`, under `## [Unreleased]`, add a new dated section. Use this exact block (promote `[Unreleased]` into it and leave a fresh empty `[Unreleased]` above):

```markdown
## [0.5.0] - 2026-06-23

Fixes the gaps a real init + dry run on a multi-target (Kotlin Multiplatform) monorepo surfaced,
and hardens the gate contract so they cannot silently recur.

### Added
- **Multiple gates per kind + addressable tokens.** A compiled stack can define both a cheap
  per-module compile and a heavy umbrella build as two `build`-kind gates; a node addresses one
  with `{kind:id}` (e.g. `{build:compile}`). Backwards-compatible: bare `{kind}` still works when
  a kind has a single gate. `scopedCommand` is now explicitly optional with a multi-target
  umbrella fallback. (#31, #34)

### Fixed
- **init `featureDir` default** is now `.develop` (hidden, git-ignored by init) instead of
  `build/develop`, which a build `clean` wipes mid-run; a validate-manifests guard blocks any
  build-output featureDir. (#2)
- **Phase 4 hook install** degrades gracefully when the host denies the `settings.json` merge:
  it emits the exact snippet to paste and reports a required manual step instead of leaving the
  guard silently inert. (#32)
- **`/develop:run` worktree step** reuses an already-isolated worktree instead of nesting, resolves
  the new worktree against the main repo root, and reads config from the main checkout. (#33)
- **CI gate discovery** is now an enforced per-job/per-step exhaustiveness contract that counts
  guard-style `exit 1` checks as gating and echoes the list back at the confirm seam, with a
  dry-run completeness re-check. Prevents a guard being missed (a breaking-class wire-compat guard
  escaped the first run). (#3)
- **planner** emits the canonical gate-token grammar; a validate-manifests guard lints gate-token
  examples in the references. (#34)
```

Update the links at the bottom of `CHANGELOG.md`:
```
[Unreleased]: https://github.com/chrisjenx/cjs-orchestrator/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/chrisjenx/cjs-orchestrator/releases/tag/v0.5.0
```
(keep the existing `[0.4.1]`, `[0.4.0]`, ... lines below.)

- [ ] **Step 3: Full green check (the RELEASING.md list + authoritative validator)**

Run:
```
claude plugin validate .claude-plugin/marketplace.json
claude plugin validate plugins/develop
python3 scripts/validate-manifests.py --selftest
python3 scripts/validate-manifests.py
python3 scripts/check-install.py
python3 scripts/check-docs-subpath.py
python3 scripts/check-docs-leaks.py --selftest && python3 scripts/check-docs-leaks.py
python3 scripts/check-scaffold.py --selftest
python3 plugins/develop/scripts/flywheel-aggregate.py --selftest && python3 plugins/develop/scripts/flywheel-ingest.py --selftest
for f in docs/*.js; do node --check "$f"; done
grep -nE $'[—–]' CHANGELOG.md && echo "EM DASH IN CHANGELOG" || echo "changelog dash-clean"
```
Expected: all PASS, changelog dash-clean.

- [ ] **Step 4: Commit, push, tag, release**

```bash
git add CHANGELOG.md plugins/develop/.claude-plugin/plugin.json
git commit -m "release: v0.5.0

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push origin main
```
Then wait for CI green on the pushed SHA, tag and release:
```bash
git tag v0.5.0 && git push origin v0.5.0
# release notes = the [0.5.0] CHANGELOG section
gh release create v0.5.0 --title "v0.5.0" --notes-file <(...extract the [0.5.0] section...)
```

- [ ] **Step 5: Install e2e (RELEASING.md after-release; this release touches manifests/skills/agents)**

Add the local marketplace from the working tree, install, confirm 3 skills + 9 agents discovered, then uninstall + remove the local marketplace to leave global state clean (same sequence used for v0.4.1).

- [ ] **Step 6: Close the tickets (EXTERNAL WRITE — needs explicit user go-ahead this task)**

Closing/commenting GitHub issues is task-scoped authorization, not standing. After the release is live, **ask the user** before closing. Then close #31, #32, #33, #2-equivalent (no ticket — note in #31 or skip), #34, #3 (MY-#3 has no ticket) with a comment linking v0.5.0. Specifically: #31, #32, #33, #34 each map to a fix above.

---

## Self-review

**Spec coverage:** Every issue from the run maps to a task — #2 → Task 1; #32 → Task 2; #33 → Task 3; #3/MY-#3 → Task 4; #31 + #34 → Task 5; ship → Task 6. The deferred `ci-gates` scout is explicitly out of scope (stated in Architecture) with the reason.

**Placeholder scan:** Each edit gives the exact current text and exact replacement. The one intentional non-literal is Task 6 Step 4's `gh release create ... --notes-file <(...)>` (the release-notes extraction), which mirrors the v0.4.1 release procedure already in the session history; the implementer extracts the `[0.5.0]` CHANGELOG section as in prior releases.

**Type/name consistency:** `feature_dir_unsafe`, `valid_gate_token`, `_looks_like_gate_token`, `check_template_feature_dir`, `check_gate_token_grammar` are defined once (Tasks 1, 5) and called from `main()`/`selftest()` consistently. Token forms (`{build}`, `{build:compile}`, `{test:<selector>}`, `{cov>=N}`, `{grep:<id>}`) match between `gate-tokens.md` (Task 5 Step 3), `config-schema.md` (Step 4), `planner.md` (Step 5), and the validator regex (Step 1). `featureDir` default `.develop` matches across template, config-schema, and init Phase 3.

**Backwards-compat check:** Task 5 keeps `schema: 1` because bare `{kind}` and single-gate-per-kind configs remain valid; the new `{kind:id}` and multi-gate-per-kind are additive. Flagged as a decision the reviewer can override.
