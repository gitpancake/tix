"""tix --mini — narrow-pane reverse-chrono ticket reader.

A stripped-down sibling of `tui.py`: flat list, newest `created:` first,
done/cancelled hidden. ↑/↓ to move, Enter opens the brief in glow/$PAGER,
`p` spawns a `wt` lane. Targets ≥20 column panes (think tmux sidecar).

Reuses tui's `Ticket` parser, `parse_created`, and the module-level
`open_in_pager` / `pickup_ticket` helpers — mini is a thinner renderer
over the identical model layer."""
import curses
import os
import sys
from pathlib import Path

from .tui import (
    CANCELLED_STATUSES,
    Ticket,
    load_tickets,
    open_in_pager,
    pickup_ticket,
    relative_age,
    run_preload_hook,
    STATUS_META,
    TICKETS_DIR,
)


# Statuses hidden from mini's flat list — done + every cancelled alias.
_HIDDEN = {s.lower() for s in CANCELLED_STATUSES} | {"done"}


def build_rows(tickets):
    """Filter + sort tickets for mini's flat list.

    Hides done/cancelled (case-insensitive — pre-migration title-case
    `Done`/`Canceled` also drop). Sort: `created` desc; ties broken by id.
    Missing `created` (0.0) sinks via -created negation (parity with
    tui.App.sort_within_group `created` mode)."""
    keep = [t for t in tickets if t.status.lower() not in _HIDDEN]
    return sorted(keep, key=lambda t: (-t.created, t.id))


def _status_icon(ticket):
    return STATUS_META.get(ticket.status, ("·", "muted", 9))[0]


def _draw(stdscr, rows, sel, top):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if w < 20:
        try:
            stdscr.addstr(0, 0, "pane too narrow"[: max(0, w - 1)])
        except curses.error:
            pass
        stdscr.refresh()
        return
    body_h = max(0, h - 1)
    for i in range(body_h):
        idx = top + i
        if idx >= len(rows):
            break
        t = rows[idx]
        icon = _status_icon(t)
        age = relative_age(t.created) or ""
        age_pad = f"{age:>4}"
        # Layout: icon (col 0) + space + title + right-aligned age.
        age_x = max(0, w - len(age_pad) - 1)
        title_x = 2
        title_w = max(0, age_x - title_x - 1)
        attr = curses.A_REVERSE if idx == sel else 0
        try:
            if idx == sel:
                stdscr.addstr(i, 0, " " * (w - 1), attr)
            stdscr.addstr(i, 0, icon, attr | curses.A_BOLD)
            stdscr.addstr(i, title_x, t.title[:title_w], attr)
            stdscr.addstr(i, age_x, age_pad, attr | curses.A_DIM)
        except curses.error:
            pass
    # Footer hint.
    if h >= 1:
        hint = "↑↓ ⏎ open · p pickup · q quit"
        try:
            stdscr.addstr(h - 1, 0, hint[: max(0, w - 1)], curses.A_DIM)
        except curses.error:
            pass
    stdscr.refresh()


def _run(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(-1)
    rows = build_rows(load_tickets())
    sel = 0
    top = 0
    while True:
        h, _ = stdscr.getmaxyx()
        body_h = max(1, h - 1)
        if sel < top:
            top = sel
        elif sel >= top + body_h:
            top = sel - body_h + 1
        top = max(0, min(top, max(0, len(rows) - body_h)))
        _draw(stdscr, rows, sel, top)
        ch = stdscr.getch()
        if ch in (ord("q"), 27, 3):  # q / esc / Ctrl-C
            return
        if not rows:
            continue
        if ch in (curses.KEY_DOWN,):
            sel = min(len(rows) - 1, sel + 1)
        elif ch in (curses.KEY_UP,):
            sel = max(0, sel - 1)
        elif ch == curses.KEY_NPAGE:
            sel = min(len(rows) - 1, sel + body_h)
        elif ch == curses.KEY_PPAGE:
            sel = max(0, sel - body_h)
        elif ch == curses.KEY_HOME:
            sel = 0
        elif ch == curses.KEY_END:
            sel = len(rows) - 1
        elif ch in (curses.KEY_ENTER, 10, 13):
            open_in_pager(stdscr, rows[sel].path)
        elif ch == ord("p"):
            ticket = rows[sel]
            pickup_ticket(stdscr, ticket)
            rows = build_rows(load_tickets())
            # Re-find the same path to keep cursor steady; else clamp.
            for i, t in enumerate(rows):
                if t.path == ticket.path:
                    sel = i
                    break
            else:
                sel = min(sel, max(0, len(rows) - 1))


def main():
    if not TICKETS_DIR.is_dir():
        print(f"tix: no ticket directory at {TICKETS_DIR}", file=sys.stderr)
        return 1
    run_preload_hook()
    if not load_tickets():
        print(f"tix: no tickets found under {TICKETS_DIR}", file=sys.stderr)
        return 1
    curses.wrapper(_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
