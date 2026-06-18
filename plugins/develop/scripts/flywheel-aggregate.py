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
        "runs": set(), "breaking": False, "preventable": False,
        "levers": collections.Counter(), "targets": collections.Counter(),
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
        row = {"category": name, "runs": n, "breaking": c["breaking"],
               "remediation": lever, "target": target}
        (promote if (n >= 2 or c["breaking"]) else watch).append(row)
    promote.sort(key=lambda r: (LEVER_RANK.get(r["remediation"], 5), -r["runs"], r["category"]))
    watch.sort(key=lambda r: (-r["runs"], r["category"]))
    floor_cats.sort()
    return promote, watch, floor_cats


def main():
    ap = argparse.ArgumentParser(description="Aggregate the develop flywheel SSOT.")
    ap.add_argument("path", nargs="?", default=".claude/develop-flywheel.jsonl")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args()

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

    print("promotion-ready (preventable · ≥2 runs or breaking) — cheapest lever first:")
    if promote:
        for r in promote:
            brk = " · breaking" if r["breaking"] else ""
            print(f"  {r['category']}  ×{r['runs']} runs{brk}  → {r['remediation']}: {r['target']}")
    else:
        print("  (none)")

    if watch:
        print("\nwatch (preventable · seen once): " + ", ".join(r["category"] for r in watch))
    print(f"\nirreducible floor: {floor_findings} findings / {len(floor_cats)} categories "
          f"(expected — not promotion targets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
