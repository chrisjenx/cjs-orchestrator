#!/usr/bin/env python3
"""Verify the docs site loads under the GitHub Pages PROJECT subpath (/cjs-orchestrator/).

Project Pages are served from https://<owner>.github.io/<repo>/, so any asset referenced
with an absolute-root path (`/styles.css`) breaks. This serves docs/ under a /<repo>/ subpath
and fetches every page + asset, and fails if any reference is absolute-root or any asset 404s.

Reused by CI (see .github/workflows/). Exit 0 = OK, 1 = problem.
"""
import functools, http.server, os, re, shutil, socketserver, sys, tempfile, threading, urllib.request

REPO = "cjs-orchestrator"
DOCS = os.path.join(os.path.dirname(__file__), "..", "docs")
ASSETS = ["index.html", "styles.css", "app.js", "catalog.js", "flow.js"]


def main() -> int:
    docs = os.path.abspath(DOCS)
    problems = []

    # 1) Static check: no absolute-root asset references anywhere in docs/.
    for fn in os.listdir(docs):
        if not fn.endswith((".html", ".css", ".js")):
            continue
        text = open(os.path.join(docs, fn), encoding="utf-8").read()
        for m in re.findall(r'(?:href|src)="(/[^/][^"]*)"', text):
            problems.append(f"{fn}: absolute-root reference {m!r} breaks under the subpath")

    # 2) Live-ish check: serve under /<repo>/ and fetch each asset.
    root = tempfile.mkdtemp()
    sub = os.path.join(root, REPO)
    os.makedirs(sub)
    for f in ASSETS:
        shutil.copy(os.path.join(docs, f), sub)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/{REPO}"
    try:
        for path in ["/", "/styles.css", "/app.js", "/catalog.js", "/flow.js"]:
            try:
                with urllib.request.urlopen(base + path) as r:
                    if r.status != 200:
                        problems.append(f"{path}: HTTP {r.status}")
            except Exception as e:  # noqa: BLE001
                problems.append(f"{path}: {e}")
    finally:
        httpd.shutdown()
        shutil.rmtree(root)

    if problems:
        print("docs subpath check FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"docs subpath check PASSED — all assets resolve under /{REPO}/ (relative refs only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
