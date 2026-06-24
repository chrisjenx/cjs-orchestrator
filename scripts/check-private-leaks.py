#!/usr/bin/env python3
"""Fail CI if a private case-study identifier (product / org / package name) appears anywhere in
the repo OUTSIDE docs/ (docs/ has its own scanner, check-docs-leaks.py).

Why this exists: a stack fingerprint once reached plugins/ because check-docs-leaks.py scans only
docs/. This guards the *unambiguous* private identifiers repo-wide. It deliberately does NOT ban
generic stack names (Kotlin / Gradle / KMP / pnpm): those legitimately appear in the plugin's
stack-detection content, so banning them would false-positive constantly. Catching the product /
org / package names is the high-value, low-false-positive protection.

Leak-safe by construction: the denylist is stored as SHA-256 hashes, never plaintext, so this
committed public script does not itself re-leak the terms it protects, and a match is reported by
location only (never by printing the token). These are "keep out of the public repo" identifiers,
not cryptographic secrets; hashing keeps the plaintext from being committed/indexed, which is the
goal. Add a term with:
    python3 -c "import hashlib; print(hashlib.sha256(b'<term-lowercased>').hexdigest())"

Usage: check-private-leaks.py [--selftest]. Exit 0 = clean, 1 = suspected leak (scrub before commit).
"""
import hashlib, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SELF = os.path.abspath(__file__)

# SHA-256 of each lowercased private identifier (product, org, package descriptor). Plaintext
# intentionally absent — see module docstring.
HASHED_PRIVATE = {
    "d4df2ec253dc95b3455b77b158630202b15e5e509c6bd341592b3019c62fbf90",
    "b769a6983b42d565e79bb4f3f534623453f301d39784e57804a649a67ea05327",
    "a9f3e592f17218362a7f37543589d95156627dc447a14fcd20a9a46a474bbe3f",
}

SKIP_DIRS = {".git", "node_modules", "docs"}  # docs/ is covered by check-docs-leaks.py
TEXT_EXT = (".md", ".py", ".json", ".js", ".html", ".css", ".sh", ".yml", ".yaml",
            ".txt", ".kts", ".toml", ".cfg", ".ini")
TOKEN_RX = re.compile(r"[a-z0-9]{4,}")  # min length 4 trims noise; private terms are all longer


def hits_in(text):
    """Return the set of denylisted tokens present in text (by hash). Tokens are never logged."""
    found = set()
    for tok in TOKEN_RX.findall(text.lower()):
        if hashlib.sha256(tok.encode()).hexdigest() in HASHED_PRIVATE:
            found.add(tok)
    return found


def main() -> int:
    leaks = []
    for dp, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(TEXT_EXT):
                continue
            path = os.path.join(dp, fn)
            if os.path.abspath(path) == SELF:
                continue
            rel = os.path.relpath(path, ROOT)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for n, line in enumerate(f, 1):
                        if hits_in(line):
                            leaks.append((rel, n))
            except OSError:
                continue

    if leaks:
        print("Possible private case-study identifier(s) outside docs/ — scrub before commit:")
        for rel, n in leaks:
            print(f"  {rel}:{n}  [private-term hash match]")  # token withheld so the log can't re-leak it
        return 1
    print("private-leak scan PASSED — no case-study product/org/package identifiers outside docs/")
    return 0


def selftest() -> int:
    ok = True
    if not HASHED_PRIVATE:
        print("  SELFTEST FAIL: denylist is empty"); ok = False
    # The matcher must catch a hashed term (inject one at runtime) and ignore clean text.
    probe = "zzprivateprobe"
    HASHED_PRIVATE.add(hashlib.sha256(probe.encode()).hexdigest())
    try:
        if probe not in hits_in(f"value com.example.{probe} here"):
            print("  SELFTEST FAIL: matcher missed an injected hashed term"); ok = False
        if hits_in("ordinary words: orchestrator plugin gate token review worktree"):
            print("  SELFTEST FAIL: false positive on clean text"); ok = False
    finally:
        HASHED_PRIVATE.discard(hashlib.sha256(probe.encode()).hexdigest())
    # Belt-and-suspenders: this script must not carry any plaintext private term itself.
    if hits_in(open(SELF, encoding="utf-8").read()):
        print("  SELFTEST FAIL: this script contains a plaintext private term"); ok = False
    print("private-leak selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else main())
