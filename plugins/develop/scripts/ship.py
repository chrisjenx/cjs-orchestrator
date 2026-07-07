#!/usr/bin/env python3
"""ship.py — mechanical engine for /develop:ship (part of the develop plugin).
Stdlib + gh CLI only.

Wraps `gh` CLI + git for PR monitoring. Pure functions over inputs + a
per-PR JSON state file. Emits compact hints; never decides.

Watch contract: stdout is wake-only — a printed JSON line means the agent must
act; all waiting, throttling, and diagnostics go to stderr (silent to the
Monitor). Per-repo behaviour comes from the `ship` object in
`.claude/develop.config.json` (written by /develop:init), deep-merged over
built-in defaults.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_TRANSIENT = 1
EXIT_HALT = 2

# ---------------------------------------------------------------------------
# Constants — fixed cadences (config-driven caps/cadences live in _apply_config)
# ---------------------------------------------------------------------------

CADENCE_EMPTY_CHECK_RUNS = 60
CADENCE_WAIT_FIRST_REVIEW = 90
CADENCE_WAIT_REVIEW_SUBMIT = 90
CADENCE_WAIT_REAPPROVAL = 270
CADENCE_STICKY_STALE = 90
CADENCE_RATE_LIMIT = 900
CADENCE_IMMEDIATE = 0

# mergeStateStatus values that permit a merge (a red/behind/dirty PR is excluded
# elsewhere). Shared by _classify_hint's clean_exit branch and the hard _merge_gate.
MERGEABLE_STATES = ("CLEAN", "HAS_HOOKS", "UNSTABLE", "MERGEABLE")

# --- watch wake taxonomy ---------------------------------------------------
# WAKE: agent must reason → emit to stdout (a wake). WAIT: keep polling silently
# (stderr). AUTO hints (promote_draft, retrigger_review, behind_base, clean_exit)
# are handled specially in _watch_decide because whether they wake or self-act
# depends on the --merge flag and sub-state. See README.md "Wake taxonomy".
WAKE_HINTS: frozenset[str] = frozenset(
    {"ci_failed", "fetch_threads", "merge_conflict", "sticky_sha_stale"}
)
WAIT_HINTS: frozenset[str] = frozenset(
    {"wait_ci", "wait_first_review", "wait_reapproval", "wait_review_submit"}
)
# AUTO/terminal hints _classify_hint emits beyond WAKE/WAIT — the watcher acts on
# these itself (rebase/promote/retrigger/merge) or exits. ALL_HINTS is the full
# hint vocabulary, the single source tooling enumerates from.
AUTO_TERMINAL_HINTS: frozenset[str] = frozenset(
    {"behind_base", "clean_exit", "promote_draft", "held_draft", "retrigger_review", "halt"}
)
ALL_HINTS: frozenset[str] = WAKE_HINTS | WAIT_HINTS | AUTO_TERMINAL_HINTS
# Wall-clock cap (seconds) past which a stuck wait becomes a halt. The watcher
# owns these so the agent sees the halt decision, never the countdown. wait_ci is
# uncapped (CI legitimately runs long); empty-runs is capped via state counters.
WAIT_WALLCLOCK_CAP: dict[str, int | None] = {
    "wait_first_review": 1800,
    "wait_reapproval": 3600,
    "wait_review_submit": 3600,
    "wait_ci": None,
}

SHIP_FASTFAIL_CADENCE = 30
# Re-emit cadence for a still-live WAKE hint, so a single missed/dropped wake
# notification can't silently stall the watch. Two tiers, keyed on whether the
# agent has ACKed the wake (`ship ack <hint> <sha>`):
#   - UN-ACKED: agent hasn't signalled receipt -> re-emit aggressively on the
#     short cadence with an escalating `nudge` counter until it ACKs. A missed
#     wake recovers in minutes, not hours.
#   - ACKED: agent is handling it -> back off to the long safety cadence, a
#     dead-man's switch that re-nudges only if the agent dies mid-handler (which
#     also clears the now-stale ack, reverting to the aggressive tier).
# Re-nudges carry an incrementing `nudge` field so the agent never dedups them.

WORKFLOW_RUN_URL_RX = re.compile(r"/actions/runs/(\d+)")

# Marker ship stamps on every reply it posts so the skill's comment audit +
# dedupe can skip our own replies. The engine's merge-gate recognition uses the
# viewer login, not this marker (see _thread_replied_by).
SHIP_REPLY_MARKER = "<!-- develop:ship -->"

STATE_HEADER_PREFIX = "// "


# ---------------------------------------------------------------------------
# subprocess wrapper
# ---------------------------------------------------------------------------


def run(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, returning the completed process. Never raises by default."""
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )


def die(msg: str, code: int = EXIT_HALT) -> None:
    sys.stderr.write(msg.rstrip("\n") + "\n")
    sys.exit(code)


# ---------------------------------------------------------------------------
# Config — `ship` object in <repo>/.claude/develop.config.json
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    # Fallback only — resolution stack: SHIP_BASE_REF env → PR baseRefName →
    # config → origin/HEAD (see _base_ref / _fallback_base_branch).
    "baseBranch": "main",
    # Each: {checkNames: [], commentLogins: [], commentSignature: "",
    #        stickyBeacon: "", stickyMeta: false, retrigger: false}
    "reviewBots": [],
    "checkExclusions": [],
    "skipLogins": ["dependabot[bot]", "renovate[bot]"],
    # Order-preserving first-match rows: {regex, mechanism, hint}
    "flakePatterns": [
        {"regex": "OutOfMemoryError", "mechanism": "memory",
         "hint": "shrink fixture; per-test cleanup"},
        {"regex": "(?i)connect(ion)? (refused|reset)|sockettimeout",
         "mechanism": "network", "hint": "stub the network dependency"},
        {"regex": "(?i)timeout", "mechanism": "timing",
         "hint": "bump timeout 2x or inject a test double"},
    ],
    "failedTestRegex": "",
    "caps": {"ciFail": 3, "flakySoak": 3, "emptyRuns": 3, "retriggerReview": 2},
    "cadence": {"waitCi": 270, "fastFailWindow": 120, "landingBuffer": 90,
                "rewake": 600, "unackedRewake": 120},
    "rateFloor": {"core": 500, "graphql": 500},
    "durationsFile": ".claude/ship-ci-durations.json",
    "hotPaths": [],
    "ticketRoute": "gh-issue",
    "mergeMethod": "squash",
}

_CONFIG: dict[str, Any] | None = None
_CONFIG_SECTION_FOUND = False


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge; lists/scalars in `override` replace wholesale."""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _repo_root() -> Path | None:
    """Main-worktree repo root (parent of the common git dir), or None."""
    proc = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).parent


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(v) if v else default
    except ValueError:
        return default


def _apply_config(cfg: dict[str, Any]) -> None:
    """Initialize module constants + compiled tables from a merged config.
    SHIP_* env vars override the values ship already read from env."""
    global CI_FAIL_CAP, FLAKY_SOAK_CAP, EMPTY_RUNS_MERGEABLE_CAP, RETRIGGER_REVIEW_CAP
    global CADENCE_WAIT_CI, SHIP_FASTFAIL_WINDOW, SHIP_LANDING_BUFFER
    global SHIP_REWAKE_SECONDS, SHIP_UNACKED_REWAKE_SECONDS
    global RATE_FLOOR_CORE, RATE_FLOOR_GRAPHQL
    global REVIEW_BOTS, REVIEW_CHECK_NAMES, GATE_EXCLUDED_CHECK_NAMES, SKIP_LOGINS
    global HOT_PATHS_RX, FLAKE_MECHANISMS, FAILED_FQN_RX, CI_DURATIONS_FILE, MERGE_METHOD
    caps = cfg.get("caps") or {}
    CI_FAIL_CAP = int(caps.get("ciFail", 3))
    FLAKY_SOAK_CAP = int(caps.get("flakySoak", 3))
    EMPTY_RUNS_MERGEABLE_CAP = int(caps.get("emptyRuns", 3))
    RETRIGGER_REVIEW_CAP = int(caps.get("retriggerReview", 2))
    cad = cfg.get("cadence") or {}
    CADENCE_WAIT_CI = int(cad.get("waitCi", 270))
    SHIP_FASTFAIL_WINDOW = _env_int("SHIP_FASTFAIL_WINDOW", int(cad.get("fastFailWindow", 120)))
    SHIP_LANDING_BUFFER = _env_int("SHIP_LANDING_BUFFER", int(cad.get("landingBuffer", 90)))
    SHIP_REWAKE_SECONDS = _env_int("SHIP_REWAKE_SECONDS", int(cad.get("rewake", 600)))
    SHIP_UNACKED_REWAKE_SECONDS = _env_int(
        "SHIP_UNACKED_REWAKE_SECONDS", int(cad.get("unackedRewake", 120)))
    floor = cfg.get("rateFloor") or {}
    # Rate-limit headroom kept in reserve for the working agents' GH actions;
    # the watcher yields below the floor.
    RATE_FLOOR_CORE = _env_int("SHIP_RATE_FLOOR_CORE", int(floor.get("core", 500)))
    RATE_FLOOR_GRAPHQL = _env_int("SHIP_RATE_FLOOR_GRAPHQL", int(floor.get("graphql", 500)))
    REVIEW_BOTS = [b for b in (cfg.get("reviewBots") or []) if isinstance(b, dict)]
    REVIEW_CHECK_NAMES = frozenset(
        n for b in REVIEW_BOTS for n in (b.get("checkNames") or []) if n
    )
    # Checks excluded from the green gate AND fixable-failure surfacing:
    # configured exclusions + every review bot's check-runs (review signal,
    # not blocking checks). Shared by classify_check_runs + cmd_failures.
    GATE_EXCLUDED_CHECK_NAMES = frozenset(cfg.get("checkExclusions") or []) | REVIEW_CHECK_NAMES
    SKIP_LOGINS = frozenset(cfg.get("skipLogins") or [])
    HOT_PATHS_RX = tuple(re.compile(p) for p in (cfg.get("hotPaths") or []))
    FLAKE_MECHANISMS = tuple(
        (row["mechanism"], re.compile(row["regex"]), row.get("hint", ""))
        for row in (cfg.get("flakePatterns") or [])
        if isinstance(row, dict) and row.get("regex") and row.get("mechanism")
    )
    rx = (cfg.get("failedTestRegex") or "").strip()
    FAILED_FQN_RX = re.compile(rx) if rx else None
    CI_DURATIONS_FILE = cfg.get("durationsFile") or DEFAULTS["durationsFile"]
    m = cfg.get("mergeMethod")
    MERGE_METHOD = m if m in ("merge", "squash", "rebase") else "squash"


def _config() -> dict[str, Any]:
    """Merged config (defaults ← repo `ship` section), loaded lazily + cached.
    Also refreshes the module constants via _apply_config."""
    global _CONFIG, _CONFIG_SECTION_FOUND
    if _CONFIG is not None:
        return _CONFIG
    merged: dict[str, Any] = json.loads(json.dumps(DEFAULTS))  # deep copy
    section: dict[str, Any] | None = None
    root = _repo_root()
    if root is not None:
        path = root / ".claude" / "develop.config.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                s = data.get("ship") if isinstance(data, dict) else None
                section = s if isinstance(s, dict) else None
            except (OSError, json.JSONDecodeError):
                section = None
    if section is None:
        sys.stderr.write("ship: no ship config found; using defaults (run /develop:init)\n")
    else:
        merged = _deep_merge(merged, section)
        _CONFIG_SECTION_FOUND = True
    _CONFIG = merged
    _apply_config(merged)
    return _CONFIG


# Import-time init from built-in defaults so every constant exists before the
# first _config() load (which re-applies with the repo's merged values).
_apply_config(json.loads(json.dumps(DEFAULTS)))


# ---------------------------------------------------------------------------
# gh CLI helpers
# ---------------------------------------------------------------------------


def _die_if_rate_limited(proc: Any) -> None:
    """If a gh subprocess failed due to rate-limiting, raise the TRANSIENT exit so
    the watch loop backs off, instead of silently treating the result as empty."""
    stderr = (proc.stderr or "").lower()
    if "rate limit" in stderr or "api rate limit exceeded" in stderr:
        die("rate_limit_backoff", EXIT_TRANSIENT)


def gh_json(args: list[str]) -> Any:
    """Run `gh <args>` and parse stdout as JSON. Handles auth / rate-limit."""
    proc = run(["gh", *args])
    if proc.returncode != 0:
        stderr = (proc.stderr or "").lower()
        if "authentication required" in stderr or "gh auth login" in stderr:
            die("gh auth failure — run `gh auth login`", EXIT_HALT)
        if "rate limit" in stderr or "api rate limit exceeded" in stderr:
            die("rate_limit_backoff", EXIT_TRANSIENT)
        die(f"gh failed: {proc.stderr.strip() or proc.stdout.strip()}", EXIT_HALT)
    if not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        die(f"gh returned non-JSON: {e}", EXIT_HALT)


# Process-lifetime memo: the repo slug (OWNER/REPO) never changes mid-run, but
# gh_repo_slug is called 3-4x per cmd_status poll. Resolve once, reuse.
_SLUG_CACHE: str | None = None


def gh_repo_slug() -> str:
    """Return `OWNER/REPO` for the current repo (memoized per process)."""
    global _SLUG_CACHE
    if _SLUG_CACHE is not None:
        return _SLUG_CACHE
    proc = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    if proc.returncode != 0:
        die(f"could not resolve repo slug: {proc.stderr.strip()}", EXIT_HALT)
    _SLUG_CACHE = proc.stdout.strip()
    return _SLUG_CACHE


def pr_web_url(pr_number: int | str) -> str:
    """Canonical github.com PR URL, or '' if the slug can't resolve. Reuses the
    memoized slug (warm by the time the cap-halt gate fires after several polls);
    unlike gh_repo_slug() it degrades to '' instead of die()ing, for best-effort
    surfacing on a gate that can run before a poll has supplied the live pr_url."""
    slug = _SLUG_CACHE
    if not slug:
        proc = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
        slug = proc.stdout.strip() if proc.returncode == 0 else ""
    return f"https://github.com/{slug}/pull/{pr_number}" if slug else ""


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------


def git_dir() -> Path:
    proc = run(["git", "rev-parse", "--git-dir"])
    if proc.returncode != 0:
        die("not a git repo", EXIT_HALT)
    return Path(proc.stdout.strip()).resolve()


def current_branch() -> str:
    proc = run(["git", "branch", "--show-current"])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def current_sha() -> str:
    proc = run(["git", "rev-parse", "HEAD"])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def merge_base_sha() -> str:
    """Stable base across rebases — the commit the branch forked from."""
    proc = run(["git", "merge-base", "HEAD", _base_ref()])
    return proc.stdout.strip() if proc.returncode == 0 else ""



# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------


def state_path(pr_number: int | str) -> Path:
    return git_dir() / f"ship-state-{pr_number}.json"


def _build_header(branch: str, base_sha: str) -> str:
    return f"{STATE_HEADER_PREFIX}branch={branch} base_sha={base_sha}"


def _parse_header(line: str) -> dict[str, str]:
    if not line.startswith(STATE_HEADER_PREFIX):
        return {}
    body = line[len(STATE_HEADER_PREFIX) :].strip()
    parts: dict[str, str] = {}
    for token in body.split():
        if "=" in token:
            k, _, v = token.partition("=")
            parts[k] = v
    return parts


def load_state(pr_number: int | str) -> tuple[dict[str, str], dict[str, Any]]:
    """Return (header, body) — empty dicts when the file is missing/corrupt."""
    path = state_path(pr_number)
    if not path.exists():
        return {}, {}
    try:
        text = path.read_text()
    except OSError:
        return {}, {}
    lines = text.split("\n", 1)
    if not lines:
        return {}, {}
    header = _parse_header(lines[0])
    body_text = lines[1] if len(lines) > 1 else "{}"
    try:
        body = json.loads(body_text) if body_text.strip() else {}
    except json.JSONDecodeError:
        body = {}
    return header, body


def write_state_atomic(pr_number: int | str, header: dict[str, str], body: dict[str, Any]) -> None:
    """Atomic write: tmp sibling + fsync + os.replace."""
    path = state_path(pr_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    header_line = _build_header(
        header.get("branch", ""),
        header.get("base_sha", ""),
    )
    payload = header_line + "\n" + json.dumps(body, indent=2, sort_keys=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _lock_path(pr_number: int | str) -> Path:
    return state_path(pr_number).with_suffix(".lock")


class _StateLock:
    """Advisory exclusive lock over a PR's state file, held across the
    read-modify-write critical section so concurrent processes (the watch
    loop's cmd_status persist vs. a `ship state inc/set/reset`) cannot
    lost-update each other. POSIX fcntl.flock — macOS/Linux only.

    Reentrant within a process: init_state_if_needed may write a branch-reset
    and is called both from already-locked writers and from unlocked readers, so
    nested acquisition of the same PR's lock must not deadlock. A per-path
    refcount reuses the held fd; only the outermost exit unlocks."""

    _held: dict[str, list[Any]] = {}  # key -> [file handle, depth]

    def __init__(self, pr_number: int | str) -> None:
        self._key = str(_lock_path(pr_number))

    def __enter__(self) -> "_StateLock":
        entry = _StateLock._held.get(self._key)
        if entry is not None:
            entry[1] += 1
            return self
        path = Path(self._key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._key, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        _StateLock._held[self._key] = [fh, 1]
        return self

    def __exit__(self, *exc: Any) -> None:
        entry = _StateLock._held.get(self._key)
        if entry is None:
            return
        entry[1] -= 1
        if entry[1] <= 0:
            fh = entry[0]
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()
                del _StateLock._held[self._key]


# Fields cmd_status owns and may overwrite on persist. Everything else in the
# body (notably ci_fail_count / flaky_soak_round, bumped by `state inc` in a
# separate process) is merged from the latest on-disk copy under lock so a
# concurrent increment is never clobbered.
_STATUS_OWNED_FIELDS = (
    "last_review_fetch", "empty_runs_mergeable_count", "ci_durations_sha",
)


def persist_status_fields(
    pr_number: int | str,
    header: dict[str, str],
    owned: dict[str, Any],
) -> None:
    """Merge cmd_status-owned fields onto the freshest on-disk body and write
    atomically, under the per-PR advisory lock. Re-reads inside the lock so a
    `state inc` that landed since cmd_status loaded its snapshot is preserved."""
    with _StateLock(pr_number):
        _, latest = load_state(pr_number)
        if not latest:
            latest = default_state_body()
        for key in _STATUS_OWNED_FIELDS:
            if key in owned:
                latest[key] = owned[key]
        write_state_atomic(pr_number, header, latest)


def init_state_if_needed(pr_number: int | str) -> tuple[dict[str, str], dict[str, Any]]:
    """Load state; reset on branch mismatch.

    Reset triggers only on branch change. The plan considered also detecting
    "external code changes since last ship run" but the implementation drifted
    on every loop-internal commit (skill commits look identical to user
    commits from the script's POV), wiping counters mid-flight. v1 ships with
    branch-only reset; external-change detection is deferred to v1.1 if
    needed.

    `base_sha` is the merge-base with the base ref — stable across rebases.
    """
    branch = current_branch()
    base = merge_base_sha()

    header, body = load_state(pr_number)
    desired = {"branch": branch, "base_sha": base}

    needs_reset = not header or header.get("branch") != branch
    if needs_reset:
        body = default_state_body()
        header = desired
        with _StateLock(pr_number):  # reentrant: safe whether or not the caller holds it
            write_state_atomic(pr_number, header, body)
    else:
        # Refresh base_sha on each load — branch unchanged but base may have advanced via rebase.
        header["base_sha"] = base
    return header, body


def default_state_body() -> dict[str, Any]:
    return {
        "pr_number": None,
        "rebase_count": 0,
        "ci_fail_count": {},
        "flaky_soak_round": {},
        "did_rebase": False,
        "force_rebase": False,
        "merge_flag": False,
        "draft_flag": False,
        "paused": False,
        "empty_runs_mergeable_count": 0,
        "retrigger_review_count": 0,
        "ci_durations_sha": None,
        "wait_first_entry": {},
        "last_review_fetch": {
            "sha": None,
            "bot_completed_at": None,
            "sticky_found": False,
            "sticky_sha": None,
            "sticky_status": None,
            "sticky_retrigger": False,
        },
    }


# ---------------------------------------------------------------------------
# PR lookup
# ---------------------------------------------------------------------------


def lookup_pr_number() -> int | None:
    """Resolve PR number for the current branch, or None if no PR exists."""
    proc = run(["gh", "pr", "view", "--json", "number", "-q", ".number"])
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def gh_pr_view_full() -> dict[str, Any] | None:
    """Single `gh pr view` call returning all fields ship status consumes.

    Returns None when no PR exists for the current branch (skill handles).
    `reviewThreads` is not available via `gh pr view` — it's a GraphQL-only
    field. Callers fetch unaddressed-thread count via `gh_unaddressed_thread_count`
    separately and merge the result.
    """
    fields = (
        "number,headRefOid,isDraft,mergeStateStatus,mergeable,reviewDecision,"
        "reviewRequests,headRefName,url"
    )
    proc = run(["gh", "pr", "view", "--json", fields])
    if proc.returncode != 0:
        stderr = (proc.stderr or "").lower()
        if "no pull requests found" in stderr or "no pull request found" in stderr:
            return None
        if "authentication required" in stderr:
            die("gh auth failure — run `gh auth login`", EXIT_HALT)
        if "rate limit" in stderr:
            die("rate_limit_backoff", EXIT_TRANSIENT)
        die(f"gh pr view failed: {proc.stderr.strip()}", EXIT_HALT)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        die(f"gh pr view returned non-JSON: {e}", EXIT_HALT)


# GraphQL selection set for the per-thread fields the resolved/replied +
# author-kind accounting needs. `body` is load-bearing: `_thread_addressed` ->
# `thread_author_kind` matches the opening comment against each bot's
# commentSignature, so dropping it would misclassify a login-matched bot thread
# as `human` and let a resolved-no-reply bot thread read as addressed.
# `comments(first: 50)` is NOT paginated — a single thread never nears 50.
_THREAD_STATE_NODE_SELECTION = (
    "isResolved isOutdated "
    "comments(first: 50) { nodes { author { login } body } }"
)

# Full per-thread selection for the actionable `cmd_threads` rows.
_THREADS_NODE_SELECTION = """
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 50) {
            totalCount
            nodes {
              id
              databaseId
              author { login }
              body
              replyTo { id }
            }
          }
"""


class ReviewThreadFetchError(Exception):
    """Raised by `fetch_all_review_threads` on a gh non-zero exit or non-JSON
    response. Callers choose the fallback: fail-soft (return a zero count so a
    transient error can't wedge the watch loop) or hard (`die`, for the
    interactive `ship threads` path). The rate-floor guard fires first: a
    rate-limited exit raises the TRANSIENT exit via `_die_if_rate_limited`
    before this is raised."""


def fetch_all_review_threads(
    pr_number: int,
    node_selection: str,
    *,
    extra_pr_fields: str = "",
    runner: Callable[[list[str]], Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch EVERY review thread on a PR, walking GraphQL cursor pagination.

    GitHub caps `reviewThreads(first: N)` at 100 nodes per page. A query that
    stops at the first 100 silently drops every thread past it — and on a busy
    PR that tail is exactly where the newest review-bot findings land. This
    helper loops on `pageInfo { hasNextPage endCursor }`, accumulating `nodes`
    across all pages.

    `node_selection` is the GraphQL selection placed inside each thread's
    `nodes { ... }`. `extra_pr_fields` are sibling fields on the `pullRequest`
    node (e.g. `reviews(first: 100) { nodes { state } }`) read from the FIRST
    page only; callers pull them from the returned first-page `data`.
    `comments(first: 50)` inside `node_selection` is NOT paginated.

    `runner` overrides the module `run` (test seam for the pagination selftest).
    Preserves the rate-floor guard: a rate-limited gh exit raises the TRANSIENT
    exit via `_die_if_rate_limited` before `ReviewThreadFetchError`.

    Returns `(first_page_data, all_thread_nodes)`.
    """
    _run = runner or run
    slug = gh_repo_slug()
    owner, repo = slug.split("/", 1)
    query = (
        "query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {"
        "  viewer { login }"
        "  repository(owner: $owner, name: $repo) {"
        "    pullRequest(number: $pr) {"
        f"      {extra_pr_fields}"
        "      reviewThreads(first: 100, after: $cursor) {"
        "        pageInfo { hasNextPage endCursor }"
        f"        nodes {{ {node_selection} }}"
        "      }"
        "    }"
        "  }"
        "}"
    )
    cursor: str | None = None
    first_data: dict[str, Any] | None = None
    nodes: list[dict[str, Any]] = []
    while True:
        cmd = [
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-f", f"owner={owner}",
            "-f", f"repo={repo}",
            "-F", f"pr={pr_number}",
        ]
        if cursor is not None:
            cmd += ["-f", f"cursor={cursor}"]
        proc = _run(cmd)
        if proc.returncode != 0:
            _die_if_rate_limited(proc)
            raise ReviewThreadFetchError(f"gh graphql failed: {(proc.stderr or '').strip()}")
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise ReviewThreadFetchError(f"non-JSON graphql response: {e}")
        data = payload.get("data") or {}
        if first_data is None:
            first_data = data
        review_threads = (
            ((data.get("repository") or {}).get("pullRequest") or {}).get("reviewThreads")
            or {}
        )
        nodes.extend(review_threads.get("nodes") or [])
        page_info = review_threads.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    return first_data or {}, nodes


def gh_unaddressed_thread_count(pr_number: int) -> int:
    """Count unaddressed review threads for the PR, walking every thread page.

    Addressed splits by author_kind via `_thread_addressed`: a review_bot thread
    is addressed only when isResolved AND the viewer authored a reply (the agent
    replies then resolves); a human/other_bot thread is addressed when isResolved
    alone, because the bot-only-reply policy forbids the agent from ever replying
    to those — requiring a viewer reply would wedge a human thread unaddressed
    forever and block clean_exit even after the human resolves it on GitHub.

    An UNRESOLVED thread of any kind is still unaddressed, so the watcher
    re-enters `fetch_threads` (deduped by (hint, sha)) instead of merging over an
    open comment. A resolved-without-reply review_bot thread stays unaddressed —
    the reply/resolve mutation never landed. All pages are walked (see
    `fetch_all_review_threads`) so a >100-thread PR is not under-counted.
    """
    try:
        data, nodes = fetch_all_review_threads(pr_number, _THREAD_STATE_NODE_SELECTION)
    except ReviewThreadFetchError:
        return 0
    viewer = (data.get("viewer") or {}).get("login")
    return sum(1 for n in nodes if not _thread_addressed(n, viewer))


def _thread_replied_by(thread: dict[str, Any], viewer_login: str | None) -> bool:
    """True iff the ship viewer authored a comment on the thread.

    Used by `gh_unaddressed_thread_count` and `cmd_threads --unresolved` to treat a
    thread as "addressed" only when ship actually replied, not just when the GitHub
    resolved bit is flipped. Recognition is by the viewer login: ship posts with the
    same token it reads with, so its comments carry that login. The reply marker is
    deliberately NOT trusted here — it is plain text any commenter can quote (and GitHub
    nulls deleted-account authors), so honoring it on the merge gate would let a quoted
    marker spoof a thread as answered. A review_bot opener can never match the viewer
    login, so all comments are scanned — a thread the viewer both opened and resolved
    still counts as replied.
    """
    if not viewer_login:
        return False
    comments = (thread.get("comments") or {}).get("nodes") or []
    return any(
        ((c.get("author") or {}).get("login")) == viewer_login for c in comments
    )


def _thread_addressed(thread: dict[str, Any], viewer_login: str | None) -> bool:
    """True iff a review thread no longer needs ship action.

    The 'addressed' bar splits by author_kind because the bot-only-reply policy
    forbids the agent from EVER replying to non-review_bot threads:

    - review_bot: addressed only when isResolved AND the viewer authored a reply
      (agent replies, then resolves). A resolved-without-reply bot thread means
      the reply/resolve mutation never landed, so it stays unaddressed.
    - human / other_bot: addressed when isResolved alone. The agent never
      replies to these, so requiring a viewer reply would wedge the thread
      unaddressed forever (it never gets one) — blocking clean_exit even after
      the human resolves their own thread on GitHub. An UNRESOLVED human thread
      is still unaddressed (don't merge over an open human comment).
    """
    if not thread.get("isResolved"):
        return False
    if thread_author_kind(thread) == "review_bot":
        return _thread_replied_by(thread, viewer_login)
    return True


def gh_pending_review_count(pr_number: int) -> int:
    """Count PENDING (started-but-unsubmitted) reviews on the PR.

    A pending review's inline threads already exist but GitHub scopes them to
    the review author's token. ship shares that token, so without this gate
    `ship status` / `ship threads` would see a half-written review (e.g. 4 of 6
    comments) and act before the human submits. Detection is symmetric: the
    same visibility that leaks the partial threads exposes the PENDING review,
    so wait for submit (threads re-surface as fetch_threads). 0 false positives
    when ship's token != reviewer's.

    Returns 0 on gh/JSON error (like gh_unaddressed_thread_count) so a transient
    failure can't wedge the loop into permanent waiting.
    """
    slug = gh_repo_slug()
    owner, repo = slug.split("/", 1)
    query = (
        "query($owner: String!, $repo: String!, $pr: Int!) {"
        "  repository(owner: $owner, name: $repo) {"
        "    pullRequest(number: $pr) {"
        "      reviews(first: 100) { nodes { state } }"
        "    }"
        "  }"
        "}"
    )
    proc = run(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={repo}",
            "-F",
            f"pr={pr_number}",
        ]
    )
    if proc.returncode != 0:
        _die_if_rate_limited(proc)
        return 0
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return 0
    nodes = (
        payload.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviews", {})
        .get("nodes", [])
    )
    return sum(1 for n in nodes if n.get("state") == "PENDING")


