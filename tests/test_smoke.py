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


def test_ticket_label_round_trip_and_search(monkeypatch, tmp_path):
    tree = tmp_path / "tickets"
    (tree / "integrations").mkdir(parents=True)
    brief = tree / "integrations" / "labeled.md"
    brief.write_text(
        "---\nstatus: open\nlabel: backend\ncreated: 2026-01-01T00:00:00Z\n---\n# labeled\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import tui
    ticket = tui.load_tickets()[0]
    assert ticket.label == "backend"

    app = tui.App()
    app.query = "backend"
    app.rebuild_rows()
    assert [row["ticket"].slug for row in app.rows if row["type"] == "ticket"] == ["labeled"]

    app.set_label(ticket, "frontend")
    assert "label: frontend" in brief.read_text(encoding="utf-8")

    app.set_label(ticket, "")
    assert "label:" not in brief.read_text(encoding="utf-8")


def test_tui_loads_extra_ticket_dirs(monkeypatch, tmp_path):
    primary = tmp_path / "primary"
    extra = tmp_path / "extra"
    (primary / "integrations").mkdir(parents=True)
    (extra / "integrations").mkdir(parents=True)
    (primary / "integrations" / "claude-ticket.md").write_text(
        "---\nstatus: open\ncreated: 2026-01-01T00:00:00Z\n---\n# claude\n",
        encoding="utf-8",
    )
    (extra / "integrations" / "pi-ticket.md").write_text(
        "---\nstatus: draft\ncreated: 2026-01-02T00:00:00Z\n---\n# pi\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(primary))
    monkeypatch.setenv("TIX_EXTRA_TICKETS_DIRS", str(extra))
    for mod in ("tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import tui
    tickets = tui.load_tickets()
    slugs = {ticket.slug for ticket in tickets}
    roots = {ticket.slug: ticket.ticket_dir for ticket in tickets}
    assert {"claude-ticket", "pi-ticket"} <= slugs
    assert roots["claude-ticket"] == primary
    assert roots["pi-ticket"] == extra


def test_pickup_env_uses_ticket_owning_root(monkeypatch, tmp_path):
    primary = tmp_path / "primary"
    extra = tmp_path / "extra"
    (primary / "integrations").mkdir(parents=True)
    (extra / "integrations").mkdir(parents=True)
    (extra / "integrations" / "pi-ticket.md").write_text(
        "---\nstatus: draft\ncreated: 2026-01-02T00:00:00Z\n---\n# pi\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(primary))
    monkeypatch.setenv("TIX_EXTRA_TICKETS_DIRS", str(extra))
    for mod in ("tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import tui
    ticket = next(ticket for ticket in tui.load_tickets() if ticket.slug == "pi-ticket")

    assert tui.pickup_env(ticket)["TICKETS_DIR"] == str(extra)


def test_pickup_env_routes_agent_cmd_by_root(monkeypatch, tmp_path):
    claude_root = tmp_path / "claude" / "tickets"
    pi_root = tmp_path / "pi" / "agent" / "tickets"
    (claude_root / "platform").mkdir(parents=True)
    (pi_root / "platform").mkdir(parents=True)
    (claude_root / "platform" / "claude-ticket.md").write_text(
        "---\nstatus: open\ncreated: 2026-01-01T00:00:00Z\n---\n# claude\n",
        encoding="utf-8",
    )
    (pi_root / "platform" / "pi-ticket.md").write_text(
        "---\nstatus: draft\ncreated: 2026-01-02T00:00:00Z\n---\n# pi\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(claude_root))
    monkeypatch.setenv("TIX_EXTRA_TICKETS_DIRS", str(pi_root))
    # Only the Claude root gets an override; Pi falls through to wt's default.
    monkeypatch.setenv("TIX_PICKUP_AGENTS", f"{claude_root}=claude-lane --model opus")
    monkeypatch.delenv("WT_AGENT_CMD", raising=False)
    for mod in ("tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import tui
    by_slug = {ticket.slug: ticket for ticket in tui.load_tickets()}

    claude_env = tui.pickup_env(by_slug["claude-ticket"])
    assert claude_env["WT_AGENT_CMD"] == "claude-lane --model opus"
    assert tui.pickup_agent_label(by_slug["claude-ticket"].path) == "claude-lane"

    pi_env = tui.pickup_env(by_slug["pi-ticket"])
    assert "WT_AGENT_CMD" not in pi_env
    assert tui.pickup_agent_label(by_slug["pi-ticket"].path) == "pi"


def test_pickup_agents_respects_preset_wt_agent_cmd(monkeypatch, tmp_path):
    claude_root = tmp_path / "claude" / "tickets"
    (claude_root / "platform").mkdir(parents=True)
    (claude_root / "platform" / "claude-ticket.md").write_text(
        "---\nstatus: open\ncreated: 2026-01-01T00:00:00Z\n---\n# claude\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(claude_root))
    monkeypatch.setenv("TIX_PICKUP_AGENTS", f"{claude_root}=claude-lane --model opus")
    monkeypatch.setenv("WT_AGENT_CMD", "pi --model preset")
    for mod in ("tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import tui
    ticket = tui.load_tickets()[0]
    # An explicit WT_AGENT_CMD in the environment wins over the per-root map.
    assert tui.pickup_env(ticket)["WT_AGENT_CMD"] == "pi --model preset"


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
    canonical = {"active", "open", "draft", "done", "cancelled", "canceled", "merged"}
    keys = set(tui.STATUS_META.keys())
    assert canonical <= keys, "status vocab regressed"


def test_merged_is_done_alias(monkeypatch, tmp_path):
    """`merged` behaves as `done` everywhere: done icon, hidden from All,
    visible under the done chip (which appears even with no `done` ticket),
    and `d` flips it back to open."""
    tree = tmp_path / "tickets"
    (tree / "integrations").mkdir(parents=True)
    (tree / "integrations" / "shipped.md").write_text(
        "---\nstatus: merged\ncreated: 2026-01-01T00:00:00Z\n---\n# shipped\n",
        encoding="utf-8",
    )
    (tree / "integrations" / "pending.md").write_text(
        "---\nstatus: open\ncreated: 2026-01-01T00:00:00Z\n---\n# pending\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import tui
    assert tui.STATUS_META["merged"] == tui.STATUS_META["done"]

    app = tui.App()
    assert "done" in app.filters

    def visible_slugs():
        return [row["ticket"].slug for row in app.rows if row["type"] == "ticket"]

    assert visible_slugs() == ["pending"]

    app.filter_idx = app.filters.index("done")
    app.rebuild_rows()
    assert visible_slugs() == ["shipped"]

    shipped = next(t for t in app.tickets if t.slug == "shipped")
    app.toggle_done(shipped)
    text = (tree / "integrations" / "shipped.md").read_text(encoding="utf-8")
    assert "status: open" in text


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
    assert "TIX_EXTRA_TICKETS_DIRS" not in os.environ
    assert Path.cwd() == code_repo


def test_resolve_project_includes_pi_and_claude_roots(monkeypatch, tmp_path):
    home = tmp_path / "home"
    pi_root = home / ".pi" / "agent" / "tickets" / "proj"
    claude_root = home / ".claude" / "tickets" / "proj"
    pi_root.mkdir(parents=True)
    claude_root.mkdir(parents=True)
    code_repo = tmp_path / "code" / "proj"
    (code_repo / ".git").mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TIX_CODE_DIR", str(tmp_path / "code"))
    monkeypatch.delenv("TICKETS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    from tix.__main__ import resolve_project
    assert resolve_project("proj") is True
    assert os.environ["TICKETS_DIR"] == str(pi_root)
    assert os.environ["TIX_EXTRA_TICKETS_DIRS"] == str(claude_root)


def test_configure_current_project_dirs_adds_pi_root(monkeypatch, tmp_path):
    home = tmp_path / "home"
    claude_root = home / ".claude" / "tickets" / "proj"
    pi_root = home / ".pi" / "agent" / "tickets" / "proj"
    claude_root.mkdir(parents=True)
    pi_root.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TICKETS_DIR", str(claude_root))
    monkeypatch.delenv("TIX_EXTRA_TICKETS_DIRS", raising=False)

    from tix.__main__ import configure_current_project_dirs
    configure_current_project_dirs()
    assert os.environ["TICKETS_DIR"] == str(claude_root)
    assert os.environ["TIX_EXTRA_TICKETS_DIRS"] == str(pi_root)


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
