#!/usr/bin/env python3
"""Validate every JSON file parses, and that the plugin manifests have required keys.

Covers the marketplace catalog, the plugin manifest, and the bundled JSON templates/fixtures
so a malformed manifest can never reach a release. Exit 0 = OK, 1 = problem.
"""
import json, os, sys

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


def main() -> int:
    problems = []

    # 1) Everything parses.
    for path in all_json():
        try:
            with open(path, encoding="utf-8") as f:
                json.load(f)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{os.path.relpath(path, ROOT)}: invalid JSON — {e}")

    # 2) Marketplace required keys + plugin cross-reference.
    mp_path = ROOT + MARKETPLACE
    try:
        mp = json.load(open(mp_path, encoding="utf-8"))
        require(mp, ["name", "owner", "plugins"], "marketplace.json", problems)
        names = [p.get("name") for p in mp.get("plugins", [])]
        if "develop" not in names:
            problems.append("marketplace.json: plugins[] must list the 'develop' plugin")
    except Exception as e:  # noqa: BLE001
        problems.append(f"marketplace.json: {e}")

    # 3) Plugin manifest required keys.
    pl_path = ROOT + PLUGIN
    try:
        pl = json.load(open(pl_path, encoding="utf-8"))
        require(pl, ["name", "version"], "plugin.json", problems)
        if pl.get("name") != "develop":
            problems.append(f"plugin.json: name must be 'develop' (got {pl.get('name')!r})")
    except Exception as e:  # noqa: BLE001
        problems.append(f"plugin.json: {e}")

    if problems:
        print("manifest validation FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print("manifest validation PASSED — all JSON valid; marketplace + plugin manifests OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