def gh_review_state(pr_number: int) -> dict[str, int]:
    """Unaddressed-thread count + pending-review count in ONE paginated fetch.

    Replaces the two-call (gh_unaddressed_thread_count + gh_pending_review_count)
    path inside cmd_status: both connections hang off the same pullRequest node,
    so a single query (walking every thread page) carries both. Unaddressed
    splits by author_kind via `_thread_addressed` (review_bot needs
    isResolved+viewer-reply; human/other_bot need isResolved alone). The
    review-thread connection is fully paginated (see `fetch_all_review_threads`)
    so a >100-thread PR is not under-counted; the `reviews` sibling is read from
    page one. pending = reviews in PENDING state. Returns zeros on gh/JSON error
    so a transient failure can't wedge the loop.
    """
    try:
        data, threads = fetch_all_review_threads(
            pr_number,
            _THREAD_STATE_NODE_SELECTION,
            extra_pr_fields="reviews(first: 100) { nodes { state } }",
        )
    except ReviewThreadFetchError:
        return {"unaddressed_threads": 0, "pending_reviews": 0}
    viewer = (data.get("viewer") or {}).get("login")
    pr = (data.get("repository") or {}).get("pullRequest") or {}
    reviews = (pr.get("reviews") or {}).get("nodes") or []
    unaddressed = sum(1 for t in threads if not _thread_addressed(t, viewer))
    pending = sum(1 for r in reviews if r.get("state") == "PENDING")
    return {"unaddressed_threads": unaddressed, "pending_reviews": pending}


def rate_limit_remaining() -> dict[str, Any]:
    """Remaining REST + GraphQL budget via `gh api rate_limit` (a FREE call —
    /rate_limit does not consume quota). Fail-open on error: unknown budget must
    not wedge the watcher into permanent backoff.
    """
    proc = run(["gh", "api", "rate_limit"])
    if proc.returncode != 0:
        return {"core": None, "graphql": None, "reset_in": 0}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"core": None, "graphql": None, "reset_in": 0}
    res = data.get("resources") or {}
    core = res.get("core") or {}
    graphql = res.get("graphql") or {}
    now = int(time.time())
    resets = [r.get("reset") for r in (core, graphql) if isinstance(r.get("reset"), int)]
    reset_in = max(0, (max(resets) - now)) if resets else 0
    return {
        "core": core.get("remaining"),
        "graphql": graphql.get("remaining"),
        "reset_in": reset_in,
    }


def _rate_floor_ok(remaining: dict[str, Any], *, core_floor: int, graphql_floor: int) -> bool:
    """True when both buckets are above their reserve floor. A None (unknown)
    bucket fails OPEN — never block the watcher on a probe failure."""
    core = remaining.get("core")
    graphql = remaining.get("graphql")
    if core is not None and core < core_floor:
        return False
    if graphql is not None and graphql < graphql_floor:
        return False
    return True


# ---------------------------------------------------------------------------
# fetch-sticky-summary
# ---------------------------------------------------------------------------


def _no_sticky() -> dict[str, Any]:
    return {
        "sticky_found": False,
        "sha": None,
        "run": None,
        "status": None,
        "findings_count": 0,
        "sha_matches_current": False,
        "findings": [],
    }


def _parse_sticky_meta(body: str, beacon: str) -> dict[str, Any] | None:
    """Extract the JSON object embedded right after `beacon` in `body`, or None.

    Balanced-object parse via `json.JSONDecoder().raw_decode` (not a `{.*?}`
    regex), so a nested `findings: [{...}]` payload is parsed whole rather than
    truncated at the first inner `}`. Returns the decoded dict, or None when the
    beacon carries no trailing JSON / the JSON is malformed."""
    idx = body.find(beacon)
    if idx < 0:
        return None
    brace = body.find("{", idx + len(beacon))
    if brace < 0:
        return None
    try:
        meta, _ = json.JSONDecoder().raw_decode(body[brace:])
    except json.JSONDecodeError:
        return None
    return meta if isinstance(meta, dict) else None


def cmd_fetch_sticky_summary(pr_number: int) -> dict[str, Any]:
    """Locate a configured review bot's sticky comment; parse its meta when asked.

    Beacons come from reviewBots[].stickyBeacon; the first bot (config order)
    whose beacon matches a comment wins. Two modes, per that bot's `stickyMeta`
    flag (default false):

      - stickyMeta false → plain beacon: report found/not-found only. sha/status
        are None; review currency is gated in _classify_hint on the bot's
        check-run being present + completed on the current head, not the body.
      - stickyMeta true → the bot embeds a JSON object `{sha, status, findings,
        …}` after its beacon. Parse it and expose {found, sha, status,
        findings}. `status` uses the neutral engine vocabulary APPROVED /
        BLOCKING / HUMAN_REVIEW_REQUIRED / SKIPPED. The matched bot's `retrigger`
        flag rides along (internal) so _classify_hint can gate retrigger_review.

    Empty reviewBots (or no beacons) ⇒ {found: false} with zero network —
    sticky-based hints degrade away and merge gating skips the sticky entirely.
    """
    bots = [
        b for b in REVIEW_BOTS if (b.get("stickyBeacon") or "").strip()
    ]
    if not bots:
        return _no_sticky()
    slug = gh_repo_slug()
    comments: list[Any] = []
    page = 1
    while True:
        chunk = gh_json(
            ["api", f"repos/{slug}/issues/{pr_number}/comments?per_page=100&page={page}"]
        ) or []
        comments.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1

    out = _sticky_summary(comments, bots)
    if out.get("sha"):
        out["sha_matches_current"] = out["sha"] == current_sha()
    return out


