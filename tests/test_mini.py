"""Tests for the mini reader. Render layer (curses) is not exercised — only
the pure data layer (`build_rows`) and CLI routing."""
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "tickets"


def _purge(monkeypatch):
    monkeypatch.setenv("TICKETS_DIR", str(FIXTURES))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)


def test_build_rows_sorts_newest_first(monkeypatch, tmp_path):
    """build_rows must order tickets by `created` desc (parity with tui's
    sort_within_group `created` mode), missing-created sinks to the bottom."""
    tree = tmp_path / "tickets"
    (tree / "area").mkdir(parents=True)
    (tree / "area" / "old.md").write_text(
        "---\nstatus: open\ncreated: 2026-01-01T00:00:00Z\n---\n# old\n",
        encoding="utf-8",
    )
    (tree / "area" / "new.md").write_text(
        "---\nstatus: open\ncreated: 2026-05-01T00:00:00Z\n---\n# new\n",
        encoding="utf-8",
    )
    (tree / "area" / "no-date.md").write_text(
        "---\nstatus: open\n---\n# no-date\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import mini, tui
    tickets = tui.load_tickets()
    rows = mini.build_rows(tickets)
    slugs = [t.slug for t in rows]
    # `new` must precede `old` — that's the load-bearing assertion: frontmatter
    # `created:` is parsed + ordered desc. `no-date` falls back to fs birthtime
    # (parity with tui.parse_created), so its position is environment-dependent
    # — just confirm it surfaces.
    assert slugs.index("new") < slugs.index("old")
    assert "no-date" in slugs


def test_mini_set_label_writes_frontmatter(monkeypatch, tmp_path):
    tree = tmp_path / "tickets"
    (tree / "area").mkdir(parents=True)
    brief = tree / "area" / "labeled.md"
    brief.write_text(
        "---\nstatus: open\ncreated: 2026-05-01T00:00:00Z\n---\n# labeled\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import mini, tui
    ticket = tui.load_tickets()[0]
    mini._set_label(ticket, "ops")
    assert ticket.label == "ops"
    assert "label: ops" in brief.read_text(encoding="utf-8")

    mini._set_label(ticket, "")
    assert ticket.label == ""
    assert "label:" not in brief.read_text(encoding="utf-8")


def test_build_rows_hides_done_and_cancelled(monkeypatch, tmp_path):
    tree = tmp_path / "tickets"
    (tree / "area").mkdir(parents=True)
    for status in ("open", "draft", "active", "done", "cancelled"):
        (tree / "area" / f"{status}.md").write_text(
            f"---\nstatus: {status}\ncreated: 2026-05-01T00:00:00Z\n---\n# {status}\n",
            encoding="utf-8",
        )
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import mini, tui
    rows = mini.build_rows(tui.load_tickets())
    slugs = {t.slug for t in rows}
    assert slugs == {"open", "draft", "active"}


def test_build_rows_orders_active_draft_open(monkeypatch, tmp_path):
    """Mini's status grouping: active → draft → open. Diverges from tui's
    STATUS_META rank (which puts open before draft). Within each group,
    created desc."""
    tree = tmp_path / "tickets"
    (tree / "area").mkdir(parents=True)
    cases = [
        ("open-new",   "open",   "2026-05-02T00:00:00Z"),
        ("open-old",   "open",   "2026-01-01T00:00:00Z"),
        ("draft-new",  "draft",  "2026-05-02T00:00:00Z"),
        ("draft-old",  "draft",  "2026-01-01T00:00:00Z"),
        ("active-new", "active", "2026-05-02T00:00:00Z"),
        ("active-old", "active", "2026-01-01T00:00:00Z"),
    ]
    for slug, status, created in cases:
        (tree / "area" / f"{slug}.md").write_text(
            f"---\nstatus: {status}\ncreated: {created}\n---\n# {slug}\n",
            encoding="utf-8",
        )
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import mini, tui
    rows = mini.build_rows(tui.load_tickets())
    assert [t.slug for t in rows] == [
        "active-new", "active-old",
        "draft-new", "draft-old",
        "open-new", "open-old",
    ]


def test_build_rows_marks_epic_children(monkeypatch, tmp_path):
    """Tickets inside an epic folder get `is_epic_child`; the epic itself and
    standalone briefs don't. Marking survives the epic being hidden (done) —
    epic dirs are collected from the unfiltered ticket list."""
    tree = tmp_path / "tickets"
    epic_dir = tree / "area" / "big-epic"
    epic_dir.mkdir(parents=True)
    (epic_dir / "_epic.md").write_text(
        "---\nstatus: open\ncreated: 2026-05-01T00:00:00Z\n---\n# big epic\n",
        encoding="utf-8",
    )
    (epic_dir / "01-child.md").write_text(
        "---\nstatus: open\ncreated: 2026-05-01T00:00:00Z\n---\n# child\n",
        encoding="utf-8",
    )
    (tree / "area" / "solo.md").write_text(
        "---\nstatus: open\ncreated: 2026-05-01T00:00:00Z\n---\n# solo\n",
        encoding="utf-8",
    )
    done_epic_dir = tree / "area" / "done-epic"
    done_epic_dir.mkdir(parents=True)
    (done_epic_dir / "_epic.md").write_text(
        "---\nstatus: done\ncreated: 2026-05-01T00:00:00Z\n---\n# done epic\n",
        encoding="utf-8",
    )
    (done_epic_dir / "01-straggler.md").write_text(
        "---\nstatus: open\ncreated: 2026-05-01T00:00:00Z\n---\n# straggler\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import mini, tui
    rows = mini.build_rows(tui.load_tickets())
    flags = {t.slug: t.is_epic_child for t in rows}
    assert flags == {
        "big-epic": False,
        "01-child": True,
        "solo": False,
        "01-straggler": True,
    }


def test_build_rows_filters_case_insensitive(monkeypatch, tmp_path):
    """Pre-migration title-case statuses (Done, Canceled) must also hide."""
    tree = tmp_path / "tickets"
    (tree / "area").mkdir(parents=True)
    for status in ("Done", "Canceled", "Cancelled"):
        (tree / "area" / f"{status}.md").write_text(
            f"---\nstatus: {status}\ncreated: 2026-05-01T00:00:00Z\n---\n# x\n",
            encoding="utf-8",
        )
    (tree / "area" / "keep.md").write_text(
        "---\nstatus: open\ncreated: 2026-05-01T00:00:00Z\n---\n# keep\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import mini, tui
    rows = mini.build_rows(tui.load_tickets())
    assert {t.slug for t in rows} == {"keep"}


def test_main_routes_mini_flag(monkeypatch, tmp_path):
    """`tix --mini` must dispatch to mini.main, not tui.main."""
    monkeypatch.setenv("TICKETS_DIR", str(FIXTURES))
    for mod in ("tix.mini", "tix.tui", "tix.__main__", "tix"):
        sys.modules.pop(mod, None)

    from tix import __main__ as entry
    called = {"mini": 0, "tui": 0}
    from tix import mini, tui
    monkeypatch.setattr(mini, "main", lambda: called.__setitem__("mini", 1) or 0)
    monkeypatch.setattr(tui, "main", lambda: called.__setitem__("tui", 1) or 0)
    assert entry.main(["--mini"]) == 0
    assert called == {"mini": 1, "tui": 0}


def test_main_routes_project_mini(monkeypatch, tmp_path):
    """`tix <proj> --mini` resolves project then dispatches to mini."""
    home = tmp_path / "home"
    central = home / ".pi" / "agent" / "tickets" / "proj"
    central.mkdir(parents=True)
    code_repo = tmp_path / "code" / "proj"
    (code_repo / ".git").mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TIX_CODE_DIR", str(tmp_path / "code"))
    monkeypatch.delenv("TICKETS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    for mod in ("tix.mini", "tix.tui", "tix.__main__", "tix"):
        sys.modules.pop(mod, None)

    from tix import __main__ as entry
    from tix import mini, tui
    flags = {"mini": 0}
    monkeypatch.setattr(mini, "main", lambda: flags.__setitem__("mini", 1) or 0)
    monkeypatch.setattr(tui, "main", lambda: 99)
    assert entry.main(["proj", "--mini"]) == 0
    assert flags["mini"] == 1
