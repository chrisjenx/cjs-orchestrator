#!/usr/bin/env python3
"""Validate / compare a `.claude/` scaffold produced by `/develop:init`.

`/develop:init` is an LLM-driven skill, so its output is never bit-identical. But the
parts that matter are sourced deterministically (gates mirror CI, routing/hooks/flywheel
come from fixed templates), so they can be asserted. This is the structural validator for
that deterministic core. Prose (CLAUDE.md text, config `evidence`, `notes`) varies per run
and is NOT asserted.

Modes:

  check-scaffold.py <target_dir> <expected.json>
      Assert the scaffold init wrote under <target_dir> matches the contract: required
      files exist, develop.config.json is schema-shaped, the discovered gate set matches
      CI (from <expected.json>), routing carries the generalist fallback, the flywheel
      SSOT is an empty .jsonl, the safe hook is installed, and CLAUDE.md carries the
      discovered sections.  Exit 0 = OK, 1 = contract violation(s).

  check-scaffold.py --compare <dirA> <dirB>
      Extract the deterministic core (gate kinds+commands, stack, routing shape, file set,
      model/cap defaults) from two scaffolds and report whether they are identical. The
      run-to-run variance probe: a well-authored init yields an identical core across runs
      even though prose varies.  Exit 0 = cores identical, 1 = they diverge.

  check-scaffold.py --selftest
      Guard the guard: unit-checks the (deliberately lenient) matchers and runs validate()
      end-to-end over a temp scaffold. Deterministic, no LLM — safe to run in CI.

A red validate/compare result drives a fix in the init SKILL.md / references, never a
tweak here (evals/README Iron Law).
"""
import json, os, sys

REQUIRED = [
    ".claude/develop.config.json",
    ".claude/develop-routing.json",
    ".claude/develop-flywheel.md",
    ".claude/develop-flywheel.jsonl",
    ".claude/hooks/worktree-guard.sh",
    ".claude/settings.json",
]


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def norm(cmd):
    return " ".join((cmd or "").split()).strip().lower()


def claude_md(target):
    """CLAUDE.md lives at repo root by convention; tolerate .claude/CLAUDE.md."""
    for p in ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md")):
        full = os.path.join(target, p)
        if os.path.isfile(full):
            return full
    return None


# ---- matchers (lenient by design: init's labelling varies, the substance is stable) ----

def eco_missing(want_list, got_list):
    """Each expected ecosystem term must appear somewhere in the produced (free-form)
    label; returns the list of missing terms ([] == match). Substring, not set equality:
    ["kotlin-multiplatform"] is satisfied by ["jvm-gradle-kotlin-multiplatform"]."""
    joined = " ".join(got_list or []).lower()
    return [w for w in (want_list or []) if w.lower() not in joined]


def bt_match(want, got):
    """Exact, or expected is a boundary-terminated leading token of the produced label
    (a free-form 'zig (unrecognised ...)' passes on 'zig'), so 'npm' still != 'pnpm'
    and 'go' still != 'golang'."""
    g, w = (got or ""), (want or "")
    return g == w or (g.lower().startswith(w.lower())
                      and (len(g) == len(w) or not g[len(w)].isalnum()))


def gate_match(expected_gate, got_pairs):
    """A gate's expected `command` may list '|'-separated acceptable alternatives (e.g. a
    build umbrella that is either 'assemble' or 'gradlew build'); the produced gate of the
    same kind must contain at least one alternative as a substring."""
    kind = expected_gate.get("kind")
    alts = [norm(a) for a in (expected_gate.get("command") or "").split("|") if a.strip()]
    return any(k == kind and any(a in c for a in alts) for k, c in got_pairs)


