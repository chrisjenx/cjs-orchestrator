"""Shared pytest setup for the ship.py suite.

Puts the shipped engine on sys.path and keeps every test hermetic: ship reads
per-repo behaviour from a lazily-loaded, cached config (`_config()` +
`_apply_config` module globals). The autouse fixture pre-seeds that cache with a
deep copy of the built-in DEFAULTS so no test ever reads THIS repo's real
`.claude/develop.config.json`, and resets the process-lifetime memos + the
advisory-lock table between tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugins" / "develop" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ship  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_ship(monkeypatch):
    """Reset ship's caches + config to built-in defaults before each test."""
    monkeypatch.delenv("SHIP_BASE_REF", raising=False)
    monkeypatch.delenv("SHIP_PR_NUMBER", raising=False)
    monkeypatch.delenv("SHIP_FLAKE_MARKER_DIR", raising=False)
    ship._BASE_REF_CACHE = None
    ship._SLUG_CACHE = None
    _clear_lock_table()
    # Seed the config cache from DEFAULTS (deep copy) and refresh the module
    # globals so _config() returns it without touching disk.
    defaults = json.loads(json.dumps(ship.DEFAULTS))
    ship._CONFIG = defaults
    ship._CONFIG_SECTION_FOUND = False
    ship._apply_config(defaults)
    yield
    _clear_lock_table()


def _clear_lock_table() -> None:
    """Clear the advisory-lock refcount table. Defensive: a test may have
    monkeypatched _StateLock (restored only after this fixture's teardown)."""
    held = getattr(ship._StateLock, "_held", None)
    if held is not None:
        held.clear()
