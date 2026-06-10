"""Tests for the mini reader. Render layer (curses) is not exercised — only
the pure data layer (`build_rows`) and CLI routing."""
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "tickets"


def _purge(monkeypatch):
    monkeypatch.setenv("TICKETS_DIR", str(FIXTURES))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)


def _write(tree, rel, status, created=None, title=None):
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    created_line = f"created: {created}\n" if created else ""
    name = title or path.stem
    path.write_text(
        f"---\nstatus: {status}\n{created_line}---\n# {name}\n",
        encoding="utf-8",
    )


def _load(monkeypatch, tree):
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)
    from tix import mini, tui
    return mini, mini.build_rows(tui.load_tickets())


def _slugs(mini, rows):
    return ["" if r is mini.SPACER
            else r.name if isinstance(r, mini.Header)
            else r.slug
            for r in rows]


def test_build_rows_sorts_newest_first(monkeypatch, tmp_path):
    """Within a section, `created` desc; missing-created sinks (fs-birthtime
    fallback makes its exact spot environment-dependent — just confirm it
    surfaces)."""
    tree = tmp_path / "tickets"
    _write(tree, "area/old.md", "open", "2026-01-01T00:00:00Z")
    _write(tree, "area/new.md", "open", "2026-05-01T00:00:00Z")
    _write(tree, "area/no-date.md", "open")
    mini, rows = _load(monkeypatch, tree)
    slugs = _slugs(mini, rows)
    assert slugs.index("new") < slugs.index("old")
    assert "no-date" in slugs
    assert slugs[0] == "BACKLOG"  # single section → one header
    assert "IN FLIGHT" not in slugs


def test_build_rows_headers_between_in_flight_and_rest(monkeypatch, tmp_path):
    """active/review sort under IN FLIGHT, open/draft under BACKLOG; each
    section is created desc (ties broken by id, so draft-new precedes
    open-new). Header counts match section sizes."""
    tree = tmp_path / "tickets"
    _write(tree, "area/open-new.md", "open", "2026-05-02T00:00:00Z")
    _write(tree, "area/open-old.md", "open", "2026-01-01T00:00:00Z")
    _write(tree, "area/draft-new.md", "draft", "2026-05-02T00:00:00Z")
    _write(tree, "area/active-old.md", "active", "2026-01-01T00:00:00Z")
    _write(tree, "area/review-new.md", "review", "2026-05-02T00:00:00Z")
    mini, rows = _load(monkeypatch, tree)
    assert _slugs(mini, rows) == [
        "IN FLIGHT", "review-new", "active-old",
        "",
        "BACKLOG", "draft-new", "open-new", "open-old",
    ]
    counts = [r.count for r in rows if isinstance(r, mini.Header)]
    assert counts == [2, 3]


def test_build_rows_single_section_keeps_header(monkeypatch, tmp_path):
    tree = tmp_path / "tickets"
    _write(tree, "area/only-active.md", "active", "2026-05-01T00:00:00Z")
    mini, rows = _load(monkeypatch, tree)
    assert _slugs(mini, rows) == ["IN FLIGHT", "only-active"]


def test_build_rows_hides_done_and_cancelled(monkeypatch, tmp_path):
    tree = tmp_path / "tickets"
    for status in ("open", "draft", "active", "done", "merged", "cancelled"):
        _write(tree, f"area/{status}.md", status, "2026-05-01T00:00:00Z")
    mini, rows = _load(monkeypatch, tree)
    slugs = set(_slugs(mini, rows)) - {"IN FLIGHT", "BACKLOG", ""}
    assert slugs == {"open", "draft", "active"}


def test_build_rows_filters_case_insensitive(monkeypatch, tmp_path):
    """Pre-migration title-case statuses (Done, Canceled) must also hide."""
    tree = tmp_path / "tickets"
    for status in ("Done", "Canceled", "Cancelled"):
        _write(tree, f"area/{status}.md", status, "2026-05-01T00:00:00Z")
    _write(tree, "area/keep.md", "open", "2026-05-01T00:00:00Z")
    mini, rows = _load(monkeypatch, tree)
    assert _slugs(mini, rows) == ["BACKLOG", "keep"]


def test_build_rows_groups_children_under_epic(monkeypatch, tmp_path):
    """A running epic groups: epic row leads, children follow indented
    (`is_epic_child`) in `NN-` prefix order — even when created stamps run
    the other way. Done children stay visible while a sibling is unfinished;
    cancelled children never render."""
    tree = tmp_path / "tickets"
    _write(tree, "area/big-epic/_epic.md", "open", "2026-05-01T00:00:00Z")
    _write(tree, "area/big-epic/01-shipped.md", "done", "2026-05-01T00:00:00Z")
    _write(tree, "area/big-epic/02-next.md", "open", "2026-05-02T00:00:00Z")
    _write(tree, "area/big-epic/03-dropped.md", "cancelled", "2026-05-03T00:00:00Z")
    _write(tree, "area/solo.md", "open", "2026-04-01T00:00:00Z")
    mini, rows = _load(monkeypatch, tree)
    assert _slugs(mini, rows) == [
        "BACKLOG", "big-epic", "01-shipped", "02-next", "solo",
    ]
    flags = {t.slug: t.is_epic_child for t in rows
             if not isinstance(t, mini.Header)}
    assert flags == {
        "big-epic": False,
        "01-shipped": True,
        "02-next": True,
        "solo": False,
    }