def validate(target, expected_path):
    exp = jload(expected_path)
    checks = []  # (label, ok, detail)

    def chk(label, ok, detail=""):
        checks.append((label, bool(ok), detail))
        return ok

    # 1. required files
    for rel in REQUIRED:
        chk(f"file: {rel}", os.path.isfile(os.path.join(target, rel)))
    cmd_path = claude_md(target)
    chk("file: CLAUDE.md (root or .claude/)", cmd_path is not None)

    # 2. develop.config.json shape + stack + gates
    cfg_path = os.path.join(target, ".claude/develop.config.json")
    cfg = None
    if os.path.isfile(cfg_path):
        try:
            cfg = jload(cfg_path)
        except Exception as e:  # noqa: BLE001
            chk("config: valid JSON", False, str(e))
    if cfg is not None:
        chk("config: valid JSON", True)
        for key in ("schema", "featureDir", "stack", "gates", "models", "caps"):
            chk(f"config.{key} present", key in cfg)
        stack = cfg.get("stack", {})
        miss = eco_missing(exp.get("stack", {}).get("ecosystems", []), stack.get("ecosystems", []))
        chk("stack.ecosystems mention expected terms", not miss,
            f"missing {miss} in {stack.get('ecosystems', [])}")
        want_bt = exp.get("stack", {}).get("buildTool")
        chk("stack.buildTool matches expected (leading token)",
            bt_match(want_bt, stack.get("buildTool")),
            f"want {want_bt!r} got {stack.get('buildTool')!r}")

        got_gates = cfg.get("gates", []) or []
        got_pairs = [(g.get("kind"), norm(g.get("command"))) for g in got_gates]
        for g in got_gates:
            chk(f"gate '{g.get('kind')}' tier cheap|heavy",
                g.get("tier") in ("cheap", "heavy"), repr(g.get("tier")))
        for eg in exp.get("gates", []):
            hit = gate_match(eg, got_pairs)
            chk(f"gate {eg.get('kind')!r} mirrors CI {eg.get('command')!r}", hit,
                "" if hit else f"got {got_pairs}")

    # 3. routing: generalist fallback present
    rt_path = os.path.join(target, ".claude/develop-routing.json")
    if os.path.isfile(rt_path):
        try:
            rt = jload(rt_path)
            chk("routing: valid JSON", True)
            writers = rt.get("writers", [])
            has_exec = any(w.get("agent") == "executor" and "**/*" in (w.get("glob") or [])
                           for w in writers)
            chk("routing: generalist executor fallback (**/*)", has_exec)
            chk("routing: reviewers present", bool(rt.get("reviewers")))
        except Exception as e:  # noqa: BLE001
            chk("routing: valid JSON", False, str(e))

    # 4. flywheel SSOT is an empty jsonl
    jl = os.path.join(target, ".claude/develop-flywheel.jsonl")
    if os.path.isfile(jl):
        chk("flywheel.jsonl is empty (append-only seed)",
            os.path.getsize(jl) == 0 or not open(jl).read().strip())

    # 5. safe hook installed + settings has hooks/timeout
    guard = os.path.join(target, ".claude/hooks/worktree-guard.sh")
    if os.path.isfile(guard):
        chk("worktree-guard.sh executable", os.access(guard, os.X_OK))
    st = os.path.join(target, ".claude/settings.json")
    if os.path.isfile(st):
        try:
            s = jload(st)
            chk("settings.json valid JSON", True)
            chk("settings: hook or bash timeout wired",
                "hooks" in s or "TIMEOUT_MS" in json.dumps(s))
        except Exception as e:  # noqa: BLE001
            chk("settings.json valid JSON", False, str(e))

    # 6. CLAUDE.md carries discovered sections (presence, not prose)
    if cmd_path:
        body = open(cmd_path, encoding="utf-8").read()
        chk("CLAUDE.md has a Commands section", "## Commands" in body)
        chk("CLAUDE.md points at develop.config.json", "develop.config.json" in body)

    failed = [c for c in checks if not c[1]]
    print(f"\nscaffold validation: {target}")
    for label, ok, detail in checks:
        line = f"  [{'PASS' if ok else 'FAIL'}] {label}"
        if detail and not ok:
            line += f"  ({detail})"
        print(line)
    print(f"{'PASS' if not failed else 'FAIL'}: {len(checks) - len(failed)}/{len(checks)} checks")
    return 0 if not failed else 1


def core(target):
    cfg = jload(os.path.join(target, ".claude/develop.config.json"))
    rt = jload(os.path.join(target, ".claude/develop-routing.json"))
    files = sorted(r for r in REQUIRED if os.path.isfile(os.path.join(target, r)))
    if claude_md(target):
        files.append("CLAUDE.md")
    return {
        "files": sorted(files),
        "schema": cfg.get("schema"),
        "featureDir": cfg.get("featureDir"),
        "ecosystems": sorted(cfg.get("stack", {}).get("ecosystems", [])),
        "buildTool": cfg.get("stack", {}).get("buildTool"),
        "gates": sorted((g.get("kind"), norm(g.get("command"))) for g in cfg.get("gates", [])),
        "models": cfg.get("models"),
        "caps": cfg.get("caps"),
        "routing": rt,
    }


def compare(a, b):
    ca, cb = core(a), core(b)
    facets = sorted(set(ca) | set(cb))
    diverged = []
    print(f"\nvariance probe (deterministic core):\n  A = {a}\n  B = {b}")
    for f in facets:
        same = ca.get(f) == cb.get(f)
        print(f"  [{'same' if same else 'DIFF'}] {f}")
        if not same:
            diverged.append(f)
            print(f"      A: {json.dumps(ca.get(f))}")
            print(f"      B: {json.dumps(cb.get(f))}")
    print("IDENTICAL core" if not diverged else f"DIVERGED on: {', '.join(diverged)}")
    return 0 if not diverged else 1


