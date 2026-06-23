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
import json, os, sys, glob

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

    if fails:
        print("validate-manifests selftest FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("validate-manifests selftest PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else main())