def test_build_rows_unprefixed_children_after_ordered(monkeypatch, tmp_path):
    """Children without an `NN-` prefix sort after prefixed siblings, created
    desc among themselves; `_epic_order` exposes the prefix for rendering."""
    tree = tmp_path / "tickets"
    _write(tree, "area/mixed-epic/_epic.md", "open", "2026-05-01T00:00:00Z")
    _write(tree, "area/mixed-epic/10-late.md", "open", "2026-05-01T00:00:00Z")
    _write(tree, "area/mixed-epic/02-early.md", "open", "2026-05-09T00:00:00Z")
    _write(tree, "area/mixed-epic/extra-old.md", "open", "2026-05-02T00:00:00Z")
    _write(tree, "area/mixed-epic/extra-new.md", "open", "2026-05-08T00:00:00Z")
    mini, rows = _load(monkeypatch, tree)
    assert _slugs(mini, rows) == [
        "BACKLOG", "mixed-epic", "02-early", "10-late", "extra-new", "extra-old",
    ]
    orders = {t.slug: mini._epic_order(t) for t in rows
              if not isinstance(t, mini.Header) and t.is_epic_child}
    assert orders == {
        "02-early": "02", "10-late": "10", "extra-old": "", "extra-new": "",
    }


def test_build_rows_drops_finished_epic_group(monkeypatch, tmp_path):
    """Once every child is done/cancelled the whole group disappears —
    including the epic header, whatever its own status says."""
    tree = tmp_path / "tickets"
    _write(tree, "area/done-epic/_epic.md", "open", "2026-05-01T00:00:00Z")
    _write(tree, "area/done-epic/01-a.md", "done", "2026-05-01T00:00:00Z")
    _write(tree, "area/done-epic/02-b.md", "cancelled", "2026-05-02T00:00:00Z")
    _write(tree, "area/solo.md", "open", "2026-04-01T00:00:00Z")
    mini, rows = _load(monkeypatch, tree)
    assert _slugs(mini, rows) == ["BACKLOG", "solo"]


def test_build_rows_epic_group_section_and_anchor(monkeypatch, tmp_path):
    """A group with any in-flight member lands in the IN FLIGHT section,
    anchored at its newest displayed member — here the active child outdates
    the lone standalone active ticket, so the group leads."""
    tree = tmp_path / "tickets"
    _write(tree, "area/hot-epic/_epic.md", "open", "2026-01-01T00:00:00Z")
    _write(tree, "area/hot-epic/01-now.md", "active", "2026-05-02T00:00:00Z")
    _write(tree, "area/lone-active.md", "active", "2026-05-01T00:00:00Z")
    _write(tree, "area/lone-open.md", "open", "2026-05-03T00:00:00Z")
    mini, rows = _load(monkeypatch, tree)
    assert _slugs(mini, rows) == [
        "IN FLIGHT", "hot-epic", "01-now", "lone-active",
        "",
        "BACKLOG", "lone-open",
    ]


def test_mini_set_label_writes_frontmatter(monkeypatch, tmp_path):
    tree = tmp_path / "tickets"
    _write(tree, "area/labeled.md", "open", "2026-05-01T00:00:00Z")
    monkeypatch.setenv("TICKETS_DIR", str(tree))
    for mod in ("tix.mini", "tix.tui", "tix"):
        sys.modules.pop(mod, None)

    from tix import mini, tui
    ticket = tui.load_tickets()[0]
    mini._set_label(ticket, "ops")
    assert ticket.label == "ops"
    brief = tree / "area" / "labeled.md"
    assert "label: ops" in brief.read_text(encoding="utf-8")

    mini._set_label(ticket, "")
    assert ticket.label == ""
    assert "label:" not in brief.read_text(encoding="utf-8")


def test_step_and_nearest_skip_headers():
    sys.modules.pop("tix.mini", None)
    from tix import mini

    class _Row:
        path = None

    a, b = _Row(), _Row()
    flight = mini.Header("IN FLIGHT", "inprogress", 1)
    backlog = mini.Header("BACKLOG", "backlog", 1)
    rows = [flight, a, mini.SPACER, backlog, b]
    assert mini._step(rows, 1, 1) == 4
    assert mini._step(rows, 4, -1) == 1
    assert mini._step(rows, 4, 1) == 4
    assert mini._step(rows, 1, -1) == 1
    assert mini._nearest_ticket(rows, 0) == 1
    assert mini._nearest_ticket(rows, 2) == 1
    assert mini._nearest_ticket(rows, 3) == 1
    assert mini._nearest_ticket(rows, 99) == 4


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
