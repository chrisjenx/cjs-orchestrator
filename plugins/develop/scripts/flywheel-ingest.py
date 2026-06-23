#!/usr/bin/env python3
"""Map confirmed escapes (agreed PR-review comments + real CI failures) to FLYWHEEL_RECORD lines,
deduped against the SSOT.

The mechanical half of /develop:flywheel's ingest step (skills/flywheel). The skill fetches and
field-filters escapes from GitHub (a connected MCP server, else the `gh` CLI), normalises each to
a tiny signal STAMPED WITH ITS SOURCE PR, and pipes the array here. This maps each to an
append-ready FLYWHEEL_RECORD (see references/schemas.md) with `escaped_phase` + the cheapest lever
filled deterministically from the maps below — so the agent never guesses the phase or lever, it
only categorises a review comment into the FINDING enum (CI maps by check kind, no judgement).
Given --ssot it appends only records not already present, keyed on (run, fingerprint), so
re-running over the same PRs is idempotent (no duplicate escapes). The whole batch is mapped
before anything is written, so a malformed signal can't leave a partial append. stdlib-only.

Usage:
  flywheel-ingest.py --ssot .claude/develop-flywheel.jsonl < signals.json  # dedup + append in place
  flywheel-ingest.py < signals.json                                        # map -> stdout (no dedup)
  flywheel-ingest.py --selftest

Signal shapes the skill builds from the filtered survivors (run = the PR id, date = its merge
date, so distinct PRs count as distinct runs and re-ingest dedups). severity/breaking are derived
here, not agent-set; pass an explicit `fingerprint` to distinguish two same-kind escapes in one PR:
  CI:     {"kind":"ci","checkKind":"build|test|coverage|lint|types|other","run":"pr-123","date":"YYYY-MM-DD"}
  review: {"kind":"review","category":"<FINDING category>","file":..,"line":..,"run":"pr-123","date":"YYYY-MM-DD"}
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
REVIEW_DEFAULT = ("PA", "rule", "review rule in CLAUDE.md (uncategorised, confirm)")

# Append-only lines read best in a stable key order.
KEY_ORDER = ["run", "date", "fingerprint", "category", "severity", "source",
             "preventable", "breaking", "escaped_phase", "remediation", "target"]


# CI checks whose failure breaks the build/suite (breaking-class -> high severity); lint/coverage
# are quality signals, not breaks. Derived mechanically (not agent-set) so severity is
# deterministic across re-ingests — which keeps the default fingerprint (the dedup key) stable.
BREAKING_CHECKS = {"build", "test", "types"}


def to_record(sig):
    kind = sig.get("kind")
    if kind == "ci":
        ck = sig.get("checkKind", "other")
        cat, phase, lever, target = CI_MAP.get(ck, CI_MAP["other"])
        breaking = ck in BREAKING_CHECKS
        source = "ci"
        fp = sig.get("fingerprint", f"ci:{ck}:{cat}")
    elif kind == "review":
        cat = sig.get("category") or "uncategorised"
        phase, lever, target = REVIEW_MAP.get(cat, REVIEW_DEFAULT)
        breaking = False  # a review escape's weight is its category, not a build break
        source = "pr-review"
        fp = sig.get("fingerprint", f"{sig.get('file','?')}:{sig.get('line','?')}:{cat}")
    else:
        raise ValueError(f"unknown signal kind: {kind!r}")
    # fingerprint is severity-free on purpose: the dedup key must not move if severity does.
    rec = {
        "run": sig.get("run", "?"), "date": sig.get("date", "?"), "fingerprint": fp,
        "category": cat, "severity": "high" if breaking else "medium", "source": source,
        "preventable": True, "breaking": breaking,
        "escaped_phase": phase, "remediation": lever, "target": target,
    }
    return {k: rec[k] for k in KEY_ORDER}


def existing_keys(path):
    """(run, fingerprint) pairs already in the SSOT, so we never re-append them."""
    keys = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(r, dict):
                    keys.add((r.get("run"), r.get("fingerprint")))
    except FileNotFoundError:
        pass
    return keys


def filter_new(records, seen):
    """Records whose (run, fingerprint) is neither in `seen` nor earlier in this batch."""
    fresh, batch = [], set(seen)
    for r in records:
        k = (r.get("run"), r.get("fingerprint"))
        if k in batch:
            continue
        batch.add(k)
        fresh.append(r)
    return fresh


def selftest():
    cases = [
        # breaking is derived from checkKind: build/test/types break the suite (high), others medium.
        ({"kind": "ci", "checkKind": "build", "run": "pr-1", "date": "2026-06-21"},
         {"source": "ci", "category": "build-break", "escaped_phase": "PF", "remediation": "gate", "severity": "high", "breaking": True}),
        ({"kind": "ci", "checkKind": "test", "run": "pr-1", "date": "2026-06-21"},
         {"category": "failing-test", "severity": "high", "breaking": True}),
        ({"kind": "ci", "checkKind": "lint", "run": "pr-1", "date": "2026-06-21"},
         {"category": "lint", "escaped_phase": "PT", "severity": "medium", "breaking": False}),
        ({"kind": "ci", "checkKind": "coverage", "run": "pr-1", "date": "2026-06-21"},
         {"source": "ci", "category": "untested-flow", "escaped_phase": "PV", "remediation": "plan-anchor", "severity": "medium", "breaking": False}),
        ({"kind": "ci", "checkKind": "wat", "run": "pr-1", "date": "2026-06-21"},  # unknown -> other
         {"source": "ci", "category": "ci-failure", "escaped_phase": "PF", "breaking": False}),
        ({"kind": "review", "category": "regression", "file": "a.py", "line": 3, "run": "pr-1", "date": "2026-06-21"},
         {"source": "pr-review", "escaped_phase": "PA", "remediation": "agent", "breaking": False}),
        ({"kind": "review", "category": "style", "file": "a.py", "line": 3, "run": "pr-1", "date": "2026-06-21"},
         {"source": "pr-review", "escaped_phase": "PT", "remediation": "rule"}),
        ({"kind": "review", "category": "weird-new-thing", "file": "a.py", "line": 3, "run": "pr-1", "date": "2026-06-21"},
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

    # Fingerprint is stable regardless of any stray input field (breaking is derived, not read),
    # so the same escape re-ingested always dedups — the idempotency guarantee.
    assert to_record({"kind": "ci", "checkKind": "build", "run": "pr-1", "date": "d"})["fingerprint"] \
        == to_record({"kind": "ci", "checkKind": "build", "run": "pr-1", "date": "d", "breaking": "x"})["fingerprint"]

    # Dedup: same (run, fingerprint) drops, both within a batch and against `seen`.
    a = to_record({"kind": "ci", "checkKind": "build", "run": "pr-1", "date": "d"})
    a2 = to_record({"kind": "ci", "checkKind": "build", "run": "pr-1", "date": "d"})  # dup of a
    b = to_record({"kind": "ci", "checkKind": "build", "run": "pr-2", "date": "d"})   # diff PR
    assert [r["run"] for r in filter_new([a, a2, b], set())] == ["pr-1", "pr-2"], "within-batch dedup"
    seen = {(a["run"], a["fingerprint"])}
    assert [r["run"] for r in filter_new([a, b], seen)] == ["pr-2"], "dedup against existing SSOT"
    # Empty input maps to nothing.
    assert filter_new([], set()) == []
    print("flywheel-ingest selftest: ok")


def main():
    ap = argparse.ArgumentParser(description="Map confirmed escapes to deduped FLYWHEEL_RECORD lines.")
    ap.add_argument("--ssot", help="dedup against and append to this JSONL SSOT, in place")
    ap.add_argument("--selftest", action="store_true", help="run the unit tests and exit")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return 0
    raw = sys.stdin.read().strip()
    signals = json.loads(raw) if raw else []  # empty stdin (no escapes this cycle) -> clean no-op
    if isinstance(signals, dict):
        signals = [signals]
    if not isinstance(signals, list):
        raise ValueError("expected a JSON array of signals on stdin")
    records = [to_record(s) for s in signals]  # map+validate the WHOLE batch before any write
    if args.ssot:
        fresh = filter_new(records, existing_keys(args.ssot))
        with open(args.ssot, "a", encoding="utf-8") as fh:
            for r in fresh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"ingest: {len(fresh)} new, {len(records) - len(fresh)} already present "
              f"({len(records)} signals)", file=sys.stderr)
    else:
        for r in records:
            sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
