#!/usr/bin/env python3
"""Scan docs/ for private-data patterns that the explainer must never re-leak.

docs/ is genericized from a private case study (see /CLAUDE.md). This fails CI if a commit
reintroduces a commit SHA, an internal ticket/anchor id, or a private W-code. It is the grep
from CLAUDE.md, made deterministic: a small allowlist removes the unavoidable technical
false positives (charset `UTF-8`, hex colours) so a clean tree passes and a real leak fails.

Exit 0 = clean, 1 = suspected leak(s) found (review in context).
"""
import os, re, sys

DOCS = os.path.join(os.path.dirname(__file__), "..", "docs")

PATTERNS = {
    "commit-sha": re.compile(r"\b[0-9a-f]{7,12}\b"),
    "ticket-id": re.compile(r"\b[A-Z]{2,4}-[0-9]+\b"),
    "w-code": re.compile(r"\bW[0-9]{2,3}\b"),
}

# Exact tokens that legitimately match a pattern but are not private data.
ALLOW_TOKENS = {"UTF-8"}


def is_false_positive(kind: str, match: str, line: str, start: int) -> bool:
    if match in ALLOW_TOKENS:
        return True
    if kind == "commit-sha":
        # hex colour: a 6/8-digit hex immediately preceded by '#'
        if start > 0 and line[start - 1] == "#":
            return True
        # part of a longer hex colour token like #aabbccdd
        if re.fullmatch(r"[0-9a-f]{6,8}", match) and "#" in line[max(0, start - 1):start + 1]:
            return True
    return False


def main() -> int:
    docs = os.path.abspath(DOCS)
    hits = []
    for dirpath, _dirs, files in os.walk(docs):
        for fn in files:
            if not fn.endswith((".html", ".css", ".js", ".md", ".svg")):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, os.path.dirname(docs))
            for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
                if "viewBox" in line or "stop-color" in line:
                    continue
                for kind, rx in PATTERNS.items():
                    for m in rx.finditer(line):
                        if is_false_positive(kind, m.group(), line, m.start()):
                            continue
                        hits.append((rel, n, kind, m.group(), line.strip()[:120]))

    if hits:
        print("Possible private-data leak(s) in docs/ — review in context:")
        for rel, n, kind, tok, ctx in hits:
            print(f"  {rel}:{n}  [{kind}] {tok!r}  | {ctx}")
        return 1
    print("docs leak scan PASSED — no commit SHAs / ticket ids / W-codes in docs/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
