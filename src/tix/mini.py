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
    TICKET_DIRS,
    dir_signature,
    load_tickets,
    open_in_pager,
    pickup_agent_label,
    pickup_ticket,
    relative_age,
    run_preload_hook,
    write_label,
    write_status,
)

# Statuses hidden from mini's flat list — done + every cancelled alias.
_HIDDEN = {s.lower() for s in CANCELLED_STATUSES} | {"done"}

# Mini-local status ordering: active → review → draft → open. Diverges from
# tui's STATUS_META rank (which puts open ahead of draft) — drafts are unstarted
# work the user owns, open are unclaimed; mini surfaces ownership first. `review`
# (open PR) sits just behind active as the most in-flight work.
# Title-case aliases map to their lowercase equivalents.
_MINI_RANK = {
    "active": 0,
    "review": 1,
    "draft": 2,
    "open": 3,
    "In Progress": 0,
    "In Review": 1,
    "Backlog": 2,
    "Todo": 3,
}


def build_rows(tickets):
    """Filter + sort tickets for mini's flat list.

    Hides done/cancelled (case-insensitive — pre-migration title-case
    `Done`/`Canceled` also drop). Sort: mini rank asc (active → draft →
    open), then `created` desc; ties broken by id. Missing `created` (0.0)
    sinks via -created negation.

    Also stamps `is_epic_child` on each kept ticket — true when the ticket
    lives inside an epic folder (a sibling `_epic.md` was loaded). Epic dirs
    come from the *unfiltered* ticket list so children stay marked even when
    their epic is done/cancelled and hidden."""
    epic_dirs = {t.path.parent for t in tickets if t.is_epic}
    keep = [t for t in tickets if t.status.lower() not in _HIDDEN]
    for t in keep:
        t.is_epic_child = not t.is_epic and t.path.parent in epic_dirs
    return sorted(
        keep,
        key=lambda t: (
            _MINI_RANK.get(t.status, 9),
            -t.created,
            t.id,
        ),
    )


def _status_meta(ticket):
    # Epics defer to Ticket.meta (▸ / accent) — same marker the full tui uses.
    if ticket.is_epic:
        return ticket.meta
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


def _set_label(ticket, label):
    label = label.strip()
    write_label(ticket.path, label)
    ticket.label = label


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
        "accent": curses.COLOR_CYAN,
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
        label_tag = f"#{t.label[:14]}" if t.label else ""
        # Layout: icon + title, then optional label + right-aligned age.
        age_x = max(0, w - len(age_pad) - 1)
        title_x = 2
        label_x = age_x - len(label_tag) - 1 if label_tag else age_x
        if label_tag and label_x <= title_x:
            label_tag = ""
            label_x = age_x
        title_w = max(0, label_x - title_x - 1)
        sel_attr = curses.A_REVERSE if idx == sel else 0
        # Hierarchy markers: epics keep their ▸ icon and render the title bold;
        # children get a `↳ ` title prefix (flat list, so indentation alone
        # wouldn't read — children aren't adjacent to their epic).
        title = f"↳ {t.title}" if getattr(t, "is_epic_child", False) else t.title
        title_attr = sel_attr | color_attr | (curses.A_BOLD if t.is_epic else 0)
        try:
            if idx == sel:
                stdscr.addstr(i, 0, " " * (w - 1), sel_attr)
            stdscr.addstr(i, 0, icon, sel_attr | color_attr | curses.A_BOLD)
            stdscr.addstr(i, title_x, title[:title_w], title_attr)
            if label_tag:
                stdscr.addstr(
                    i, label_x, label_tag,
                    sel_attr | colors.get("muted", 0) | curses.A_DIM,
                )
            stdscr.addstr(
                i, age_x, age_pad,
                sel_attr | colors.get("muted", 0) | curses.A_DIM,
            )
        except curses.error:
            pass
    # Footer hint. Surfaces the agent `p` will spawn for the selected ticket
    # (per TIX_PICKUP_AGENTS) so routing is visible in the narrow reader too.
    if h >= 1:
        agent = pickup_agent_label(rows[sel].path) if rows else "pi"
        hint = f"↑↓ ⏎ · p pickup→{agent} · l label · i/d/x status · q quit"
        try:
            stdscr.addstr(h - 1, 0, hint[: max(0, w - 1)], curses.A_DIM)
        except curses.error:
            pass
    stdscr.refresh()


