#!/usr/bin/env python3
"""Validate everything `/plugin install develop@cjs-orchestrator` + skill triggering rely on.

The live e2e (`/plugin marketplace add ...` then `/plugin install ...`) runs inside Claude
Code against the pushed repo. This validates the structure that install resolves and that the
skills are discoverable/triggerable, so a structural break is caught before a release:

- marketplace.json -> plugin 'develop' source resolves to a real plugin dir
- plugin.json valid (name=develop, version, skills/agents dirs declared + present)
- every SKILL.md / agent .md has YAML frontmatter with non-empty name + description
  (description = what makes /develop:init and /develop:work trigger)
- every relative cross-reference link in the plugin's markdown resolves to a real file
  (catches broken references the loop would hit at runtime)

Exit 0 = installable, 1 = problem.
"""
import os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN = os.path.join(ROOT, "plugins", "develop")
problems = []


def frontmatter(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        km = re.match(r"^(\w+):\s*(.*)$", line)
        if km:
            fm[km.group(1)] = km.group(2).strip()
    return fm


def check_frontmatter(path, label):
    fm = frontmatter(path)
    rel = os.path.relpath(path, ROOT)
    if fm is None:
        problems.append(f"{rel}: missing YAML frontmatter")
        return
    for key in ("name", "description"):
        if not fm.get(key):
            problems.append(f"{rel}: {label} frontmatter missing/empty {key!r}")


def main() -> int:
    import json

    # 1) marketplace -> plugin dir resolves
    mp = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
    proot = mp.get("metadata", {}).get("pluginRoot", ".")
    entry = next((p for p in mp.get("plugins", []) if p.get("name") == "develop"), None)
    if not entry:
        problems.append("marketplace.json: no 'develop' plugin entry")
    else:
        resolved = os.path.normpath(os.path.join(ROOT, proot, entry.get("source", "")))
        if not os.path.isdir(resolved):
            problems.append(f"marketplace.json: develop source resolves to missing dir {resolved}")

    # 2) plugin.json declared dirs present
    pj = json.load(open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    for key in ("skills", "agents"):
        if key in pj:
            d = os.path.normpath(os.path.join(PLUGIN, pj[key].lstrip("./")))
            if not os.path.isdir(d):
                problems.append(f"plugin.json: {key} dir {pj[key]} missing")

    # 3) skills present + triggerable (discover all skill dirs)
    sdir = os.path.join(PLUGIN, "skills")
    skills = sorted(d for d in os.listdir(sdir) if os.path.isdir(os.path.join(sdir, d))) \
        if os.path.isdir(sdir) else []
    for required in ("init", "work", "flywheel"):
        if required not in skills:
            problems.append(f"skills/{required}/ missing")
    for skill in skills:
        sp = os.path.join(sdir, skill, "SKILL.md")
        if not os.path.isfile(sp):
            problems.append(f"skills/{skill}/SKILL.md missing")
        else:
            check_frontmatter(sp, f"skill:{skill}")

    # 4) agents frontmatter
    adir = os.path.join(PLUGIN, "agents")
    agents = [f for f in os.listdir(adir) if f.endswith(".md")] if os.path.isdir(adir) else []
    if not agents:
        problems.append("agents/: no agent .md files found")
    for a in agents:
        check_frontmatter(os.path.join(adir, a), "agent")

    # 5) cross-reference links resolve
    md_files = []
    for dp, _dirs, files in os.walk(PLUGIN):
        for fn in files:
            if fn.endswith(".md"):
                md_files.append(os.path.join(dp, fn))
    link_rx = re.compile(r"\]\((?!https?://|#|mailto:)([^)#]+)(?:#[^)]*)?\)")
    for path in md_files:
        base = os.path.dirname(path)
        for link in link_rx.findall(open(path, encoding="utf-8").read()):
            target = os.path.normpath(os.path.join(base, link))
            if not os.path.exists(target):
                problems.append(f"{os.path.relpath(path, ROOT)}: broken link -> {link}")

    if problems:
        print("install validation FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"install validation PASSED — plugin resolves, {len(agents)} agents, "
          f"{len(skills)} skills, all {len(md_files)} plugin docs' cross-links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
