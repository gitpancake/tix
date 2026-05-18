"""Smoke tests — no curses, no network. Verify the package imports and the
core data shapes load from a fixture tree."""
import os
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "tickets"


def _set_tickets_dir(monkeypatch):
    monkeypatch.setenv("TICKETS_DIR", str(FIXTURES))
    # Force re-import so module-level TICKETS_DIR picks up the env.
    for mod in ("tix.tui", "tix.sync", "tix"):
        sys.modules.pop(mod, None)


def test_package_imports():
    import tix
    assert tix.__version__


def test_tui_loads_tickets(monkeypatch):
    _set_tickets_dir(monkeypatch)
    from tix import tui
    assert tui.TICKETS_DIR == FIXTURES
    # `App.__init__` calls rebuild_rows which walks the tree.
    app = tui.App()
    slugs = {t.slug for t in app.tickets}
    assert {"alpha", "beta"} <= slugs


def test_sync_runs_against_fixtures(monkeypatch):
    _set_tickets_dir(monkeypatch)
    # Pin gh out so the merged-PR pass is skipped.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    from tix import sync
    # reconcile() must complete without raising — we don't assert on stdout.
    sync.reconcile(only_slug="alpha")


def test_status_vocab_pinned():
    from tix import tui
    # Lowercase canonical set.
    canonical = {"active", "open", "draft", "done", "cancelled", "canceled"}
    keys = set(tui.STATUS_META.keys())
    assert canonical <= keys, "status vocab regressed"
