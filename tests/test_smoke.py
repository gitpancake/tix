"""Smoke tests — no curses, no network. Verify the package imports and the
core data shapes load from a fixture tree."""
import os
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


def test_tui_default_tickets_dir_is_pi_agent(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TICKETS_DIR", raising=False)
    for mod in ("tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import tui
    assert tui.TICKETS_DIR == tmp_path / "home" / ".pi" / "agent" / "tickets"


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


def test_resolve_project_chdirs_into_code_repo(monkeypatch, tmp_path):
    """`tix <project>` points TICKETS_DIR at the centralized tree and chdirs
    into the code repo under $TIX_CODE_DIR so pickup runs against it."""
    home = tmp_path / "home"
    central = home / ".pi" / "agent" / "tickets" / "proj"
    central.mkdir(parents=True)
    code_repo = tmp_path / "code" / "proj"
    (code_repo / ".git").mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TIX_CODE_DIR", str(tmp_path / "code"))
    monkeypatch.delenv("TICKETS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    from tix.__main__ import resolve_project
    assert resolve_project("proj") is True
    assert os.environ["TICKETS_DIR"] == str(central)
    assert Path.cwd() == code_repo


def test_resolve_project_missing_returns_false(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TIX_CODE_DIR", str(tmp_path / "code"))
    monkeypatch.chdir(tmp_path)
    from tix.__main__ import resolve_project
    assert resolve_project("nope") is False
    assert "no ticket directory" in capsys.readouterr().err


def test_pager_and_pickup_helpers_exposed():
    """Mini imports these — they must live at module scope, not on App."""
    from tix import tui
    assert callable(getattr(tui, "open_in_pager", None))
    assert callable(getattr(tui, "pickup_ticket", None))


def test_pickup_git_sync_skips_unborn_repo(monkeypatch, tmp_path, capfd):
    from tix import tui

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    assert os.system("git init -b main >/dev/null 2>&1") == 0

    tui.run_pickup_git_sync()

    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""