def _write_scaffold(d, gates, eco="node", bt="npm"):
    """Write a minimal but complete, passing scaffold under d (for selftest)."""
    os.makedirs(os.path.join(d, ".claude/hooks"), exist_ok=True)
    cfg = {"schema": 1, "featureDir": "build/develop",
           "stack": {"ecosystems": [eco], "buildTool": bt, "monorepo": False},
           "gates": gates,
           "models": {"cheap": "default-cheap", "mid": "default-mid", "top": "default-top"},
           "caps": {"validator": 3, "audit": 2, "fork": 1, "gate": 2}}
    json.dump(cfg, open(os.path.join(d, ".claude/develop.config.json"), "w"))
    json.dump({"writers": [{"glob": ["**/*"], "agent": "executor"}],
               "reviewers": [{"glob": ["**/*"], "agent": "general-quality-reviewer"}],
               "audit": []}, open(os.path.join(d, ".claude/develop-routing.json"), "w"))
    open(os.path.join(d, ".claude/develop-flywheel.md"), "w").write("# flywheel\n")
    open(os.path.join(d, ".claude/develop-flywheel.jsonl"), "w").close()
    gp = os.path.join(d, ".claude/hooks/worktree-guard.sh")
    open(gp, "w").write("#!/bin/sh\n")
    os.chmod(gp, 0o755)
    json.dump({"hooks": {}}, open(os.path.join(d, ".claude/settings.json"), "w"))
    open(os.path.join(d, "CLAUDE.md"), "w").write("# x\n## Commands\nsee develop.config.json\n")


def selftest():
    """Guard the guard: the matchers must accept real label/command variation while still
    catching real regressions; validate() must pass a complete scaffold and fail a broken one."""
    import tempfile, shutil, contextlib, io
    ok = True

    def expect(cond, msg):
        nonlocal ok
        if not cond:
            print(f"  SELFTEST FAIL: {msg}")
            ok = False

    # ecosystem matcher
    expect(not eco_missing(["kotlin-multiplatform"], ["jvm-gradle-kotlin-multiplatform"]), "eco term in combined label")
    expect(not eco_missing(["kotlin-multiplatform"], ["jvm-gradle", "kotlin-multiplatform"]), "eco term across tags")
    expect(eco_missing(["node"], ["python"]), "eco mismatch must be reported")
    # buildTool matcher
    expect(bt_match("pnpm", "pnpm"), "bt exact")
    expect(bt_match("zig", "zig (unrecognised — not in support matrix)"), "bt free-form leading token")
    expect(not bt_match("npm", "pnpm"), "bt npm must NOT match pnpm")
    expect(not bt_match("pnpm", "npm"), "bt pnpm must NOT match npm")
    expect(not bt_match("go", "golang"), "bt go must NOT match golang")
    # gate matcher
    gp = [("build", "./gradlew assemble --stacktrace"), ("test", "./gradlew alltests test"),
          ("lint", "./gradlew detektall --continue")]
    expect(gate_match({"kind": "build", "command": "assemble|gradlew build"}, gp), "build umbrella alt matches assemble")
    expect(gate_match({"kind": "test", "command": "test"}, gp), "test substring matches")
    expect(gate_match({"kind": "lint", "command": "detekt"}, gp), "lint substring matches")
    expect(not gate_match({"kind": "build", "command": "assemble|gradlew build"},
                          [("build", "./gradlew :app:compiledebugkotlin")]),
           "single-module compile must NOT satisfy build umbrella")

    # validate() end-to-end over a temp scaffold
    gates = [{"id": "lint", "kind": "lint", "tier": "cheap", "command": "npm run lint"},
             {"id": "test", "kind": "test", "tier": "heavy", "command": "npm test"}]
    expd = {"stack": {"ecosystems": ["node"], "buildTool": "npm"},
            "gates": [{"kind": "lint", "command": "npm run lint"},
                      {"kind": "test", "command": "npm test"}]}
    d = tempfile.mkdtemp()
    try:
        ej = os.path.join(d, "expected.json")
        json.dump(expd, open(ej, "w"))
        _write_scaffold(d, gates)
        with contextlib.redirect_stdout(io.StringIO()):
            expect(validate(d, ej) == 0, "a complete valid scaffold must PASS")
            cfgp = os.path.join(d, ".claude/develop.config.json")
            c = jload(cfgp); c["gates"] = c["gates"][:1]; json.dump(c, open(cfgp, "w"))  # drop test gate
            expect(validate(d, ej) == 1, "a missing expected gate must FAIL")
            _write_scaffold(d, gates)  # rebuild valid
            os.remove(os.path.join(d, ".claude/develop-routing.json"))
            expect(validate(d, ej) == 1, "a missing required file must FAIL")
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("check-scaffold selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def usage():
    print("usage: check-scaffold.py <target_dir> <expected.json>")
    print("       check-scaffold.py --compare <dirA> <dirB>")
    print("       check-scaffold.py --selftest")
    return 2


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        sys.exit(selftest())
    if len(args) == 3 and args[0] == "--compare":
        sys.exit(compare(args[1], args[2]))
    if len(args) == 2 and not args[0].startswith("--"):
        sys.exit(validate(args[0], args[1]))
    sys.exit(usage())
