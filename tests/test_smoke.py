"""Smoke tests — no curses, no network. Verify the package imports and the
core data shapes load from a fixture tree."""
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "tickets"


def _set_tickets_dir(monkeypatch):
    monkeypatch.setenv("TICKETS_DIR", str(FIXTURES))
    # Force re-import so module-level TICKETS_DIR picks up the env.
    for mod in ("tix.tui", "tix"):
        sys.modules.pop(mod, None)


def test_package_imports():
    import tix
    assert tix.__version__


def test_tui_loads_tickets(monkeypatch):
    _set_tickets_dir(monkeypatch)
    from tix import tui
    assert tui.TICKETS_DIR == FIXTURES
    app = tui.App()
    slugs = {t.slug for t in app.tickets}
    assert {"alpha", "beta"} <= slugs


def test_preload_hook_runs_when_set(monkeypatch, tmp_path):
    _set_tickets_dir(monkeypatch)
    sentinel = tmp_path / "hook-ran"
    monkeypatch.setenv("TIX_PRELOAD_HOOK", f"touch {sentinel}")
    from tix import tui
    tui.run_preload_hook()
    assert sentinel.exists()


def test_preload_hook_noop_when_unset(monkeypatch):
    _set_tickets_dir(monkeypatch)
    monkeypatch.delenv("TIX_PRELOAD_HOOK", raising=False)
    from tix import tui
    tui.run_preload_hook()  # must not raise


def test_status_vocab_pinned():
    from tix import tui
    canonical = {"active", "open", "draft", "done", "cancelled", "canceled"}
    keys = set(tui.STATUS_META.keys())
    assert canonical <= keys, "status vocab regressed"