def _sticky_summary(comments: list[Any], bots: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure sticky classification from already-fetched comments (no network).

    First bot (config order) whose beacon appears in a comment wins. Plain mode
    (stickyMeta false) → found/not-found only. Meta mode (stickyMeta true) →
    parse the JSON after the beacon and expose sha/status/findings. `retrigger`
    (the matched bot's flag) rides along for _classify_hint. `sha_matches_current`
    is left False here — the network caller (cmd_fetch_sticky_summary) fills it."""
    for bot in bots:
        beacon = (bot.get("stickyBeacon") or "").strip()
        if not beacon:
            continue
        # Most recent matching comment wins (multiple stickies → last in list).
        sticky_body: str | None = None
        for c in comments:
            if beacon in (c.get("body") or ""):
                sticky_body = c.get("body") or ""
        if sticky_body is None:
            continue  # this bot's sticky not present — try the next configured bot
        out = _no_sticky()
        out["sticky_found"] = True
        out["retrigger"] = bool(bot.get("retrigger"))
        if not bot.get("stickyMeta"):
            return out  # plain beacon mode: found/not-found only
        meta = _parse_sticky_meta(sticky_body, beacon)
        if not meta:
            return out  # beacon present but no/invalid JSON — found, no meta
        findings = meta.get("findings") or []
        findings = findings if isinstance(findings, list) else []
        out["sha"] = meta.get("sha")
        out["run"] = meta.get("run")
        out["status"] = meta.get("status")
        out["findings"] = findings
        out["findings_count"] = len(findings)
        return out
    return _no_sticky()


# ---------------------------------------------------------------------------
# check-runs classification
# ---------------------------------------------------------------------------


def classify_check_runs(check_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Dedupe by name keeping latest attempt; return counts + lists per state.

    The green gate excludes the configured checkExclusions plus every review
    bot's check-runs (review signal, not blocking checks; see
    GATE_EXCLUDED_CHECK_NAMES). Every other check must be
    SUCCESS/SKIPPED/NEUTRAL or the PR gates. Unknown conclusions gate
    conservatively as failure. SKIPPED and NEUTRAL count green.
    """
    def _key(r: dict[str, Any]) -> tuple[str, str, int]:
        return (r.get("started_at") or "", r.get("completed_at") or "", int(r.get("id") or 0))

    latest_by_name: dict[str, dict[str, Any]] = {}
    for r in check_runs:
        name = r.get("name") or ""
        prev = latest_by_name.get(name)
        if prev is None or _key(r) > _key(prev):
            latest_by_name[name] = r
    runs = list(latest_by_name.values())
    total = len(runs)
    by_status: dict[str, list[dict[str, Any]]] = {
        "queued": [], "in_progress": [], "success": [],
        "skipped": [], "neutral": [], "failure": [],
    }
    for r in runs:
        status = r.get("status")
        conclusion = r.get("conclusion")
        if status in ("queued", "in_progress"):
            by_status[status].append(r)
            continue
        if conclusion == "success":
            by_status["success"].append(r)
        elif conclusion == "skipped":
            by_status["skipped"].append(r)
        elif conclusion == "neutral":
            by_status["neutral"].append(r)
        elif conclusion in ("failure", "timed_out", "cancelled", "action_required"):
            by_status["failure"].append(r)
        else:
            by_status["failure"].append(r)  # Unknown conclusion gates conservatively

    gating_runs = [r for r in runs if r.get("name") not in GATE_EXCLUDED_CHECK_NAMES]

    gating_any_failure = False
    gating_any_pending = False
    for r in gating_runs:
        status = r.get("status")
        conclusion = r.get("conclusion")
        # Any non-terminal status (queued/in_progress/waiting/requested/pending
        # — deployment-protection / concurrency gated) is PENDING, not failure.
        # Only a completed run with a non-passing (or unknown) conclusion fails.
        if status != "completed":
            gating_any_pending = True
        elif conclusion not in ("success", "skipped", "neutral"):
            gating_any_failure = True

    all_done_ok = len(gating_runs) > 0 and not gating_any_pending and not gating_any_failure

    # Review-bot currency: the check-runs endpoint is queried for the CURRENT
    # head, so any review-bot run in `runs` IS the run for the current commit
    # (a run from a prior commit lives under that commit's URL and is never
    # fetched). Presence + completed-status — NOT a head_sha comparison — is the
    # signal that the bot has re-reviewed the current head. Excluded from the CI
    # gating tally (it is a review signal, not CI); this is a separate gate.
    # Empty reviewBots ⇒ review_present/review_completed stay False and
    # _classify_hint skips this gate entirely.
    review_runs = [r for r in runs if (r.get("name") or "") in REVIEW_CHECK_NAMES]
    review_present = len(review_runs) > 0
    review_completed = review_present and all(
        r.get("status") == "completed" for r in review_runs
    )
    return {
        "total": total,
        "gating_total": len(gating_runs),
        "by_status": by_status,
        "review_present": review_present,
        "review_completed": review_completed,
        "any_failure": gating_any_failure,
        "any_pending": gating_any_pending,
        "all_done_ok": all_done_ok,
    }


def review_bot_completed_at(check_runs: list[dict[str, Any]]) -> str | None:
    """Most recent completion timestamp from review bot check-runs."""
    latest: str | None = None
    for r in check_runs:
        name = r.get("name") or ""
        if name not in REVIEW_CHECK_NAMES:
            continue
        if r.get("status") != "completed":
            continue
        completed = r.get("completed_at")
        if completed and (latest is None or completed > latest):
            latest = completed
    return latest


# ---------------------------------------------------------------------------
# `ship status` — the workhorse
# ---------------------------------------------------------------------------


def cmd_status(*, fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    """Probe current state, write back cache fields, return hint envelope.

    `fixture` injects pre-fetched data for tests:
        {
          "pr": {... gh pr view json ...},
          "check_runs": {"check_runs": [...]},
          "sticky": {... fetch_sticky_summary return ...} | None,
          "threads_unaddressed": int,  # (legacy: "threads_unresolved" still accepted)
        }
    Production path calls gh; tests pass fixtures so no shelling.
    """
    if fixture is not None:
        pr = fixture["pr"]
        check_runs_resp = fixture.get("check_runs") or {"check_runs": []}
        sticky = fixture.get("sticky")
        # Accept the new key name and the legacy one. "Unaddressed" = unresolved
        # AND not outdated; the old "unresolved" key carried the same intent
        # but the name was misleading once outdated threads were excluded.
        if "threads_unaddressed" in fixture:
            unaddressed_threads = int(fixture["threads_unaddressed"])
        else:
            unaddressed_threads = int(fixture.get("threads_unresolved", 0))
        pending_reviews = int(fixture.get("pending_reviews", 0))
        sha = pr.get("headRefOid") or "fixture-sha"
    else:
        pr = gh_pr_view_full()
        if not pr:
            return _envelope(
                sha="",
                is_draft=False,
                hint="halt",
                reason="no PR found for current branch",
                cadence=0,
            )
        sha = pr.get("headRefOid", current_sha())
        slug = gh_repo_slug()
        check_runs_resp = gh_json(
            ["api", f"repos/{slug}/commits/{sha}/check-runs?per_page=100"]
        ) or {"check_runs": []}
        sticky = None
        pr_num_live = pr.get("number")
        if pr_num_live is not None:
            review_state = gh_review_state(pr_num_live)
            unaddressed_threads = review_state["unaddressed_threads"]
            pending_reviews = review_state["pending_reviews"]
        else:
            unaddressed_threads = 0
            pending_reviews = 0

    check_runs = check_runs_resp.get("check_runs", [])
    classified = classify_check_runs(check_runs)
    bot_completed = review_bot_completed_at(check_runs)
    is_draft = bool(pr.get("isDraft"))
    merge_state = pr.get("mergeStateStatus")
    review_decision = pr.get("reviewDecision")
    rr_raw = pr.get("reviewRequests") or []
    if isinstance(rr_raw, dict):
        review_requests = rr_raw.get("nodes") or []
    else:
        review_requests = rr_raw
    # `unaddressed_threads` already populated above (live or via fixture).

    # Load state for cache comparison + maintain bot-completed-at + sticky cache
    pr_number = pr.get("number")
    state_body = default_state_body()
    state_header: dict[str, str] = {}
    if pr_number is not None and fixture is None:
        state_header, state_body = init_state_if_needed(pr_number)
        state_body.setdefault("last_review_fetch", default_state_body()["last_review_fetch"])
    state_snapshot = json.dumps(state_body, sort_keys=True)

    last_fetch = state_body.get("last_review_fetch") or {}
    bot_advanced = bot_completed and bot_completed != last_fetch.get("bot_completed_at")
    cached_sticky_found = bool(last_fetch.get("sticky_found"))
    cached_sticky_sha = last_fetch.get("sticky_sha")
    cached_sticky_status = last_fetch.get("sticky_status")
    cached_sticky_retrigger = bool(last_fetch.get("sticky_retrigger"))

    # Refresh the sticky probe when the bot advanced or it was never seen. Once
    # parsed, a stickyMeta sha/status/retrigger persists across polls via the
    # cache rebuilt below — so retrigger_review / sticky_sha_stale see a stable
    # verdict without re-fetching every tick, and a plain-beacon sticky (no
    # sha/status) still only pays the fetch on the bot-advanced / cold poll.
    # (No configured beacons ⇒ the probe is a zero-network no-op → found=False.)
    need_sticky_refresh = bot_advanced or not cached_sticky_found
    if sticky is None and need_sticky_refresh and pr_number is not None and fixture is None:
        sticky = cmd_fetch_sticky_summary(pr_number)
    if sticky is None:
        sticky = {
            "sticky_found": cached_sticky_found,
            "sha": cached_sticky_sha,
            "run": None,
            "status": cached_sticky_status,
            "findings_count": 0,
            "sha_matches_current": cached_sticky_sha == sha if cached_sticky_sha else False,
            "findings": [],
            "retrigger": cached_sticky_retrigger,
        }

    # ---------- hint state machine ----------
    hint, cadence, reason = _classify_hint(
        check_runs=check_runs,
        classified=classified,
        is_draft=is_draft,
        merge_state=merge_state,
        review_decision=review_decision,
        review_requests=review_requests,
        unaddressed_threads=unaddressed_threads,
        pending_reviews=pending_reviews,
        sticky=sticky,
        sha=sha,
        bot_advanced=bool(bot_advanced),
        empty_mergeable_count=int(state_body.get("empty_runs_mergeable_count", 0)),
    )

    # Single state write per cmd_status invocation. Change-detection guard
    # skips the atomic-rename + fsync churn on idle iters where nothing
    # actually changed (most common case during long CI waits).
    if fixture is None and pr_number is not None:
        last_fetch["bot_completed_at"] = bot_completed
        last_fetch["sticky_found"] = bool(sticky.get("sticky_found"))
        last_fetch["sticky_sha"] = sticky.get("sha")
        last_fetch["sticky_status"] = sticky.get("status")
        last_fetch["sticky_retrigger"] = bool(sticky.get("retrigger"))
        state_body["last_review_fetch"] = last_fetch
        no_gating_ci = not check_runs or classified.get("gating_total", 0) == 0
        if hint == "wait_ci" and no_gating_ci and merge_state in ("MERGEABLE", "CLEAN"):
            state_body["empty_runs_mergeable_count"] = (
                int(state_body.get("empty_runs_mergeable_count", 0)) + 1
            )
        elif not no_gating_ci:
            state_body["empty_runs_mergeable_count"] = 0
        # Durations self-maintenance: the first poll that observes the suite
        # fully green for this sha harvests each successful check-run's own
        # started_at/completed_at into the durationsFile baseline (once per
        # sha, best-effort — upkeep must never break status).
        if classified.get("all_done_ok") and state_body.get("ci_durations_sha") != sha:
            try:
                cmd_ci_durations_record(check_runs)
            except Exception:  # noqa: BLE001
                pass
            state_body["ci_durations_sha"] = sha
        if json.dumps(state_body, sort_keys=True) != state_snapshot:
            persist_status_fields(
                pr_number,
                state_header,
                {key: state_body[key] for key in _STATUS_OWNED_FIELDS if key in state_body},
            )

    # Per-job CI ETA enrichment: the fixture path reads an injected baseline; the
    # live path loads the committed baseline file. _ci_eta yields (None, None) when
    # no in-progress check-run matches a baseline job, so this is purely additive.
    if fixture is not None:
        ci_baseline = fixture.get("ci_baseline") or {}
    else:
        ci_baseline = _load_ci_baseline()
    ci_elapsed, ci_est_total = (None, None)
    if ci_baseline and check_runs:
        ci_elapsed, ci_est_total = _ci_eta(check_runs, ci_baseline, time.time())

    return _envelope(
        sha=sha,
        is_draft=is_draft,
        hint=hint,
        reason=reason,
        cadence=cadence,
        merge_state=merge_state,
        review_decision=review_decision,
        sticky=sticky,
        classified=classified,
        pr_url=pr.get("url") or "",
        ci_elapsed=ci_elapsed,
        ci_est_total=ci_est_total,
    )


def _envelope(
    *,
    sha: str,
    is_draft: bool,
    hint: str,
    reason: str,
    cadence: int,
    merge_state: str | None = None,
    review_decision: str | None = None,
    sticky: dict[str, Any] | None = None,
    classified: dict[str, Any] | None = None,
    pr_url: str = "",
    ci_elapsed: int | None = None,
    ci_est_total: int | None = None,
) -> dict[str, Any]:
    ci_summary: dict[str, Any] = {}
    if classified:
        ci_summary = {
            "total": classified["total"],
            "pending": len(classified["by_status"]["queued"])
            + len(classified["by_status"]["in_progress"]),
            "success": len(classified["by_status"]["success"]),
            "failure": len(classified["by_status"]["failure"]),
            "skipped": len(classified["by_status"]["skipped"]),
            "neutral": len(classified["by_status"]["neutral"]),
        }
    return {
        "sha": sha,
        "pr_url": pr_url,
        "is_draft": is_draft,
        "ci": {"summary": ci_summary},
        "review": {
            "decision": review_decision,
            "sticky": {
                "sha": (sticky or {}).get("sha"),
                "status": (sticky or {}).get("status"),
                "sha_matches_current": (sticky or {}).get("sha_matches_current", False),
                "findings_count": (sticky or {}).get("findings_count", 0),
            },
        },
        "merge_state": merge_state,
        "conflict": merge_state == "DIRTY",
        "hint": hint,
        "cadence_hint_seconds": cadence,
        "reason": reason,
        "ci_elapsed": ci_elapsed,
        "ci_est_total": ci_est_total,
    }


def _classify_hint(
    *,
    check_runs: list[dict[str, Any]],
    classified: dict[str, Any],
    is_draft: bool,
    merge_state: str | None,
    review_decision: str | None,
    review_requests: list[Any],
    unaddressed_threads: int,
    pending_reviews: int = 0,
    sticky: dict[str, Any],
    sha: str,
    bot_advanced: bool,
    empty_mergeable_count: int,
) -> tuple[str, int, str]:
    """Return (hint, cadence_seconds, reason)."""
    # 0. Merge conflict short-circuits everything: GitHub will not schedule CI
    # while mergeStateStatus is DIRTY, so waiting for check-runs deadlocks.
    if merge_state == "DIRTY":
        return "merge_conflict", CADENCE_IMMEDIATE, "merge conflict (mergeStateStatus=DIRTY)"

    # 1. No real CI registered → mergeStateStatus probe. Either zero check-runs,
    # OR only excluded checks (checkExclusions / review-bot runs) are present —
    # in both cases no gating check has run, so we must NOT treat the PR as green.
    no_gating_ci = not check_runs or classified.get("gating_total", 0) == 0
    if no_gating_ci:
        if merge_state in ("MERGEABLE", "CLEAN") and empty_mergeable_count + 1 >= EMPTY_RUNS_MERGEABLE_CAP:
            return "halt", CADENCE_IMMEDIATE, (
                f"workflows likely disabled ({EMPTY_RUNS_MERGEABLE_CAP}x empty + MERGEABLE)"
            )
        return "wait_ci", CADENCE_EMPTY_CHECK_RUNS, "no gating check-runs yet"

    # 2. Any failure → ci_failed
    if classified["any_failure"]:
        return "ci_failed", CADENCE_IMMEDIATE, "one or more check-runs failed"

    # 3. Still pending → wait_ci
    if classified["any_pending"]:
        return "wait_ci", CADENCE_WAIT_CI, "CI in progress"

    # CI is fully green from here ---------------------------------------------
    # 4. Review-bot sticky sha behind HEAD → re-probe threads (transient WAKE).
    # Only meaningful with stickyMeta: sticky.sha is populated only when a
    # configured bot parsed a meta JSON. Fires when the bot just advanced but its
    # sticky still points at an older head — the thread set may be stale, so wake
    # the agent to re-probe rather than acting on a stale verdict. Inert under
    # empty reviewBots / plain-beacon stickies (sha stays None).
    if REVIEW_BOTS and bot_advanced and sticky.get("sha") and sticky.get("sha") != sha:
        return "sticky_sha_stale", CADENCE_STICKY_STALE, "review-bot sticky on an older head sha — re-probe threads"

    # 5. Draft → promote
    if is_draft:
        return "promote_draft", CADENCE_IMMEDIATE, "draft + CI green; ready for review"

    # 6. Merge state: BEHIND / BLOCKED → behind_base probe
    if merge_state == "BEHIND":
        return "behind_base", CADENCE_IMMEDIATE, "PR behind base branch"

    # 6.5 PENDING (unsubmitted) review open → wait, don't act. Before the
    # thread/clean_exit branches so we neither reply to a half-written review
    # nor merge out from under it. See gh_pending_review_count.
    if pending_reviews > 0:
        return (
            "wait_review_submit",
            CADENCE_WAIT_REVIEW_SUBMIT,
            f"{pending_reviews} pending (unsubmitted) review(s) — wait for submit",
        )

    # 7. Unaddressed threads → fetch. Outdated threads (line no longer in
    # diff) are excluded by gh_unaddressed_thread_count, so a reviewer's
    # comment that was made stale by a later push no longer triggers
    # fetch_threads. Only threads the human still expects a response on.
    if unaddressed_threads > 0:
        return (
            "fetch_threads",
            CADENCE_IMMEDIATE,
            f"{unaddressed_threads} unaddressed threads",
        )

    # 8. Pending first review
    if review_decision is None and review_requests:
        return "wait_first_review", CADENCE_WAIT_FIRST_REVIEW, "awaiting first review"

    # 9. Changes requested / review required
    if review_decision in ("CHANGES_REQUESTED", "REVIEW_REQUIRED"):
        # Stale-blocking deadlock (opt-in per matched bot's `retrigger`): the
        # bot's last verdict was BLOCKING, it reviewed HEAD (sticky.sha == sha),
        # and every finding thread is now addressed (branch 7 above already
        # returned fetch_threads for any still-open thread, so reaching here
        # means unaddressed_threads == 0). A review bot typically recomputes its
        # sticky only on a push / ready_for_review event, never on a thread
        # resolve, so reviewDecision stays REVIEW_REQUIRED and wait_reapproval
        # would spin silently to the wall-clock cap. When the bot is configured
        # `retrigger: true`, nudge it (draft→ready toggle re-runs review only).
        # Requires `not bot_advanced` so an already-re-running bot isn't toggled.
        # Default-off (retrigger falsy / empty reviewBots) ⇒ strict no-op → falls
        # through to wait_reapproval.
        if (
            sticky.get("retrigger")
            and sticky.get("status") == "BLOCKING"
            and sticky.get("sha") == sha
            and unaddressed_threads == 0
            and not bot_advanced
        ):
            return (
                "retrigger_review",
                CADENCE_IMMEDIATE,
                "sticky BLOCKING but all findings addressed — re-run review bot",
            )
        return "wait_reapproval", CADENCE_WAIT_REAPPROVAL, "awaiting re-approval"

    # 10. Approved + all gating CI passed + mergeable → clean_exit. all_done_ok
    # requires at least one gating run that passed, so a PR with only excluded
    # checks (handled at step 1) can never reach a phantom-green clean_exit.
    if (
        review_decision == "APPROVED"
        and classified.get("all_done_ok")
        and merge_state in ("CLEAN", "HAS_HOOKS", "UNSTABLE", "MERGEABLE")
    ):
        # Review-currency precondition (only when review bots are configured):
        # the review bot's check-run for the CURRENT head must be present AND
        # completed. The check-runs endpoint is queried per-commit, so a
        # review-bot run in `classified` IS the current-head run; an
        # in_progress run means the bot is actively re-reviewing this commit,
        # and an absent run means it hasn't started (e.g. just pushed). In both
        # cases wait — do NOT merge out from under an in-flight re-review.
        # wait_reapproval carries the wall-clock cap that escalates to halt if
        # the bot never runs. Separate from the CI gating tally (a review
        # signal, not a blocking check). Empty reviewBots ⇒ gate skipped.
        if REVIEW_CHECK_NAMES and not classified.get("review_completed"):
            if classified.get("review_present"):
                reason = "review bot in progress on current head — wait"
            else:
                reason = "review bot not yet started on current head — wait"
            return "wait_reapproval", CADENCE_WAIT_REAPPROVAL, reason
        return "clean_exit", CADENCE_IMMEDIATE, "all green; ready to merge"

    if merge_state == "BLOCKED":
        # BLOCKED + null review_decision typically = freshly-promoted PR waiting
        # for the review bot to auto-request itself + start. Treat as pending
        # first review rather than halt — bot will populate review state in a
        # few seconds. If state stays this way past the 30-min cap, the skill
        # will halt via wait_first_review wall-clock cap.
        if review_decision is None:
            return "wait_first_review", CADENCE_WAIT_FIRST_REVIEW, "BLOCKED awaiting bot review"
        return "halt", CADENCE_IMMEDIATE, "PR mergeStateStatus=BLOCKED with no clear cause"

    return "halt", CADENCE_IMMEDIATE, "unclassified state"


# ---------------------------------------------------------------------------
# `ship failures`
# ---------------------------------------------------------------------------


def cmd_failures(*, fixture: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return failed check-runs with workflow_run_id + failed_tests."""
    if fixture is not None:
        check_runs = (fixture.get("check_runs") or {}).get("check_runs", [])
    else:
        sha = current_sha()
        slug = gh_repo_slug()
        resp = gh_json(
            ["api", f"repos/{slug}/commits/{sha}/check-runs?per_page=100"]
        ) or {"check_runs": []}
        check_runs = resp.get("check_runs", [])

    # Compute changed files once outside loop (same for every failed job)
    changed_files: list[str] = []
    if fixture is None:
        diff_proc = run(["git", "diff", "--name-only", f"{_base_ref()}...HEAD"])
        if diff_proc.returncode == 0:
            changed_files = [l.strip() for l in (diff_proc.stdout or "").splitlines() if l.strip()]

    rows: list[dict[str, Any]] = []
    for r in check_runs:
        # Exclude the SAME checks the green gate excludes — configured
        # exclusions and review-bot runs are not fixable CI failures.
        if r.get("name") in GATE_EXCLUDED_CHECK_NAMES:
            continue
        conclusion = r.get("conclusion")
        if conclusion not in ("failure", "timed_out", "cancelled", "action_required"):
            continue
        details_url = r.get("details_url") or ""
        run_match = WORKFLOW_RUN_URL_RX.search(details_url)
        wf_run_id = run_match.group(1) if run_match else None
        # Populate failed_tests + flaky_signal from the failed-step log. Fetch
        # the log once and feed both parsers — extract + classify share it.
        # Fixture rows carry their log inline as `failed_log` for tests.
        failed_tests: list[str] = []
        flaky_signal = classify_flaky("")
        log = ""
        if fixture is None and wf_run_id is not None:
            try:
                log = _fetch_failed_log(wf_run_id)
            except Exception:  # noqa: BLE001 — non-fatal; skill matches by file diff still
                log = ""
        elif fixture is not None:
            log = r.get("failed_log") or ""
        if log:
            failed_tests = _parse_failed_fqns(log)
            flaky_signal = classify_flaky(log)
        rows.append(
            {
                "name": r.get("name"),
                "workflow_run_id": wf_run_id,
                "html_url": r.get("html_url") or details_url,
                "failed_tests": failed_tests,
                "flaky_signal": flaky_signal,
                "failed_jobs_changed_files": changed_files,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# `ship threads`
# ---------------------------------------------------------------------------

def cmd_threads(
    pr_number: int,
    *,
    unresolved_only: bool = False,
    fixture: dict[str, Any] | None = None,
    sticky_findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if fixture is not None:
        threads = fixture.get("threads", [])
        viewer_login: str | None = fixture.get("viewer_login")
    else:
        # Defense-in-depth: a direct `ship threads` call must not leak a
        # half-written review either. See gh_pending_review_count.
        if gh_pending_review_count(pr_number) > 0:
            return []
        # Walk every page — on a >100-thread PR the tail is where the newest
        # bot findings land, and dropping it silently green-lights the watch.
        try:
            data, threads = fetch_all_review_threads(pr_number, _THREADS_NODE_SELECTION)
        except ReviewThreadFetchError as e:
            die(str(e), EXIT_HALT)
        viewer_login = (data.get("viewer") or {}).get("login")

    # No local caching of thread state. Comments and resolved-bits can mutate
    # on GitHub outside ship's view (a reviewer edits, deletes, or re-opens a
    # thread; the human user manually marks a thread resolved or adds a new
    # comment). Trusting a hash from a previous fetch would silently hide
    # those changes. Every call goes back to GraphQL — the network round trip
    # is cheap relative to a wrong "all clear" decision.

    sticky_findings = sticky_findings or []
    sticky_by_node = {
        f.get("node_id"): f for f in sticky_findings if f.get("node_id")
    }

    rows: list[dict[str, Any]] = []
    for t in threads:
        is_resolved = bool(t.get("isResolved"))
        is_outdated = bool(t.get("isOutdated"))
        replied_by_viewer = _thread_replied_by(t, viewer_login)
        # `--unresolved` filters to threads still needing action. A thread is
        # only considered addressed when it is BOTH marked resolved on GitHub
        # AND the ship viewer has actually authored a reply. Resolved-without-
        # reply (mutation never landed) and outdated-without-reply (line was
        # rewritten before we answered) both surface so the watcher cannot
        # exit on a false "I already replied" self-report. Outdated comments
        # the viewer already answered drop out naturally because the
        # resolved+reply pair will have been recorded.
        if unresolved_only and is_resolved and replied_by_viewer:
            continue
        comments = (t.get("comments") or {}).get("nodes") or []
        if not comments:
            continue
        first = comments[0]
        node_id = first.get("id")
        match = sticky_by_node.get(node_id)
        if is_resolved and replied_by_viewer:
            state = "resolved"
        elif is_outdated:
            state = "outdated"
        elif is_resolved:
            # Resolved bit flipped but no viewer reply — treat as actionable
            # so the orchestrator either posts the missing reply or asks the
            # user. `resolved_no_reply` is its own state so consumers can
            # distinguish from the "needs first response" case below.
            state = "resolved_no_reply"
        else:
            state = "unresolved"
        rows.append(
            {
                "thread_id": t.get("id"),
                "comment_id": first.get("databaseId") or first.get("id"),
                "path": t.get("path"),
                "line": t.get("line"),
                "author": (first.get("author") or {}).get("login"),
                "body": first.get("body"),
                "in_reply_to": (first.get("replyTo") or {}).get("id"),
                "node_id": node_id,
                "is_resolved": is_resolved,
                "is_outdated": is_outdated,
                "replied_by_viewer": replied_by_viewer,
                "state": state,
                "author_kind": thread_author_kind(t),
                "sticky_match": (
                    {"finding_id": match.get("id"), "severity": match.get("severity")}
                    if match
                    else None
                ),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# `ship reply-thread` / `ship resolve-thread`
# ---------------------------------------------------------------------------


REPLY_GQL = """
mutation($threadId: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $threadId, body: $body}) {
    comment { id }
  }
}
"""

RESOLVE_GQL = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
"""


def _stamp_reply_marker(body: str) -> str:
    """Prepend SHIP_REPLY_MARKER unless the body already carries it.

    Stamping in the engine (not the skill) guarantees every ship reply is
    self-identifying for the skill's comment audit + dedupe (sticky-comments.md).
    """
    if SHIP_REPLY_MARKER in body:
        return body
    return f"{SHIP_REPLY_MARKER}\n{body}"


def cmd_reply_thread(thread_id: str, body: str) -> str:
    """Post a single inline reply on a review thread.

    `addPullRequestReviewThreadReply` adds ONE comment to an existing thread —
    it does not open a new review. This is the only sanctioned reply path.
    Responding with `gh pr review` / `gh api .../pulls/N/reviews` instead
    creates a pending (unsubmitted) review under ship's own token, which the
    next `ship status` reports as `wait_review_submit` and the watcher then
    waits on indefinitely (it expects a human to submit). Always route
    replies through here.
    """
    body = _stamp_reply_marker(body)
    proc = run(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={REPLY_GQL}",
            "-f",
            f"threadId={thread_id}",
            "-f",
            f"body={body}",
        ]
    )
    if proc.returncode != 0:
        die(f"reply-thread failed: {proc.stderr.strip()}", EXIT_HALT)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        die(f"non-JSON reply: {e}", EXIT_HALT)
    return (
        payload.get("data", {})
        .get("addPullRequestReviewThreadReply", {})
        .get("comment", {})
        .get("id", "")
    )


def cmd_resolve_thread(thread_id: str) -> None:
    proc = run(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={RESOLVE_GQL}",
            "-f",
            f"threadId={thread_id}",
        ]
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").lower()
        if "already resolved" in stderr:
            return
        die(f"resolve-thread failed: {proc.stderr.strip()}", EXIT_HALT)


def thread_author_kind(thread: dict[str, Any]) -> str:
    """Classify a review thread by its originating comment's author + body.

    Returns 'review_bot' | 'human' | 'other_bot'. The skill auto-replies to and
    resolves ONLY 'review_bot' threads; 'human' threads are SURFACED for the PR
    author and never auto-answered; 'other_bot' threads are skipped (not even
    surfaced). Derived from the FIRST (thread-opening) comment so a ship or
    human reply cannot reclassify a thread.

    review_bot classification is CONSERVATIVE and fail-safe toward SURFACING:
    auto-resolving a foreign blocking thread is the dangerous failure, so we
    only return 'review_bot' when the thread confidently matches a configured
    bot — login in that bot's commentLogins AND (when the bot defines a
    commentSignature regex) the opening comment matches it. Shared CI logins
    (e.g. a default-token Action) can author threads for many tools, so a
    login match WITHOUT the required signature is classified 'human'
    (surfaced, blocks clean_exit, never auto-resolved). A null/empty author
    also falls through to 'human' for the same reason. Logins in the
    configured skipLogins are 'other_bot'.
    """
    comments = (thread.get("comments") or {}).get("nodes") or []
    if not comments:
        return "other_bot"
    first = comments[0]
    login = (first.get("author") or {}).get("login", "") or ""
    body = first.get("body") or ""
    for bot in REVIEW_BOTS:
        if login not in (bot.get("commentLogins") or []):
            continue
        sig = (bot.get("commentSignature") or "").strip()
        if not sig or re.search(sig, body):
            return "review_bot"
        # Login matched but the bot's signature is absent: a foreign tool
        # could have posted this inline thread. Surface (never auto-resolve).
        return "human"
    if login in SKIP_LOGINS:
        return "other_bot"
    return "human"


def _pct(xs: list[float], p: float) -> float:
    """Linear-interpolated percentile (p in 0..100) of a non-empty list."""
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    k = (len(ys) - 1) * p / 100.0
    f = int(k)
    if f + 1 >= len(ys):
        return ys[f]
    return ys[f] + (ys[f + 1] - ys[f]) * (k - f)


def _round_up_30(v: float) -> int:
    """Round a duration up to the next 30s bucket (30s ≪ per-job stdev, so this
    is inside the noise floor and keeps the committed baseline stable)."""
    return int(math.ceil(v / 30.0) * 30)


CI_WINDOW_DAYS = 7


def _iso_epoch(s: str) -> float:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:  # naive string (no Z/offset) → treat as UTC, never local
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _ci_durations_update(
    existing: dict[str, Any],
    new_samples: dict[str, list[list[Any]]],
    *,
    now: str,
    window_days: int = CI_WINDOW_DAYS,
) -> dict[str, Any]:
    """Merge `new_samples` ({job_name: [[run_id, completed_at_iso, dur], ...]})
    into `existing`, dedupe by run_id, prune samples older than `window_days`,
    recompute `p90_s` (round up to 30s). Pure — caller does the I/O.

    A job whose samples all prune out is dropped (stale conditional job).
    """
    cutoff = _iso_epoch(now) - window_days * 86400
    jobs_in = (existing.get("jobs") or {})
    # union of job names from existing + new
    names = set(jobs_in) | set(new_samples)
    out_jobs: dict[str, Any] = {}
    for name in names:
        by_run: dict[Any, list[Any]] = {}
        for s in (jobs_in.get(name, {}).get("samples") or []):
            by_run[s[0]] = s
        for s in new_samples.get(name, []):
            by_run[s[0]] = s  # new wins on dedupe (same run_id)
        kept = [s for s in by_run.values() if _iso_epoch(s[1]) >= cutoff]
        if not kept:
            continue  # all pruned → drop the job
        kept.sort(key=lambda s: s[1])
        durs = [float(s[2]) for s in kept]
        out_jobs[name] = {
            "p90_s": _round_up_30(_pct(durs, 90)),
            "n": len(kept),
            "samples": kept,
        }
    return {"_updated": now, "_window_days": window_days, "jobs": out_jobs}


def _durations_path(file_path: str | None = None) -> Path:
    """Resolve the durations baseline path: explicit arg, else the configured
    durationsFile — relative paths anchor at the repo root (falls back to cwd)."""
    p = Path(file_path or CI_DURATIONS_FILE)
    if p.is_absolute():
        return p
    root = _repo_root()
    return (root / p) if root else p


def _ci_samples_from_check_runs(check_runs: list[dict[str, Any]]) -> dict[str, list[list[Any]]]:
    """Per-check success durations derived from the check-runs a watch poll
    already fetched, in `new_samples` shape: {name: [[check_run_id,
    completed_at_iso, duration_seconds]]}. Dedupe key is the check-run id."""
    out: dict[str, list[list[Any]]] = {}
    for r in check_runs:
        if r.get("status") != "completed" or r.get("conclusion") != "success":
            continue
        name = r.get("name")
        rid = r.get("id")
        s, c = r.get("started_at"), r.get("completed_at")
        if not name or rid is None or not s or not c:
            continue
        dur = _iso_epoch(c) - _iso_epoch(s)
        if dur > 0:
            out.setdefault(name, []).append([rid, c, dur])
    return out


def cmd_ci_durations_record(
    check_runs: list[dict[str, Any]],
    *,
    file_path: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Self-maintain the rolling baseline: merge one green suite's per-check
    durations into the durationsFile (atomic write, write-on-change only).
    Called by the watch poll once per fully-green sha; no workflow coupling."""
    if now is None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = _durations_path(file_path)
    try:
        existing = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        existing = {}
    updated = _ci_durations_update(existing, _ci_samples_from_check_runs(check_runs), now=now)
    changed = _ci_p90_map(updated) != _ci_p90_map(existing)
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")  # same dir → os.replace is atomic
        try:
            tmp.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n")
            os.replace(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)  # don't leave a stray .tmp behind
            raise
    return {"changed": changed, "jobs": len(updated.get("jobs") or {})}


def _ci_p90_map(doc: dict[str, Any]) -> dict[str, int]:
    # -1 sentinel: a malformed on-disk entry missing p90_s differs from any real
    # (>=0) value, so change-detection self-heals it rather than silently matching.
    return {n: j.get("p90_s", -1) for n, j in (doc.get("jobs") or {}).items()}


def _load_ci_baseline(file_path: str | None = None) -> dict[str, int]:
    """{job_name: p90_s} from the baseline file, or {} when absent/bad —
    callers fall back to fast-fail + the fixed waitCi cadence."""
    p = _durations_path(file_path)
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {n: int(j["p90_s"]) for n, j in (doc.get("jobs") or {}).items()
            if isinstance(j.get("p90_s"), (int, float))}


def _ci_eta(
    check_runs: list[dict[str, Any]], baseline: dict[str, int], now_epoch: float
) -> tuple[int | None, int | None]:
    """(suite_elapsed, est_total) for the in-progress suite, or (None, None) when
    no in-progress check-run matches a baseline job. est_total = suite_elapsed +
    max remaining over in-progress jobs (the slowest job gates completion)."""
    starts: list[float] = []
    remaining = 0.0
    matched = False
    for r in check_runs:
        sa = r.get("started_at")
        if sa:
            starts.append(_iso_epoch(sa))
        if r.get("status") not in ("queued", "in_progress"):
            continue
        p90 = baseline.get(r.get("name"))
        if p90 is None:
            continue
        matched = True
        job_elapsed = (now_epoch - _iso_epoch(sa)) if sa else 0.0
        remaining = max(remaining, p90 - job_elapsed)
    if not matched:
        return (None, None)
    suite_elapsed = int(now_epoch - min(starts)) if starts else 0
    return (suite_elapsed, int(suite_elapsed + max(0.0, remaining)))


# ---------------------------------------------------------------------------
# `ship rebase-decision`
# ---------------------------------------------------------------------------
# Hot-path regexes come from config hotPaths (HOT_PATHS_RX in _apply_config);
# default [] means hot-file logic never fires until configured.

STALENESS_THRESHOLD = 10


def _has_pr() -> bool:
    return lookup_pr_number() is not None


_BASE_REF_CACHE: str | None = None


_KNOWN_REMOTES: frozenset[str] = frozenset({"origin", "upstream"})


def _origin_head_branch() -> str:
    """Short branch name of origin/HEAD (e.g. 'main'), or '' when unset.
    Pure-local (reads the cached symbolic ref, no network)."""
    proc = run(["git", "rev-parse", "--abbrev-ref", "origin/HEAD"])
    if proc.returncode != 0:
        return ""
    ref = proc.stdout.strip()
    return ref.split("/", 1)[-1] if ref and "/" in ref else ref


def _fallback_base_branch() -> str:
    """Base branch when no env/PR answer exists: an explicitly configured
    baseBranch wins; otherwise origin/HEAD; otherwise the built-in default."""
    cfg = _config()
    if _CONFIG_SECTION_FOUND and cfg.get("baseBranch"):
        return str(cfg["baseBranch"])
    return _origin_head_branch() or str(cfg.get("baseBranch") or "main")


def _normalize_base_ref(ref: str) -> str:
    """Ensure a base ref is 'remote/branch' (default remote origin) so callers
    that split on '/' (e.g. git fetch) get a valid remote + refspec.

    A bare branch without '/' or a slashed branch whose first segment is not a
    known remote (e.g. 'release/1.0') both get the 'origin/' prefix,
    preventing 'git fetch release 1.0' against a nonexistent remote."""
    ref = (ref or "").strip()
    if not ref:
        return f"origin/{_fallback_base_branch()}"
    if "/" not in ref:
        return f"origin/{ref}"
    remote, _, _ = ref.partition("/")
    if remote not in _KNOWN_REMOTES:
        return f"origin/{ref}"
    return ref


def _base_ref() -> str:
    """PR base branch ref as 'remote/branch'. Resolution order:

    1. Explicit SHIP_BASE_REF env override (highest priority; cmd_watch
       exports it from the PR's baseRefName for child processes).
    2. The PR's actual base via lookup_pr_number + gh pr view --json baseRefName,
       so standalone subcommands (size, rebase-decision) run as separate
       processes target the real base. Cached per-process.
    3. Config baseBranch, then origin/HEAD, when no PR/base resolvable.
       Never hardcode a branch name."""
    global _BASE_REF_CACHE
    override = os.environ.get("SHIP_BASE_REF")
    if override:
        return _normalize_base_ref(override)
    if _BASE_REF_CACHE is not None:
        return _BASE_REF_CACHE
    pr_number = lookup_pr_number()
    if pr_number is None:
        # No PR yet — return the fallback but do NOT cache it; a later call
        # (after cmd_find_or_create_pr creates the PR) must re-resolve the
        # real base rather than returning a stale fallback.
        return f"origin/{_fallback_base_branch()}"
    _BASE_REF_CACHE = _pr_base_ref(pr_number)
    return _BASE_REF_CACHE


def _pr_base_ref(pr_number: int) -> str:
    """Resolve the PR's base branch to an origin ref; config/origin-HEAD fallback."""
    proc = run(["gh", "pr", "view", str(pr_number), "--json", "baseRefName"])
    if proc.returncode != 0:
        return f"origin/{_fallback_base_branch()}"
    try:
        base = (json.loads(proc.stdout or "{}").get("baseRefName") or "").strip()
    except (ValueError, AttributeError):
        base = ""
    return f"origin/{base or _fallback_base_branch()}"


def _master_ahead() -> int:
    """Count commits HEAD..<base_ref> (kept name for diffability)."""
    proc = run(["git", "rev-list", "--count", f"HEAD..{_base_ref()}"])
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return 0


def _files_changed(spec: str) -> list[str]:
    proc = run(["git", "diff", "--name-only", spec])
    return [l.strip() for l in (proc.stdout or "").splitlines() if l.strip()]


def _merge_tree_conflict() -> bool:
    proc = run(
        ["git", "merge-tree", "--write-tree", "--name-only", "--no-messages",
         "HEAD", _base_ref()]
    )
    if proc.returncode != 0:
        return True
    return "<<<<<<<" in (proc.stdout or "")


def cmd_rebase_decision(*, force_rebase: bool = False) -> dict[str, Any]:
    remote, _, branch = _base_ref().partition("/")
    run(["git", "fetch", remote, branch, "--quiet"])
    ahead = _master_ahead()
    if ahead == 0:
        return _rebase_result("SKIP", "already up to date", [], ahead)

    if not _has_pr():
        return _rebase_result("REBASE", "no PR yet — free rebase", [], ahead)

    master_changed = set(_files_changed(f"HEAD...{_base_ref()}"))
    branch_changed = set(_files_changed(f"{_base_ref()}...HEAD"))
    overlap = sorted(master_changed & branch_changed)
    hot_overlap = [f for f in overlap if any(rx.match(f) for rx in HOT_PATHS_RX)]

    if _merge_tree_conflict():
        return _rebase_result("REBASE", "merge-tree reports conflict", hot_overlap, ahead, overlap)

    if overlap:
        return _rebase_result(
            "REBASE",
            f"file overlap with base ({len(overlap)} files)",
            hot_overlap,
            ahead,
            overlap,
        )

    if force_rebase:
        # force_rebase only triggers when paired with conflict/overlap/staleness.
        # If no conflict + no overlap, fall through to staleness check.
        pass

    if ahead >= STALENESS_THRESHOLD:
        return _rebase_result("REBASE", f"base +{ahead} commits (>= threshold)", hot_overlap, ahead, overlap)

    return _rebase_result(
        "SKIP",
        f"base +{ahead}, no overlap, no conflict, force_rebase={force_rebase}",
        hot_overlap,
        ahead,
        overlap,
    )


def _rebase_result(
    decision: str,
    reason: str,
    hot_files: list[str],
    staleness: int,
    overlap_files: list[str] | None = None,
) -> dict[str, Any]:
    overlap_files = overlap_files or []
    # code_overlap = both sides touched the same NON-hot file. merge-tree
    # only catches textual conflicts; two edits to different parts of one
    # function merge clean yet break logically. Flag those for agent inspection.
    code_overlap = any(f not in hot_files for f in overlap_files)
    return {
        "decision": decision,
        "reason": reason,
        "hot_files_changed": hot_files,
        "overlap_files": overlap_files,
        "code_overlap": code_overlap,
        "staleness_count": staleness,
    }


# ---------------------------------------------------------------------------
# `ship size` — mechanical pre-push size facts
# ---------------------------------------------------------------------------

_ZERO_CODE_PATHS_RX: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (r"^.*\.md$", r"^docs/.*", r"^\.claude/.*", r"^LICENSE$", r"^\.gitignore$")
)


def _is_zero_code_change(files: list[str]) -> bool:
    return bool(files) and all(any(rx.match(f) for rx in _ZERO_CODE_PATHS_RX) for f in files)


def cmd_size() -> dict[str, Any]:
    """Mechanical pre-push facts: informational tier + zero-code-change flag +
    whether any configured hot path was touched. tier never gates anything;
    which local test commands to run is the SKILL's job via the repo's
    configured gates, not the engine's.
    """
    base_ref = _base_ref()
    spec = f"{base_ref}...HEAD"
    files = _files_changed(spec)
    numstat = run(["git", "diff", "--numstat", spec])
    lines = 0
    for row in (numstat.stdout or "").splitlines():
        cols = row.split("\t")
        if len(cols) >= 2:
            lines += sum(int(c) for c in cols[:2] if c.isdigit())

    code_change = not _is_zero_code_change(files)
    hot_touched = any(any(rx.match(f) for rx in HOT_PATHS_RX) for f in files)

    nfiles = len(files)
    if nfiles > 20 or lines > 500:
        tier = "Large"
    elif nfiles >= 6 or lines >= 100:
        tier = "Medium"
    else:
        tier = "Small"

    return {
        "tier": tier, "files": nfiles, "lines": lines,
        "hot_touched": hot_touched, "code_change": code_change,
    }


# ---------------------------------------------------------------------------
# Simpler wrappers
# ---------------------------------------------------------------------------


def cmd_promote_draft() -> int:
    proc = run(["gh", "pr", "ready"])
    if proc.returncode == 0:
        return EXIT_OK
    stderr = (proc.stderr or "").lower()
    if "already" in stderr and "ready" in stderr:
        return EXIT_OK
    die(f"promote-draft failed: {proc.stderr.strip()}", EXIT_HALT)
    return EXIT_HALT  # unreachable


def cmd_rerun_workflow(workflow_run_id: str) -> int:
    proc = run(["gh", "run", "rerun", "--failed", workflow_run_id])
    if proc.returncode != 0:
        die(f"rerun-workflow failed: {proc.stderr.strip()}", EXIT_HALT)
    return EXIT_OK


def cmd_branch_name_valid() -> int:
    """Exit 0 for any branch that may host a PR: a non-empty branch that is not
    the RESOLVED base branch. The remote branch and PR reuse the local branch
    name verbatim (gh defaults `--head` to it) — no naming convention is
    imposed. Only the resolved base branch name and a detached HEAD (empty)
    are rejected, since neither can be a PR head. No hardcoded branch names.

    This command must remain pure-local (no gh subprocess) — it is the Phase-0
    gate called as the FIRST command of every invocation before any network op.
    Resolution here is therefore env → config → origin/HEAD (skips the PR
    lookup, which would shell gh)."""
    branch = current_branch()
    if not branch:
        return EXIT_HALT
    override = os.environ.get("SHIP_BASE_REF", "")
    if override:
        base_short = _normalize_base_ref(override).split("/", 1)[-1]
    else:
        base_short = _fallback_base_branch()
    if branch == base_short:
        return EXIT_HALT
    return EXIT_OK


def _parse_worktree_porcelain(stdout: str) -> list[dict[str, str]]:
    """Parse `git worktree list --porcelain` into a list of {path, branch} dicts.

    `branch` is the short refname (e.g. `master`, `claude/foo-bar-abc123`) or
    empty string for a detached worktree. The first entry is the main worktree.
    """
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for raw in stdout.splitlines():
        line = raw.rstrip()
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": line[len("worktree ") :].strip(), "branch": ""}
        elif line.startswith("branch "):
            ref = line[len("branch ") :].strip()
            cur["branch"] = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ref
        elif line == "" and cur:
            entries.append(cur)
            cur = {}
    if cur:
        entries.append(cur)
    return entries


def cmd_cleanup_worktree(path: str | None = None, branch: str | None = None) -> int:
    if path and branch:
        die("cleanup-worktree: pass either <path> or --branch, not both", EXIT_HALT)
    if not path and not branch:
        die(
            "cleanup-worktree requires <path> or --branch <name>; "
            "the worktree to remove must be named explicitly so this command "
            "can be invoked safely from the main checkout",
            EXIT_HALT,
        )

    proc = run(["git", "worktree", "list", "--porcelain"])
    if proc.returncode != 0:
        die(f"worktree list failed: {proc.stderr.strip()}", EXIT_HALT)
    entries = _parse_worktree_porcelain(proc.stdout)
    if not entries:
        die("worktree list returned no entries", EXIT_HALT)
    main_path = Path(entries[0]["path"]).resolve()

    target: Path | None = None
    if path:
        wanted = Path(path).resolve()
        for e in entries:
            if Path(e["path"]).resolve() == wanted:
                target = wanted
                break
        if target is None:
            die(f"cleanup-worktree: {wanted} is not a registered worktree", EXIT_HALT)
    else:
        # branch lookup
        matches = [Path(e["path"]).resolve() for e in entries if e["branch"] == branch]
        if not matches:
            die(f"cleanup-worktree: no worktree found for branch {branch!r}", EXIT_HALT)
        if len(matches) > 1:
            die(
                f"cleanup-worktree: multiple worktrees match branch {branch!r}: "
                f"{[str(p) for p in matches]}",
                EXIT_HALT,
            )
        target = matches[0]

    if target == main_path:
        die(f"refusing to remove main worktree {target}", EXIT_HALT)

    # Refuse to remove the worktree we're currently running inside — that
    # would yank the CWD out from under any caller still in this directory.
    here = Path.cwd().resolve()
    inside = here == target
    if not inside:
        try:
            inside = here.is_relative_to(target)
        except AttributeError:  # py3.8
            inside = str(here).startswith(str(target) + "/")
    if inside:
        die(
            f"refusing to remove active worktree {target}; "
            f"cd to the main checkout first, then re-invoke `ship cleanup-worktree`",
            EXIT_HALT,
        )

    proc = run(["git", "worktree", "remove", "--force", str(target)])
    if proc.returncode != 0:
        die(f"worktree remove failed: {proc.stderr.strip()}", EXIT_HALT)
    return EXIT_OK


# ---------------------------------------------------------------------------
# `ship merge-pr`
# ---------------------------------------------------------------------------


def _delete_remote_branch(pr_number: int) -> None:
    """Delete the PR's head branch on the remote via the API only.

    Best-effort: a leftover remote branch is harmless (repo auto-delete or a
    later `cleanup-worktree` mops it up), so never fail an already-completed
    merge over it. An already-deleted ref (prior run, or repo auto-delete
    racing us) returns HTTP 422 "Reference does not exist" — that is success.

    Pure API call: no `git checkout` / `git worktree` side effects, so it
    cannot trip the default-branch worktree lock that `gh pr merge
    --delete-branch` does when run inside a per-PR worktree.
    """
    # Direct run() + local returns, never gh_json()/gh_repo_slug(): those
    # die(EXIT_HALT) on any gh failure (auth, rate limit, network), which
    # would abort the skill *after* the merge already landed — the exact
    # contract this best-effort cleanup must not break.
    info_proc = run(["gh", "pr", "view", str(pr_number), "--json", "headRefName"])
    if info_proc.returncode != 0:
        sys.stderr.write(
            "merge-pr: could not fetch head branch name "
            f"({info_proc.stderr.strip()}); skipping remote ref deletion\n"
        )
        return
    try:
        info = json.loads(info_proc.stdout) if info_proc.stdout.strip() else {}
    except json.JSONDecodeError:
        return
    branch = info.get("headRefName")
    if not branch:
        return
    slug_proc = run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]
    )
    if slug_proc.returncode != 0:
        sys.stderr.write(
            "merge-pr: could not resolve repo slug "
            f"({slug_proc.stderr.strip()}); skipping remote ref deletion\n"
        )
        return
    slug = slug_proc.stdout.strip()
    proc = run(["gh", "api", "-X", "DELETE", f"repos/{slug}/git/refs/heads/{branch}"])
    if proc.returncode == 0:
        return
    stderr = (proc.stderr or "").lower()
    if "does not exist" in stderr or "not found" in stderr or "422" in stderr:
        return  # already gone — fine
    sys.stderr.write(
        f"merge-pr: remote branch {branch!r} not deleted "
        f"({proc.stderr.strip()}); harmless, continuing\n"
    )


