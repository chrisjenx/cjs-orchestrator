#!/usr/bin/env python3
"""Validate JSON manifests, plugin source/field shapes, and agent/skill frontmatter.

Beyond "every JSON parses", this guards the three classes that made v0.4.0 uninstallable
(gh #30) — CI passed but `claude plugin install` failed for every user:
  - marketplace plugins[].source must be a './'-relative path that exists (a bare name is
    rejected, and metadata.pluginRoot is NOT honored for a string source), or an object source.
  - plugin.json 'agents' must not be a directory string (the schema rejects it) — omit it for
    auto-discovery, or give a file-path array.
  - every shipped agent/skill frontmatter must parse as YAML with a name + description. An
    unquoted ': ' (or other special token) in a value silently drops the whole block at runtime,
    so the agent loads with no name and routing-by-name breaks.

`claude plugin validate` is the authoritative check; this mirrors its verdicts deterministically
in CI without that dependency. Exit 0 = OK, 1 = problem. Run with --selftest to verify the guards.
"""
import json, os, sys, glob, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

MARKETPLACE = "/.claude-plugin/marketplace.json"
PLUGIN = "/plugins/develop/.claude-plugin/plugin.json"

SKIP_DIRS = {".git", "node_modules"}


def all_json():
    for dp, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn.endswith(".json"):
                yield os.path.join(dp, fn)


def require(obj, keys, where, problems):
    for k in keys:
        if k not in obj:
            problems.append(f"{where}: missing required key {k!r}")


def check_source(mp, problems):
    """plugins[].source: object is fine; a string must be a './'-relative path that exists."""
    for i, p in enumerate(mp.get("plugins", [])):
        src = p.get("source")
        where = f"marketplace.json plugins[{i}] ({p.get('name', '?')})"
        if isinstance(src, dict):
            continue  # object sources (git-subdir etc.) — out of scope for the path check
        if not isinstance(src, str):
            problems.append(f"{where}: source must be a './'-relative path string or an object")
            continue
        if not (src.startswith("./") or src.startswith("../")):
            problems.append(
                f"{where}: source {src!r} must be a './'-relative path from the marketplace root "
                f"(a bare name is rejected; metadata.pluginRoot is not honored for a string source)")
            continue
        resolved = os.path.normpath(os.path.join(ROOT, src))
        if not os.path.isdir(resolved):
            problems.append(f"{where}: source path does not exist: {src}")
        elif not os.path.isfile(os.path.join(resolved, ".claude-plugin", "plugin.json")):
            problems.append(f"{where}: source {src} has no .claude-plugin/plugin.json")


def check_plugin_fields(pl, problems):
    if isinstance(pl.get("agents"), str):
        problems.append(
            "plugin.json: 'agents' must not be a directory string (the schema rejects it) — "
            "omit it for auto-discovery, or give a file-path array")


BUILD_OUTPUT_SEGMENTS = ("build", "target", "out", "dist", "bin")


def feature_dir_unsafe(fd):
    """Return a reason string if featureDir sits under a build-output dir a 'clean' wipes, else None."""
    parts = [s for s in str(fd).split("/") if s and s != "."]
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


TOKEN_KIND_HEADS = ("build", "test", "lint", "format", "types", "coverage", "cov", "grep")


def valid_gate_token(tok):
    """tok includes braces. Canonical grammar (gate-tokens.md)."""
    if re.fullmatch(r"\{(build|lint|types|format)(:[A-Za-z0-9_.\-]+)?\}", tok):
        return True   # bare kind, or {kind:id} to disambiguate multiple same-kind gates
    if re.fullmatch(r"\{test:[^}]+\}", tok):
        return True   # test always carries a selector
    if re.fullmatch(r"\{cov(>=|<=|=)(\d+|N)\}", tok):
        return True   # \d+ concrete, or literal 'N' in grammar-description text
    if re.fullmatch(r"\{grep:[^}]+\}", tok):
        return True
    return False


def _looks_like_gate_token(tok):
    head = re.split(r"[:<>=}]", tok[1:], maxsplit=1)[0]
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


def parse_frontmatter(path):
    """Return the parsed YAML frontmatter mapping, or raise on any parse/shape error."""
    import yaml
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("no opening '---' frontmatter fence")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("unterminated frontmatter (no closing '---')")
    data = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    return data


def check_frontmatter(problems):
    files = sorted(glob.glob(os.path.join(ROOT, "plugins/develop/agents/*.md")))
    files += sorted(glob.glob(os.path.join(ROOT, "plugins/develop/skills/*/SKILL.md")))
    for p in files:
        rel = os.path.relpath(p, ROOT)
        try:
            data = parse_frontmatter(p)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{rel}: frontmatter failed to parse — {str(e).splitlines()[0]}")
            continue
        for k in ("name", "description"):
            if not data.get(k):
                problems.append(f"{rel}: frontmatter missing/empty {k!r}")


