#!/usr/bin/env python3
"""Aggregate the develop flywheel SSOT for /develop:flywheel.

Reads the append-only `.claude/develop-flywheel.jsonl` (one FLYWHEEL_RECORD per line,
see references/schemas.md) and emits the prioritised tweak list — recurrences counted
across runs, cheapest lever first. Read-only, stdlib-only, runs only at flywheel time
(never in the run hot loop). Stays out of judgement: it counts; the skill + human decide.

Usage:
  flywheel-aggregate.py [path/to/develop-flywheel.jsonl] [--json]
Defaults to .claude/develop-flywheel.jsonl.
"""
import argparse, collections, json, sys

# Cheapest, earliest lever first (references/flywheel.md). Unknown sorts last.
LEVER_RANK = {"hook": 0, "gate": 1, "plan-anchor": 2, "rule": 3, "agent": 4}


def load(path):
    records, skipped = [], 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    skipped += 1
    except FileNotFoundError:
        return None, 0
    return records, skipped


def aggregate(records):
    cats = collections.defaultdict(lambda: {
        "runs": set(), "breaking": False, "preventable": False, "escaped": False,
        "levers": collections.Counter(), "targets": collections.Counter(),
        "phases": collections.Counter(),
    })
    runkeys, dates = set(), []
    for r in records:
        runkey = f"{r.get('run','?')}@{r.get('date','?')}"
        runkeys.add(runkey)
        if r.get("date"):
            dates.append(r["date"])
        c = cats[r.get("category", "uncategorised")]
        c["runs"].add(runkey)
        c["breaking"] = c["breaking"] or bool(r.get("breaking"))
        if r.get("source", "run") in ("pr-review", "ci"):  # a confirmed escape
            c["escaped"] = True
            if r.get("escaped_phase"):
                c["phases"][r["escaped_phase"]] += 1
        if r.get("preventable", True):
            c["preventable"] = True
            if r.get("remediation"):
                c["levers"][r["remediation"]] += 1
            if r.get("target"):
                c["targets"][r["target"]] += 1
    return cats, runkeys, dates


def rows(cats):
    promote, watch, floor_cats = [], [], []
    for name, c in cats.items():
        n = len(c["runs"])
        if not c["preventable"]:
            floor_cats.append((name, n))
            continue
        lever = c["levers"].most_common(1)[0][0] if c["levers"] else "?"
        target = c["targets"].most_common(1)[0][0] if c["targets"] else "?"
        phase = c["phases"].most_common(1)[0][0] if c["phases"] else None
        row = {"category": name, "runs": n, "breaking": c["breaking"],
               "escaped": c["escaped"], "phase": phase,
               "remediation": lever, "target": target}
        # An escape is a proven miss -> promotion-ready at x1 (alongside >=2 runs / breaking).
        (promote if (n >= 2 or c["breaking"] or c["escaped"]) else watch).append(row)
    # escaped (proven) first, then cheapest lever, then most-recurring.
    promote.sort(key=lambda r: (0 if r["escaped"] else 1,
                                LEVER_RANK.get(r["remediation"], 5), -r["runs"], r["category"]))
    watch.sort(key=lambda r: (-r["runs"], r["category"]))
    floor_cats.sort()
    return promote, watch, floor_cats


def selftest():
    # A single confirmed escape promotes at x1; a once-seen internal residual only watches.
    promote, watch, _ = rows(aggregate([
        {"run": "f", "date": "2026-06-21", "category": "regression",
         "source": "pr-review", "escaped_phase": "PA", "preventable": True,
         "remediation": "agent", "target": "regression route"},
        {"run": "f", "date": "2026-06-21", "category": "style",
         "preventable": True, "remediation": "rule", "target": "CLAUDE.md"},
    ])[0])
    pcats = {r["category"] for r in promote}
    assert "regression" in pcats, "escape should be promotion-ready at x1"
    assert {r["category"] for r in watch} == {"style"}, "once-seen residual should only watch"
    esc = next(r for r in promote if r["category"] == "regression")
    assert esc["escaped"] and esc["phase"] == "PA", esc
    # x2 internal recurrence promotes without any escape.
    promote2, _, _ = rows(aggregate([
        {"run": "a", "date": "2026-06-20", "category": "stub", "preventable": True,
         "remediation": "plan-anchor", "target": "no-todo"},
        {"run": "b", "date": "2026-06-21", "category": "stub", "preventable": True,
         "remediation": "plan-anchor", "target": "no-todo"},
    ])[0])
    assert {r["category"] for r in promote2} == {"stub"}, "x2 residual should promote"
    print("flywheel-aggregate selftest: ok")


def main():
    ap = argparse.ArgumentParser(description="Aggregate the develop flywheel SSOT.")
    ap.add_argument("path", nargs="?", default=".claude/develop-flywheel.jsonl")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--selftest", action="store_true", help="run the aggregation unit tests and exit")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return 0
    records, skipped = load(args.path)
    if records is None:
        print(f"no flywheel SSOT yet at {args.path} — runs append records as they finalize.")
        return 0
    cats, runkeys, dates = aggregate(records)
    promote, watch, floor_cats = rows(cats)
    floor_findings = sum(n for _, n in floor_cats)

    if args.json:
        json.dump({
            "records": len(records), "runs": len(runkeys), "skipped": skipped,
            "dateRange": [min(dates), max(dates)] if dates else None,
            "promotionReady": promote, "watch": watch,
            "irreducible": {"categories": len(floor_cats), "findings": floor_findings},
        }, sys.stdout, indent=2)
        print()
        return 0

    span = f" ({min(dates)}..{max(dates)})" if dates else ""
    extra = f" · {skipped} malformed skipped" if skipped else ""
    print(f"flywheel · {len(records)} records · {len(runkeys)} runs{span}{extra}\n")

    print("promotion-ready (preventable · ≥2 runs, breaking, or escaped to PR/CI) — "
          "escaped & cheapest lever first:")
    if promote:
        for r in promote:
            tags = []
            if r["escaped"]:
                tags.append(f"ESCAPED→{r['phase']}" if r["phase"] else "ESCAPED")
            if r["breaking"]:
                tags.append("breaking")
            tag = (" · " + " · ".join(tags)) if tags else ""
            print(f"  {r['category']}  ×{r['runs']} runs{tag}  → {r['remediation']}: {r['target']}")
    else:
        print("  (none)")

    if watch:
        print("\nwatch (preventable · seen once): " + ", ".join(r["category"] for r in watch))
    print(f"\nirreducible floor: {floor_findings} findings / {len(floor_cats)} categories "
          f"(expected — not promotion targets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