def cmd_merge_pr(pr_number: int) -> int:
    """Merge the PR with the configured mergeMethod (default squash).
    Worktree-safe: deletes only the remote head branch via API (never
    --delete-branch, which would yank the local worktree off its branch).
    Tolerates already-merged.
    """
    proc = run(["gh", "pr", "merge", f"--{MERGE_METHOD}", str(pr_number)])
    stderr = (proc.stderr or "").lower()
    already_done = "already" in stderr and ("merged" in stderr or "closed" in stderr)
    if proc.returncode != 0 and not already_done:
        die(f"merge-pr failed: {proc.stderr.strip()}", EXIT_HALT)
    _delete_remote_branch(pr_number)
    return EXIT_OK


# ---------------------------------------------------------------------------
# `ship open-flake-ticket`
# ---------------------------------------------------------------------------


def _flake_marker_dir() -> str:
    return os.environ.get("SHIP_FLAKE_MARKER_DIR", "/tmp")


def cmd_open_flake_ticket(
    fqn: str,
    module: str = "",
    run_url: str = "",
    frames: str = "",
    pr_number: int | str | None = None,
) -> int:
    """Signal the skill to open a flake ticket via the configured ticketRoute
    (ticketing is the skill's job — the engine only writes the handoff marker).

    Scopes the marker filename by PR number so concurrent PRs don't clobber one
    marker. Resolution order: explicit --pr-number arg, SHIP_PR_NUMBER env
    (cmd_watch only), then lookup_pr_number() since the skill runs this as a
    separate process with the env unset. Falls back to 'unknown' only when no PR
    is resolvable. Prints the marker path to stdout (the skill reads the path
    reported by the engine)."""
    if pr_number is None:
        pr_number = os.environ.get("SHIP_PR_NUMBER")
    if pr_number is None:
        pr_number = lookup_pr_number()
    if pr_number is None:
        pr_number = "unknown"
    marker = Path(_flake_marker_dir()) / f"ship-flake-ticket-request-{pr_number}.json"
    payload = {
        "fqn": fqn,
        "module": module,
        "run_url": run_url,
        "relevant_frames": frames,
        "route": _config().get("ticketRoute", "gh-issue"),
    }
    try:
        marker.write_text(json.dumps(payload, indent=2))
    except OSError as e:
        die(f"could not write flake marker: {e}", EXIT_HALT)
    sys.stdout.write(str(marker) + "\n")
    sys.stderr.write("ticket_handoff_required\n")
    return EXIT_TRANSIENT