def main() -> int:
    problems = []

    # 1) Everything parses.
    for path in all_json():
        try:
            with open(path, encoding="utf-8") as f:
                json.load(f)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{os.path.relpath(path, ROOT)}: invalid JSON — {e}")

    # 2) Marketplace required keys + plugin cross-reference + source shape.
    try:
        mp = json.load(open(ROOT + MARKETPLACE, encoding="utf-8"))
        require(mp, ["name", "owner", "plugins"], "marketplace.json", problems)
        if "develop" not in [p.get("name") for p in mp.get("plugins", [])]:
            problems.append("marketplace.json: plugins[] must list the 'develop' plugin")
        check_source(mp, problems)
    except Exception as e:  # noqa: BLE001
        problems.append(f"marketplace.json: {e}")

    # 3) Plugin manifest required keys + field shapes.
    try:
        pl = json.load(open(ROOT + PLUGIN, encoding="utf-8"))
        require(pl, ["name", "version"], "plugin.json", problems)
        if pl.get("name") != "develop":
            problems.append(f"plugin.json: name must be 'develop' (got {pl.get('name')!r})")
        check_plugin_fields(pl, problems)
    except Exception as e:  # noqa: BLE001
        problems.append(f"plugin.json: {e}")

    # 4) Every shipped agent/skill frontmatter parses as YAML with a name + description.
    check_frontmatter(problems)

    # 5) Template featureDir must not be wiped by a build 'clean'.
    check_template_feature_dir(problems)

    # 6) Gate-token examples in the docs match the canonical grammar.
    check_gate_token_grammar(problems)

    if problems:
        print("manifest validation FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print("manifest validation PASSED — JSON valid; source/agents shapes OK; frontmatter parses")
    return 0


def selftest() -> int:
    import tempfile
    fails = []

    def expect(cond, msg):
        if not cond:
            fails.append(msg)

    # source shape
    p = []
    check_source({"plugins": [{"name": "x", "source": "develop"}]}, p)
    expect(p, "bare-string source should be rejected")
    p = []
    check_source({"plugins": [{"name": "develop", "source": "./plugins/develop"}]}, p)
    expect(not p, f"./plugins/develop source should pass, got {p}")
    p = []
    check_source({"plugins": [{"name": "x", "source": {"source": "git-subdir"}}]}, p)
    expect(not p, "object source should pass the path check")

    # plugin field shape
    p = []
    check_plugin_fields({"agents": "./agents/"}, p)
    expect(p, "agents-as-directory-string should be rejected")
    p = []
    check_plugin_fields({"agents": ["./agents/a.md"]}, p)
    check_plugin_fields({"skills": "./skills/"}, p)
    expect(not p, f"agents-as-array / skills-as-string should pass, got {p}")

    # frontmatter parse (the ': ' class that broke 6 agents)
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.md")
        with open(bad, "w") as f:
            f.write("---\nname: x\ndescription: Reuse-first: applies rules here.\n---\nbody\n")
        try:
            parse_frontmatter(bad); raised = False
        except Exception:
            raised = True
        expect(raised, "unquoted ': ' in a description should fail to parse")

        good = os.path.join(d, "good.md")
        with open(good, "w") as f:
            f.write('---\nname: x\ndescription: "Reuse-first: applies rules here."\n---\nbody\n')
        try:
            data = parse_frontmatter(good)
            expect(data.get("name") == "x" and "Reuse-first" in data.get("description", ""),
                   "quoted description should parse with its value intact")
        except Exception as e:  # noqa: BLE001
            fails.append(f"quoted description should parse, raised {e}")

    # featureDir safety
    expect(feature_dir_unsafe("build/develop"), "build/develop should be flagged")
    expect(feature_dir_unsafe("target/x"), "target/ should be flagged")
    expect(not feature_dir_unsafe(".develop"), ".develop should pass")
    expect(not feature_dir_unsafe(".claude/develop"), ".claude/develop should pass")
    expect(feature_dir_unsafe("./build/x"), "./build/x should be flagged")
    expect(not feature_dir_unsafe(""), "empty featureDir should not be flagged")

    # gate-token grammar
    for good in ("{build}", "{build:compile}", "{lint}", "{types}", "{format}", "{test:server}", "{cov>=80}", "{grep:no-todo}"):
        expect(valid_gate_token(good), f"{good} should be valid")
    for bad in ("{build:}", "{frobnicate}", "{cov>=}", "{test}", "{grep}"):
        expect(not valid_gate_token(bad), f"{bad} should be rejected")
    expect(_looks_like_gate_token("{build:compile}") and not _looks_like_gate_token("{pkg}"), "placeholder {pkg} must not look like a gate token")

    if fails:
        print("validate-manifests selftest FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("validate-manifests selftest PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else main())
