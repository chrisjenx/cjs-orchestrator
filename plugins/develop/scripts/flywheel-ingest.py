#!/usr/bin/env python3
"""Map confirmed escapes (agreed PR-review comments + real CI failures) to FLYWHEEL_RECORD lines.

The mechanical half of /develop:flywheel's ingest step (skills/flywheel). The skill fetches and
field-filters escapes from GitHub (a connected MCP server, else the `gh` CLI), normalises each to
a tiny signal, and pipes the array here; this emits one append-ready FLYWHEEL_RECORD per signal
(see references/schemas.md) with `escaped_phase` + the cheapest lever filled deterministically
from the maps below — so the agent never guesses the phase or lever, it only categorises a review
comment into the FINDING enum (CI maps by check kind, no judgement). stdlib-only, read-only; runs
at flywheel time, never in the run hot loop.

Usage:
  flywheel-ingest.py < signals.json   # JSON array (or one object) on stdin -> FLYWHEEL_RECORD lines
  flywheel-ingest.py --selftest

Signal shapes the skill builds from the filtered survivors:
  CI:     {"kind":"ci","checkKind":"build|test|coverage|lint|types|other","run":..,"date":..,"breaking":bool}
  review: {"kind":"review","category":"<FINDING category>","file":..,"line":..,"run":..,"date":..,"breaking":bool}
"""
import argparse, json, sys

# A CI check that fails in CI but not in local finalize means the local gate set is narrower than
# CI -> escaped_phase PF, add the gate; coverage points further upstream (untested flow).
# checkKind -> (category, escaped_phase, remediation, target)
CI_MAP = {
    "build":    ("build-break",   "PF", "gate",        "build gate in develop.config.json"),
    "test":     ("failing-test",  "PF", "gate",        "test gate in develop.config.json"),
    "coverage": ("untested-flow", "PV", "plan-anchor", "tests-named anchor / coverage gate"),
    "lint":     ("lint",          "PT", "gate",        "lint gate / hook"),
    "types":    ("type-error",    "PF", "gate",        "types gate in develop.config.json"),
    "other":    ("ci-failure",    "PF", "gate",        "add the missing check as a gate"),
}

# Cheapest, earliest lever that expresses the check (references/flywheel.md).
# FINDING category -> (escaped_phase, remediation, target)
REVIEW_MAP = {
    "missing-feature": ("planner", "plan-anchor", "Requirements Inventory row"),
    "missing-test":    ("PV",      "plan-anchor", "tests-named anchor"),
    "untested-flow":   ("PV",      "plan-anchor", "tests-named anchor"),
    "incomplete":      ("PA",      "plan-anchor", "wiring anchor"),
    "unwired":         ("PA",      "plan-anchor", "wiring anchor"),
    "stub":            ("PA",      "plan-anchor", "{grep:no-todo} anchor"),
    "regression":      ("PA",      "agent",       "regression route in develop-routing.json"),
    "missing-guard":   ("PA",      "rule",        "guard rule in CLAUDE.md"),
    "duplicate":       ("PV",      "plan-anchor", "reuse-map anchor"),
    "style":           ("PT",      "rule",        "convention in CLAUDE.md"),
    "naming":          ("PT",      "rule",        "convention in CLAUDE.md"),
    "quality":         ("PT",      "rule",        "convention in CLAUDE.md"),
}
REVIEW_DEFAULT = ("PA", "rule", "review rule in CLAUDE.md (uncategorised — confirm)")

# Append-only lines read best in a stable key order.
KEY_ORDER = ["run", "date", "fingerprint", "category", "severity", "source",
             "preventable", "breaking", "escaped_phase", "remediation", "target"]


def to_record(sig):
    kind = sig.get("kind")
    breaking = bool(sig.get("breaking"))
    sev = "high" if breaking else "medium"
    if kind == "ci":
        ck = sig.get("checkKind", "other")
        cat, phase, lever, target = CI_MAP.get(ck, CI_MAP["other"])
        source = "ci"
        fp = sig.get("fingerprint", f"{sev}:ci:{ck}:{cat}")
    elif kind == "review":
        cat = sig.get("category") or "uncategorised"
        phase, lever, target = REVIEW_MAP.get(cat, REVIEW_DEFAULT)
        source = "pr-review"
        fp = sig.get("fingerprint", f"{sev}:{sig.get('file','?')}:{sig.get('line','?')}:{cat}")
    else:
        raise ValueError(f"unknown signal kind: {kind!r}")
    rec = {
        "run": sig.get("run", "?"), "date": sig.get("date", "?"), "fingerprint": fp,
        "category": cat, "severity": sev, "source": source,
        "preventable": True, "breaking": breaking,
        "escaped_phase": phase, "remediation": lever, "target": target,
    }
    return {k: rec[k] for k in KEY_ORDER}


def emit(signals, out):
    for sig in signals:
        out.write(json.dumps(to_record(sig), ensure_ascii=False) + "\n")


def selftest():
    cases = [
        ({"kind": "ci", "checkKind": "build", "run": "f", "date": "2026-06-21", "breaking": True},
         {"source": "ci", "category": "build-break", "escaped_phase": "PF", "remediation": "gate", "severity": "high"}),
        ({"kind": "ci", "checkKind": "coverage", "run": "f", "date": "2026-06-21"},
         {"source": "ci", "category": "untested-flow", "escaped_phase": "PV", "remediation": "plan-anchor", "severity": "medium"}),
        ({"kind": "ci", "checkKind": "wat", "run": "f", "date": "2026-06-21"},  # unknown -> other
         {"source": "ci", "category": "ci-failure", "escaped_phase": "PF"}),
        ({"kind": "review", "category": "regression", "file": "a.py", "line": 3, "run": "f", "date": "2026-06-21"},
         {"source": "pr-review", "escaped_phase": "PA", "remediation": "agent"}),
        ({"kind": "review", "category": "style", "file": "a.py", "line": 3, "run": "f", "date": "2026-06-21"},
         {"source": "pr-review", "escaped_phase": "PT", "remediation": "rule"}),
        ({"kind": "review", "category": "weird-new-thing", "file": "a.py", "line": 3, "run": "f", "date": "2026-06-21"},
         {"source": "pr-review", "escaped_phase": "PA", "remediation": "rule"}),  # default
    ]
    for sig, want in cases:
        got = to_record(sig)
        for k, v in want.items():
            assert got[k] == v, f"{sig}: {k} = {got[k]!r}, want {v!r}"
        assert got["preventable"] is True
        assert list(got.keys()) == KEY_ORDER
    for bad in ({"kind": "bogus"}, {}):
        try:
            to_record(bad)
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass
    print("flywheel-ingest selftest: ok")


def main():
    ap = argparse.ArgumentParser(description="Map confirmed escapes to FLYWHEEL_RECORD lines.")
    ap.add_argument("--selftest", action="store_true", help="run the mapping unit tests and exit")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return 0
    data = json.load(sys.stdin)
    emit([data] if isinstance(data, dict) else data, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