# ---------------------------------------------------------------------------
# `ship post-pr-body` / `ship find-or-create-pr`
# ---------------------------------------------------------------------------


def cmd_post_pr_body(summary: str) -> str:
    proc = run(["git", "diff", "--name-only", f"{_base_ref()}...HEAD"])
    changed = [l.strip() for l in (proc.stdout or "").splitlines() if l.strip()]
    # Group by top-level path segment — stack-neutral, works in any repo layout.
    groups: dict[str, list[str]] = {}
    for f in changed:
        top = f.split("/", 1)[0] if "/" in f else "(root)"
        groups.setdefault(top, []).append(f)
    body_parts: list[str] = ["## Summary", "", summary.strip(), "", "## Changes", ""]
    if groups:
        for group in sorted(groups):
            body_parts.append(f"- **{group}** ({len(groups[group])} files)")
    else:
        body_parts.append("- (no files changed)")
    body_parts += [
        "",
        "## Test Plan",
        "",
        "- [ ] Local gates run pre-push",
        "",
        "---",
        "",
        "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
    ]
    return "\n".join(body_parts)


def cmd_find_or_create_pr(
    *,
    draft: bool = True,
    title: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    def _pr_info() -> dict[str, Any]:
        info = gh_json(["pr", "view", "--json", "number,url,isDraft,headRefName"]) or {}
        return {
            "number": info.get("number"),
            "url": info.get("url"),
            "is_draft": info.get("isDraft"),
            "branch": info.get("headRefName"),
        }

    if lookup_pr_number() is not None:
        return _pr_info()
    if cmd_branch_name_valid() != EXIT_OK:
        die(f"branch name invalid: {current_branch()}", EXIT_HALT)
    if title is None:
        die("--title required to create PR", EXIT_HALT)
    body = cmd_post_pr_body(summary or "")
    args = ["pr", "create", "--title", title, "--body", body]
    if draft:
        args.append("--draft")
    proc = run(["gh", *args])
    if proc.returncode != 0:
        die(f"pr create failed: {proc.stderr.strip()}", EXIT_HALT)
    return _pr_info()


# ---------------------------------------------------------------------------
# `ship state ...`
# ---------------------------------------------------------------------------


def _resolve_pr_for_state() -> int:
    n = lookup_pr_number()
    if n is None:
        die("no PR found for state file", EXIT_HALT)
    return n  # type: ignore[return-value]


def cmd_state_get(key: str) -> str:
    pr = _resolve_pr_for_state()
    _, body = init_state_if_needed(pr)
    val = _nested_get(body, key)
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return str(val)


def cmd_state_set(key: str, value: str) -> None:
    pr = _resolve_pr_for_state()
    with _StateLock(pr):
        header, body = init_state_if_needed(pr)
        _nested_set(body, key, _coerce(value))
        write_state_atomic(pr, header, body)


def cmd_state_inc(key: str) -> int:
    pr = _resolve_pr_for_state()
    with _StateLock(pr):
        header, body = init_state_if_needed(pr)
        cur = _nested_get(body, key) or 0
        if not isinstance(cur, int):
            try:
                cur = int(cur)
            except (TypeError, ValueError):
                cur = 0
        new = cur + 1
        _nested_set(body, key, new)
        write_state_atomic(pr, header, body)
    return new


def cmd_state_reset() -> None:
    pr = _resolve_pr_for_state()
    with _StateLock(pr):
        path = state_path(pr)
        if path.exists():
            path.unlink()
        init_state_if_needed(pr)


def _cap_hits(body: dict[str, Any]) -> list[str]:
    """Cap keys at-or-above their halt threshold in a state body. Shared by the
    `ship state check-caps` subcommand and the watch loop's per-poll cap gate."""
    hits: list[str] = []
    for cause, count in (body.get("ci_fail_count") or {}).items():
        if isinstance(count, int) and count >= CI_FAIL_CAP:
            hits.append(f"ci_fail_count.{cause}")
    for fqn, count in (body.get("flaky_soak_round") or {}).items():
        if isinstance(count, int) and count >= FLAKY_SOAK_CAP:
            hits.append(f"flaky_soak_round.{fqn}")
    if int(body.get("empty_runs_mergeable_count", 0)) >= EMPTY_RUNS_MERGEABLE_CAP:
        hits.append("empty_runs_mergeable_count")
    if int(body.get("retrigger_review_count", 0) or 0) >= RETRIGGER_REVIEW_CAP:
        hits.append("retrigger_review_count")
    return hits


def cmd_state_check_caps() -> list[str]:
    pr = _resolve_pr_for_state()
    _, body = init_state_if_needed(pr)
    return _cap_hits(body)


def _watch_check_caps(pr_number: int) -> list[str]:
    """Cap hits for a known PR — no `gh` (reads the state file directly). The
    watch loop calls this each poll so the halt-caps the old ScheduleWakeup loop
    enforced via `ship state check-caps` still fire under the Monitor model."""
    _, body = init_state_if_needed(pr_number)
    return _cap_hits(body)


def cmd_ack(hint: str, sha: str) -> None:
    """Record the agent's receipt of a WAKE event so the watcher stops nudging.

    The agent calls `ship ack <hint> <sha>` the moment it picks up a WAKE
    line. The watch loop reads `wake_ack` each poll and, while it matches the
    live wake, backs off from the aggressive un-acked nudge cadence to the long
    safety cadence — the agent is engaged, so don't spam it."""
    pr = _resolve_pr_for_state()
    with _StateLock(pr):
        header, body = init_state_if_needed(pr)
        _nested_set(body, "wake_ack", {"hint": hint, "sha": sha})
        write_state_atomic(pr, header, body)


def _watch_read_ack(pr_number: int) -> tuple[str, str] | None:
    """The acked wake key `(hint, sha)` from the state file, or None. No `gh`
    (reads the state file directly), so the watch loop can poll it cheaply."""
    _, body = init_state_if_needed(pr_number)
    ack = body.get("wake_ack")
    if isinstance(ack, dict) and ack.get("hint") and ack.get("sha"):
        return (ack["hint"], ack["sha"])
    return None


def _watch_clear_ack(pr_number: int) -> None:
    """Invalidate a stale ack (agent ACKed then stalled past the safety cadence)
    so the re-nudged wake reverts to the aggressive un-acked cadence."""
    with _StateLock(pr_number):
        header, body = init_state_if_needed(pr_number)
        if body.get("wake_ack") is not None:
            _nested_set(body, "wake_ack", None)
            write_state_atomic(pr_number, header, body)


def _nested_get(d: dict[str, Any], dotted: str) -> Any:
    cur: Any = d
    # split(".", 1): state keys are <=2 levels ({counter: {subkey: int}}); a
    # subkey can be a dotted test FQN, so only the first dot separates levels.
    for part in dotted.split(".", 1):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _nested_set(d: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".", 1)  # 2-level max; subkeys (test FQNs) keep their dots
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _coerce(s: str) -> Any:
    """Best-effort scalar coercion for `state set` values."""
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() in ("null", "none"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    if s.startswith(("{", "[")):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    return s


# ---------------------------------------------------------------------------
# `ship rebase-attempt`
# ---------------------------------------------------------------------------


def cmd_rebase_attempt() -> dict[str, Any]:
    proc = run(["git", "rebase", _base_ref()])
    if proc.returncode == 0:
        pr = lookup_pr_number()
        if pr is not None:
            with _StateLock(pr):
                header, body = init_state_if_needed(pr)
                body["did_rebase"] = True
                body["force_rebase"] = False
                write_state_atomic(pr, header, body)
        return {"success": True, "conflicted_files": []}
    # abort + return conflict list
    status_proc = run(["git", "status", "--porcelain"])
    conflicted: list[dict[str, Any]] = []
    for line in (status_proc.stdout or "").splitlines():
        if line.startswith("UU ") or line.startswith("AA "):
            path = line[3:].strip()
            conflicted.append(
                {
                    "path": path,
                    "can_auto_resolve": False,
                    "conflict_markers": [],
                }
            )
    run(["git", "rebase", "--abort"])
    return {"success": False, "conflicted_files": conflicted}


# ---------------------------------------------------------------------------
# `ship push`
# ---------------------------------------------------------------------------


def cmd_push(*, force_with_lease: bool = False, force: bool = False) -> dict[str, Any]:
    """Push current branch, optionally --force-with-lease. Clears did_rebase on
    success so the per-iter state-write ordering invariant holds. `force` is
    kept for signature compatibility (no-op gate).
    """
    cmd = ["git", "push"]
    if force_with_lease:
        cmd.append("--force-with-lease")
    cmd.extend(["origin", "HEAD"])
    proc = run(cmd)
    if proc.returncode != 0:
        return {"success": False, "stderr": (proc.stderr or "").strip()}
    pr = lookup_pr_number()
    if pr is not None:
        with _StateLock(pr):
            header, body = init_state_if_needed(pr)
            body["did_rebase"] = False
            body["force_rebase"] = False
            write_state_atomic(pr, header, body)
    return {"success": True}


# ---------------------------------------------------------------------------
# `ship extract-failed-tests`
# ---------------------------------------------------------------------------


# Mechanical flake signals come from config flakePatterns (FLAKE_MECHANISMS in
# _apply_config): order-preserving first-match rows of (mechanism, regex, hint).
# A failed-log frame matching one is a known-flaky mechanism the skill can
# deflake inline without a fixer agent.


def _fetch_failed_log(workflow_run_id: str) -> str:
    """Best-effort fetch of a run's failed-step log. Empty string on error."""
    proc = run(["gh", "run", "view", workflow_run_id, "--log-failed"])
    return (proc.stdout or "") if proc.returncode == 0 else ""


def _parse_failed_fqns(log: str) -> list[str]:
    """Failed-test ids via the configured failedTestRegex. Empty config value
    ⇒ always [] (callers must tolerate). Capture groups, when present, are
    dot-joined into the id; otherwise the whole match is used."""
    if FAILED_FQN_RX is None:
        return []
    fqns: set[str] = set()
    for m in FAILED_FQN_RX.finditer(log):
        groups = [g for g in m.groups() if g]
        fqns.add(".".join(groups) if groups else m.group(0))
    return sorted(fqns)


def _line_at(log: str, idx: int) -> str:
    start = log.rfind("\n", 0, idx) + 1
    end = log.find("\n", idx)
    return log[start : (end if end != -1 else len(log))].strip()[:200]


def classify_flaky(log: str) -> dict[str, Any]:
    """Map a failed-log to a configured flake mechanism, or is_flaky=False.

    Row order matters (first match wins): keep specific patterns before broad
    substrings like `timeout` in the config so a specific failure whose
    message also mentions a timeout classifies by its real mechanism.
    """
    for mechanism, rx, hint in FLAKE_MECHANISMS:
        m = rx.search(log)
        if m:
            return {
                "is_flaky": True,
                "mechanism": mechanism,
                "hint": hint,
                "matched_frame": _line_at(log, m.start()),
            }
    return {"is_flaky": False, "mechanism": None, "hint": None, "matched_frame": None}


def cmd_extract_failed_tests(workflow_run_id: str) -> list[str]:
    """Best-effort: scan a run's failed-step log for failed test FQNs."""
    return _parse_failed_fqns(_fetch_failed_log(workflow_run_id))


# ---------------------------------------------------------------------------
# `ship watch` — event-driven watch loop (Monitor-consumed)
# ---------------------------------------------------------------------------
#
# Principle: wake the agent (stdout) ONLY when it must exercise judgment. The
# watcher swallows all waiting (stderr) and performs mechanical actions itself,
# waking only on failure or a judgment gate. See README.md "Watch lifecycle".


class WatchDecision(NamedTuple):
    """One poll's decision. stdout != None is the ONLY thing that wakes the agent."""

    stdout: dict[str, Any] | None  # JSON event to emit (a wake), or None
    stderr: str | None             # silent diagnostic (file-only), or None
    action: str | None             # mechanical action the loop must run, or None
    do_exit: bool                  # terminate the watch after this decision
    sleep: int                     # seconds to sleep before the next poll


def _watch_event(envelope: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Build a stdout event from the status envelope, prefixed event=transition.

    `overrides` win over envelope fields (dict.update after the spread), so a
    caller can force e.g. hint="halt". Keep override keys to fields a consumer
    keys on (hint/reason) — overriding sha/pr_url would silently replace the
    live envelope values.
    """
    ev = {"event": "transition", **envelope}
    ev.update(overrides)
    return ev


def _wait_ci_cadence(*, elapsed: int, est_total: int | None) -> int:
    """Phased wait_ci sleep. elapsed = seconds since the CI run started;
    est_total = historical-avg run duration (None when unknown).

    Zones: fast-fail (0..FASTFAIL_WINDOW → dense 30s, catches compile errors
    right after a push), dead-middle (one long sleep toward est completion),
    landing (within LANDING_BUFFER of est, or overrun → 60s). The estimate is a
    FLOOR on sleep, never a 'done at X' — a failure flips the hint to ci_failed
    on the next poll regardless of cadence.
    """
    if elapsed < SHIP_FASTFAIL_WINDOW:
        return SHIP_FASTFAIL_CADENCE
    if est_total is None:
        return CADENCE_WAIT_CI
    remaining = est_total - SHIP_LANDING_BUFFER - elapsed
    if remaining <= 0:
        return 60  # landing zone or overrun — tighten up
    return max(60, remaining)


def _watch_decide(
    envelope: dict[str, Any],
    *,
    merge_flag: bool,
    last_wake_key: tuple[str, str] | None,
    wait_elapsed: int,
    rewake: bool = False,
    nudge: int = 0,
    draft_flag: bool = False,
) -> WatchDecision:
    """Pure wake-taxonomy decision for one poll. No I/O.

    Caller contract: update last_wake_key to (hint, sha) only when the returned
    stdout is not None — updating it unconditionally breaks WAKE dedup.

    `rewake` (caller sets it once the prior wake has gone stale) forces a
    persisting WAKE hint to re-emit instead of staying deduped-silent — so a
    single missed wake notification can't stall the watch indefinitely. `nudge`
    (>0 only on a re-emit) rides along in the event as an escalating counter so
    the agent never dedups a re-nudge against the first emit it already missed.

    `draft_flag` (the --draft watch flag) inverts the promote_draft AUTO action
    into a WAKE-terminal handoff — the watcher holds the PR as a draft instead of
    promoting it. Mutually exclusive with merge_flag (the CLI enforces it).
    """
    hint = envelope.get("hint") or ""
    sha = envelope.get("sha") or ""
    cadence = int(envelope.get("cadence_hint_seconds") or 60)
    reason = envelope.get("reason") or ""
    key = (hint, sha)

    # Terminal halt — always a wake (no dedup: halt must always surface).
    if hint == "halt":
        return WatchDecision(_watch_event(envelope), None, None, True, 0)

    # clean_exit: AUTO-merge under --merge, else WAKE-terminal (agent merges).
    if hint == "clean_exit":
        if merge_flag:
            return WatchDecision(None, f"auto-merge: {reason}", "merge", False, 0)
        return WatchDecision(_watch_event(envelope), None, None, True, 0)

    # promote_draft: AUTO-promote, UNLESS --draft → terminal held_draft WAKE (agent promotes by hand).
    if hint == "promote_draft":
        if draft_flag:
            held = _watch_event(
                envelope, hint="held_draft",
                reason="CI green; held as draft (--draft) — promote manually when ready",
            )
            return WatchDecision(held, None, None, True, 0)
        return WatchDecision(None, f"auto-promote: {reason}", "promote", False, 0)

    # retrigger_review: AUTO always — _classify_hint only emits it when the
    # matched bot opted in (`retrigger: true`) and its BLOCKING sticky is stale
    # (every finding addressed). Nudge the bot via a draft→ready toggle
    # (re-runs review only). Self-capped in the action → halt once it keeps
    # re-blocking past caps.retriggerReview. Default-off path never reaches here.
    if hint == "retrigger_review":
        return WatchDecision(None, f"auto-retrigger: {reason}", "retrigger", False, 0)

    # behind_base: AUTO under --merge (rebase-decision gates conflict→wake),
    # else a plain WAKE so the agent rebases.
    if hint == "behind_base" and merge_flag:
        return WatchDecision(None, f"auto-rebase: {reason}", "rebase", False, 0)

    # WAKE hints (judgment) + behind_base without --merge.
    if hint in WAKE_HINTS or hint == "behind_base":
        if key != last_wake_key or rewake:
            overrides = {"nudge": nudge} if nudge > 0 else {}
            return WatchDecision(_watch_event(envelope, **overrides), None, None, False, cadence)
        return WatchDecision(None, f"{hint} persists (already woken)", None, False, cadence)

    # WAIT hints: silent, but enforce the wall-clock cap → halt.
    if hint in WAIT_HINTS:
        cap = WAIT_WALLCLOCK_CAP.get(hint)
        if cap is not None and wait_elapsed >= cap:
            halt = _watch_event(
                envelope, hint="halt",
                reason=f"{hint} exceeded wall-clock cap {cap}s ({wait_elapsed}s waited)",
            )
            return WatchDecision(halt, None, None, True, 0)
        sleep = cadence
        if hint == "wait_ci":
            # cmd_status populates ci_elapsed/ci_est_total from the per-job
            # durationsFile baseline when present, so the dead-middle sleep
            # targets predicted completion. When the file is absent or no in-progress
            # job matches a baseline key, est_total is None → dead-middle falls back to
            # the fixed CADENCE_WAIT_CI; the fast-fail window still works via wait_elapsed.
            # `or wait_elapsed`: a 0 suite-elapsed (all jobs still queued) is falsy by
            # design — the watcher's own clock is the better estimate until a job starts.
            sleep = _wait_ci_cadence(
                elapsed=int(envelope.get("ci_elapsed") or wait_elapsed),
                est_total=envelope.get("ci_est_total"),
            )
        return WatchDecision(None, f"{hint}: {reason} (waited {wait_elapsed}s, next {sleep}s)", None, False, sleep)

    # Unknown hint: wake to be safe, and re-nudge like a WAKE so the re-nudge
    # guarantee covers every surfaced wake, not just the classified ones.
    if key != last_wake_key or rewake:
        overrides: dict[str, Any] = {"reason": f"unclassified hint {hint!r}"}
        if nudge > 0:
            overrides["nudge"] = nudge
        return WatchDecision(
            _watch_event(envelope, **overrides),
            None, None, False, cadence,
        )
    return WatchDecision(None, f"unknown hint {hint!r} (already woken)", None, False, cadence)


def _merge_gate(
    *,
    classified: dict[str, Any],
    merge_state: str | None,
    review_decision: str | None,
    latest_reviews: list[dict[str, Any]],
    threads_addressed: bool,
) -> tuple[bool, str, str]:
    """Pure pre-merge gate. Returns (ok, wake, reason).

    Merge ONLY if: CI green AND mergeable AND every review thread addressed AND
    (review approved OR — when no reviewBots are configured — the approval
    sub-check is skipped). Any condition false ⇒ ok=False plus the wake the
    watcher should surface: `wait_ci` (CI not green / not yet mergeable),
    `behind_base` (PR behind its base), `fetch_threads` (open thread),
    `wait_review` (no affirmative approval). Enforced against a FRESH fetch at
    merge time (see `_fetch_merge_gate`) so a race between the clean_exit poll
    and the merge action can't land a red/behind/unaddressed/unapproved merge.

    Every failure condition here is one the clean_exit hint already required, so
    a block implies the poll's state went stale — the next poll legitimately
    re-classifies and no hot-loop forms. With empty reviewBots the approval
    sub-check is skipped, so the gate never deadlocks waiting for an approval
    that no bot will give.
    """
    if classified.get("total", 0) == 0:
        return False, "wait_ci", "no check-runs on HEAD"
    if classified.get("any_failure"):
        return False, "wait_ci", "CI has failing/cancelled check-runs"
    if classified.get("any_pending"):
        return False, "wait_ci", "CI still in progress"
    if merge_state == "BEHIND":
        return False, "behind_base", "PR behind its base branch"
    if merge_state not in MERGEABLE_STATES:
        return False, "wait_ci", f"not mergeable (mergeStateStatus={merge_state})"
    if not threads_addressed:
        return False, "fetch_threads", "unaddressed review thread(s)"
    # Approval sub-check only when review bots are configured; otherwise skipped.
    if REVIEW_BOTS:
        if review_decision in ("CHANGES_REQUESTED", "REVIEW_REQUIRED"):
            return False, "wait_review", f"review blocking (reviewDecision={review_decision})"
        approved = review_decision == "APPROVED" or any(
            r.get("state") == "APPROVED" for r in latest_reviews
        )
        if not approved:
            return False, "wait_review", "no affirmative approval (latest review not APPROVED)"
    return True, "", "CI green, mergeable, threads addressed, approved"


def _fetch_merge_gate(pr_number: int) -> dict[str, Any]:
    """Fresh fetch of the CI / mergeability / review / thread inputs `_merge_gate`
    needs, all keyed on `pr_number` from one `gh pr view` (so an explicit
    `merge-pr --pr-number N` from a branch tracking a different PR can't mix a
    foreign branch's state with PR N's). Threads are fetched paginated and scored
    with the config-driven `_thread_addressed`. A gh/JSON failure degrades to a
    blocking-empty input → `_merge_gate` never merges."""
    pr = gh_json(
        [
            "pr", "view", str(pr_number),
            "--json", "mergeStateStatus,reviewDecision,headRefOid,latestReviews",
        ]
    ) or {}
    sha = pr.get("headRefOid") or current_sha()
    slug = gh_repo_slug()
    resp = gh_json(
        ["api", f"repos/{slug}/commits/{sha}/check-runs?per_page=100"]
    ) or {"check_runs": []}
    try:
        data, nodes = fetch_all_review_threads(pr_number, _THREAD_STATE_NODE_SELECTION)
        viewer = (data.get("viewer") or {}).get("login")
        threads_addressed = all(_thread_addressed(t, viewer) for t in nodes)
    except ReviewThreadFetchError:
        threads_addressed = False  # unknown thread state ⇒ block, never merge
    return {
        "classified": classify_check_runs(resp.get("check_runs", [])),
        "merge_state": pr.get("mergeStateStatus"),
        "review_decision": pr.get("reviewDecision"),
        "latest_reviews": pr.get("latestReviews") or [],
        "threads_addressed": threads_addressed,
    }


def _watch_do_merge(pr_number: int) -> tuple[str, str]:
    """Hard merge gate + merge with the configured mergeMethod.

    Re-fetches live state and runs `_merge_gate` before touching `gh pr merge`.
    A blocked gate returns 'ok' with the gate's wake in the detail — the loop
    logs it and re-polls, which surfaces the real taxonomy wake (wait_ci silent,
    fetch_threads/behind_base a WAKE) via normal classification; it never merges.
    On a passing gate, `cmd_merge_pr` dies on a merge error → caught here as
    halt. On success returns 'done': the watcher CANNOT remove its own active
    worktree (ship refuses), so it emits the terminal DONE line and the agent
    does the cd-out + cleanup-worktree on that notification.
    """
    ok, wake, reason = _merge_gate(**_fetch_merge_gate(pr_number))
    if not ok:
        return ("ok", f"merge gate blocked [{wake}]: {reason} — re-polling")
    try:
        cmd_merge_pr(pr_number)
    except SystemExit as e:
        return ("halt", f"merge halted (exit {e.code}) — needs the agent")
    return ("done", "merged; agent does worktree cleanup")


def _do_retrigger_review(pr_number: int) -> tuple[str, str]:
    """Nudge the review bot to re-run without changing the sha or re-running CI.

    A draft→ready toggle fires the ready_for_review event (which review-only
    workflows key on) but not the push/synchronize event the full CI suite keys
    on, so it re-runs only the review. The bot then re-reads the (now addressed)
    finding threads → 0 surviving findings → an approving verdict that clears
    reviewDecision. Closes the gap where a BLOCKING sticky never recomputes after
    a thread resolve and wait_reapproval spins to the cap.

    Load-bearing: the toggle must reset reviewDecision away from REVIEW_REQUIRED
    until the bot re-reviews. Otherwise the next ~1s poll re-satisfies the
    retrigger condition (bot not yet advanced, sticky still cached BLOCKING) and
    the toggle re-fires until the self-cap halts. The self-cap bounds the worst
    case to a premature halt, never an unbounded loop.

    Self-capped: increments retrigger_review_count and halts once it reaches
    caps.retriggerReview (RETRIGGER_REVIEW_CAP) — a bot that keeps re-blocking on
    already-addressed findings needs a human, not another toggle. The watch
    loop's per-poll cap gate (`_cap_hits`) also catches this. Returns a
    `_watch_run_action` (outcome, detail) tuple.
    """
    header, body = init_state_if_needed(pr_number)
    count = int(body.get("retrigger_review_count", 0) or 0)
    if count >= RETRIGGER_REVIEW_CAP:
        return (
            "halt",
            f"review bot still BLOCKING after {count} retrigger(s) — "
            "needs human approval or a real fix",
        )
    _nested_set(body, "retrigger_review_count", count + 1)
    write_state_atomic(pr_number, header, body)
    undo = run(["gh", "pr", "ready", str(pr_number), "--undo"])
    if undo.returncode != 0:
        return ("halt", f"retrigger draft toggle failed: {undo.stderr.strip()}")
    ready = run(["gh", "pr", "ready", str(pr_number)])
    if ready.returncode != 0:
        return ("halt", f"retrigger ready toggle failed: {ready.stderr.strip()}")
    return ("ok", f"retriggered review bot (draft toggle {count + 1}/{RETRIGGER_REVIEW_CAP})")


def _watch_run_action(action: str, pr_number: int, *, merge_flag: bool, reply_only: bool = False) -> tuple[str, str]:
    """Run a mechanical AUTO action. Returns (outcome, detail):
      'ok'   — succeeded, keep watching (state changed; re-poll next iter)
      'done' — terminal success (merged), exit with a DONE event
      'halt' — needs the agent, exit with a halt wake
    """
    if reply_only and action in ("promote", "rebase", "merge", "retrigger"):
        return ("halt", f"{action} suppressed in --reply-only mode (not PR owner) — agent must act")
    if action == "retrigger":
        return _do_retrigger_review(pr_number)

    if action == "promote":
        try:
            cmd_promote_draft()
            return ("ok", "promoted draft to ready")
        except SystemExit as e:
            return ("halt", f"promote-draft failed (exit {e.code})")

    if action == "merge":
        return _watch_do_merge(pr_number)

    if action == "rebase":
        decision = cmd_rebase_decision()
        if decision.get("decision") == "SKIP":
            # behind_base + --merge + nothing to rebase → BEHIND-terminal merge
            # (mirrors the existing skill's behind_base SKIP → merge-pr path).
            return _watch_do_merge(pr_number)
        # Never auto-resolve a conflict / hot-file / cross-edit — hand to the agent.
        if decision.get("code_overlap") or decision.get("hot_files_changed"):
            return ("halt", f"rebase needs judgment: {decision.get('reason')}")
        result = cmd_rebase_attempt()
        if not result.get("success"):
            paths = [c.get("path") for c in result.get("conflicted_files", [])]
            return ("halt", f"rebase conflict on {paths} — needs the agent")
        push = cmd_push(force_with_lease=True)
        if not push.get("success"):
            return ("halt", f"force-push after rebase failed: {push.get('stderr')}")
        return ("ok", "rebased + force-pushed")

    return ("halt", f"unknown action {action!r}")


def cmd_watch(
    *,
    merge_flag: bool = False,
    reply_only: bool = False,
    draft_flag: bool = False,
    pr_number: int,
    poll: Callable[[], dict[str, Any]] = cmd_status,
    sleeper: Callable[[int], None] = time.sleep,
    rate_remaining: Callable[[], dict[str, Any]] = rate_limit_remaining,
    run_action: Callable[..., tuple[str, str]] = _watch_run_action,
    check_caps: Callable[[int], list[str]] | None = None,
    read_ack: Callable[[int], tuple[str, str] | None] | None = None,
    clear_ack: Callable[[int], None] | None = None,
    core_floor: int | None = None,
    graphql_floor: int | None = None,
    rewake_seconds: int | None = None,
    unacked_rewake_seconds: int | None = None,
    max_iters: int = 0,
) -> int:
    """Long-running watch loop. Emits a stdout line ONLY on a wake; everything
    else (waits, throttle, AUTO-action success) goes to stderr. Exits on a
    terminal hint or a DONE/halt action outcome. Dependencies are injected so
    tests run without shelling or sleeping. `max_iters=0` means unbounded.

    `check_caps(pr_number)` (when supplied) runs each poll; any returned cap key
    (e.g. `ci_fail_count.foo` at 3) emits a halt and exits — the Monitor-model
    equivalent of the old loop's per-iter `ship state check-caps`.

    A persisting WAKE re-emits so one missed wake can't stall forever. The
    cadence is ACK-gated via `read_ack(pr_number)` (the `(hint, sha)` the agent
    last `ship ack`ed, or None): un-acked -> `unacked_rewake_seconds` with an
    escalating `nudge` counter; acked -> the long `rewake_seconds` safety net. A
    safety re-nudge that fires despite an ack treats the ack as stale and calls
    `clear_ack(pr_number)`, dropping back to the aggressive cadence.
    """
    # None ⇒ the config-initialized module constants (resolved at call time so
    # a lazily-loaded config, not the import-time defaults, wins).
    if core_floor is None:
        core_floor = RATE_FLOOR_CORE
    if graphql_floor is None:
        graphql_floor = RATE_FLOOR_GRAPHQL
    if rewake_seconds is None:
        rewake_seconds = SHIP_REWAKE_SECONDS
    if unacked_rewake_seconds is None:
        unacked_rewake_seconds = SHIP_UNACKED_REWAKE_SECONDS

    last_wake_key: tuple[str, str] | None = None
    last_wake_at = 0.0
    nudge_count = 0
    wait_hint: str | None = None
    wait_started = 0.0
    iters = 0

    os.environ.setdefault("SHIP_BASE_REF", _pr_base_ref(pr_number))
    os.environ["SHIP_PR_NUMBER"] = str(pr_number)

    def log(msg: str) -> None:
        sys.stderr.write(msg.rstrip("\n") + "\n")
        sys.stderr.flush()

    while True:
        iters += 1

        # Free rate-limit gate — yield budget to working agents below the floor.
        rem = rate_remaining()
        if not _rate_floor_ok(rem, core_floor=core_floor, graphql_floor=graphql_floor):
            reset_in = int(rem.get("reset_in") or 60)
            log(f"throttled: rate floor; core={rem.get('core')} graphql={rem.get('graphql')} reset_in={reset_in}")
            if max_iters and iters >= max_iters:
                return EXIT_OK
            sleeper(min(reset_in, 60))
            continue

        # Halt-cap gate — repeated CI failures / empty-runs reach cap → stop.
        if check_caps is not None:
            caps = check_caps(pr_number)
            if caps:
                _emit({"event": "transition", "hint": "halt",
                       "reason": f"halt cap reached: {', '.join(caps)}",
                       "pr_url": pr_web_url(pr_number)})
                return EXIT_OK

        try:
            env = poll()
        except SystemExit as exc:
            # poll() (cmd_status -> gh_json) raises die(EXIT_TRANSIENT) on a
            # rate-limit; a long-running watch must back off and resume, not die.
            # Non-transient exits (halt) still propagate. The next iteration's
            # rate-floor probe handles sustained limiting.
            if exc.code != EXIT_TRANSIENT:
                raise
            log("transient gh error in poll (rate-limit?); backing off 60s")
            if max_iters and iters >= max_iters:
                return EXIT_OK
            sleeper(60)
            continue
        hint = env.get("hint") or ""

        # Track elapsed time in the current wait hint (for wall-clock caps).
        if hint in WAIT_HINTS:
            if wait_hint != hint:
                wait_hint = hint
                wait_started = time.time()
            wait_elapsed = int(time.time() - wait_started)
        else:
            wait_hint = None
            wait_elapsed = 0

        # Re-wake a still-live WAKE hint once the prior wake has gone stale. The
        # staleness window is ACK-gated: short while un-acked (nudge hard until
        # the agent signals receipt), long once acked (dead-man's switch only).
        ack = read_ack(pr_number) if read_ack else None
        acked = last_wake_key is not None and ack == last_wake_key
        interval = rewake_seconds if acked else unacked_rewake_seconds
        rewake = last_wake_key is not None and (time.time() - last_wake_at) >= interval
        # A re-emit of the same key carries the next nudge number; a fresh key resets it.
        cur_key = (hint, env.get("sha") or "")
        is_renudge = rewake and cur_key == last_wake_key
        nudge = nudge_count + 1 if is_renudge else 0

        decision = _watch_decide(
            env, merge_flag=merge_flag,
            last_wake_key=last_wake_key, wait_elapsed=wait_elapsed,
            rewake=rewake, nudge=nudge,
            draft_flag=draft_flag,
        )

        if decision.stderr:
            log(decision.stderr)

        if decision.action:
            outcome, detail = run_action(decision.action, pr_number, merge_flag=merge_flag, reply_only=reply_only)
            if outcome == "halt":
                _emit(_watch_event(env, hint="halt", reason=detail))
                return EXIT_OK
            if outcome == "done":
                _emit({"event": "done", "reason": detail, "pr_url": env.get("pr_url", "")})
                return EXIT_OK
            log(f"auto-action {decision.action}: {detail}")
            if max_iters and iters >= max_iters:
                return EXIT_OK
            # Brief backoff before re-polling: the action changed state (promote
            # → ready, rebase → new sha), but a defensive sleep keeps a stuck
            # "ok" (state didn't actually move) from hot-spinning the loop.
            sleeper(1)
            continue

        if decision.stdout is not None:
            if cur_key == last_wake_key and rewake:
                nudge_count += 1
                # Acked but still re-nudging -> the ack was stale (agent stalled);
                # drop it so the next poll uses the aggressive un-acked cadence.
                if acked and clear_ack:
                    clear_ack(pr_number)
            else:
                nudge_count = 0
            last_wake_key = cur_key
            last_wake_at = time.time()
            _emit(decision.stdout)

        if decision.do_exit:
            return EXIT_OK

        if max_iters and iters >= max_iters:
            return EXIT_OK

        sleeper(decision.sleep)


# ---------------------------------------------------------------------------
# `ship doctor` — environment/config preflight
# ---------------------------------------------------------------------------


def cmd_doctor() -> int:
    """Human-readable preflight: gh auth, repo slug, config, base ref. Exit 0/1."""
    ok = True

    def report(label: str, good: bool, detail: str = "", *, hard: bool = True) -> None:
        nonlocal ok
        mark = "ok  " if good else ("FAIL" if hard else "warn")
        print(f"{mark} {label}" + (f" — {detail}" if detail else ""))
        if not good and hard:
            ok = False

    auth = run(["gh", "auth", "status"])
    detail = "" if auth.returncode == 0 else (auth.stderr or auth.stdout or "").strip().splitlines()[0] if (auth.stderr or auth.stdout or "").strip() else "gh auth status failed"
    report("gh auth", auth.returncode == 0, detail)

    slug_proc = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    slug = slug_proc.stdout.strip() if slug_proc.returncode == 0 else ""
    report("repo slug", bool(slug), slug or "not resolvable (run inside a repo with a GitHub remote)")

    root = _repo_root()
    cfg_path = (root / ".claude" / "develop.config.json") if root else None
    report("config file", bool(cfg_path and cfg_path.exists()),
           str(cfg_path) if cfg_path else "not a git repo", hard=False)
    _config()
    report("ship config section", _CONFIG_SECTION_FOUND,
           "present" if _CONFIG_SECTION_FOUND else "missing — defaults in use (run /develop:init)",
           hard=False)

    base = _base_ref()
    report("base ref", bool(base), base)

    print(f"launch: python3 {Path(__file__).resolve()} watch [--merge]")
    return EXIT_OK if ok else 1


# ---------------------------------------------------------------------------
# `ship --selftest` — stdlib-only inline assertions (no network, no gh)
# ---------------------------------------------------------------------------


def _selftest() -> int:
    global _CONFIG, _CONFIG_SECTION_FOUND
    checks = 0

    def ok(cond: bool, msg: str) -> None:
        nonlocal checks
        if not cond:
            print(f"selftest FAILED: {msg}")
            sys.exit(1)
        checks += 1

    # 1. Config deep-merge: override wins per-key, siblings survive.
    merged = _deep_merge({"a": 1, "caps": {"ciFail": 3, "flakySoak": 3}},
                         {"caps": {"ciFail": 5}, "hotPaths": ["x"]})
    ok(merged == {"a": 1, "caps": {"ciFail": 5, "flakySoak": 3}, "hotPaths": ["x"]},
       "deep-merge override/sibling semantics")
    cfg = _deep_merge(json.loads(json.dumps(DEFAULTS)),
                      {"baseBranch": "develop", "caps": {"ciFail": 2}})
    ok(cfg["caps"]["ciFail"] == 2 and cfg["caps"]["flakySoak"] == 3
       and cfg["baseBranch"] == "develop" and cfg["mergeMethod"] == "squash",
       "defaults + ship-section merge")
    # Seed the cached config so nothing below shells git/gh.
    _CONFIG = cfg
    _CONFIG_SECTION_FOUND = True
    _apply_config(cfg)

    # 2. Base-ref normalization.
    ok(_normalize_base_ref("") == "origin/develop", "empty ref → configured base")
    ok(_normalize_base_ref("main") == "origin/main", "bare branch gets origin/")
    ok(_normalize_base_ref("release/1.0") == "origin/release/1.0",
       "slashed non-remote gets origin/")
    ok(_normalize_base_ref("upstream/main") == "upstream/main", "known remote kept")

    # 3. flakePatterns classification (default rows, order-preserving).
    ok(classify_flaky("java.lang.OutOfMemoryError: Java heap space")["mechanism"] == "memory",
       "flake: memory")
    ok(classify_flaky("Connection refused: no further information")["mechanism"] == "network",
       "flake: network")
    ok(classify_flaky("Test timed out — Timeout waiting for reply")["mechanism"] == "timing",
       "flake: timing")
    ok(classify_flaky("ordinary assertion failure")["is_flaky"] is False, "flake: none")

    # 4. Watch decide/hint taxonomy on synthetic envelopes.
    env_halt = {"hint": "halt", "sha": "s1", "cadence_hint_seconds": 0, "reason": "r"}
    d = _watch_decide(env_halt, merge_flag=False, last_wake_key=None, wait_elapsed=0)
    ok(d.stdout is not None and d.do_exit, "halt wakes + exits")
    env_clean = {"hint": "clean_exit", "sha": "s1", "cadence_hint_seconds": 0, "reason": "r"}
    d = _watch_decide(env_clean, merge_flag=True, last_wake_key=None, wait_elapsed=0)
    ok(d.action == "merge" and d.stdout is None, "clean_exit + --merge → AUTO merge")
    d = _watch_decide(env_clean, merge_flag=False, last_wake_key=None, wait_elapsed=0)
    ok(d.stdout is not None and d.do_exit, "clean_exit without --merge → WAKE-terminal")
    env_fail = {"hint": "ci_failed", "sha": "s2", "cadence_hint_seconds": 0, "reason": "r"}
    d = _watch_decide(env_fail, merge_flag=False, last_wake_key=None, wait_elapsed=0)
    ok(d.stdout is not None and not d.do_exit, "ci_failed wakes")
    d = _watch_decide(env_fail, merge_flag=False, last_wake_key=("ci_failed", "s2"), wait_elapsed=0)
    ok(d.stdout is None, "same (hint, sha) wake dedups")
    env_wait = {"hint": "wait_ci", "sha": "s2", "cadence_hint_seconds": 270, "reason": "r"}
    d = _watch_decide(env_wait, merge_flag=False, last_wake_key=None, wait_elapsed=10)
    ok(d.stdout is None and d.sleep == SHIP_FASTFAIL_CADENCE, "wait_ci is silent, fast-fail cadence")
    env_frv = {"hint": "wait_first_review", "sha": "s2", "cadence_hint_seconds": 90, "reason": "r"}
    d = _watch_decide(env_frv, merge_flag=False, last_wake_key=None,
                      wait_elapsed=WAIT_WALLCLOCK_CAP["wait_first_review"] + 1)
    ok(d.stdout is not None and d.do_exit and d.stdout.get("hint") == "halt",
       "wait wall-clock cap escalates to halt")

    # 5. Cap-hit detection (ciFail overridden to 2 above).
    ok(_cap_hits({"ci_fail_count": {"lint": 2}}) == ["ci_fail_count.lint"], "cap hit at threshold")
    ok(_cap_hits({"ci_fail_count": {"lint": 1}, "empty_runs_mergeable_count": 0}) == [],
       "no cap hit below threshold")

    # 6. Cadence math: fast-fail window vs landing buffer vs fallback.
    ok(_wait_ci_cadence(elapsed=10, est_total=None) == SHIP_FASTFAIL_CADENCE,
       "fast-fail window → dense cadence")
    ok(_wait_ci_cadence(elapsed=SHIP_FASTFAIL_WINDOW + 1, est_total=None) == CADENCE_WAIT_CI,
       "no baseline → fixed waitCi fallback")
    ok(_wait_ci_cadence(elapsed=200, est_total=1000) == 1000 - SHIP_LANDING_BUFFER - 200,
       "dead-middle sleeps toward estimate")
    ok(_wait_ci_cadence(elapsed=950, est_total=1000) == 60, "landing buffer tightens to 60s")

    # 7. failedTestRegex: empty ⇒ [], configured ⇒ dot-joined groups.
    ok(_parse_failed_fqns("com.example.FooTest > bar FAILED") == [],
       "empty failedTestRegex → no failed tests")
    _apply_config(_deep_merge(cfg, {"failedTestRegex": r"(\S+) > (\S+) FAILED"}))
    ok(_parse_failed_fqns("com.example.FooTest > bar FAILED") == ["com.example.FooTest.bar"],
       "configured failedTestRegex extracts + joins groups")
    _apply_config(cfg)

    # 8. Paginated review-thread fetch: walk a mock 2-page cursor.
    class _FakeProc:
        def __init__(self, stdout: str) -> None:
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def _page(has_next: bool, cursor: Any, node: dict[str, Any]) -> str:
        return json.dumps({"data": {"viewer": {"login": "me"}, "repository": {"pullRequest": {
            "reviewThreads": {"pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                              "nodes": [node]}}}}})

    pages = [_page(True, "CUR1", {"isResolved": True}), _page(False, None, {"isResolved": False})]
    calls: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> Any:
        calls.append(cmd)
        return _FakeProc(pages[len(calls) - 1])

    _orig_slug = globals()["gh_repo_slug"]
    globals()["gh_repo_slug"] = lambda: "owner/repo"
    try:
        data, nodes = fetch_all_review_threads(1, _THREAD_STATE_NODE_SELECTION, runner=fake_runner)
        ok(len(nodes) == 2 and len(calls) == 2, "pagination walks both cursor pages")
        ok("cursor=CUR1" in calls[1], "page-2 request carries the page-1 endCursor")
        ok((data.get("viewer") or {}).get("login") == "me", "first-page data (viewer) returned")
    finally:
        globals()["gh_repo_slug"] = _orig_slug

    # 9. Sticky meta parse: meta mode vs plain mode vs empty reviewBots.
    meta_bot = {"stickyBeacon": "<!-- rb -->", "stickyMeta": True, "retrigger": True}
    plain_bot = {"stickyBeacon": "<!-- rb -->", "stickyMeta": False}
    meta_comments = [{"body": 'x <!-- rb --> {"sha":"abc","status":"BLOCKING","findings":[{"id":1},{"id":2}]} y'}]
    sm = _sticky_summary(meta_comments, [meta_bot])
    ok(sm["sticky_found"] and sm["sha"] == "abc" and sm["status"] == "BLOCKING"
       and sm["findings_count"] == 2 and sm["retrigger"] is True,
       "stickyMeta true parses embedded {sha,status,findings}")
    sp = _sticky_summary([{"body": "only a <!-- rb --> beacon here"}], [plain_bot])
    ok(sp["sticky_found"] and sp["sha"] is None and sp["status"] is None,
       "stickyMeta false → plain found/not-found (no meta)")
    sp2 = _sticky_summary(meta_comments, [plain_bot])
    ok(sp2["sticky_found"] and sp2["sha"] is None,
       "plain bot ignores embedded JSON even when present")
    ok(_sticky_summary([{"body": "nothing"}], [meta_bot])["sticky_found"] is False,
       "beacon absent → not found")
    ok(_sticky_summary([{"body": "x <!-- rb --> here"}], [])["sticky_found"] is False,
       "empty reviewBots → {found:false}")
    ok(_parse_sticky_meta('<!-- rb --> {"a":{"b":1}} tail', "<!-- rb -->") == {"a": {"b": 1}},
       "raw_decode parses nested braces whole (no regex truncation)")

    # 10. sticky_sha_stale + retrigger_review hints (require configured reviewBots).
    def _green() -> dict[str, Any]:
        return {"total": 1, "any_failure": False, "any_pending": False,
                "all_done_ok": True, "gating_total": 1,
                "review_present": True, "review_completed": True}
    cr = [{"name": "build"}]
    bots_cfg = _deep_merge(cfg, {"reviewBots": [
        {"checkNames": ["review"], "stickyBeacon": "<!-- rb -->",
         "stickyMeta": True, "retrigger": True}]})
    _apply_config(bots_cfg)

    h_stale = _classify_hint(
        check_runs=cr, classified=_green(), is_draft=False, merge_state="MERGEABLE",
        review_decision="APPROVED", review_requests=[], unaddressed_threads=0,
        pending_reviews=0, sticky={"sha": "OLD", "status": "BLOCKING", "retrigger": True},
        sha="NEW", bot_advanced=True, empty_mergeable_count=0)[0]
    ok(h_stale == "sticky_sha_stale", "sticky sha behind HEAD + bot advanced → sticky_sha_stale")

    h_retrig = _classify_hint(
        check_runs=cr, classified=_green(), is_draft=False, merge_state="BLOCKED",
        review_decision="REVIEW_REQUIRED", review_requests=[], unaddressed_threads=0,
        pending_reviews=0, sticky={"sha": "NEW", "status": "BLOCKING", "retrigger": True},
        sha="NEW", bot_advanced=False, empty_mergeable_count=0)[0]
    ok(h_retrig == "retrigger_review", "BLOCKING sticky + findings addressed + retrigger on → retrigger_review")

    h_noop = _classify_hint(
        check_runs=cr, classified=_green(), is_draft=False, merge_state="BLOCKED",
        review_decision="REVIEW_REQUIRED", review_requests=[], unaddressed_threads=0,
        pending_reviews=0, sticky={"sha": "NEW", "status": "BLOCKING", "retrigger": False},
        sha="NEW", bot_advanced=False, empty_mergeable_count=0)[0]
    ok(h_noop == "wait_reapproval", "retrigger default-off → wait_reapproval (strict no-op)")

    env_rt = {"hint": "retrigger_review", "sha": "s", "cadence_hint_seconds": 0, "reason": "r"}
    d = _watch_decide(env_rt, merge_flag=True, last_wake_key=None, wait_elapsed=0)
    ok(d.action == "retrigger" and d.stdout is None, "retrigger_review → AUTO retrigger action")

    # 11. Hard _merge_gate: pass-all merges; each single failure → its wake.
    ok(_merge_gate(classified=_green(), merge_state="CLEAN", review_decision="APPROVED",
                   latest_reviews=[], threads_addressed=True)[0],
       "merge gate: green + approved + threads addressed → merge")
    ok(_merge_gate(classified={"total": 1, "any_failure": False, "any_pending": True},
                   merge_state="CLEAN", review_decision="APPROVED", latest_reviews=[],
                   threads_addressed=True)[1] == "wait_ci", "gate: CI pending → wait_ci")
    ok(_merge_gate(classified=_green(), merge_state="BEHIND", review_decision="APPROVED",
                   latest_reviews=[], threads_addressed=True)[1] == "behind_base",
       "gate: behind base → behind_base")
    ok(_merge_gate(classified=_green(), merge_state="CLEAN", review_decision="APPROVED",
                   latest_reviews=[], threads_addressed=False)[1] == "fetch_threads",
       "gate: unaddressed thread → fetch_threads")
    ok(_merge_gate(classified=_green(), merge_state="CLEAN", review_decision="REVIEW_REQUIRED",
                   latest_reviews=[], threads_addressed=True)[1] == "wait_review",
       "gate: review blocking (bots configured) → wait_review")
    # empty reviewBots → approval sub-check skipped (must not deadlock).
    _apply_config(cfg)
    ok(_merge_gate(classified=_green(), merge_state="CLEAN", review_decision=None,
                   latest_reviews=[], threads_addressed=True)[0],
       "empty reviewBots → approval sub-check skipped, gate merges")

    print(f"selftest: {checks} checks passed")
    return EXIT_OK


# ---------------------------------------------------------------------------
# argparse dispatch
# ---------------------------------------------------------------------------


def _emit(obj: Any) -> None:
    """Print machine-consumed JSON compact (no indent).

    `ship status` runs every loop tick and its output lands in the agent's
    context; pretty-printing (`indent=2`) ~doubles the line count for zero
    benefit — the skill parses with `jq`, which is whitespace-agnostic.
    On-disk artifacts (state file, flake marker) keep indentation; those are
    human-inspected, not per-tick context.

    `flush=True` is load-bearing for `ship watch`: its stdout is a pipe (the
    Monitor captures it), so Python block-buffers by default and a printed event
    would sit unflushed in the 4KB buffer until the long-running loop fills it or
    exits — neither happens between wakes, so the Monitor never sees the line and
    the agent is never notified. stderr `log()` already flushes explicitly; this
    keeps the WAKE events on parity.
    """
    print(json.dumps(obj, separators=(",", ":")), flush=True)


def main(argv: list[str] | None = None) -> int:
    args_in = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args_in:
        return _selftest()
    _config()  # load + apply repo config before parser defaults / dispatch

    parser = argparse.ArgumentParser(prog="ship", description=__doc__)
    parser.add_argument("--selftest", action="store_true",
                        help="run stdlib-only inline assertions and exit (no gh/network)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Snapshot current PR state, emit hint envelope")

    sub.add_parser("doctor", help="Preflight: gh auth, repo slug, config, base ref; prints the watch launch line")

    sub.add_parser("failures", help="List failed check-runs with workflow_run_id")

    th = sub.add_parser("threads", help="Fetch review threads")
    th.add_argument(
        "--unresolved",
        action="store_true",
        help=(
            "Return only actionable threads — hide a thread only when it is "
            "both isResolved on GitHub AND the ship viewer has authored a "
            "reply on it. Everything else (open, resolved-without-reply, "
            "outdated-without-reply) is surfaced."
        ),
    )

    sub.add_parser("fetch-sticky-summary", help="Probe for a configured review bot's sticky comment")

    sub.add_parser(
        "size",
        help="Pre-push size tier + hot-path touch flag (mechanical)",
    )

    rd = sub.add_parser("rebase-decision", help="Decide whether to rebase")
    rd.add_argument("--force-rebase", action="store_true")

    sub.add_parser("rebase-attempt", help="Execute rebase, return conflict info")

    ph = sub.add_parser(
        "push",
        help=(
            "git push origin HEAD; --force-with-lease for the git flag; "
            "clears did_rebase on success"
        ),
    )
    ph.add_argument("--force-with-lease", action="store_true", dest="force_with_lease")
    ph.add_argument(
        "--force",
        action="store_true",
        dest="force",
        help="accepted for compatibility, no-op (tidy gate removed)",
    )

    rr = sub.add_parser("rerun-workflow", help="Re-run a failed workflow")
    rr.add_argument("workflow_run_id")

    ef = sub.add_parser("extract-failed-tests", help="Extract failed test FQNs from a run")
    ef.add_argument("workflow_run_id")

    sub.add_parser("promote-draft", help="Promote draft PR to ready")

    mp = sub.add_parser("merge-pr", help="Merge the PR with the configured mergeMethod (default squash)")
    mp.add_argument("--pr-number", type=int)

    fc = sub.add_parser("find-or-create-pr", help="Find or create PR")
    fc.add_argument("--draft", action="store_true", default=True)
    fc.add_argument("--ready", action="store_true")
    fc.add_argument("--title")
    fc.add_argument("--summary", help="Use `-` to read summary from stdin")

    sub.add_parser("branch-name-valid", help="Exit 0 iff branch can host a PR (not the base branch / detached)")

    pb = sub.add_parser("post-pr-body", help="Render PR body markdown from a summary line")
    pb.add_argument("--summary", required=True, help="Use `-` to read from stdin")

    rt = sub.add_parser(
        "reply-thread",
        help=(
            "Post a single inline reply on a review thread "
            "(addPullRequestReviewThreadReply). This is the ONLY sanctioned "
            "way to respond to a reviewer — it does NOT open or submit a "
            "review. Never use `gh pr review` / `gh api .../pulls/N/reviews` "
            "to respond: those create a pending review that surfaces as "
            "`wait_review_submit` and deadlocks the watcher."
        ),
    )
    rt.add_argument("thread_id")
    rt.add_argument("--body", required=True, help="Use `-` to read from stdin")

    rs = sub.add_parser("resolve-thread", help="Mark a review thread resolved (idempotent)")
    rs.add_argument("thread_id")

    cw = sub.add_parser(
        "cleanup-worktree",
        help="Remove a worktree (must be named via <path> or --branch)",
    )
    cw.add_argument("path", nargs="?", help="Worktree path to remove")
    cw.add_argument("--branch", help="Resolve worktree path from branch name")

    ft = sub.add_parser("open-flake-ticket", help="Write the flake-ticket handoff marker (skill files it via ticketRoute)")
    ft.add_argument("fqn")
    ft.add_argument("--module", required=True)
    ft.add_argument("--run-url", required=True)
    ft.add_argument("--frames", required=True)
    ft.add_argument("--pr-number", type=int, default=None,
                    help="Override PR number for the marker filename")

    st = sub.add_parser("state", help="State file ops")
    st_sub = st.add_subparsers(dest="state_cmd", required=True)
    sg = st_sub.add_parser("get")
    sg.add_argument("key")
    ss = st_sub.add_parser("set")
    ss.add_argument("key")
    ss.add_argument("value")
    si = st_sub.add_parser("inc")
    si.add_argument("key")
    st_sub.add_parser("reset")
    st_sub.add_parser("check-caps")

    ak = sub.add_parser(
        "ack",
        help=(
            "Acknowledge a WAKE event (`ship ack <hint> <sha>`) so the watcher "
            "stops the aggressive un-acked re-nudge and backs off to the safety "
            "cadence. Call it the moment you pick up a WAKE line."
        ),
    )
    ak.add_argument("hint")
    ak.add_argument("sha")

    wt = sub.add_parser(
        "watch",
        help=(
            "Long-running watch loop (Monitor-consumed). Emits a JSON line to "
            "stdout ONLY when the agent must act; waits/throttle/auto-actions go "
            "to stderr. --merge lets the watcher auto-promote/rebase/merge; "
            "--draft holds the PR as a draft (never auto-promotes)."
        ),
    )
    wt_mode = wt.add_mutually_exclusive_group()
    wt_mode.add_argument("--merge", action="store_true", dest="merge",
                    help="auto-promote/rebase/merge mechanically; wake only on failure/judgment")
    wt_mode.add_argument("--draft", action="store_true", dest="draft",
                    help="hold the PR as a draft: ship CI but NEVER auto-promote; "
                         "wake terminally (held_draft) once CI is green so you promote/merge by hand")
    wt.add_argument("--reply-only", action="store_true", dest="reply_only",
                    help="suppress every mutating AUTO action (promote/rebase/merge) — for PRs not owned by the viewer")
    wt.add_argument("--max-iters", type=int, default=0, dest="max_iters",
                    help="stop after N poll iterations (0 = unbounded; for testing)")
    wt.add_argument("--floor-core", type=int, default=RATE_FLOOR_CORE, dest="floor_core")
    wt.add_argument("--floor-graphql", type=int, default=RATE_FLOOR_GRAPHQL, dest="floor_graphql")

    cd = sub.add_parser(
        "ci-durations",
        help=(
            "Per-check CI duration baseline (self-maintained by the watch poll "
            "on each fully-green suite). --show prints the p90 map."
        ),
    )
    cd.add_argument("--show", action="store_true", required=True,
                    help="print the {check_name: p90_s} baseline map")
    cd.add_argument("--file", default=None, dest="ci_file",
                    help="override the configured durationsFile path")

    args = parser.parse_args(args_in)

    if args.cmd == "status":
        _emit(cmd_status())
        return EXIT_OK

    if args.cmd == "failures":
        _emit(cmd_failures())
        return EXIT_OK

    if args.cmd == "threads":
        pr = _resolve_pr_for_state()
        sticky = cmd_fetch_sticky_summary(pr) if not args.unresolved else {"findings": []}
        rows = cmd_threads(
            pr,
            unresolved_only=args.unresolved,
            sticky_findings=sticky.get("findings"),
        )
        _emit(rows)
        return EXIT_OK

    if args.cmd == "fetch-sticky-summary":
        pr = _resolve_pr_for_state()
        _emit(cmd_fetch_sticky_summary(pr))
        return EXIT_OK

    if args.cmd == "size":
        _emit(cmd_size())
        return EXIT_OK

    if args.cmd == "doctor":
        return cmd_doctor()

    if args.cmd == "ci-durations":
        _emit(_load_ci_baseline(args.ci_file))
        return EXIT_OK

    if args.cmd == "rebase-decision":
        _emit(cmd_rebase_decision(force_rebase=args.force_rebase))
        return EXIT_OK

    if args.cmd == "push":
        result = cmd_push(
            force_with_lease=args.force_with_lease,
            force=args.force,
        )
        _emit(result)
        return 0 if result.get("success") else EXIT_TRANSIENT

    if args.cmd == "rebase-attempt":
        result = cmd_rebase_attempt()
        _emit(result)
        return EXIT_OK if result["success"] else EXIT_TRANSIENT

    if args.cmd == "rerun-workflow":
        return cmd_rerun_workflow(args.workflow_run_id)

    if args.cmd == "extract-failed-tests":
        _emit(cmd_extract_failed_tests(args.workflow_run_id))
        return EXIT_OK

    if args.cmd == "promote-draft":
        return cmd_promote_draft()

    if args.cmd == "merge-pr":
        pr = args.pr_number or _resolve_pr_for_state()
        return cmd_merge_pr(pr)

    if args.cmd == "find-or-create-pr":
        draft = not args.ready  # --ready overrides default --draft
        summary = args.summary
        if summary == "-":
            summary = sys.stdin.read()
        info = cmd_find_or_create_pr(draft=draft, title=args.title, summary=summary)
        _emit(info)
        return EXIT_OK

    if args.cmd == "branch-name-valid":
        return cmd_branch_name_valid()

    if args.cmd == "post-pr-body":
        summary = args.summary
        if summary == "-":
            summary = sys.stdin.read()
        sys.stdout.write(cmd_post_pr_body(summary or ""))
        return EXIT_OK

    if args.cmd == "reply-thread":
        body = args.body
        if body == "-":
            body = sys.stdin.read()
        cid = cmd_reply_thread(args.thread_id, body)
        print(cid)
        return EXIT_OK

    if args.cmd == "resolve-thread":
        cmd_resolve_thread(args.thread_id)
        return EXIT_OK

    if args.cmd == "cleanup-worktree":
        return cmd_cleanup_worktree(path=args.path, branch=args.branch)

    if args.cmd == "open-flake-ticket":
        return cmd_open_flake_ticket(
            args.fqn, args.module, args.run_url, args.frames, args.pr_number
        )

    if args.cmd == "state":
        if args.state_cmd == "get":
            sys.stdout.write(cmd_state_get(args.key))
            return EXIT_OK
        if args.state_cmd == "set":
            cmd_state_set(args.key, args.value)
            return EXIT_OK
        if args.state_cmd == "inc":
            print(cmd_state_inc(args.key))
            return EXIT_OK
        if args.state_cmd == "reset":
            cmd_state_reset()
            return EXIT_OK
        if args.state_cmd == "check-caps":
            hits = cmd_state_check_caps()
            for h in hits:
                print(h)
            return EXIT_OK

    if args.cmd == "ack":
        cmd_ack(args.hint, args.sha)
        return EXIT_OK

    if args.cmd == "watch":
        pr = _resolve_pr_for_state()
        # init_state_if_needed resets state on a branch-header mismatch, so a stale
        # persisted flag from a prior branch can't leak into this session (a raw
        # load_state read would not reset it).
        _, body = init_state_if_needed(pr)
        merge_flag = args.merge or bool(body.get("merge_flag"))
        draft_flag = args.draft or bool(body.get("draft_flag"))
        # Draft wins over merge: holding the PR is the safe resolution of any conflict
        # (a CLI flag vs a stale persisted flag, or an interrupted skill flag-set).
        if draft_flag:
            merge_flag = False
        return cmd_watch(
            merge_flag=merge_flag,
            reply_only=args.reply_only,
            draft_flag=draft_flag,
            pr_number=pr,
            check_caps=_watch_check_caps,
            read_ack=_watch_read_ack,
            clear_ack=_watch_clear_ack,
            core_floor=args.floor_core,
            graphql_floor=args.floor_graphql,
            max_iters=args.max_iters,
        )

    parser.print_help()
    return EXIT_HALT


if __name__ == "__main__":
    sys.exit(main())
