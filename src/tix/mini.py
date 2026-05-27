"""tix --mini — narrow-pane reverse-chrono ticket reader.

A stripped-down sibling of `tui.py`: flat list, newest `created:` first,
done/cancelled hidden. ↑/↓ to move, Enter opens the brief in glow/$PAGER,
`p` spawns a `wt` lane. Targets ≥20 column panes (think tmux sidecar).

Reuses tui's `Ticket` parser, `parse_created`, and the module-level
`open_in_pager` / `pickup_ticket` helpers — mini is a thinner renderer
over the identical model layer."""
import curses
import sys

from .tui import (
    CANCELLED_STATUSES,
    DEFAULT_STATUS_META,
    STATUS_META,
    TICKETS_DIR,
    load_tickets,
    open_in_pager,
    pickup_ticket,
    relative_age,
    run_preload_hook,
    write_status,
)

# Statuses hidden from mini's flat list — done + every cancelled alias.
_HIDDEN = {s.lower() for s in CANCELLED_STATUSES} | {"done"}


def build_rows(tickets):
    """Filter + sort tickets for mini's flat list.

    Hides done/cancelled (case-insensitive — pre-migration title-case
    `Done`/`Canceled` also drop). Sort: STATUS_META rank asc (active first),
    then `created` desc; ties broken by id. Missing `created` (0.0) sinks
    via -created negation."""
    keep = [t for t in tickets if t.status.lower() not in _HIDDEN]
    return sorted(
        keep,
        key=lambda t: (
            STATUS_META.get(t.status, DEFAULT_STATUS_META)[2],
            -t.created,
            t.id,
        ),
    )


def _status_meta(ticket):
    return STATUS_META.get(ticket.status, DEFAULT_STATUS_META)


# Mini's status toggles — same sticky semantics as tui's `i`/`d`/`x`. Each
# key flips between its target status and `open`; cancelled toggle treats any
# CANCELLED_STATUSES alias as "currently cancelled".
def _toggle_status(ticket, ch):
    cur = ticket.status
    if ch == ord("i"):
        new = "open" if cur.lower() == "active" else "active"
    elif ch == ord("d"):
        new = "open" if cur.lower() == "done" else "done"
    else:  # ord("x")
        new = "open" if cur in CANCELLED_STATUSES else "cancelled"
    write_status(ticket.path, new)
    ticket.status = new


def _init_colors():
    """Mirror tui.App.init_colors — same palette so mini matches the main UI."""
    colors = {}
    if not curses.has_colors():
        return colors
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    spec = {
        "inprogress": curses.COLOR_YELLOW,
        "inreview": curses.COLOR_MAGENTA,
        "todo": curses.COLOR_CYAN,
        "backlog": curses.COLOR_BLUE,
        "done": curses.COLOR_GREEN,
        "muted": curses.COLOR_WHITE,
    }
    for i, (name, fg) in enumerate(spec.items(), start=1):
        try:
            curses.init_pair(i, fg, -1)
        except curses.error:
            curses.init_pair(i, fg, curses.COLOR_BLACK)
        colors[name] = curses.color_pair(i)
    return colors


def _draw(stdscr, rows, sel, top, colors):
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
        icon, color_name, _ = _status_meta(t)
        color_attr = colors.get(color_name, 0)
        age = relative_age(t.created) or ""
        age_pad = f"{age:>4}"
        # Layout: icon (col 0) + space + title + right-aligned age.
        age_x = max(0, w - len(age_pad) - 1)
        title_x = 2
        title_w = max(0, age_x - title_x - 1)
        sel_attr = curses.A_REVERSE if idx == sel else 0
        try:
            if idx == sel:
                stdscr.addstr(i, 0, " " * (w - 1), sel_attr)
            stdscr.addstr(i, 0, icon, sel_attr | color_attr | curses.A_BOLD)
            stdscr.addstr(i, title_x, t.title[:title_w], sel_attr | color_attr)
            stdscr.addstr(
                i, age_x, age_pad,
                sel_attr | colors.get("muted", 0) | curses.A_DIM,
            )
        except curses.error:
            pass
    # Footer hint.
    if h >= 1:
        hint = "↑↓ ⏎ · p pickup · i/d/x status · q quit"
        try:
            stdscr.addstr(h - 1, 0, hint[: max(0, w - 1)], curses.A_DIM)
        except curses.error:
            pass
    stdscr.refresh()


def _run(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(-1)
    colors = _init_colors()
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
        _draw(stdscr, rows, sel, top, colors)
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
        elif ch in (ord("i"), ord("d"), ord("x")):
            ticket = rows[sel]
            _toggle_status(ticket, ch)
            rows = build_rows(load_tickets())
            for i, t in enumerate(rows):
                if t.path == ticket.path:
                    sel = i
                    break
            else:
                # Ticket dropped from view (now done/cancelled).
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
