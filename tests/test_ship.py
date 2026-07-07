"""Tests for ship.py — the fixtured/integration layer over the generic engine.

Companion to ship's own `--selftest` (stdlib assertions); this suite drives the
config seam, state-file atomicity/locking, the hint classifier + watch taxonomy,
review-thread accounting, and merge gating through real temp state + mocked
`gh`/`git` subprocesses. All per-repo behaviour arrives via the `configure()`
helper (a deep-merge over DEFAULTS) so nothing depends on THIS repo's config.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import ship

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURES / f"{name}.json").open() as f:
        return json.load(f)


def configure(**overrides):
    """Apply a test config over the built-in DEFAULTS (marks section present)."""
    cfg = ship._deep_merge(json.loads(json.dumps(ship.DEFAULTS)), overrides)
    ship._CONFIG = cfg
    ship._CONFIG_SECTION_FOUND = True
    ship._apply_config(cfg)
    return cfg


# A configured review bot: a check-run name that gates review currency, an inline
# comment login + signature for author-kind, and a sticky beacon with meta.
REVIEW_BOT = {
    "checkNames": ["review-bot"],
    "commentLogins": ["review-bot"],
    "commentSignature": r"\*\*\[",
    "stickyBeacon": "<!-- review-bot -->",
    "stickyMeta": True,
    "retrigger": True,
}


class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _unaddressed(pr: dict) -> int:
    return sum(
        1
        for t in pr.get("reviewThreads", {}).get("nodes", [])
        if not t.get("isResolved") and not t.get("isOutdated")
    )


def run_watch(**kwargs):
    """cmd_watch with the base-ref preamble (`gh pr view`) stubbed out."""
    with patch.object(ship, "_pr_base_ref", lambda n: "origin/main"):
        return ship.cmd_watch(**kwargs)


# ===========================================================================
# Config seam — the point of the generic engine
# ===========================================================================


def test_config_deep_merge_from_written_file(tmp_path: Path, monkeypatch) -> None:
    cfgdir = tmp_path / ".claude"
    cfgdir.mkdir()
    (cfgdir / "develop.config.json").write_text(
        json.dumps({"ship": {"baseBranch": "develop", "caps": {"ciFail": 5}}})
    )
    monkeypatch.setattr(ship, "_repo_root", lambda: tmp_path)
    ship._CONFIG = None  # autouse seeded it; force a real disk load
    ship._CONFIG_SECTION_FOUND = False
    cfg = ship._config()
    assert cfg["caps"]["ciFail"] == 5          # override wins
    assert cfg["caps"]["flakySoak"] == 3       # sibling default survives
    assert cfg["baseBranch"] == "develop"
    assert cfg["mergeMethod"] == "squash"      # untouched default
    assert ship._CONFIG_SECTION_FOUND is True
    assert ship.CI_FAIL_CAP == 5               # module global refreshed


def test_config_absent_file_uses_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ship, "_repo_root", lambda: tmp_path)  # no .claude/ here
    ship._CONFIG = None
    ship._CONFIG_SECTION_FOUND = False
    cfg = ship._config()
    assert ship._CONFIG_SECTION_FOUND is False
    assert cfg["caps"]["ciFail"] == 3
    assert ship.MERGE_METHOD == "squash"


def test_apply_config_recompiles_module_tables() -> None:
    configure(hotPaths=[r".*\.lock$"], checkExclusions=["gen"],
              reviewBots=[REVIEW_BOT], mergeMethod="rebase")
    assert any(rx.match("deps.lock") for rx in ship.HOT_PATHS_RX)
    assert "gen" in ship.GATE_EXCLUDED_CHECK_NAMES
    assert "review-bot" in ship.GATE_EXCLUDED_CHECK_NAMES  # bot checks excluded too
    assert "review-bot" in ship.REVIEW_CHECK_NAMES
    assert ship.MERGE_METHOD == "rebase"


# ===========================================================================
# Hint classification — fixture-driven, one per hint (default config)
# ===========================================================================


@pytest.mark.parametrize(
    "fixture_name,expected_hint",
    [
        ("wait_ci", "wait_ci"),
        ("empty_check_runs", "wait_ci"),
        ("ci_failed", "ci_failed"),
        ("merge_conflict", "merge_conflict"),
        ("promote_draft", "promote_draft"),
        ("fetch_threads", "fetch_threads"),
        ("wait_first_review", "wait_first_review"),
        ("wait_reapproval", "wait_reapproval"),
        ("behind_base", "behind_base"),
        ("clean_exit", "clean_exit"),
        ("halt", "halt"),
    ],
)
def test_status_hint_classification(fixture_name: str, expected_hint: str) -> None:
    fx = load_fixture(fixture_name)
    pr = fx["pr"]
    env = ship.cmd_status(fixture={
        "pr": pr,
        "check_runs": fx.get("check_runs"),
        "sticky": fx.get("sticky"),
        "threads_unaddressed": _unaddressed(pr),
    })
    assert env["hint"] == expected_hint, env


def test_pending_review_overrides_fetch_threads() -> None:
    fx = load_fixture("pending_review")
    pr = fx["pr"]
    unaddressed = _unaddressed(pr)
    assert unaddressed > 0
    base = {
        "pr": pr, "check_runs": fx.get("check_runs"),
        "sticky": fx.get("sticky"), "threads_unaddressed": unaddressed,
    }
    assert ship.cmd_status(fixture=base)["hint"] == "fetch_threads"
    gated = ship.cmd_status(fixture={**base, "pending_reviews": 1})
    assert gated["hint"] == "wait_review_submit", gated
    assert gated["cadence_hint_seconds"] == ship.CADENCE_WAIT_REVIEW_SUBMIT


def test_envelope_carries_pr_url_for_user_followup() -> None:
    fx = load_fixture("halt")
    pr = dict(fx["pr"])
    pr["url"] = "https://github.com/o/r/pull/999"
    env = ship.cmd_status(fixture={"pr": pr, "check_runs": fx.get("check_runs"),
                                   "sticky": fx.get("sticky")})
    assert env["hint"] == "halt"
    assert env["pr_url"] == "https://github.com/o/r/pull/999"
    env2 = ship.cmd_status(fixture={"pr": fx["pr"], "check_runs": fx.get("check_runs"),
                                    "sticky": fx.get("sticky")})
    assert env2["pr_url"] == ""


def test_threads_returns_empty_while_pending_review_open() -> None:
    with patch("ship.gh_pending_review_count", return_value=1):
        assert ship.cmd_threads(213) == []


def test_status_empty_check_runs_with_conflict_returns_merge_conflict() -> None:
    fx = load_fixture("merge_conflict")
    env = ship.cmd_status(fixture={"pr": fx["pr"], "check_runs": {"check_runs": []},
                                   "sticky": None, "threads_unaddressed": 0})
    assert env["hint"] == "merge_conflict"


def test_status_accepts_legacy_threads_unresolved_key() -> None:
    fx = load_fixture("fetch_threads")
    env = ship.cmd_status(fixture={"pr": fx["pr"], "check_runs": fx.get("check_runs"),
                                   "sticky": fx.get("sticky"), "threads_unresolved": 2})
    assert env["hint"] == "fetch_threads"


def test_status_outdated_only_does_not_classify_fetch_threads() -> None:
    fx = load_fixture("fetch_threads")
    pr = dict(fx["pr"])
    pr["reviewThreads"] = {"nodes": [{"id": "PRRT_STALE", "isResolved": False,
                                      "isOutdated": True}]}
    env = ship.cmd_status(fixture={"pr": pr, "check_runs": fx.get("check_runs"),
                                   "sticky": fx.get("sticky"), "threads_unaddressed": 0})
    assert env["hint"] != "fetch_threads", env


def test_status_3x_empty_mergeable_returns_halt() -> None:
    fx = load_fixture("empty_check_runs")
    pr = dict(fx["pr"])
    pr["mergeStateStatus"] = "MERGEABLE"
    hint, _, _ = ship._classify_hint(
        check_runs=[], classified=ship.classify_check_runs([]),
        is_draft=False, merge_state="MERGEABLE", review_decision=None,
        review_requests=[], unaddressed_threads=0, pending_reviews=0,
        sticky={"sha": None, "status": None}, sha="x" * 40,
        bot_advanced=False, empty_mergeable_count=2,
    )
    assert hint == "halt"


def test_empty_runs_halt_fixture_classifies_halt() -> None:
    fx = load_fixture("empty_runs_halt")
    pr = fx["pr"]
    hint, _, _ = ship._classify_hint(
        check_runs=[], classified=ship.classify_check_runs([]),
        is_draft=False, merge_state="MERGEABLE", review_decision="APPROVED",
        review_requests=[], unaddressed_threads=0, pending_reviews=0,
        sticky={"sha": None, "status": None}, sha=pr["headRefOid"],
        bot_advanced=False, empty_mergeable_count=2,
    )
    assert hint == "halt"


def test_blocked_with_no_review_is_wait_first_review() -> None:
    env = ship.cmd_status(fixture={
        "pr": {"isDraft": False, "headRefOid": "sha", "mergeStateStatus": "BLOCKED",
               "reviewDecision": None, "reviewRequests": {"nodes": []}, "number": 1},
        "check_runs": {"check_runs": [
            {"name": "gate", "status": "completed", "conclusion": "success"},
            {"name": "test", "status": "completed", "conclusion": "success"},
        ]},
        "sticky": None, "threads_unresolved": 0,
    })
    assert env["hint"] == "wait_first_review"
    assert env["cadence_hint_seconds"] == ship.CADENCE_WAIT_FIRST_REVIEW


def test_status_rate_limit_backoff_via_gh_stderr() -> None:
    proc = _FakeProc(stderr="API rate limit exceeded for user ID 12345.", returncode=1)
    with patch.object(ship, "run", return_value=proc):
        with pytest.raises(SystemExit) as exc:
            ship.gh_json(["api", "rate-test"])
    assert exc.value.code == ship.EXIT_TRANSIENT


# ===========================================================================
# Review-bot-configured classification (review currency + exclusions)
# ===========================================================================


def test_classify_hint_review_in_progress_blocks_clean_exit() -> None:
    configure(reviewBots=[REVIEW_BOT])
    cr = [
        {"name": "lint", "status": "completed", "conclusion": "success", "id": 1},
        {"name": "review-bot", "status": "in_progress", "conclusion": None, "id": 2},
    ]
    classified = ship.classify_check_runs(cr)
    assert classified["review_present"] is True
    assert classified["review_completed"] is False
    hint, cadence, _ = ship._classify_hint(
        check_runs=cr, classified=classified, is_draft=False, merge_state="CLEAN",
        review_decision="APPROVED", review_requests=[], unaddressed_threads=0,
        sticky={"sticky_found": True, "sha": None, "status": None}, sha="newhead",
        bot_advanced=False, empty_mergeable_count=0,
    )
    assert hint == "wait_reapproval", hint
    assert cadence == ship.CADENCE_WAIT_REAPPROVAL


def _classify_from_fixture(fx: dict, **overrides):
    pr = fx["pr"]
    cr = fx["check_runs"]["check_runs"]
    kwargs = dict(
        check_runs=cr, classified=ship.classify_check_runs(cr), is_draft=False,
        merge_state=pr.get("mergeStateStatus", "CLEAN"),
        review_decision=pr.get("reviewDecision", "APPROVED"),
        review_requests=pr.get("reviewRequests", []), unaddressed_threads=0,
        pending_reviews=0, sticky=fx.get("sticky") or {},
        sha=pr.get("headRefOid", ""), bot_advanced=False, empty_mergeable_count=0,
    )
    kwargs.update(overrides)
    return ship._classify_hint(**kwargs)


def test_review_currency_in_progress_no_clean_exit() -> None:
    configure(reviewBots=[REVIEW_BOT])
    fx = load_fixture("review_in_progress")
    assert ship.classify_check_runs(fx["check_runs"]["check_runs"])["review_completed"] is False
    assert _classify_from_fixture(fx)[0] == "wait_reapproval"


def test_review_currency_completed_clean_exit() -> None:
    configure(reviewBots=[REVIEW_BOT])
    fx = load_fixture("review_completed")
    assert ship.classify_check_runs(fx["check_runs"]["check_runs"])["review_completed"] is True
    assert _classify_from_fixture(fx)[0] == "clean_exit"


def test_review_currency_absent_no_clean_exit() -> None:
    configure(reviewBots=[REVIEW_BOT])
    fx = load_fixture("review_absent")
    assert ship.classify_check_runs(fx["check_runs"]["check_runs"])["review_present"] is False
    assert _classify_from_fixture(fx)[0] == "wait_reapproval"


def test_green_nongated_clean_exit() -> None:
    configure(reviewBots=[REVIEW_BOT], checkExclusions=["task-check"])
    fx = load_fixture("green_nongated")
    assert _classify_from_fixture(fx)[0] == "clean_exit"


def test_status_hint_review_classifications() -> None:
    configure(reviewBots=[REVIEW_BOT], checkExclusions=["task-check"])
    cases = [
        ("green_nongated", "clean_exit"),
        ("review_completed", "clean_exit"),
        ("review_in_progress", "wait_reapproval"),
        ("review_absent", "wait_reapproval"),
    ]
    for name, expected in cases:
        fx = load_fixture(name)
        env = ship.cmd_status(fixture={"pr": fx["pr"], "check_runs": fx.get("check_runs"),
                                       "sticky": fx.get("sticky"), "threads_unaddressed": 0})
        assert env["hint"] == expected, f"{name}: {env['hint']}"


def test_only_excluded_checks_never_clean_exit() -> None:
    configure(reviewBots=[REVIEW_BOT], checkExclusions=["task-check"])
    cr = [
        {"name": "task-check", "status": "completed", "conclusion": "success", "id": 1},
        {"name": "review-bot", "status": "completed", "conclusion": "success", "id": 2},
    ]
    classified = ship.classify_check_runs(cr)
    assert classified["gating_total"] == 0
    assert classified["all_done_ok"] is False
    hint, _, _ = ship._classify_hint(
        check_runs=cr, classified=classified, is_draft=False, merge_state="MERGEABLE",
        review_decision="APPROVED", review_requests=[], unaddressed_threads=0,
        pending_reviews=0, sticky={"sticky_found": True, "sha": None, "status": None},
        sha="head", bot_advanced=False, empty_mergeable_count=0,
    )
    assert hint == "wait_ci", hint


def test_status_only_excluded_checks_never_clean_exit() -> None:
    configure(reviewBots=[REVIEW_BOT], checkExclusions=["task-check"])
    env = ship.cmd_status(fixture={
        "pr": {"number": 300, "headRefOid": "h" * 40, "isDraft": False,
               "mergeStateStatus": "MERGEABLE", "reviewDecision": "APPROVED",
               "reviewRequests": []},
        "check_runs": {"check_runs": [
            {"name": "task-check", "status": "completed", "conclusion": "success", "id": 1},
            {"name": "review-bot", "status": "completed", "conclusion": "success", "id": 2},
        ]},
        "sticky": {"sticky_found": True, "sha": None, "status": None},
        "threads_unaddressed": 0,
    })
    assert env["hint"] != "clean_exit", env["hint"]


def test_waits_on_review_required_without_retrigger() -> None:
    runs = load_fixture("sticky_sha_stale")["check_runs"]["check_runs"]
    hint, _, _ = ship._classify_hint(
        check_runs=runs, classified=ship.classify_check_runs(runs), is_draft=False,
        merge_state="BLOCKED", review_decision="REVIEW_REQUIRED", review_requests=[],
        unaddressed_threads=0, sticky={"status": None, "sha": "deadbeef"},
        sha="deadbeef", bot_advanced=False, empty_mergeable_count=0,
    )
    assert hint == "wait_reapproval"


def test_sticky_sha_stale_hint_requires_review_bots() -> None:
    configure(reviewBots=[REVIEW_BOT])
    green = {"total": 1, "any_failure": False, "any_pending": False,
             "all_done_ok": True, "gating_total": 1,
             "review_present": True, "review_completed": True}
    hint, _, _ = ship._classify_hint(
        check_runs=[{"name": "build"}], classified=green, is_draft=False,
        merge_state="MERGEABLE", review_decision="APPROVED", review_requests=[],
        unaddressed_threads=0, pending_reviews=0,
        sticky={"sha": "OLD", "status": "BLOCKING", "retrigger": True},
        sha="NEW", bot_advanced=True, empty_mergeable_count=0,
    )
    assert hint == "sticky_sha_stale"


def test_retrigger_review_hint_when_opted_in() -> None:
    configure(reviewBots=[REVIEW_BOT])
    green = {"total": 1, "any_failure": False, "any_pending": False,
             "all_done_ok": True, "gating_total": 1,
             "review_present": True, "review_completed": True}
    common = dict(
        check_runs=[{"name": "build"}], classified=green, is_draft=False,
        merge_state="BLOCKED", review_decision="REVIEW_REQUIRED", review_requests=[],
        unaddressed_threads=0, pending_reviews=0, sha="NEW",
        bot_advanced=False, empty_mergeable_count=0,
    )
    assert ship._classify_hint(
        sticky={"sha": "NEW", "status": "BLOCKING", "retrigger": True}, **common
    )[0] == "retrigger_review"
    # retrigger falsy → strict no-op, falls through to wait_reapproval.
    assert ship._classify_hint(
        sticky={"sha": "NEW", "status": "BLOCKING", "retrigger": False}, **common
    )[0] == "wait_reapproval"


# ===========================================================================
# classify_check_runs
# ===========================================================================


def test_classify_check_runs_dedupes_by_name_keeping_latest() -> None:
    runs = [
        {"name": "gate", "status": "completed", "conclusion": "success", "id": 1},
        {"name": "rerunner", "status": "completed", "conclusion": "failure",
         "started_at": "2026-01-01T00:00:00Z", "id": 10},
        {"name": "rerunner", "status": "completed", "conclusion": "success",
         "started_at": "2026-01-02T00:00:00Z", "id": 11},
        {"name": "rerunner", "status": "in_progress",
         "started_at": "2026-01-03T00:00:00Z", "id": 12},
        {"name": "unit-tests", "status": "completed", "conclusion": "success",
         "started_at": "2026-01-01T00:00:00Z", "id": 20},
        {"name": "unit-tests", "status": "completed", "conclusion": "failure",
         "started_at": "2026-01-01T00:00:00Z",
         "completed_at": "2026-01-01T01:00:00Z", "id": 21},
    ]
    out = ship.classify_check_runs(runs)
    assert out["total"] == 3
    assert out["by_status"]["in_progress"][0]["id"] == 12  # latest started_at
    assert out["by_status"]["failure"][0]["id"] == 21      # tie-break completed_at


def test_classify_check_runs_excludes_configured_and_review_from_gating() -> None:
    configure(reviewBots=[REVIEW_BOT], checkExclusions=["task-check"])
    assert "review-bot" in ship.GATE_EXCLUDED_CHECK_NAMES
    cr = [
        {"name": "task-check", "status": "completed", "conclusion": "failure", "id": 1},
        {"name": "review-bot", "status": "completed", "conclusion": "skipped", "id": 2},
        {"name": "lint", "status": "completed", "conclusion": "success", "id": 3},
        {"name": "unit-test", "status": "completed", "conclusion": "skipped", "id": 4},
    ]
    out = ship.classify_check_runs(cr)
    assert out["any_failure"] is False   # task-check failure excluded
    assert out["all_done_ok"] is True
    out2 = ship.classify_check_runs(cr + [{"name": "build", "status": "completed",
                                           "conclusion": "success", "id": 5}])
    assert out2["gating_total"] == 3


def test_classify_check_runs_unknown_conclusion_gates_conservatively() -> None:
    out = ship.classify_check_runs([
        {"name": "lint", "status": "completed", "conclusion": "success", "id": 1},
        {"name": "x", "status": "completed", "conclusion": "unknown_future", "id": 2},
    ])
    assert out["any_failure"] is True
    assert out["all_done_ok"] is False


def test_classify_check_runs_non_terminal_status_is_pending() -> None:
    for status in ("waiting", "requested", "pending", "queued", "in_progress",
                   "unknown_future_status"):
        out = ship.classify_check_runs([
            {"name": "lint", "status": "completed", "conclusion": "success", "id": 1},
            {"name": "gated", "status": status, "conclusion": None, "id": 2},
        ])
        assert out["any_failure"] is False, status
        assert out["any_pending"] is True, status
        assert out["all_done_ok"] is False, status


def test_classify_check_runs_completed_unknown_conclusion_is_failure() -> None:
    out = ship.classify_check_runs([
        {"name": "lint", "status": "completed", "conclusion": "success", "id": 1},
        {"name": "weird", "status": "completed", "conclusion": None, "id": 2},
    ])
    assert out["any_failure"] is True
    assert out["all_done_ok"] is False


def test_classify_check_runs_skipped_counts_green() -> None:
    out = ship.classify_check_runs([
        {"name": "ui-test", "status": "completed", "conclusion": "skipped", "id": 1},
        {"name": "lint", "status": "completed", "conclusion": "success", "id": 2},
    ])
    assert out["any_failure"] is False
    assert out["all_done_ok"] is True


def test_classify_check_runs_empty_runs() -> None:
    out = ship.classify_check_runs([])
    assert out == {"total": 0, "gating_total": 0} or out["total"] == 0
    assert out["any_failure"] is False
    assert out["all_done_ok"] is False


def test_review_bot_completed_at_returns_latest_completion() -> None:
    configure(reviewBots=[REVIEW_BOT])
    runs = [
        {"name": "review-bot", "status": "completed", "completed_at": "2026-01-01T10:00:00Z"},
        {"name": "lint", "status": "completed", "completed_at": "2026-01-01T09:00:00Z"},
        {"name": "review-bot", "status": "completed", "completed_at": "2026-01-01T11:00:00Z"},
    ]
    assert ship.review_bot_completed_at(runs) == "2026-01-01T11:00:00Z"


def test_review_bot_completed_at_none_when_no_completed_bot_run() -> None:
    configure(reviewBots=[REVIEW_BOT])
    runs = [
        {"name": "review-bot", "status": "in_progress", "completed_at": None},
        {"name": "lint", "status": "completed", "completed_at": "2026-01-01T09:00:00Z"},
    ]
    assert ship.review_bot_completed_at(runs) is None


# ===========================================================================
# State file atomicity + locking
# ===========================================================================


def test_state_atomic_write_survives_mid_write_kill(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(ship._build_header("br", "sha") + "\n" + json.dumps({"x": 1}))
    original = path.read_text()
    real_open = open

    def explode_open(p, *a, **kw):
        if str(p).endswith(".tmp"):
            raise OSError("disk full simulated")
        return real_open(p, *a, **kw)

    with patch("ship.git_dir", return_value=tmp_path):
        with patch("builtins.open", side_effect=explode_open):
            with pytest.raises(OSError):
                ship.write_state_atomic("PR", {"branch": "br", "base_sha": "sha"}, {"x": 2})
    assert path.read_text() == original


def test_state_atomic_write_replaces_via_tmp(tmp_path: Path) -> None:
    with patch("ship.git_dir", return_value=tmp_path):
        ship.write_state_atomic("PR", {"branch": "br", "base_sha": "sha1"},
                                {"foo": "bar", "n": 3})
        header, body = ship.load_state("PR")
    assert header == {"branch": "br", "base_sha": "sha1"}
    assert body == {"foo": "bar", "n": 3}


def test_persist_status_fields_preserves_concurrent_inc(tmp_path: Path) -> None:
    header = {"branch": "br", "base_sha": "sha"}
    with patch("ship.git_dir", return_value=tmp_path):
        ship.write_state_atomic("PR", header, ship.default_state_body())
        _, latest = ship.load_state("PR")
        latest["ci_fail_count"] = {"lint": 3}
        ship.write_state_atomic("PR", header, latest)
        ship.persist_status_fields("PR", header, {"empty_runs_mergeable_count": 5})
        _, merged = ship.load_state("PR")
    assert merged["ci_fail_count"] == {"lint": 3}
    assert merged["empty_runs_mergeable_count"] == 5


def test_cmd_status_persist_keeps_inc_landed_after_snapshot(tmp_path: Path) -> None:
    fx = load_fixture("wait_ci")
    pr = dict(fx["pr"])
    pr["number"] = 4242
    pr["headRefName"] = "claude/x"
    with patch("ship.git_dir", return_value=tmp_path), \
         patch("ship.current_branch", return_value="claude/x"), \
         patch("ship.merge_base_sha", return_value="base"):
        seed_header, seed_body = ship.init_state_if_needed(4242)
        seed_body["empty_runs_mergeable_count"] = 99
        ship.write_state_atomic(4242, seed_header, seed_body)

    _real_classify = ship._classify_hint

    def concurrent_inc(*a, **kw):
        ship.cmd_state_inc("ci_fail_count.lint")
        return _real_classify(*a, **kw)

    with patch("ship.git_dir", return_value=tmp_path), \
         patch("ship.current_branch", return_value="claude/x"), \
         patch("ship.current_sha", return_value="sha"), \
         patch("ship.merge_base_sha", return_value="base"), \
         patch("ship.gh_pr_view_full", return_value=pr), \
         patch("ship.gh_repo_slug", return_value="o/r"), \
         patch("ship.gh_json", return_value=fx.get("check_runs") or {"check_runs": []}), \
         patch("ship.gh_review_state",
               return_value={"unaddressed_threads": 0, "pending_reviews": 0}), \
         patch("ship._resolve_pr_for_state", return_value=4242), \
         patch("ship._classify_hint", side_effect=concurrent_inc), \
         patch("ship.cmd_fetch_sticky_summary", return_value=None):
        ship.cmd_status()

    with patch("ship.git_dir", return_value=tmp_path):
        _, body = ship.load_state(4242)
    assert body.get("ci_fail_count", {}).get("lint") == 1, body


def test_state_lock_is_reentrant(tmp_path: Path) -> None:
    with patch("ship.git_dir", return_value=tmp_path):
        key = str(ship._lock_path(99))
        with ship._StateLock(99):
            with ship._StateLock(99):
                assert ship._StateLock._held[key][1] == 2
            assert ship._StateLock._held[key][1] == 1
        assert key not in ship._StateLock._held


def test_state_preserves_counters_across_loop_internal_commits(tmp_path: Path) -> None:
    with patch("ship.git_dir", return_value=tmp_path), \
         patch("ship.current_branch", return_value="claude/alpha-beta-abc123"), \
         patch("ship.merge_base_sha", return_value="base-sha"):
        _, body1 = ship.init_state_if_needed("PR")
        body1["ci_fail_count"] = {"flake-x": 2}
        ship.write_state_atomic("PR", {"branch": "claude/alpha-beta-abc123",
                                       "base_sha": "base-sha"}, body1)
        _, body2 = ship.init_state_if_needed("PR")
    assert body2["ci_fail_count"] == {"flake-x": 2}


def test_state_resets_on_branch_change(tmp_path: Path) -> None:
    with patch("ship.git_dir", return_value=tmp_path), \
         patch("ship.merge_base_sha", return_value="base-sha"):
        with patch("ship.current_branch", return_value="claude/old-aaa"):
            _, body = ship.init_state_if_needed("PR")
            body["ci_fail_count"] = {"x": 1}
            ship.write_state_atomic("PR", {"branch": "claude/old-aaa",
                                           "base_sha": "base-sha"}, body)
        with patch("ship.current_branch", return_value="claude/new-bbb"):
            _, body2 = ship.init_state_if_needed("PR")
    assert body2["ci_fail_count"] == {}


def _state_env(tmp_path, pr=42):
    return [
        patch("ship.git_dir", return_value=tmp_path),
        patch("ship.current_branch", return_value="claude/alpha-beta-abc123"),
        patch("ship.current_sha", return_value="sha"),
        patch("ship.merge_base_sha", return_value="base"),
        patch("ship.lookup_pr_number", return_value=pr),
    ]


def test_state_set_then_get_roundtrip(tmp_path: Path) -> None:
    with _state_env(tmp_path)[0], _state_env(tmp_path)[1], _state_env(tmp_path)[2], \
         _state_env(tmp_path)[3], _state_env(tmp_path)[4]:
        ship.cmd_state_set("ci_fail_count.test_foo", "2")
        assert ship.cmd_state_get("ci_fail_count.test_foo") == "2"


def test_state_paused_defaults_false_and_clears_on_reset(tmp_path: Path) -> None:
    ps = _state_env(tmp_path)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        assert ship.cmd_state_get("paused") == "False"
        ship.cmd_state_set("paused", "true")
        assert ship.cmd_state_get("paused") == "True"
        ship.cmd_state_reset()
        assert ship.cmd_state_get("paused") == "False"


def test_state_inc_increments(tmp_path: Path) -> None:
    ps = _state_env(tmp_path)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        ship.cmd_state_set("rebase_count", "0")
        assert ship.cmd_state_inc("rebase_count") == 1
        assert ship.cmd_state_inc("rebase_count") == 2


def test_state_check_caps_flags_at_threshold(tmp_path: Path) -> None:
    ps = _state_env(tmp_path)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        ship.cmd_state_set("ci_fail_count.boom", "3")
        assert "ci_fail_count.boom" in ship.cmd_state_check_caps()


def test_state_inc_fqn_soak_key_fires_cap(tmp_path: Path) -> None:
    fqn = "com.example.core.FooTest.flakyCase"
    ps = _state_env(tmp_path, pr=7)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        for _ in range(ship.FLAKY_SOAK_CAP):
            ship.cmd_state_inc(f"flaky_soak_round.{fqn}")
        _, body = ship.init_state_if_needed(7)
    assert body["flaky_soak_round"] == {fqn: ship.FLAKY_SOAK_CAP}
    assert f"flaky_soak_round.{fqn}" in ship._cap_hits(body)


def test_cap_hits_flags_at_threshold() -> None:
    body = {
        "ci_fail_count": {"root_a": ship.CI_FAIL_CAP, "root_b": 1},
        "flaky_soak_round": {"com.example.Foo.bar": ship.FLAKY_SOAK_CAP},
        "empty_runs_mergeable_count": 0,
        "retrigger_review_count": ship.RETRIGGER_REVIEW_CAP,
    }
    hits = ship._cap_hits(body)
    assert "ci_fail_count.root_a" in hits
    assert "ci_fail_count.root_b" not in hits
    assert "flaky_soak_round.com.example.Foo.bar" in hits
    assert "empty_runs_mergeable_count" not in hits
    assert "retrigger_review_count" in hits


def test_ack_roundtrips_through_state(tmp_path: Path) -> None:
    ps = _state_env(tmp_path)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        assert ship._watch_read_ack(42) is None
        ship.cmd_ack("ci_failed", "deadbee")
        assert ship._watch_read_ack(42) == ("ci_failed", "deadbee")
        ship._watch_clear_ack(42)
        assert ship._watch_read_ack(42) is None


def test_ack_writers_hold_state_lock(tmp_path: Path) -> None:
    entered = {"n": 0}
    real = ship._StateLock

    class _Track(real):
        def __enter__(self):
            entered["n"] += 1
            return super().__enter__()

    ps = _state_env(tmp_path)
    with ps[0], ps[1], ps[2], ps[3], ps[4], patch("ship._StateLock", _Track):
        ship.cmd_ack("ci_failed", "abc")
        assert entered["n"] >= 1
        before = entered["n"]
        ship._watch_clear_ack(42)
        assert entered["n"] > before


def test_rebase_and_push_hold_state_lock(tmp_path: Path) -> None:
    entered = {"n": 0}
    real = ship._StateLock

    class _Track(real):
        def __enter__(self):
            entered["n"] += 1
            return super().__enter__()

    ok = _FakeProc()
    ps = _state_env(tmp_path, pr=7)
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("ship.run", return_value=ok), patch("ship._StateLock", _Track):
        ship.cmd_push()
        assert entered["n"] >= 1
        before = entered["n"]
        ship.cmd_rebase_attempt()
        assert entered["n"] > before


# ===========================================================================
# threads: fresh fetch + state tagging + author-kind + addressed
# ===========================================================================


def test_threads_repeated_call_returns_fresh_rows(tmp_path: Path) -> None:
    threads = [{"id": "PRRT_1", "isResolved": False,
                "comments": {"nodes": [{"id": "PRRC_1"}]}}]
    with patch("ship.git_dir", return_value=tmp_path):
        first = ship.cmd_threads(1, fixture={"threads": threads})
        second = ship.cmd_threads(1, fixture={"threads": threads})
    assert len(first) == 1
    assert first == second


def test_threads_rows_expose_resolved_outdated_state(tmp_path: Path) -> None:
    threads = [
        {"id": "PRRT_OPEN", "isResolved": False, "isOutdated": False,
         "comments": {"nodes": [{"id": "C1", "body": "still relevant"}]}},
        {"id": "PRRT_DONE", "isResolved": True, "isOutdated": False,
         "comments": {"nodes": [{"id": "C2", "body": "resolved"}]}},
        {"id": "PRRT_STALE", "isResolved": False, "isOutdated": True,
         "comments": {"nodes": [{"id": "C3", "body": "rewritten"}]}},
    ]
    with patch("ship.git_dir", return_value=tmp_path):
        rows = ship.cmd_threads(1, fixture={"threads": threads, "viewer_login": "ship-bot"})
    by_id = {r["thread_id"]: r for r in rows}
    assert by_id["PRRT_OPEN"]["state"] == "unresolved"
    assert by_id["PRRT_DONE"]["state"] == "resolved_no_reply"
    assert by_id["PRRT_DONE"]["replied_by_viewer"] is False
    assert by_id["PRRT_STALE"]["state"] == "outdated"


def test_threads_tag_author_kind(tmp_path: Path) -> None:
    configure(reviewBots=[REVIEW_BOT])
    threads = [
        {"id": "BOT", "isResolved": False, "isOutdated": False,
         "comments": {"nodes": [{"id": "B1", "author": {"login": "review-bot"},
                                 "body": "**[Critical]** null deref"}]}},
        {"id": "FOREIGN", "isResolved": False, "isOutdated": False,
         "comments": {"nodes": [{"id": "F1", "author": {"login": "review-bot"},
                                 "body": "coverage dropped"}]}},
        {"id": "NULL", "isResolved": False, "isOutdated": False,
         "comments": {"nodes": [{"id": "N1", "author": None, "body": "ghost"}]}},
        {"id": "HUMAN", "isResolved": False, "isOutdated": False,
         "comments": {"nodes": [{"id": "H1", "author": {"login": "alice"}}]}},
        {"id": "OTHERBOT", "isResolved": False, "isOutdated": False,
         "comments": {"nodes": [{"id": "O1", "author": {"login": "dependabot[bot]"}}]}},
        {"id": "REPLY", "isResolved": False, "isOutdated": False,
         "comments": {"nodes": [{"id": "R1", "author": {"login": "alice"}},
                                 {"id": "R2", "author": {"login": "review-bot"},
                                  "body": "**[Important]** x"}]}},
    ]
    with patch("ship.git_dir", return_value=tmp_path):
        rows = ship.cmd_threads(1, fixture={"threads": threads, "viewer_login": "ship-bot"})
    by_id = {r["thread_id"]: r for r in rows}
    assert by_id["BOT"]["author_kind"] == "review_bot"
    assert by_id["FOREIGN"]["author_kind"] == "human"    # login but no signature
    assert by_id["NULL"]["author_kind"] == "human"
    assert by_id["HUMAN"]["author_kind"] == "human"
    assert by_id["OTHERBOT"]["author_kind"] == "other_bot"
    assert by_id["REPLY"]["author_kind"] == "human"      # reply cannot reclassify


def test_thread_author_kind_precedence_and_empty() -> None:
    configure(reviewBots=[REVIEW_BOT])
    assert ship.thread_author_kind({"comments": {"nodes": [
        {"author": {"login": "review-bot"}, "body": "**[Critical]** boom"}]}}) == "review_bot"
    assert ship.thread_author_kind({"comments": {"nodes": [
        {"author": {"login": "review-bot"}, "body": "lint warning"}]}}) == "human"
    assert ship.thread_author_kind({"comments": {"nodes": [
        {"author": {"login": "renovate[bot]"}}]}}) == "other_bot"
    assert ship.thread_author_kind({"comments": {"nodes": [
        {"author": {"login": "carol"}}]}}) == "human"
    assert ship.thread_author_kind({"comments": {"nodes": [
        {"author": None, "body": "x"}]}}) == "human"
    assert ship.thread_author_kind({"comments": {"nodes": []}}) == "other_bot"


def test_thread_replied_by() -> None:
    t = {"comments": {"nodes": [{"author": {"login": "reviewer"}},
                                {"author": {"login": "ship-bot"}}]}}
    assert ship._thread_replied_by(t, "ship-bot") is True
    assert ship._thread_replied_by(t, "other") is False
    assert ship._thread_replied_by({"comments": {"nodes": []}}, "ship-bot") is False
    assert ship._thread_replied_by(t, None) is False


def test_thread_replied_by_does_not_trust_reply_marker() -> None:
    # A non-viewer comment quoting the reply marker must NOT read as replied.
    t = {"comments": {"nodes": [
        {"author": {"login": "reviewer"}, "body": f"quoting {ship.SHIP_REPLY_MARKER}"}]}}
    assert ship._thread_replied_by(t, "ship-bot") is False


def test_thread_addressed_human_resolved_no_reply_is_addressed() -> None:
    t = {"isResolved": True, "comments": {"nodes": [{"author": {"login": "alice"}}]}}
    assert ship._thread_addressed(t, "ship-bot") is True


def test_thread_addressed_human_unresolved_blocks() -> None:
    t = {"isResolved": False, "comments": {"nodes": [{"author": {"login": "alice"}}]}}
    assert ship._thread_addressed(t, "ship-bot") is False


def test_thread_addressed_review_bot_resolved_no_reply_still_unaddressed() -> None:
    configure(reviewBots=[REVIEW_BOT])
    t = {"isResolved": True, "comments": {"nodes": [
        {"author": {"login": "review-bot"}, "body": "**[Critical]** boom"}]}}
    assert ship._thread_addressed(t, "ship-bot") is False


def test_thread_addressed_review_bot_resolved_and_replied_is_addressed() -> None:
    configure(reviewBots=[REVIEW_BOT])
    t = {"isResolved": True, "comments": {"nodes": [
        {"author": {"login": "review-bot"}, "body": "**[Important]** x"},
        {"author": {"login": "ship-bot"}}]}}
    assert ship._thread_addressed(t, "ship-bot") is True


def test_thread_addressed_other_bot_resolved_no_reply_is_addressed() -> None:
    t = {"isResolved": True, "comments": {"nodes": [{"author": {"login": "dependabot[bot]"}}]}}
    assert ship._thread_addressed(t, "ship-bot") is True


def test_threads_unresolved_filter_only_hides_resolved_and_replied(tmp_path: Path) -> None:
    threads = [
        {"id": "OPEN", "isResolved": False, "isOutdated": False,
         "comments": {"nodes": [{"id": "C1", "author": {"login": "reviewer"}}]}},
        {"id": "DONE", "isResolved": True, "isOutdated": False,
         "comments": {"nodes": [{"id": "C2a", "author": {"login": "reviewer"}},
                                 {"id": "C2b", "author": {"login": "ship-bot"}}]}},
        {"id": "RESOLVED_NO_REPLY", "isResolved": True, "isOutdated": False,
         "comments": {"nodes": [{"id": "C3", "author": {"login": "reviewer"}}]}},
        {"id": "STALE_NO_REPLY", "isResolved": False, "isOutdated": True,
         "comments": {"nodes": [{"id": "C4", "author": {"login": "reviewer"}}]}},
        {"id": "STALE_REPLIED", "isResolved": False, "isOutdated": True,
         "comments": {"nodes": [{"id": "C5a", "author": {"login": "reviewer"}},
                                 {"id": "C5b", "author": {"login": "ship-bot"}}]}},
    ]
    with patch("ship.git_dir", return_value=tmp_path):
        rows = ship.cmd_threads(1, fixture={"threads": threads, "viewer_login": "ship-bot"},
                                unresolved_only=True)
    by_id = {r["thread_id"]: r for r in rows}
    assert set(by_id) == {"OPEN", "RESOLVED_NO_REPLY", "STALE_NO_REPLY", "STALE_REPLIED"}
    assert by_id["RESOLVED_NO_REPLY"]["state"] == "resolved_no_reply"
    assert by_id["STALE_REPLIED"]["replied_by_viewer"] is True


def test_gh_review_state_human_resolved_thread_does_not_block(tmp_path: Path) -> None:
    ship._SLUG_CACHE = "octo/repo"
    payload = {"data": {"viewer": {"login": "ship-bot"}, "repository": {"pullRequest": {
        "reviewThreads": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [
            {"isResolved": True, "isOutdated": False,
             "comments": {"nodes": [{"author": {"login": "alice"}}]}},
            {"isResolved": False, "isOutdated": False,
             "comments": {"nodes": [{"author": {"login": "bob"}}]}},
        ]}, "reviews": {"nodes": []}}}}}
    with patch.object(ship, "run", return_value=_FakeProc(stdout=json.dumps(payload))):
        state = ship.gh_review_state(213)
    assert state["unaddressed_threads"] == 1, state


def test_gh_review_state_single_call_returns_both_counts() -> None:
    ship._SLUG_CACHE = "octo/repo"
    payload = {"data": {"viewer": {"login": "ship-bot"}, "repository": {"pullRequest": {
        "reviewThreads": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [
            {"isResolved": False, "isOutdated": False,
             "comments": {"nodes": [{"author": {"login": "human"}}]}},
            {"isResolved": True, "isOutdated": False,
             "comments": {"nodes": [{"author": {"login": "ship-bot"}}]}},
        ]}, "reviews": {"nodes": [{"state": "PENDING"}, {"state": "APPROVED"}]}}}}}
    with patch.object(ship, "run", return_value=_FakeProc(stdout=json.dumps(payload))) as m:
        state = ship.gh_review_state(213)
    assert state == {"unaddressed_threads": 1, "pending_reviews": 1}
    assert m.call_count == 1


def test_gh_review_state_rate_limit_backs_off() -> None:
    ship._SLUG_CACHE = "o/r"
    with patch.object(ship, "run",
                      return_value=_FakeProc(stderr="API rate limit exceeded", returncode=1)):
        with pytest.raises(SystemExit) as e:
            ship.gh_review_state(1)
    assert e.value.code == ship.EXIT_TRANSIENT


def test_gh_review_state_other_error_returns_zeros() -> None:
    ship._SLUG_CACHE = "o/r"
    with patch.object(ship, "run", return_value=_FakeProc(stderr="network blip", returncode=1)):
        assert ship.gh_review_state(1) == {"unaddressed_threads": 0, "pending_reviews": 0}


def test_review_thread_selection_fetches_comment_body() -> None:
    # thread_author_kind matches the opening comment against commentSignature, so
    # the state selection must request `body` or bot threads misclassify as human.
    assert "body" in ship._THREAD_STATE_NODE_SELECTION


def test_gh_repo_slug_is_cached_after_first_call() -> None:
    ship._SLUG_CACHE = None
    with patch.object(ship, "run", return_value=_FakeProc(stdout="octo/repo\n")) as m:
        assert ship.gh_repo_slug() == "octo/repo"
        assert ship.gh_repo_slug() == "octo/repo"
    assert m.call_count == 1


# ===========================================================================
# fetch_all_review_threads pagination
# ===========================================================================


def test_fetch_all_review_threads_walks_cursor_pages() -> None:
    ship._SLUG_CACHE = "owner/repo"

    def page(has_next, cursor, node):
        return json.dumps({"data": {"viewer": {"login": "me"}, "repository": {"pullRequest": {
            "reviewThreads": {"pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                              "nodes": [node]}}}}})

    pages = [page(True, "CUR1", {"isResolved": True}),
             page(False, None, {"isResolved": False})]
    calls: list[list[str]] = []

    def fake_runner(cmd):
        calls.append(cmd)
        return _FakeProc(stdout=pages[len(calls) - 1])

    data, nodes = ship.fetch_all_review_threads(
        1, ship._THREAD_STATE_NODE_SELECTION, runner=fake_runner)
    assert len(nodes) == 2 and len(calls) == 2
    assert any("cursor=CUR1" in c for c in calls[1])
    assert (data.get("viewer") or {}).get("login") == "me"


def test_fetch_all_review_threads_rate_limit_raises_transient() -> None:
    ship._SLUG_CACHE = "owner/repo"

    def fake_runner(cmd):
        return _FakeProc(stderr="API rate limit exceeded", returncode=1)

    with pytest.raises(SystemExit) as e:
        ship.fetch_all_review_threads(1, ship._THREAD_STATE_NODE_SELECTION, runner=fake_runner)
    assert e.value.code == ship.EXIT_TRANSIENT


# ===========================================================================
# sticky summary (config-driven beacons + meta)
# ===========================================================================


def test_sticky_summary_meta_parses_embedded_json() -> None:
    bot = {"stickyBeacon": "<!-- review-bot -->", "stickyMeta": True, "retrigger": True}
    comments = [{"body": 'x <!-- review-bot --> {"sha":"abc","status":"BLOCKING",'
                         '"findings":[{"id":1},{"id":2}]} y'}]
    out = ship._sticky_summary(comments, [bot])
    assert out["sticky_found"] and out["sha"] == "abc" and out["status"] == "BLOCKING"
    assert out["findings_count"] == 2 and out["retrigger"] is True


def test_sticky_summary_plain_mode_no_meta() -> None:
    bot = {"stickyBeacon": "<!-- review-bot -->", "stickyMeta": False}
    out = ship._sticky_summary([{"body": "only a <!-- review-bot --> beacon"}], [bot])
    assert out["sticky_found"] and out["sha"] is None and out["status"] is None


def test_sticky_summary_empty_reviewbots_is_not_found() -> None:
    assert ship._sticky_summary([{"body": "x <!-- review-bot --> here"}], [])["sticky_found"] is False


def test_parse_sticky_meta_nested_braces_whole() -> None:
    assert ship._parse_sticky_meta('<!-- rb --> {"a":{"b":1}} tail', "<!-- rb -->") == {"a": {"b": 1}}


def test_fetch_sticky_summary_found_by_configured_beacon() -> None:
    configure(reviewBots=[{"checkNames": ["review-bot"], "stickyBeacon": "<!-- review-bot -->",
                           "stickyMeta": False}])
    body = "<!-- review-bot -->\n\n## Code review\n\nLooks good.\n"
    ship._SLUG_CACHE = "o/r"
    with patch.object(ship, "run", return_value=_FakeProc(stdout=json.dumps([{"body": body}]))):
        out = ship.cmd_fetch_sticky_summary(99)
    assert out["sticky_found"] is True
    assert out["sha"] is None and out["status"] is None


def test_fetch_sticky_summary_not_found_when_no_beacon() -> None:
    configure(reviewBots=[{"checkNames": ["review-bot"], "stickyBeacon": "<!-- review-bot -->"}])
    ship._SLUG_CACHE = "o/r"
    with patch.object(ship, "run",
                      return_value=_FakeProc(stdout=json.dumps([{"body": "regular comment"}]))):
        out = ship.cmd_fetch_sticky_summary(99)
    assert out["sticky_found"] is False


def test_fetch_sticky_summary_empty_reviewbots_zero_network() -> None:
    def boom(cmd, **k):
        raise AssertionError(f"empty reviewBots must not shell: {cmd}")

    with patch.object(ship, "run", side_effect=boom):
        out = ship.cmd_fetch_sticky_summary(99)  # default config: reviewBots == []
    assert out["sticky_found"] is False


def test_fetch_sticky_summary_uses_per_page_100_not_paginate() -> None:
    configure(reviewBots=[{"checkNames": ["review-bot"], "stickyBeacon": "<!-- review-bot -->",
                           "stickyMeta": False}])
    ship._SLUG_CACHE = "owner/repo"
    comments = [{"id": 1, "body": "unrelated"}, {"id": 2, "body": "here <!-- review-bot -->"}]
    captured: list[list[str]] = []

    def fake_run(args, **_kw):
        captured.append(list(args))
        return _FakeProc(stdout=json.dumps(comments))

    with patch.object(ship, "run", side_effect=fake_run):
        out = ship.cmd_fetch_sticky_summary(42)
    api = [a for a in captured if "issues" in str(a)]
    assert api
    assert all("--paginate" not in a for a in api)
    assert all(any("per_page=100" in arg for arg in a) for a in api)
    assert any(any("page=1" in arg for arg in a) for a in api)
    assert out["sticky_found"] is True


# ===========================================================================
# branch-name-valid
# ===========================================================================


@pytest.mark.parametrize(
    "branch,expected",
    [
        ("claude/distracted-saha-3e9299", 0),
        ("feature/foo", 0),
        ("claude/UPPERCASE-name-1234", 0),
        ("main", 2),
        ("", 2),
    ],
)
def test_branch_name_valid(branch: str, expected: int, monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    with patch("ship.current_branch", return_value=branch):
        assert ship.cmd_branch_name_valid() == expected


def test_branch_name_valid_is_pure_local(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    monkeypatch.setattr(ship, "current_branch", lambda: "feature/x")

    def no_gh(cmd, **k):
        assert cmd[0] != "gh", cmd
        return _FakeProc()

    monkeypatch.setattr(ship, "run", no_gh)
    assert ship.cmd_branch_name_valid() == ship.EXIT_OK


# ===========================================================================
# merge-pr (default squash, worktree-safe remote-branch delete)
# ===========================================================================


def test_cmd_merge_pr_uses_configured_method_default_squash(monkeypatch) -> None:
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return _FakeProc()

    monkeypatch.setattr(ship, "run", fake_run)
    monkeypatch.setattr(ship, "_delete_remote_branch", lambda pr: None)
    assert ship.cmd_merge_pr(42) == ship.EXIT_OK
    merge = [c for c in calls if c[:3] == ["gh", "pr", "merge"]]
    assert merge and "--squash" in merge[0] and "--merge" not in merge[0]


def test_cmd_merge_pr_already_merged_is_ok(monkeypatch) -> None:
    monkeypatch.setattr(ship, "run",
                        lambda cmd: _FakeProc(stderr="Pull request already merged", returncode=1))
    monkeypatch.setattr(ship, "_delete_remote_branch", lambda pr: None)
    assert ship.cmd_merge_pr(42) == ship.EXIT_OK


def _merge_pr_fake_run(calls, *, delete_proc):
    def fake_run(cmd, **_kw):
        calls.append(cmd)
        if cmd[:4] == ["gh", "pr", "merge", "--squash"]:
            return _FakeProc()
        if cmd[:3] == ["gh", "pr", "view"] and "headRefName" in cmd:
            return _FakeProc(stdout='{"headRefName": "claude/foo-bar-abc123"}')
        if cmd[:3] == ["gh", "repo", "view"]:
            return _FakeProc(stdout="example-org/example-repo")
        if cmd[:4] == ["gh", "api", "-X", "DELETE"]:
            return delete_proc
        raise AssertionError(f"unexpected cmd: {cmd}")

    return fake_run


def test_merge_pr_drops_delete_branch_and_deletes_remote_ref() -> None:
    calls: list[list[str]] = []
    with patch.object(ship, "run", side_effect=_merge_pr_fake_run(calls, delete_proc=_FakeProc())):
        assert ship.cmd_merge_pr(123) == ship.EXIT_OK
    assert not any("--delete-branch" in c for c in calls)
    assert not any(c[:2] == ["git", "checkout"] for c in calls)
    assert ["gh", "api", "-X", "DELETE",
            "repos/example-org/example-repo/git/refs/heads/claude/foo-bar-abc123"] in calls


def test_merge_pr_tolerates_already_deleted_remote_ref() -> None:
    calls: list[list[str]] = []
    gone = _FakeProc(stderr="HTTP 422: Reference does not exist", returncode=1)
    with patch.object(ship, "run", side_effect=_merge_pr_fake_run(calls, delete_proc=gone)):
        assert ship.cmd_merge_pr(456) == ship.EXIT_OK


def test_merge_pr_best_effort_when_gh_view_fails_post_merge() -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        if cmd[:4] == ["gh", "pr", "merge", "--squash"]:
            return _FakeProc()
        if cmd[:3] == ["gh", "pr", "view"]:
            return _FakeProc(stderr="HTTP 503: upstream timeout", returncode=1)
        raise AssertionError(f"unexpected cmd: {cmd}")

    with patch.object(ship, "run", side_effect=fake_run):
        assert ship.cmd_merge_pr(789) == ship.EXIT_OK
    assert not any(c[:4] == ["gh", "api", "-X", "DELETE"] for c in calls)


# ===========================================================================
# rebase-decision
# ===========================================================================


def test_rebase_decision_up_to_date_skips() -> None:
    with patch.object(ship, "_master_ahead", return_value=0), \
         patch.object(ship, "run", return_value=_FakeProc()):
        assert ship.cmd_rebase_decision()["decision"] == "SKIP"


def test_rebase_decision_no_pr_rebases() -> None:
    with patch.object(ship, "_master_ahead", return_value=5), \
         patch.object(ship, "_has_pr", return_value=False), \
         patch.object(ship, "run", return_value=_FakeProc()):
        assert ship.cmd_rebase_decision()["decision"] == "REBASE"


def test_rebase_decision_file_overlap_triggers_rebase() -> None:
    def fake_changed(spec):
        return ["src/foo.py", "src/bar.py"] if "HEAD..." in spec else ["src/foo.py"]

    with patch.object(ship, "_master_ahead", return_value=5), \
         patch.object(ship, "_has_pr", return_value=True), \
         patch.object(ship, "_files_changed", side_effect=fake_changed), \
         patch.object(ship, "_merge_tree_conflict", return_value=False), \
         patch.object(ship, "run", return_value=_FakeProc()):
        out = ship.cmd_rebase_decision()
    assert out["decision"] == "REBASE"
    assert "overlap" in out["reason"].lower()


def test_rebase_decision_code_overlap_flags_source_files() -> None:
    configure(hotPaths=[r".*\.lock$"])

    def fake_changed(spec):
        return (["src/service.py", "deps.lock"] if "HEAD..." in spec else ["src/service.py"])

    with patch.object(ship, "_master_ahead", return_value=5), \
         patch.object(ship, "_has_pr", return_value=True), \
         patch.object(ship, "_files_changed", side_effect=fake_changed), \
         patch.object(ship, "_merge_tree_conflict", return_value=False), \
         patch.object(ship, "run", return_value=_FakeProc()):
        out = ship.cmd_rebase_decision()
    assert out["decision"] == "REBASE"
    assert out["code_overlap"] is True
    assert "src/service.py" in out["overlap_files"]


def test_rebase_decision_hot_only_overlap_no_code_flag() -> None:
    configure(hotPaths=[r".*\.lock$"])

    def fake_changed(spec):
        return (["deps.lock", "x.txt"] if "HEAD..." in spec else ["deps.lock"])

    with patch.object(ship, "_master_ahead", return_value=5), \
         patch.object(ship, "_has_pr", return_value=True), \
         patch.object(ship, "_files_changed", side_effect=fake_changed), \
         patch.object(ship, "_merge_tree_conflict", return_value=False), \
         patch.object(ship, "run", return_value=_FakeProc()):
        out = ship.cmd_rebase_decision()
    assert out["decision"] == "REBASE"
    assert out["code_overlap"] is False
    assert out["hot_files_changed"] == ["deps.lock"]


def test_rebase_decision_fetches_resolved_base_ref(monkeypatch) -> None:
    monkeypatch.setattr(ship, "lookup_pr_number", lambda: 7)
    monkeypatch.setattr(ship, "_pr_base_ref", lambda n: "origin/release/x")
    monkeypatch.setattr(ship, "_master_ahead", lambda: 0)
    calls = []
    monkeypatch.setattr(ship, "run",
                        lambda cmd: (calls.append(cmd), _FakeProc())[1])
    out = ship.cmd_rebase_decision()
    assert out["decision"] == "SKIP"
    assert calls[0] == ["git", "fetch", "origin", "release/x", "--quiet"]


# ===========================================================================
# size (new shape: tier/files/lines/hot_touched/code_change)
# ===========================================================================


def _numstat(text: str):
    return _FakeProc(stdout=text)


def test_size_small_tier(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    with patch.object(ship, "_files_changed", return_value=["src/foo.py"]), \
         patch.object(ship, "run", return_value=_numstat("10\t2\t-\tsrc/foo.py\n")):
        out = ship.cmd_size()
    assert out == {"tier": "Small", "files": 1, "lines": 12,
                   "hot_touched": False, "code_change": True}


@pytest.mark.parametrize(
    "nfiles,lines,expected",
    [(5, 99, "Small"), (5, 100, "Medium"), (6, 10, "Medium"),
     (20, 500, "Medium"), (21, 10, "Large"), (1, 501, "Large")],
)
def test_size_tier_boundaries(nfiles, lines, expected, monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    files = [f"src/F{i}.py" for i in range(nfiles)]
    per = [lines // nfiles] * nfiles
    per[0] += lines - sum(per)
    numstat = "".join(f"{n}\t0\tsrc/F{i}.py\n" for i, n in enumerate(per))
    with patch.object(ship, "_files_changed", return_value=files), \
         patch.object(ship, "run", return_value=_numstat(numstat)):
        out = ship.cmd_size()
    assert out["tier"] == expected
    assert out["lines"] == lines


def test_size_ignores_binary_numstat_dashes(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    with patch.object(ship, "_files_changed", return_value=["assets/logo.png"]), \
         patch.object(ship, "run", return_value=_numstat("-\t-\tassets/logo.png\n")):
        out = ship.cmd_size()
    assert out["lines"] == 0 and out["tier"] == "Small"


def test_size_empty_diff_is_small(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    with patch.object(ship, "_files_changed", return_value=[]), \
         patch.object(ship, "run", return_value=_numstat("")):
        out = ship.cmd_size()
    assert out == {"tier": "Small", "files": 0, "lines": 0,
                   "hot_touched": False, "code_change": True}


def test_size_zero_code_change_for_docs_and_config(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    with patch.object(ship, "_files_changed",
                      return_value=["README.md", "docs/guide.md", ".claude/x.json"]), \
         patch.object(ship, "run", return_value=_numstat("2\t1\ta\n2\t1\tb\n2\t1\tc\n")):
        out = ship.cmd_size()
    assert out["code_change"] is False


def test_size_hot_touched_flag(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    configure(hotPaths=[r".*\.lock$"])
    with patch.object(ship, "_files_changed", return_value=["deps.lock", "src/foo.py"]), \
         patch.object(ship, "run", return_value=_numstat("1\t0\ta\n1\t0\tb\n")):
        out = ship.cmd_size()
    assert out["hot_touched"] is True
    assert out["code_change"] is True


# ===========================================================================
# post-pr-body (grouped by top-level path segment)
# ===========================================================================


def test_post_pr_body_groups_files_by_top_segment(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    proc = _FakeProc(stdout=("src/app/foo.py\nsrc/lib/bar.py\ntests/test_x.py\n"
                             "docs/guide.md\nREADME.md\n"))
    with patch.object(ship, "run", return_value=proc):
        body = ship.cmd_post_pr_body("Adds X for Y.")
    assert "## Summary" in body and "Adds X for Y." in body
    assert "**src**" in body and "**tests**" in body and "**docs**" in body
    assert "**(root)**" in body            # README.md has no slash
    assert "Claude Code" in body


def test_post_pr_body_diffs_against_base_ref(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    calls = []
    monkeypatch.setattr(ship, "run", lambda cmd: (calls.append(cmd), _FakeProc())[1])
    ship.cmd_post_pr_body("S")
    assert calls[0] == ["git", "diff", "--name-only", "origin/main...HEAD"]

    calls.clear()
    monkeypatch.setenv("SHIP_BASE_REF", "origin/feature-base")
    ship.cmd_post_pr_body("S")
    assert calls[0] == ["git", "diff", "--name-only", "origin/feature-base...HEAD"]


# ===========================================================================
# failures + flake classification (config-driven)
# ===========================================================================


def test_failures_returns_failed_rows_with_workflow_id() -> None:
    fx = load_fixture("ci_failed")
    rows = ship.cmd_failures(fixture={"check_runs": fx["check_runs"]})
    assert len(rows) == 1
    assert rows[0]["name"] == "ui-test"
    assert rows[0]["workflow_run_id"] == "201"
    assert rows[0]["flaky_signal"] == {
        "is_flaky": False, "mechanism": None, "hint": None, "matched_frame": None}


def test_failures_excludes_configured_and_review_checks() -> None:
    configure(reviewBots=[REVIEW_BOT], checkExclusions=["task-check"])
    cr = [
        {"name": "task-check", "conclusion": "failure",
         "details_url": "https://github.com/o/r/actions/runs/998"},
        {"name": "review-bot", "conclusion": "failure",
         "details_url": "https://github.com/o/r/actions/runs/999"},
        {"name": "unit-test", "conclusion": "failure",
         "details_url": "https://github.com/o/r/actions/runs/1000"},
    ]
    rows = ship.cmd_failures(fixture={"check_runs": {"check_runs": cr}})
    assert [r["name"] for r in rows] == ["unit-test"]


@pytest.mark.parametrize(
    "log,mechanism",
    [
        ("OutOfMemoryError: heap exhausted", "memory"),
        ("Connection refused: no route", "network"),
        ("connection reset by peer", "network"),
        ("SocketTimeout while reading", "network"),
        ("test exceeded timeout of 5000ms", "timing"),
    ],
)
def test_classify_flaky_default_mechanisms(log, mechanism) -> None:
    out = ship.classify_flaky(log)
    assert out["is_flaky"] is True
    assert out["mechanism"] == mechanism
    assert out["hint"]           # non-empty deflake hint
    assert out["matched_frame"]


def test_classify_flaky_unknown_is_not_flaky() -> None:
    assert ship.classify_flaky("ordinary assertion: expected 1 was 2") == {
        "is_flaky": False, "mechanism": None, "hint": None, "matched_frame": None}


def test_classify_flaky_config_driven_first_match_wins() -> None:
    configure(flakePatterns=[
        {"regex": "SpecificLeakX", "mechanism": "custom-leak", "hint": "close the resource"},
        {"regex": "(?i)timeout", "mechanism": "timing", "hint": "bump timeout"},
    ])
    # A log matching both the specific row and the broad timeout row → specific wins.
    out = ship.classify_flaky("SpecificLeakX after timeout of 5s")
    assert out["mechanism"] == "custom-leak"
    assert out["hint"] == "close the resource"
    # Non-matching → not flaky.
    assert ship.classify_flaky("plain failure")["is_flaky"] is False


@pytest.mark.parametrize(
    "fixture_name,mechanism",
    [("flaky-memory", "memory"), ("flaky-network", "network"), ("flaky-timing", "timing")],
)
def test_classify_flaky_recognizes_flaky_fixtures(fixture_name, mechanism) -> None:
    fx = load_fixture(fixture_name)
    rows = ship.cmd_failures(fixture=fx)
    assert rows[0]["flaky_signal"]["is_flaky"] is True
    assert rows[0]["flaky_signal"]["mechanism"] == mechanism


def test_cmd_failures_check_runs_uses_per_page_100_not_paginate() -> None:
    resp = {"check_runs": [{"name": "Build", "conclusion": "failure", "status": "completed",
                            "details_url": "https://github.com/owner/repo/actions/runs/9999/jobs/1",
                            "failed_log": ""}]}
    captured: list[list[str]] = []

    def fake_run(args, **_kw):
        captured.append(list(args))
        return _FakeProc() if args[0] == "git" else _FakeProc(stdout=json.dumps(resp))

    ship._SLUG_CACHE = "owner/repo"
    with patch.object(ship, "run", side_effect=fake_run):
        rows = ship.cmd_failures()
    call = next((a for a in captured if "check-runs" in str(a)), None)
    assert call is not None
    assert "--paginate" not in call
    assert any("per_page=100" in arg for arg in call)
    assert rows[0]["name"] == "Build"


# ===========================================================================
# extract-failed-tests (config-driven failedTestRegex)
# ===========================================================================


def test_extract_failed_tests_empty_config_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(ship, "_fetch_failed_log", lambda rid: "com.example.FooTest > bar FAILED")
    assert ship.cmd_extract_failed_tests("run-1") == []  # default failedTestRegex is ""


def test_extract_failed_tests_configured_regex(monkeypatch) -> None:
    configure(failedTestRegex=r"(\S+) > (\S+) FAILED")
    monkeypatch.setattr(ship, "_fetch_failed_log",
                        lambda rid: "com.example.FooTest > bar FAILED\ncom.example.BazTest > qux FAILED\n")
    fqns = ship.cmd_extract_failed_tests("run-2")
    assert "com.example.FooTest.bar" in fqns
    assert "com.example.BazTest.qux" in fqns


def test_cmd_extract_failed_tests_empty_on_fetch_failure(monkeypatch) -> None:
    configure(failedTestRegex=r"(\S+) FAILED")
    monkeypatch.setattr(ship, "_fetch_failed_log", lambda rid: "")
    assert ship.cmd_extract_failed_tests("run-3") == []


# ===========================================================================
# flake ticket handoff
# ===========================================================================


def test_cmd_open_flake_ticket_writes_pr_scoped_marker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHIP_PR_NUMBER", "42")
    monkeypatch.setenv("SHIP_FLAKE_MARKER_DIR", str(tmp_path))
    rc = ship.cmd_open_flake_ticket(
        "com.example.FooTest.bar", module="core",
        run_url="https://github.com/example-org/example-repo/actions/runs/789",
        frames="OutOfMemoryError: heap exhausted")
    assert rc == ship.EXIT_TRANSIENT
    payload = json.loads((tmp_path / "ship-flake-ticket-request-42.json").read_text())
    assert payload["fqn"] == "com.example.FooTest.bar"
    assert payload["module"] == "core"
    assert payload["route"] == "gh-issue"        # default ticketRoute
    assert "OutOfMemoryError" in payload["relevant_frames"]


def test_cmd_open_flake_ticket_marker_dir_defaults_to_tmp(monkeypatch) -> None:
    monkeypatch.delenv("SHIP_FLAKE_MARKER_DIR", raising=False)
    assert ship._flake_marker_dir() == "/tmp"


# ===========================================================================
# reply/resolve thread + reply marker
# ===========================================================================


def test_reply_thread_posts_via_graphql(monkeypatch) -> None:
    captured = {}

    def fake_run(cmd):
        captured["cmd"] = cmd
        return _FakeProc(stdout=json.dumps(
            {"data": {"addPullRequestReviewThreadReply": {"comment": {"id": "PRRC_new"}}}}))

    monkeypatch.setattr(ship, "run", fake_run)
    assert ship.cmd_reply_thread("PRRT_1", "thanks") == "PRRC_new"
    assert "addPullRequestReviewThreadReply" in str(captured["cmd"])


def test_reply_thread_stamps_marker_idempotently(monkeypatch) -> None:
    bodies = []

    def fake_run(cmd):
        # capture the -f body=... argument
        for i, a in enumerate(cmd):
            if a == "-f" and cmd[i + 1].startswith("body="):
                bodies.append(cmd[i + 1][len("body="):])
        return _FakeProc(stdout=json.dumps(
            {"data": {"addPullRequestReviewThreadReply": {"comment": {"id": "x"}}}}))

    monkeypatch.setattr(ship, "run", fake_run)
    ship.cmd_reply_thread("PRRT_1", "hello")
    assert bodies[0].startswith(ship.SHIP_REPLY_MARKER)
    # Already-stamped body is not double-stamped.
    ship.cmd_reply_thread("PRRT_1", f"{ship.SHIP_REPLY_MARKER}\nhello")
    assert bodies[1].count(ship.SHIP_REPLY_MARKER) == 1


def test_stamp_reply_marker_prepends_and_idempotent() -> None:
    stamped = ship._stamp_reply_marker("body")
    assert stamped.startswith(ship.SHIP_REPLY_MARKER)
    assert ship._stamp_reply_marker(stamped) == stamped


def test_resolve_thread_ignores_already_resolved(monkeypatch) -> None:
    monkeypatch.setattr(ship, "run",
                        lambda cmd: _FakeProc(stderr="thread is already resolved", returncode=1))
    ship.cmd_resolve_thread("PRRT_1")  # no raise


def test_resolve_thread_dies_on_other_error(monkeypatch) -> None:
    monkeypatch.setattr(ship, "run",
                        lambda cmd: _FakeProc(stderr="Permission denied", returncode=1))
    with pytest.raises(SystemExit):
        ship.cmd_resolve_thread("PRRT_1")


# ===========================================================================
# push
# ===========================================================================


def test_cmd_push_success_clears_did_rebase(monkeypatch) -> None:
    import contextlib
    monkeypatch.setattr(ship, "run", lambda cmd: _FakeProc())
    monkeypatch.setattr(ship, "lookup_pr_number", lambda: 42)
    monkeypatch.setattr(ship, "_StateLock", lambda pr: contextlib.nullcontext())
    captured = {}
    monkeypatch.setattr(ship, "init_state_if_needed",
                        lambda pr: ({"hdr": 1}, {"did_rebase": True, "force_rebase": True}))
    monkeypatch.setattr(ship, "write_state_atomic", lambda pr, h, b: captured.update(b))
    out = ship.cmd_push()
    assert out["success"] is True
    assert captured["did_rebase"] is False
    assert captured["force_rebase"] is False


def test_cmd_push_failure_returns_stderr(monkeypatch) -> None:
    monkeypatch.setattr(ship, "run",
                        lambda cmd: _FakeProc(stderr="error: rejected by remote", returncode=1))
    out = ship.cmd_push()
    assert out["success"] is False
    assert "rejected" in out["stderr"]


# ===========================================================================
# cleanup-worktree
# ===========================================================================


def _worktree_porcelain(main: Path, feature: Path) -> str:
    return (f"worktree {main}\nHEAD 0000000000000000000000000000000000000000\n"
            f"branch refs/heads/main\n\n"
            f"worktree {feature}\nHEAD 1111111111111111111111111111111111111111\n"
            f"branch refs/heads/claude/alpha-beta-abc123\n")


def test_cleanup_worktree_requires_explicit_target(tmp_path: Path) -> None:
    main = tmp_path / "main"; main.mkdir()
    feature = tmp_path / "wt" / "alpha-beta-abc123"; feature.mkdir(parents=True)
    with patch.object(ship, "run", return_value=_FakeProc(stdout=_worktree_porcelain(main, feature))), \
         patch("ship.Path.cwd", return_value=main):
        with pytest.raises(SystemExit) as exc:
            ship.cmd_cleanup_worktree()
    assert exc.value.code == ship.EXIT_HALT


def test_cleanup_worktree_by_path_from_main_succeeds(tmp_path: Path) -> None:
    main = tmp_path / "main"; main.mkdir()
    feature = tmp_path / "wt" / "alpha-beta-abc123"; feature.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        if cmd[:3] == ["git", "worktree", "list"]:
            return _FakeProc(stdout=_worktree_porcelain(main, feature))
        if cmd[:3] == ["git", "worktree", "remove"]:
            return _FakeProc()
        raise AssertionError(f"unexpected: {cmd}")

    with patch.object(ship, "run", side_effect=fake_run), patch("ship.Path.cwd", return_value=main):
        assert ship.cmd_cleanup_worktree(path=str(feature)) == ship.EXIT_OK
    assert ["git", "worktree", "remove", "--force", str(feature.resolve())] in calls


def test_cleanup_worktree_by_branch_resolves_path(tmp_path: Path) -> None:
    main = tmp_path / "main"; main.mkdir()
    feature = tmp_path / "wt" / "alpha-beta-abc123"; feature.mkdir(parents=True)
    removed: list[str] = []

    def fake_run(cmd, **_kw):
        if cmd[:3] == ["git", "worktree", "list"]:
            return _FakeProc(stdout=_worktree_porcelain(main, feature))
        if cmd[:3] == ["git", "worktree", "remove"]:
            removed.append(cmd[-1])
            return _FakeProc()
        raise AssertionError(f"unexpected: {cmd}")

    with patch.object(ship, "run", side_effect=fake_run), patch("ship.Path.cwd", return_value=main):
        assert ship.cmd_cleanup_worktree(branch="claude/alpha-beta-abc123") == ship.EXIT_OK
    assert removed == [str(feature.resolve())]


def test_cleanup_worktree_unknown_branch_halts(tmp_path: Path) -> None:
    main = tmp_path / "main"; main.mkdir()
    feature = tmp_path / "wt" / "alpha-beta-abc123"; feature.mkdir(parents=True)
    with patch.object(ship, "run", return_value=_FakeProc(stdout=_worktree_porcelain(main, feature))), \
         patch("ship.Path.cwd", return_value=main):
        with pytest.raises(SystemExit) as exc:
            ship.cmd_cleanup_worktree(branch="claude/no-such")
    assert exc.value.code == ship.EXIT_HALT


def test_cleanup_worktree_refuses_main_worktree(tmp_path: Path) -> None:
    main = tmp_path / "main"; main.mkdir()
    feature = tmp_path / "wt" / "alpha-beta-abc123"; feature.mkdir(parents=True)
    with patch.object(ship, "run", return_value=_FakeProc(stdout=_worktree_porcelain(main, feature))), \
         patch("ship.Path.cwd", return_value=main):
        with pytest.raises(SystemExit) as exc:
            ship.cmd_cleanup_worktree(path=str(main))
    assert exc.value.code == ship.EXIT_HALT


def test_cleanup_worktree_refuses_self_removal_from_inside(tmp_path: Path) -> None:
    main = tmp_path / "main"; main.mkdir()
    feature = tmp_path / "wt" / "alpha-beta-abc123"; feature.mkdir(parents=True)
    with patch.object(ship, "run", return_value=_FakeProc(stdout=_worktree_porcelain(main, feature))), \
         patch("ship.Path.cwd", return_value=feature):
        with pytest.raises(SystemExit) as exc:
            ship.cmd_cleanup_worktree(path=str(feature))
    assert exc.value.code == ship.EXIT_HALT


# ===========================================================================
# rate-limit probe + floor
# ===========================================================================


def test_rate_floor_ok_blocks_below_floor_and_fails_open_on_unknown() -> None:
    assert ship._rate_floor_ok({"core": 100, "graphql": 5000}, core_floor=3000, graphql_floor=3000) is False
    assert ship._rate_floor_ok({"core": 5000, "graphql": 10}, core_floor=3000, graphql_floor=3000) is False
    assert ship._rate_floor_ok({"core": 5000, "graphql": 5000}, core_floor=3000, graphql_floor=3000) is True
    assert ship._rate_floor_ok({"core": None, "graphql": None}, core_floor=3000, graphql_floor=3000) is True


def test_rate_limit_remaining_parses_gh_payload() -> None:
    payload = {"resources": {"core": {"remaining": 4200, "reset": 9999999999},
                             "graphql": {"remaining": 4900, "reset": 9999999999}}}
    with patch.object(ship, "run", return_value=_FakeProc(stdout=json.dumps(payload))):
        rem = ship.rate_limit_remaining()
    assert rem["core"] == 4200 and rem["graphql"] == 4900 and rem["reset_in"] >= 0


def test_rate_limit_remaining_fails_open_on_error() -> None:
    with patch.object(ship, "run", return_value=_FakeProc(stderr="boom", returncode=1)):
        assert ship.rate_limit_remaining() == {"core": None, "graphql": None, "reset_in": 0}


def test_rate_limit_remaining_fails_open_on_malformed_json() -> None:
    with patch.object(ship, "run", return_value=_FakeProc(stdout="not json {")):
        assert ship.rate_limit_remaining() == {"core": None, "graphql": None, "reset_in": 0}


# ===========================================================================
# wake taxonomy + _watch_decide
# ===========================================================================


def test_wake_taxonomy_buckets_are_disjoint_and_cover_caps() -> None:
    assert ship.WAKE_HINTS.isdisjoint(ship.WAIT_HINTS)
    assert {"ci_failed", "fetch_threads", "merge_conflict", "sticky_sha_stale"} <= ship.WAKE_HINTS
    assert {"wait_ci", "wait_first_review", "wait_reapproval", "wait_review_submit"} <= ship.WAIT_HINTS
    assert ship.WAIT_WALLCLOCK_CAP["wait_first_review"] == 1800
    assert ship.WAIT_WALLCLOCK_CAP["wait_reapproval"] == 3600
    assert ship.WAIT_WALLCLOCK_CAP["wait_review_submit"] == 3600
    assert ship.WAIT_WALLCLOCK_CAP.get("wait_ci") is None


def _env(hint, *, sha="abc", cadence=60, reason="r"):
    return {"hint": hint, "sha": sha, "cadence_hint_seconds": cadence, "reason": reason,
            "pr_url": "https://github.com/o/r/pull/1"}


def test_watch_decide_wait_is_silent_with_cadence() -> None:
    d = ship._watch_decide(_env("wait_ci", cadence=270), merge_flag=False,
                           last_wake_key=None, wait_elapsed=0)
    assert d.stdout is None and d.stderr is not None and d.action is None
    assert d.do_exit is False and d.sleep == 30  # fast-fail cadence


def test_watch_decide_wake_emits_once_then_dedups() -> None:
    first = ship._watch_decide(_env("ci_failed"), merge_flag=False,
                               last_wake_key=None, wait_elapsed=0)
    assert first.stdout is not None
    assert first.stdout["event"] == "transition" and first.stdout["hint"] == "ci_failed"
    again = ship._watch_decide(_env("ci_failed"), merge_flag=False,
                               last_wake_key=("ci_failed", "abc"), wait_elapsed=0)
    assert again.stdout is None and again.do_exit is False


def test_watch_decide_promote_is_auto_no_wake() -> None:
    d = ship._watch_decide(_env("promote_draft"), merge_flag=False,
                           last_wake_key=None, wait_elapsed=0)
    assert d.stdout is None and d.action == "promote" and d.do_exit is False


def test_watch_decide_promote_is_held_terminal_with_draft_flag() -> None:
    d = ship._watch_decide(_env("promote_draft"), merge_flag=False,
                           last_wake_key=None, wait_elapsed=0, draft_flag=True)
    assert d.action is None and d.stdout is not None
    assert d.stdout["hint"] == "held_draft" and "draft" in d.stdout["reason"]
    assert d.do_exit is True


def test_watch_decide_clean_exit_wakes_terminal_without_merge_flag() -> None:
    d = ship._watch_decide(_env("clean_exit"), merge_flag=False,
                           last_wake_key=None, wait_elapsed=0)
    assert d.stdout is not None and d.action is None and d.do_exit is True


def test_watch_decide_clean_exit_is_auto_merge_with_flag() -> None:
    d = ship._watch_decide(_env("clean_exit"), merge_flag=True,
                           last_wake_key=None, wait_elapsed=0)
    assert d.stdout is None and d.action == "merge" and d.do_exit is False


def test_watch_decide_behind_base_auto_only_with_merge_flag() -> None:
    auto = ship._watch_decide(_env("behind_base"), merge_flag=True,
                              last_wake_key=None, wait_elapsed=0)
    assert auto.action == "rebase" and auto.stdout is None
    wake = ship._watch_decide(_env("behind_base"), merge_flag=False,
                              last_wake_key=None, wait_elapsed=0)
    assert wake.action is None and wake.stdout is not None


def test_watch_decide_retrigger_is_auto() -> None:
    d = ship._watch_decide(_env("retrigger_review"), merge_flag=True,
                           last_wake_key=None, wait_elapsed=0)
    assert d.action == "retrigger" and d.stdout is None


def test_watch_decide_halt_is_terminal_wake() -> None:
    d = ship._watch_decide(_env("halt"), merge_flag=True, last_wake_key=None, wait_elapsed=0)
    assert d.stdout is not None and d.do_exit is True


def test_watch_decide_wait_past_cap_becomes_halt() -> None:
    d = ship._watch_decide(_env("wait_first_review"), merge_flag=False,
                           last_wake_key=None, wait_elapsed=1801)
    assert d.stdout is not None and d.stdout["hint"] == "halt"
    assert "cap" in d.stdout["reason"] and d.do_exit is True


def test_watch_decide_rewake_reemits_persisting_wake() -> None:
    key = ("ci_failed", "abc")
    fresh = ship._watch_decide(_env("ci_failed"), merge_flag=False,
                               last_wake_key=key, wait_elapsed=0, rewake=False)
    assert fresh.stdout is None
    stale = ship._watch_decide(_env("ci_failed"), merge_flag=False,
                               last_wake_key=key, wait_elapsed=0, rewake=True)
    assert stale.stdout is not None and stale.stdout["hint"] == "ci_failed"


def test_watch_decide_carries_nudge_on_renudge_only() -> None:
    key = ("ci_failed", "abc")
    renudge = ship._watch_decide(_env("ci_failed"), merge_flag=False,
                                 last_wake_key=key, wait_elapsed=0, rewake=True, nudge=3)
    assert renudge.stdout["nudge"] == 3
    fresh = ship._watch_decide(_env("ci_failed"), merge_flag=False,
                               last_wake_key=None, wait_elapsed=0, nudge=0)
    assert "nudge" not in fresh.stdout


# ===========================================================================
# _watch_run_action
# ===========================================================================


def test_watch_run_action_promote_ok() -> None:
    with patch.object(ship, "cmd_promote_draft", return_value=ship.EXIT_OK):
        assert ship._watch_run_action("promote", 1, merge_flag=False)[0] == "ok"


def test_watch_run_action_promote_failure_halts() -> None:
    def boom():
        raise SystemExit(ship.EXIT_HALT)

    with patch.object(ship, "cmd_promote_draft", side_effect=boom):
        outcome, detail = ship._watch_run_action("promote", 1, merge_flag=False)
    assert outcome == "halt" and "promote" in detail


def test_watch_run_action_merge_success_is_done() -> None:
    with patch.object(ship, "_watch_do_merge", lambda pr: ("done", "merged")):
        assert ship._watch_run_action("merge", 7, merge_flag=True) == ("done", "merged")


def test_watch_run_action_merge_human_review_halts() -> None:
    with patch.object(ship, "_watch_do_merge", lambda pr: ("halt", "needs agent")):
        assert ship._watch_run_action("merge", 7, merge_flag=True)[0] == "halt"


def test_watch_run_action_rebase_conflict_halts_without_mutating() -> None:
    decision = {"decision": "REBASE", "reason": "overlap", "code_overlap": True,
                "hot_files_changed": [], "overlap_files": ["x.py"], "staleness_count": 2}
    with patch.object(ship, "cmd_rebase_decision", return_value=decision), \
         patch.object(ship, "cmd_rebase_attempt") as mock:
        outcome, detail = ship._watch_run_action("rebase", 3, merge_flag=True)
    assert outcome == "halt" and "judgment" in detail
    mock.assert_not_called()


def test_watch_run_action_rebase_clean_then_push_ok() -> None:
    decision = {"decision": "REBASE", "reason": "stale", "code_overlap": False,
                "hot_files_changed": [], "overlap_files": [], "staleness_count": 12}
    with patch.object(ship, "cmd_rebase_decision", return_value=decision), \
         patch.object(ship, "cmd_rebase_attempt", return_value={"success": True, "conflicted_files": []}), \
         patch.object(ship, "cmd_push", return_value={"success": True}):
        assert ship._watch_run_action("rebase", 3, merge_flag=True)[0] == "ok"


def test_watch_run_action_rebase_skip_chains_to_merge() -> None:
    decision = {"decision": "SKIP", "reason": "up to date", "code_overlap": False,
                "hot_files_changed": [], "overlap_files": [], "staleness_count": 0}
    with patch.object(ship, "cmd_rebase_decision", return_value=decision), \
         patch.object(ship, "_watch_do_merge", lambda pr: ("done", "merged")):
        assert ship._watch_run_action("rebase", 3, merge_flag=True)[0] == "done"


def test_watch_run_action_reply_only_suppresses_mutations() -> None:
    for action in ("promote", "rebase", "merge", "retrigger"):
        outcome, detail = ship._watch_run_action(action, 42, merge_flag=True, reply_only=True)
        assert outcome == "halt" and "reply-only" in detail.lower()


def test_watch_run_action_retrigger_delegates() -> None:
    with patch.object(ship, "_do_retrigger_review", lambda pr: ("ok", "toggled")):
        assert ship._watch_run_action("retrigger", 1, merge_flag=True) == ("ok", "toggled")


def test_do_retrigger_review_self_caps(tmp_path: Path) -> None:
    with patch("ship.git_dir", return_value=tmp_path), \
         patch("ship.current_branch", return_value="claude/x"), \
         patch("ship.current_sha", return_value="sha"), \
         patch("ship.merge_base_sha", return_value="base"):
        header, body = ship.init_state_if_needed(1)
        body["retrigger_review_count"] = ship.RETRIGGER_REVIEW_CAP
        ship.write_state_atomic(1, header, body)
        outcome, detail = ship._do_retrigger_review(1)
    assert outcome == "halt" and "retrigger" in detail.lower()


def test_do_retrigger_review_toggles_and_increments(tmp_path: Path) -> None:
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return _FakeProc()

    with patch("ship.git_dir", return_value=tmp_path), \
         patch("ship.current_branch", return_value="claude/x"), \
         patch("ship.current_sha", return_value="sha"), \
         patch("ship.merge_base_sha", return_value="base"), \
         patch("ship.run", side_effect=fake_run):
        outcome, _ = ship._do_retrigger_review(1)
        _, body = ship.init_state_if_needed(1)
    assert outcome == "ok"
    assert body["retrigger_review_count"] == 1
    assert ["gh", "pr", "ready", "1", "--undo"] in calls
    assert ["gh", "pr", "ready", "1"] in calls


# ===========================================================================
# _merge_gate + _fetch_merge_gate
# ===========================================================================


def _green_classified():
    return {"total": 1, "any_failure": False, "any_pending": False, "all_done_ok": True,
            "gating_total": 1, "review_present": True, "review_completed": True}


def test_merge_gate_all_pass_merges() -> None:
    configure(reviewBots=[REVIEW_BOT])
    ok, wake, _ = ship._merge_gate(classified=_green_classified(), merge_state="CLEAN",
                                   review_decision="APPROVED", latest_reviews=[],
                                   threads_addressed=True)
    assert ok is True and wake == ""


def test_merge_gate_ci_pending_wait_ci() -> None:
    assert ship._merge_gate(
        classified={"total": 1, "any_failure": False, "any_pending": True},
        merge_state="CLEAN", review_decision="APPROVED", latest_reviews=[],
        threads_addressed=True)[1] == "wait_ci"


def test_merge_gate_behind_base() -> None:
    assert ship._merge_gate(classified=_green_classified(), merge_state="BEHIND",
                            review_decision="APPROVED", latest_reviews=[],
                            threads_addressed=True)[1] == "behind_base"


def test_merge_gate_unaddressed_thread_fetch_threads() -> None:
    assert ship._merge_gate(classified=_green_classified(), merge_state="CLEAN",
                            review_decision="APPROVED", latest_reviews=[],
                            threads_addressed=False)[1] == "fetch_threads"


def test_merge_gate_review_blocking_wait_review() -> None:
    configure(reviewBots=[REVIEW_BOT])
    assert ship._merge_gate(classified=_green_classified(), merge_state="CLEAN",
                            review_decision="REVIEW_REQUIRED", latest_reviews=[],
                            threads_addressed=True)[1] == "wait_review"


def test_merge_gate_empty_reviewbots_skips_approval() -> None:
    # default config: reviewBots == [] → approval sub-check skipped, gate merges.
    ok, _, _ = ship._merge_gate(classified=_green_classified(), merge_state="CLEAN",
                                review_decision=None, latest_reviews=[],
                                threads_addressed=True)
    assert ok is True


# ===========================================================================
# _pr_base_ref + base ref resolution + normalization
# ===========================================================================


def test_pr_base_ref_reads_base_ref_name(monkeypatch) -> None:
    monkeypatch.setattr(ship, "run",
                        lambda cmd: _FakeProc(stdout=json.dumps({"baseRefName": "main"})))
    assert ship._pr_base_ref(42) == "origin/main"


def test_pr_base_ref_falls_back_on_error(monkeypatch) -> None:
    monkeypatch.setattr(ship, "_fallback_base_branch", lambda: "main")
    monkeypatch.setattr(ship, "run", lambda cmd: _FakeProc(stderr="no pr", returncode=1))
    assert ship._pr_base_ref(42) == "origin/main"


def test_base_ref_honors_env(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/feature-x")
    assert ship._base_ref() == "origin/feature-x"


def test_base_ref_resolves_pr_base_when_env_unset(monkeypatch) -> None:
    monkeypatch.setattr(ship, "lookup_pr_number", lambda: 99)

    def fake_run(cmd):
        assert cmd == ["gh", "pr", "view", "99", "--json", "baseRefName"]
        return _FakeProc(stdout=json.dumps({"baseRefName": "release/x"}))

    monkeypatch.setattr(ship, "run", fake_run)
    assert ship._base_ref() == "origin/release/x"


def test_base_ref_env_override_beats_pr_resolution(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/release/y")

    def boom(*a, **k):
        raise AssertionError("must not lookup PR when env set")

    monkeypatch.setattr(ship, "lookup_pr_number", boom)
    assert ship._base_ref() == "origin/release/y"


def test_base_ref_no_pr_fallback_not_cached(monkeypatch) -> None:
    monkeypatch.setattr(ship, "_fallback_base_branch", lambda: "main")
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return None

    monkeypatch.setattr(ship, "lookup_pr_number", counting)
    assert ship._base_ref() == "origin/main"
    assert ship._base_ref() == "origin/main"
    assert calls["n"] == 2, "no-PR fallback must NOT be cached (re-resolve after PR created)"


def test_base_ref_real_resolution_is_cached(monkeypatch) -> None:
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return 7

    monkeypatch.setattr(ship, "lookup_pr_number", counting)
    monkeypatch.setattr(ship, "_pr_base_ref", lambda n: "origin/release/z")
    assert ship._base_ref() == "origin/release/z"
    assert ship._base_ref() == "origin/release/z"
    assert calls["n"] == 1, "PR-resolved base must be cached per process"


def test_master_ahead_uses_base_ref(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    calls = []
    monkeypatch.setattr(ship, "run",
                        lambda cmd: (calls.append(cmd), _FakeProc(stdout="3\n"))[1])
    assert ship._master_ahead() == 3
    assert calls[0] == ["git", "rev-list", "--count", "HEAD..origin/main"]


def test_merge_tree_conflict_uses_base_ref(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    calls = []
    monkeypatch.setattr(ship, "run", lambda cmd: (calls.append(cmd), _FakeProc())[1])
    assert ship._merge_tree_conflict() is False
    assert calls[0][-2:] == ["HEAD", "origin/main"]


def test_merge_base_sha_uses_base_ref(monkeypatch) -> None:
    monkeypatch.setenv("SHIP_BASE_REF", "origin/main")
    calls = []
    monkeypatch.setattr(ship, "run",
                        lambda cmd: (calls.append(cmd), _FakeProc(stdout="abc123"))[1])
    assert ship.merge_base_sha() == "abc123"
    assert calls[-1] == ["git", "merge-base", "HEAD", "origin/main"]


def test_normalize_base_ref_variants(monkeypatch) -> None:
    monkeypatch.setattr(ship, "_fallback_base_branch", lambda: "main")
    assert ship._normalize_base_ref("") == "origin/main"
    assert ship._normalize_base_ref("develop") == "origin/develop"
    assert ship._normalize_base_ref("release/1.0") == "origin/release/1.0"
    assert ship._normalize_base_ref("origin/main") == "origin/main"
    assert ship._normalize_base_ref("upstream/main") == "upstream/main"


# ===========================================================================
# rerun-workflow
# ===========================================================================


def test_cmd_rerun_workflow_reruns_failed(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(ship, "run", lambda cmd: (calls.append(cmd), _FakeProc())[1])
    assert ship.cmd_rerun_workflow("run-123") == ship.EXIT_OK
    assert calls == [["gh", "run", "rerun", "--failed", "run-123"]]


def test_cmd_rerun_workflow_halts_on_failure(monkeypatch) -> None:
    monkeypatch.setattr(ship, "run", lambda cmd: _FakeProc(stderr="no such run", returncode=1))
    with pytest.raises(SystemExit) as e:
        ship.cmd_rerun_workflow("run-999")
    assert e.value.code == ship.EXIT_HALT


# ===========================================================================
# gh api paginate regression
# ===========================================================================


def test_gh_json_concatenated_two_page_body_raises_exit() -> None:
    two_page = json.dumps([{"id": 1}]) + "\n" + json.dumps([{"id": 2}])
    with patch.object(ship, "run", return_value=_FakeProc(stdout=two_page)):
        with pytest.raises(SystemExit):
            ship.gh_json(["api", "repos/owner/repo/issues/1/comments"])


# ===========================================================================
# CI durations: pure math + self-maintained record + ETA
# ===========================================================================


def test_pct_linear_interpolation() -> None:
    xs = [10, 20, 30, 40]
    assert ship._pct(xs, 0) == 10
    assert ship._pct(xs, 100) == 40
    assert ship._pct(xs, 50) == 25


def test_round_up_30() -> None:
    assert ship._round_up_30(829.4) == 840
    assert ship._round_up_30(840.0) == 840
    assert ship._round_up_30(811.0) == 840
    assert ship._round_up_30(0.0) == 0


def test_iso_epoch_treats_naive_string_as_utc() -> None:
    assert ship._iso_epoch("2026-05-30T00:00:00") == ship._iso_epoch("2026-05-30T00:00:00Z")


def test_ci_durations_update_adds_prunes_dedupes_and_rounds() -> None:
    now = "2026-05-31T00:00:00Z"
    existing = {"_updated": "2026-05-20T00:00:00Z", "_window_days": 7, "jobs": {
        "Backend": {"p90_s": 840, "n": 2, "samples": [
            [1, "2026-05-30T00:00:00Z", 800.0], [2, "2026-05-01T00:00:00Z", 999.0]]}}}
    new = {"Backend": [[3, "2026-05-30T12:00:00Z", 820.0], [1, "2026-05-30T00:00:00Z", 800.0]],
           "iOS": [[3, "2026-05-30T12:00:00Z", 290.0]]}
    out = ship._ci_durations_update(existing, new, now=now)
    backend = out["jobs"]["Backend"]
    assert sorted(s[0] for s in backend["samples"]) == [1, 3]
    assert backend["n"] == 2 and backend["p90_s"] == 840
    assert out["jobs"]["iOS"]["p90_s"] == 300
    assert out["_updated"] == now


def test_ci_durations_update_drops_emptied_job() -> None:
    out = ship._ci_durations_update(
        {"_updated": "x", "_window_days": 7, "jobs": {
            "Old": {"p90_s": 100, "n": 1, "samples": [[9, "2026-05-01T00:00:00Z", 100.0]]}}},
        {}, now="2026-05-31T00:00:00Z")
    assert "Old" not in out["jobs"]


def test_ci_durations_update_seeds_from_empty() -> None:
    out = ship._ci_durations_update({}, {"Backend": [[1, "2026-05-30T00:00:00Z", 700.0]]},
                                    now="2026-05-31T00:00:00Z")
    assert out["jobs"]["Backend"]["p90_s"] == 720


def test_ci_durations_update_dedupes_by_run_id() -> None:
    existing = {"_updated": "2025-06-01T00:00:00Z", "jobs": {"lint": {"p90_s": 30, "n": 2, "samples": [
        [1001, "2025-05-31T10:00:00Z", 25.0], [1002, "2025-05-31T11:00:00Z", 28.0]]}}}
    new = {"lint": [[1002, "2025-05-31T11:00:01Z", 29.0], [1003, "2025-05-31T12:00:00Z", 26.0]]}
    out = ship._ci_durations_update(existing, new, now="2025-06-01T01:00:00Z", window_days=7)
    assert out["jobs"]["lint"]["n"] == 3
    assert any(s[0] == 1002 and s[2] == 29.0 for s in out["jobs"]["lint"]["samples"])


def test_ci_p90_map_extracts_p90s() -> None:
    doc = {"jobs": {"lint": {"p90_s": 30, "n": 5}, "unit-test": {"p90_s": 180, "n": 3},
                    "broken": {"n": 1}}}
    assert ship._ci_p90_map(doc) == {"lint": 30, "unit-test": 180, "broken": -1}


def test_ci_samples_from_check_runs_extracts_success_durations() -> None:
    check_runs = [
        {"name": "Backend", "id": 555, "status": "completed", "conclusion": "success",
         "started_at": "2026-05-30T10:00:00Z", "completed_at": "2026-05-30T10:13:20Z"},
        {"name": "Flaky", "id": 556, "status": "completed", "conclusion": "failure",
         "started_at": "2026-05-30T10:00:00Z", "completed_at": "2026-05-30T10:01:00Z"},
        {"name": "NoTimes", "id": 557, "status": "completed", "conclusion": "success",
         "started_at": None, "completed_at": None},
    ]
    out = ship._ci_samples_from_check_runs(check_runs)
    assert out == {"Backend": [[555, "2026-05-30T10:13:20Z", 800.0]]}


def test_cmd_ci_durations_record_writes_only_on_change(tmp_path: Path) -> None:
    f = tmp_path / "ci-durations.json"
    check_runs = [{"name": "Backend", "id": 1, "status": "completed", "conclusion": "success",
                   "started_at": "2026-05-30T10:00:00Z", "completed_at": "2026-05-30T10:13:20Z"}]
    res = ship.cmd_ci_durations_record(check_runs, file_path=str(f), now="2026-05-31T00:00:00Z")
    assert res["changed"] is True and f.exists()
    p90 = json.loads(f.read_text())["jobs"]["Backend"]["p90_s"]
    # Re-record the SAME sample → same p90 → no write.
    res2 = ship.cmd_ci_durations_record(check_runs, file_path=str(f), now="2026-05-31T01:00:00Z")
    assert res2["changed"] is False
    assert json.loads(f.read_text())["jobs"]["Backend"]["p90_s"] == p90


def test_load_ci_baseline_degrades_gracefully(tmp_path: Path) -> None:
    assert ship._load_ci_baseline(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"; bad.write_text("{not json")
    assert ship._load_ci_baseline(str(bad)) == {}
    good = tmp_path / "ok.json"
    good.write_text(json.dumps({"jobs": {
        "Good": {"p90_s": 840.0, "n": 3, "samples": []},
        "NoP90": {"n": 1, "samples": []},
        "BadType": {"p90_s": "slow", "n": 1, "samples": []}}}))
    assert ship._load_ci_baseline(str(good)) == {"Good": 840}


def test_ci_eta_uses_slowest_in_progress_job() -> None:
    baseline = {"Backend": 840, "iOS": 300}
    now = ship._iso_epoch("2026-05-30T10:05:00Z")
    check_runs = [
        {"name": "Backend", "status": "in_progress", "started_at": "2026-05-30T10:00:00Z"},
        {"name": "iOS", "status": "in_progress", "started_at": "2026-05-30T10:03:00Z"},
        {"name": "Done", "status": "completed", "started_at": "2026-05-30T10:00:00Z"},
    ]
    elapsed, est_total = ship._ci_eta(check_runs, baseline, now)
    assert elapsed == 300 and est_total == 300 + 540


def test_ci_eta_none_when_no_baseline_match() -> None:
    now = ship._iso_epoch("2026-05-30T10:05:00Z")
    check_runs = [{"name": "Unknown", "status": "in_progress", "started_at": "2026-05-30T10:00:00Z"}]
    assert ship._ci_eta(check_runs, {"Backend": 840}, now) == (None, None)


def test_ci_eta_queued_job_assumes_full_p90() -> None:
    now = ship._iso_epoch("2026-05-30T10:01:00Z")
    check_runs = [{"name": "Backend", "status": "queued", "started_at": None}]
    elapsed, est_total = ship._ci_eta(check_runs, {"Backend": 840}, now)
    assert elapsed == 0 and est_total == 840


def test_status_fixture_enriches_wait_ci_when_baseline_present() -> None:
    fx = load_fixture("wait_ci")
    env = ship.cmd_status(fixture={"pr": fx["pr"], "check_runs": fx.get("check_runs"),
                                   "sticky": fx.get("sticky"), "ci_baseline": {"r": 99999}})
    assert env["hint"] == "wait_ci"
    assert "ci_elapsed" in env and "ci_est_total" in env


# ===========================================================================
# wait_ci cadence
# ===========================================================================


def test_wait_ci_cadence_fast_fail_window_polls_dense() -> None:
    assert ship._wait_ci_cadence(elapsed=10, est_total=480) == 30
    assert ship._wait_ci_cadence(elapsed=119, est_total=480) == 30
    assert ship._wait_ci_cadence(elapsed=120, est_total=480) == 270


def test_wait_ci_cadence_dead_middle_one_long_sleep() -> None:
    c = ship._wait_ci_cadence(elapsed=130, est_total=480)
    assert c == 260 and c >= 60


def test_wait_ci_cadence_landing_zone_tightens() -> None:
    assert ship._wait_ci_cadence(elapsed=420, est_total=480) == 60
    assert ship._wait_ci_cadence(elapsed=600, est_total=480) == 60


def test_wait_ci_cadence_no_estimate_falls_back_but_keeps_fast_fail() -> None:
    assert ship._wait_ci_cadence(elapsed=300, est_total=None) == ship.CADENCE_WAIT_CI
    assert ship._wait_ci_cadence(elapsed=30, est_total=None) == 30


# ===========================================================================
# cmd_watch loop glue
# ===========================================================================


def _scripted_poll(envelopes):
    box = {"i": 0}

    def poll():
        i = min(box["i"], len(envelopes) - 1)
        box["i"] += 1
        return envelopes[i]

    return poll


def test_watch_loop_wait_then_wake_only_emits_on_wake(capsys) -> None:
    polls = _scripted_poll([_env("wait_ci", cadence=1), _env("wait_first_review", cadence=1),
                            _env("ci_failed")])
    run_watch(merge_flag=False, pr_number=1, poll=polls, sleeper=lambda s: None,
              rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0}, max_iters=3)
    out = capsys.readouterr()
    lines = [l for l in out.out.splitlines() if l.strip()]
    assert len(lines) == 1 and json.loads(lines[0])["hint"] == "ci_failed"
    assert "wait_ci" in out.err and "wait_first_review" in out.err


def test_emit_flushes_stdout_so_pipe_consumers_see_events() -> None:
    class _Rec:
        def __init__(self):
            self.buf = ""
            self.flushed = []

        def write(self, s):
            self.buf += s
            return len(s)

        def flush(self):
            self.flushed.append(len(self.buf))

    stream = _Rec()
    with patch("sys.stdout", stream):
        ship._emit({"event": "transition", "hint": "ci_failed"})
    assert stream.buf.endswith("\n")
    assert stream.flushed and stream.flushed[-1] == len(stream.buf)


def test_watch_loop_throttle_is_stderr_only(capsys) -> None:
    polls = _scripted_poll([_env("wait_ci", cadence=1)])
    run_watch(merge_flag=False, pr_number=1, poll=polls, sleeper=lambda s: None,
              rate_remaining=lambda: {"core": 10, "graphql": 10, "reset_in": 5}, max_iters=1)
    out = capsys.readouterr()
    assert out.out.strip() == "" and "throttled" in out.err


def test_watch_loop_auto_promote_then_continue_no_wake(capsys) -> None:
    polls = _scripted_poll([_env("promote_draft"), _env("wait_first_review", cadence=1)])
    calls = []
    run_watch(merge_flag=False, pr_number=1, poll=polls, sleeper=lambda s: None,
              rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
              run_action=lambda a, pr, merge_flag, reply_only=False: (calls.append(a) or ("ok", "did")),
              max_iters=2)
    out = capsys.readouterr()
    assert calls == ["promote"] and out.out.strip() == "" and "promote" in out.err


def test_watch_loop_auto_merge_emits_done_and_exits(capsys) -> None:
    polls = _scripted_poll([_env("clean_exit")])
    rc = run_watch(merge_flag=True, pr_number=7, poll=polls, sleeper=lambda s: None,
                   rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
                   run_action=lambda a, pr, merge_flag, reply_only=False: ("done", "merged"),
                   max_iters=5)
    out = capsys.readouterr()
    lines = [l for l in out.out.splitlines() if l.strip()]
    assert len(lines) == 1 and json.loads(lines[0])["event"] == "done"
    assert rc == ship.EXIT_OK


def test_watch_loop_action_halt_emits_halt_and_exits(capsys) -> None:
    polls = _scripted_poll([_env("clean_exit")])
    run_watch(merge_flag=True, pr_number=7, poll=polls, sleeper=lambda s: None,
              rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
              run_action=lambda a, pr, merge_flag, reply_only=False: ("halt", "HUMAN_REVIEW_REQUIRED"),
              max_iters=5)
    out = capsys.readouterr()
    line = json.loads([l for l in out.out.splitlines() if l.strip()][0])
    assert line["hint"] == "halt" and "HUMAN_REVIEW_REQUIRED" in line["reason"]


def test_watch_loop_merge_flag_off_clean_exit_wakes_terminal(capsys) -> None:
    polls = _scripted_poll([_env("clean_exit")])
    called = []
    run_watch(merge_flag=False, pr_number=7, poll=polls, sleeper=lambda s: None,
              rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
              run_action=lambda a, pr, merge_flag, reply_only=False: called.append(a), max_iters=5)
    out = capsys.readouterr()
    assert called == []
    assert json.loads([l for l in out.out.splitlines() if l.strip()][0])["hint"] == "clean_exit"


def test_watch_loop_draft_flag_holds_green_draft_and_exits(capsys) -> None:
    polls = _scripted_poll([_env("promote_draft"), _env("ci_failed")])
    calls = []
    rc = run_watch(merge_flag=False, draft_flag=True, pr_number=1, poll=polls,
                   sleeper=lambda s: None,
                   rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
                   run_action=lambda a, pr, merge_flag, reply_only=False: calls.append(a),
                   max_iters=5)
    out = capsys.readouterr()
    lines = [json.loads(l) for l in out.out.splitlines() if l.strip()]
    assert calls == [] and len(lines) == 1 and lines[0]["hint"] == "held_draft"
    assert rc == ship.EXIT_OK


def test_watch_loop_rewake_zero_reemits_each_poll(capsys) -> None:
    polls = _scripted_poll([_env("ci_failed"), _env("ci_failed"), _env("ci_failed")])
    run_watch(merge_flag=False, pr_number=1, poll=polls, sleeper=lambda s: None,
              rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
              read_ack=lambda pr: None, unacked_rewake_seconds=0, max_iters=3)
    events = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(events) == 3 and all(e["hint"] == "ci_failed" for e in events)
    assert "nudge" not in events[0]
    assert [e["nudge"] for e in events[1:]] == [1, 2]


def test_watch_loop_acked_wake_backs_off_to_safety_cadence(capsys) -> None:
    polls = _scripted_poll([_env("ci_failed"), _env("ci_failed"), _env("ci_failed")])
    run_watch(merge_flag=False, pr_number=1, poll=polls, sleeper=lambda s: None,
              rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
              read_ack=lambda pr: ("ci_failed", "abc"), unacked_rewake_seconds=0,
              rewake_seconds=10_000, max_iters=3)
    out = capsys.readouterr()
    events = [l for l in out.out.splitlines() if l.strip()]
    assert len(events) == 1
    assert "ci_failed persists (already woken)" in out.err


def test_watch_loop_stale_ack_clears_and_renudges(capsys) -> None:
    cleared = []
    polls = _scripted_poll([_env("ci_failed"), _env("ci_failed")])
    run_watch(merge_flag=False, pr_number=1, poll=polls, sleeper=lambda s: None,
              rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
              read_ack=lambda pr: ("ci_failed", "abc"), clear_ack=lambda pr: cleared.append(pr),
              rewake_seconds=0, max_iters=2)
    events = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(events) == 2 and events[1]["nudge"] == 1
    assert cleared == [1]


def test_watch_loop_stale_ack_for_old_sha_does_not_suppress_new_sha(capsys) -> None:
    polls = _scripted_poll([_env("ci_failed", sha="abc"), _env("ci_failed", sha="def"),
                            _env("ci_failed", sha="def")])
    run_watch(merge_flag=False, pr_number=1, poll=polls, sleeper=lambda s: None,
              rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
              read_ack=lambda pr: ("ci_failed", "abc"), unacked_rewake_seconds=0, max_iters=3)
    events = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert [e["sha"] for e in events] == ["abc", "def", "def"]
    assert "nudge" not in events[1]
    assert events[2]["nudge"] == 1


def test_watch_loop_cap_hit_emits_halt(capsys) -> None:
    polls = _scripted_poll([_env("ci_failed")])
    with patch("ship.pr_web_url", return_value="https://github.com/o/r/pull/1"):
        rc = run_watch(merge_flag=False, pr_number=1, poll=polls, sleeper=lambda s: None,
                       rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
                       check_caps=lambda pr: ["ci_fail_count.flaky_root_cause"], max_iters=5)
    line = json.loads([l for l in capsys.readouterr().out.splitlines() if l.strip()][0])
    assert line["hint"] == "halt" and "ci_fail_count.flaky_root_cause" in line["reason"]
    assert line["pr_url"] == "https://github.com/o/r/pull/1"
    assert rc == ship.EXIT_OK


def test_watch_poll_transient_exit_backs_off_not_dies() -> None:
    calls = {"n": 0}

    def flaky_poll():
        calls["n"] += 1
        if calls["n"] == 1:
            raise SystemExit(ship.EXIT_TRANSIENT)
        return _env("ci_failed")

    slept = []
    rc = run_watch(merge_flag=False, pr_number=1, poll=flaky_poll,
                   sleeper=lambda s: slept.append(s),
                   rate_remaining=lambda: {"core": 5000, "graphql": 5000, "reset_in": 0},
                   read_ack=lambda pr: None, max_iters=2)
    assert rc == ship.EXIT_OK and calls["n"] == 2 and 60 in slept


def test_pr_web_url_builds_or_empties(monkeypatch) -> None:
    monkeypatch.setattr(ship, "_SLUG_CACHE", None)
    monkeypatch.setattr(ship, "run", lambda cmd: _FakeProc(stdout="o/r\n"))
    assert ship.pr_web_url(7) == "https://github.com/o/r/pull/7"
    monkeypatch.setattr(ship, "run", lambda cmd: _FakeProc(stderr="boom", returncode=1))
    assert ship.pr_web_url(7) == ""


def test_pr_web_url_reuses_warm_slug_cache(monkeypatch) -> None:
    monkeypatch.setattr(ship, "_SLUG_CACHE", "o/r")

    def no_run(cmd):
        raise AssertionError(f"must reuse cache, not run {cmd}")

    monkeypatch.setattr(ship, "run", no_run)
    assert ship.pr_web_url(7) == "https://github.com/o/r/pull/7"


# ===========================================================================
# main dispatch
# ===========================================================================


def test_main_status_help_runs(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        ship.main(["status", "--help"])
    assert exc.value.code == 0
    assert "status" in capsys.readouterr().out.lower()


def test_main_watch_dispatches_with_resolved_pr_and_merge_flag() -> None:
    captured = {}

    def fake_watch(**kwargs):
        captured.update(kwargs)
        return ship.EXIT_OK

    with patch.object(ship, "_resolve_pr_for_state", return_value=42), \
         patch.object(ship, "init_state_if_needed", return_value=(None, {})), \
         patch.object(ship, "cmd_watch", side_effect=fake_watch):
        rc = ship.main(["watch", "--merge", "--max-iters", "5"])
    assert rc == ship.EXIT_OK
    assert captured["pr_number"] == 42 and captured["merge_flag"] is True
    assert captured["draft_flag"] is False and captured["max_iters"] == 5


def test_main_watch_draft_flag_dispatches() -> None:
    captured = {}

    def fake_watch(**kwargs):
        captured.update(kwargs)
        return ship.EXIT_OK

    with patch.object(ship, "_resolve_pr_for_state", return_value=42), \
         patch.object(ship, "init_state_if_needed", return_value=(None, {})), \
         patch.object(ship, "cmd_watch", side_effect=fake_watch):
        rc = ship.main(["watch", "--draft", "--max-iters", "3"])
    assert rc == ship.EXIT_OK
    assert captured["draft_flag"] is True and captured["merge_flag"] is False


def test_main_watch_merge_and_draft_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc:
        ship.main(["watch", "--merge", "--draft"])
    assert exc.value.code == 2


def test_main_watch_cli_merge_yields_to_persisted_draft() -> None:
    captured = {}

    def fake_watch(**kwargs):
        captured.update(kwargs)
        return ship.EXIT_OK

    with patch.object(ship, "_resolve_pr_for_state", return_value=7), \
         patch.object(ship, "init_state_if_needed", return_value=(None, {"draft_flag": True})), \
         patch.object(ship, "cmd_watch", side_effect=fake_watch):
        rc = ship.main(["watch", "--merge"])
    assert rc == ship.EXIT_OK
    assert captured["draft_flag"] is True and captured["merge_flag"] is False


def test_main_ci_durations_show() -> None:
    with patch.object(ship, "_load_ci_baseline", return_value={"lint": 30}):
        rc = ship.main(["ci-durations", "--show", "--file", "/tmp/x.json"])
    assert rc == ship.EXIT_OK
