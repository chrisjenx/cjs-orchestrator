#!/usr/bin/env python3
"""Catch doc rosters that drifted from what's actually shipped.

`plugins/develop/README.md` and `docs/use.html` each keep a hand-written roster of the
bundled skills/agents; root `README.md` keeps a repo-layout tree. Nothing re-derives those
lists from the filesystem, so adding a skill/agent without touching every roster silently
goes stale (this happened: v0.9.0 added `ci-failure-extractor` and `general-quality-reviewer`
went unmentioned in one roster each). This makes that mechanical:

- every skill (a dir under `plugins/develop/skills/`) must be named via its `/develop:<x>`
  command token in all three roster files
- every agent (an `agents/*.md` frontmatter `name`) must be mentioned — by its own name or a
  documented alias/group phrase, see AGENT_ALIASES — in both `plugins/develop/README.md` and
  `docs/use.html`
- the plugin version must agree across `plugin.json`, `templates/develop.config.json`
  (`pluginVersion`), and CHANGELOG.md's latest dated section

Adding an agent/skill? Update the rosters, then add its alias set below if it's grouped
under a category phrase rather than named outright (like the three diff-reading auditors).

Exit 0 = in sync, 1 = a roster (or version) is stale.
"""
import json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN = os.path.join(ROOT, "plugins", "develop")

ROOT_README = os.path.join(ROOT, "README.md")
PLUGIN_README = os.path.join(PLUGIN, "README.md")
USE_HTML = os.path.join(ROOT, "docs", "use.html")

# Acceptable ways a roster doc may refer to each agent. Most agents are just named
# outright; the three diff-reading auditors are sometimes named individually (as in
# plugins/develop/README.md) and sometimes grouped under a category phrase (as in
# docs/use.html) — both count as "mentioned".
AGENT_ALIASES = {
    "planner": ["planner"],
    "executor": ["executor"],
    "completeness-auditor": ["completeness-auditor", "completeness", "diff-reading auditor"],
    "stubs-auditor": ["stubs-auditor", "stubs", "diff-reading auditor"],
    "regression-auditor": ["regression-auditor", "regression", "diff-reading auditor"],
    "general-quality-reviewer": ["general-quality-reviewer"],
    "code-reviewer": ["code-reviewer"],
    "tidy": ["tidy"],
    "refuter": ["refuter"],
    "ci-failure-extractor": ["ci-failure-extractor"],
}

AGENT_ROSTER_FILES = [PLUGIN_README, USE_HTML]
SKILL_ROSTER_FILES = [ROOT_README, PLUGIN_README, USE_HTML]


def frontmatter_name(path: str) -> str:
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if m:
        nm = re.search(r"^name:\s*(.+)$", m.group(1), re.MULTILINE)
        if nm:
            return nm.group(1).strip()
    return os.path.splitext(os.path.basename(path))[0]


def agent_mentioned(text: str, agent: str) -> bool:
    aliases = AGENT_ALIASES.get(agent, [agent])
    return any(alias in text for alias in aliases)


def discover_skills() -> list[str]:
    sdir = os.path.join(PLUGIN, "skills")
    return sorted(d for d in os.listdir(sdir) if os.path.isdir(os.path.join(sdir, d)))


def discover_agents() -> list[str]:
    adir = os.path.join(PLUGIN, "agents")
    return sorted(frontmatter_name(os.path.join(adir, f)) for f in os.listdir(adir) if f.endswith(".md"))


def check_skill_rosters(skills: list[str], problems: list[str]) -> None:
    for roster in SKILL_ROSTER_FILES:
        text = open(roster, encoding="utf-8").read()
        rel = os.path.relpath(roster, ROOT)
        for skill in skills:
            token = f"/develop:{skill}"
            if token not in text:
                problems.append(f"{rel}: missing skill roster entry for {token!r}")


def check_agent_rosters(agents: list[str], problems: list[str]) -> None:
    for roster in AGENT_ROSTER_FILES:
        text = open(roster, encoding="utf-8").read()
        rel = os.path.relpath(roster, ROOT)
        for agent in agents:
            if not agent_mentioned(text, agent):
                problems.append(f"{rel}: missing agent roster mention for {agent!r} "
                                 f"(aliases tried: {AGENT_ALIASES.get(agent, [agent])})")


def check_versions(problems: list[str]) -> None:
    pj = json.load(open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    plugin_version = pj.get("version")

    cfg = json.load(open(os.path.join(PLUGIN, "templates", "develop.config.json"), encoding="utf-8"))
    template_version = cfg.get("pluginVersion")

    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
    changelog_version = m.group(1) if m else None

    if not (plugin_version and template_version and changelog_version):
        problems.append("version check: could not read one of plugin.json / "
                         "templates/develop.config.json / CHANGELOG.md")
        return
    if not (plugin_version == template_version == changelog_version):
        problems.append(
            f"version mismatch: plugin.json={plugin_version!r}, "
            f"templates/develop.config.json pluginVersion={template_version!r}, "
            f"CHANGELOG.md latest={changelog_version!r}"
        )


def main() -> int:
    problems: list[str] = []
    skills = discover_skills()
    agents = discover_agents()
    check_skill_rosters(skills, problems)
    check_agent_rosters(agents, problems)
    check_versions(problems)

    if problems:
        print("docs freshness check FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"docs freshness check PASSED — {len(skills)} skills and {len(agents)} agents "
          f"accounted for in every roster, versions agree")
    return 0


def selftest() -> int:
    """Guard the guard: alias matching must accept grouped phrasing and reject real drift."""
    ok = True

    grouped_doc = "the diff-reading auditors, code-reviewer, tidy, refuter"
    if not agent_mentioned(grouped_doc, "completeness-auditor"):
        print("  SELFTEST FAIL: grouped phrase should satisfy completeness-auditor"); ok = False

    named_doc = "completeness-auditor, stubs-auditor, regression-auditor"
    if not agent_mentioned(named_doc, "regression-auditor"):
        print("  SELFTEST FAIL: literal name should satisfy regression-auditor"); ok = False

    stale_doc = "planner, executor, code-reviewer, tidy, refuter"
    if agent_mentioned(stale_doc, "ci-failure-extractor"):
        print("  SELFTEST FAIL: absent agent should not be reported as mentioned"); ok = False

    print("docs-freshness selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(main())
