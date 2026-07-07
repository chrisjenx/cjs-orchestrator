#!/usr/bin/env bash
# install-smoke.sh — pre-release live-install smoke test for the develop plugin.
#
# Exercises the REAL `claude plugin` install path against the CURRENT working tree, so a
# release is proven to actually install (not just parse). Complements the structural gates:
#   - scripts/check-install.py  — marketplace/plugin shape + cross-link resolution
#   - claude plugin validate     — manifest schema (source of truth)
# This one adds the missing link: `marketplace add` + `install` really resolve the plugin at
# the version plugin.json declares, with its skills, agents, and the guard hook.
#
# Fully isolated: everything runs inside a throwaway CLAUDE_CONFIG_DIR, so it never touches or
# collides with your real marketplaces/installs. Tests the LOCAL tree (no push required), so it
# can gate a release before tagging. Needs the `claude` CLI; exits 2 (skip) if absent.
#
# Note: this verifies the plugin installs and resolves with its full component set. The
# interactive last mile (typing /develop:init and watching it trigger / degrade gracefully in
# an empty repo) still needs a human keystroke in a Claude Code session — see evals/install-e2e.md.
#
# Usage: scripts/install-smoke.sh        Exit 0 = install path healthy, 1 = broken, 2 = skipped.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
PLUGIN_JSON="$REPO/plugins/develop/.claude-plugin/plugin.json"

if ! command -v claude >/dev/null 2>&1; then
  echo "install-smoke: SKIP — 'claude' CLI not found (run check-install.py + 'claude plugin validate' instead)"
  exit 2
fi

EXPECTED=$(python3 -c "import json;print(json.load(open('$PLUGIN_JSON'))['version'])")
AGENT_COUNT=$(find "$REPO/plugins/develop/agents" -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')

SANDBOX=$(mktemp -d)
cleanup() { rm -rf "$SANDBOX"; }
trap cleanup EXIT INT TERM
export CLAUDE_CONFIG_DIR="$SANDBOX"

echo "install-smoke: expected develop v$EXPECTED, $AGENT_COUNT agents (isolated config: $SANDBOX)"

# 1) Add the marketplace from the LOCAL working tree (this tree, pre-push).
claude plugin marketplace add "$REPO" >/dev/null

# 2) Install it (into the isolated sandbox). set -e fails the smoke if the install errors.
claude plugin install develop@cjs-orchestrator >/dev/null

# 3) Assert the installed plugin resolves at the expected version with its full component set.
#    `|| true` so a details failure surfaces as an assertion FAIL, not a bare set -e abort.
details=$(claude plugin details develop@cjs-orchestrator 2>&1 || true)
fail=0
check() { printf '%s\n' "$details" | grep -Eq "$1" || { echo "install-smoke: FAIL — $2"; fail=1; }; }

check "\(develop\) $EXPECTED([^0-9.]|$)"  "version $EXPECTED not resolved (install did not serve the working-tree version)"
check "\binit\b"                          "skill 'init' missing from inventory"
check "\bwork\b"                          "skill 'work' missing from inventory"
check "\bship\b"                          "skill 'ship' missing from inventory"
check "\bflywheel\b"                      "skill 'flywheel' missing from inventory"
check "Agents \($AGENT_COUNT\)"           "expected $AGENT_COUNT agents in inventory"
check "Hooks \(1\)|PreToolUse"            "expected the PreToolUse guard hook"

if [ "$fail" -ne 0 ]; then
  echo "install-smoke: install path is BROKEN — see failures above. Details were:"
  printf '%s\n' "$details" | sed -n '1,12p'
  exit 1
fi

echo "install-smoke: PASS — develop@$EXPECTED installs from the working tree (4 skills, $AGENT_COUNT agents, 1 guard hook)"
