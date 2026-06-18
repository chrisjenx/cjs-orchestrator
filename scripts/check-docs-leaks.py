#!/usr/bin/env python3
"""Scan docs/ for private-data patterns that the explainer must never re-leak.

docs/ is genericized from a private case study (see /CLAUDE.md). This fails CI if a commit
reintroduces a commit SHA, an internal ticket/anchor id, a private W-code, or a brand /
framework / language / build-tool name that would reveal the private stack or domain. It is
the grep from CLAUDE.md, made deterministic: a small allowlist removes the unavoidable
technical false positives (charset `UTF-8`, hex colours) so a clean tree passes and a real
leak fails.

Usage: check-docs-leaks.py [--selftest]   (--selftest checks the brand matcher itself)
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

# Brand / framework / language / build-tool names that would reveal the private
# case study's real stack or domain. docs/ stays stack-neutral and brand-free
# (CLAUDE.md -> "Keep it generic"). The *allowed* platform references — Anthropic,
# Claude, Claude Code, MCP, GitHub, git — are deliberately NOT listed here. Matched
# CASE-SENSITIVELY in each name's canonical casing on word boundaries: brands are
# proper nouns, so the common lowercase look-alikes ("linear-gradient", "the notion",
# "in jest", "guardrails") don't false-positive, while a real "Linear"/"React"/"Gradle"
# still does (lowercase tool names like esbuild/pnpm/pytest keep their real casing).
# Add a term the moment a real leak gets through; this list is meant to grow.
BRAND_TERMS = [
    # products / SaaS
    "Linear", "Jira", "Asana", "Trello", "Notion", "Slack", "Figma", "Zeplin",
    "GitLab", "Bitbucket", "Vercel", "Netlify", "Heroku", "Datadog", "Sentry",
    "Stripe", "Twilio", "Auth0", "Okta", "Supabase", "Firebase", "Cloudflare",
    # cloud
    "AWS", "Azure", "GCP", "Google Cloud",
    # frameworks
    "React", "Vue", "Angular", "Svelte", "Next.js", "Nuxt", "Django", "Flask",
    "Rails", "Laravel", "Spring Boot", "Flutter", "SwiftUI", "Jetpack Compose",
    "FastAPI", "Symfony", "Ktor",
    # build / test tooling
    "Gradle", "Maven", "Webpack", "Vite", "Rollup", "esbuild", "Bazel",
    "pnpm", "pytest", "Jest", "Vitest", "Cypress", "Playwright", "RSpec",
    "JUnit", "Poetry",
    # languages
    "Kotlin", "TypeScript", "Golang", "Scala", "Clojure", "Elixir", "Haskell",
]
BRAND_RX = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in BRAND_TERMS) + r")\b")

# Brand-regex matches that are legitimate in context (keep tight; justify each).
BRAND_ALLOW = set()


def is_false_positive(kind: str, match: str, line: str, start: int) -> bool:
    if match in ALLOW_TOKENS:
        return True
    if kind == "brand-name":
        return match.lower() in {t.lower() for t in BRAND_ALLOW}
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
    scans = dict(PATTERNS)
    scans["brand-name"] = BRAND_RX
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
                for kind, rx in scans.items():
                    for m in rx.finditer(line):
                        if is_false_positive(kind, m.group(), line, m.start()):
                            continue
                        hits.append((rel, n, kind, m.group(), line.strip()[:120]))

    if hits:
        print("Possible private-data leak(s) in docs/ — review in context:")
        for rel, n, kind, tok, ctx in hits:
            print(f"  {rel}:{n}  [{kind}] {tok!r}  | {ctx}")
        return 1
    print("docs leak scan PASSED — no commit SHAs / ticket ids / W-codes / brand names in docs/")
    return 0


def selftest() -> int:
    """Guard the guard: the brand matcher must catch real leaks and ignore look-alikes."""
    must_hit = [
        "name: 'Linear MCP'", "built with React", "run ./gradlew (Gradle)", "tracked in Jira",
        "deployed to Vercel", "written in Kotlin", "a Next.js app", "a Spring Boot service",
        "uses TypeScript", "on AWS",
    ]
    must_miss = [  # ordinary English / allowed platform terms that brush past the terms
        "the rest is composition", "UI conventions + reactivity", "guardrails on every gate",
        "Anthropic's Building Effective Agents", "github.com/chrisjenx", "Claude Code", "an MCP server",
        "ready-with-escalations", "self-scaled to the change", "git worktree", "scope creep",
        "background: linear-gradient(110deg, var(--skill))",  # CSS, not the product
        "the notion that it helps", "non-linear growth", "said partly in jest",
    ]
    ok = True
    for s in must_hit:
        if not BRAND_RX.search(s):
            print(f"  SELFTEST FAIL: expected a brand hit in {s!r}"); ok = False
    for s in must_miss:
        m = BRAND_RX.search(s)
        if m:
            print(f"  SELFTEST FAIL: false positive {m.group()!r} in {s!r}"); ok = False
    print("brand-matcher selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(main())