def _draw_label_prompt(stdscr, ticket, label_buffer):
    h, w = stdscr.getmaxyx()
    if h < 1:
        return
    y = h - 1
    prompt = f"label `{ticket.slug}`: {label_buffer}"
    try:
        stdscr.addstr(y, 0, " " * max(0, w - 1), curses.A_REVERSE)
        stdscr.addstr(y, 0, prompt[: max(0, w - 1)], curses.A_REVERSE)
        stdscr.move(y, min(len(prompt), max(0, w - 1)))
    except curses.error:
        pass
    stdscr.refresh()


def _run(stdscr):
    curses.curs_set(0)
    stdscr.keypad(True)
    colors = _init_colors()
    # Capture dir_sig BEFORE load_tickets so any write racing the initial scan
    # bumps the next poll and triggers a reload.
    dir_sig = dir_signature()
    rows = build_rows(load_tickets())
    sel = 0
    top = 0
    label_ticket = None
    label_buffer = ""
    while True:
        # Re-apply the 2 s idle timeout every iter. open_in_pager / pickup_ticket
        # suspend curses (def_prog_mode/endwin/reset_prog_mode) and some terminals
        # drop the window timeout on resume — leaving getch() blocking, so the
        # dir_signature poll never fires and externally-created tickets are
        # invisible until the user quits + reopens.
        stdscr.timeout(2000)
        h, _ = stdscr.getmaxyx()
        body_h = max(1, h - 1)
        if sel < top:
            top = sel
        elif sel >= top + body_h:
            top = sel - body_h + 1
        top = max(0, min(top, max(0, len(rows) - body_h)))
        _draw(stdscr, rows, sel, top, colors)
        if label_ticket is None:
            curses.curs_set(0)
        else:
            curses.curs_set(1)
            _draw_label_prompt(stdscr, label_ticket, label_buffer)
        ch = stdscr.getch()
        if ch == -1:
            if label_ticket is not None:
                continue
            new_sig = dir_signature()
            if new_sig != dir_sig:
                prev_path = rows[sel].path if rows else None
                # Capture sig BEFORE load_tickets — writes during load bump
                # next poll instead of being missed.
                dir_sig = dir_signature()
                rows = build_rows(load_tickets())
                if prev_path is not None:
                    for i, t in enumerate(rows):
                        if t.path == prev_path:
                            sel = i
                            break
                    else:
                        sel = min(sel, max(0, len(rows) - 1))
                else:
                    sel = 0
            continue
        if label_ticket is not None:
            if ch in (27, 3):  # esc / Ctrl-C — cancel
                label_ticket = None
                label_buffer = ""
            elif ch in (curses.KEY_ENTER, 10, 13):
                ticket = label_ticket
                _set_label(ticket, label_buffer)
                label_ticket = None
                label_buffer = ""
                dir_sig = dir_signature()
                rows = build_rows(load_tickets())
                for i, t in enumerate(rows):
                    if t.path == ticket.path:
                        sel = i
                        break
                else:
                    sel = min(sel, max(0, len(rows) - 1))
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                label_buffer = label_buffer[:-1]
            elif 32 <= ch < 127:
                label_buffer += chr(ch)
            continue
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
            dir_sig = dir_signature()
            rows = build_rows(load_tickets())
            # Re-find the same path to keep cursor steady; else clamp.
            for i, t in enumerate(rows):
                if t.path == ticket.path:
                    sel = i
                    break
            else:
                sel = min(sel, max(0, len(rows) - 1))
        elif ch == ord("l"):
            label_ticket = rows[sel]
            label_buffer = label_ticket.label
        elif ch in (ord("i"), ord("d"), ord("x")):
            ticket = rows[sel]
            _toggle_status(ticket, ch)
            dir_sig = dir_signature()
            rows = build_rows(load_tickets())
            for i, t in enumerate(rows):
                if t.path == ticket.path:
                    sel = i
                    break
            else:
                # Ticket dropped from view (now done/cancelled).
                sel = min(sel, max(0, len(rows) - 1))


def main():
    if not any(ticket_dir.is_dir() for ticket_dir in TICKET_DIRS):
        roots = ", ".join(str(ticket_dir) for ticket_dir in TICKET_DIRS)
        print(f"tix: no ticket directory at {roots}", file=sys.stderr)
        return 1
    run_preload_hook()
    # No empty-tree bail: mini is meant to sit open as a sidecar, so it must
    # survive a cold start with zero tickets and surface the first one created
    # via the same idle-poll path that handles later additions.
    curses.wrapper(_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
