"""tix --mini — narrow-pane ticket reader.

A stripped-down sibling of `tui.py`: newest `created:` first, in-flight
(active/review) work above a divider, everything else below. Epic children
group indented under their epic row — done children stay visible until the
whole epic is finished, then the group drops. ↑/↓ to move, Enter opens the
brief in glow/$PAGER, `p` spawns a `wt` lane. Targets ≥20 column panes
(think tmux sidecar).

Reuses tui's `Ticket` parser, `parse_created`, and the module-level
`open_in_pager` / `pickup_ticket` helpers — mini is a thinner renderer
over the identical model layer."""
import curses
import sys
from datetime import datetime

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
    run_preload_hook,
    write_label,
    write_status,
)

# Finished statuses — hidden as standalone rows; inside a still-running epic,
# done children stay visible (cancelled never do).
_DONEISH = {s.lower() for s in CANCELLED_STATUSES} | {"done"}
_CANCELLED = {s.lower() for s in CANCELLED_STATUSES}

# In-flight statuses sort above the divider. Lowercase compare — covers the
# pre-migration title-case aliases (`In Progress`, `In Review`).
_IN_FLIGHT = {"active", "review", "in progress", "in review"}

# Sentinel row separating the in-flight section from the rest. Not selectable
# — navigation steps over it, rendering draws a rule.
DIVIDER = object()


def _is_doneish(ticket):
    return ticket.status.lower() in _DONEISH


def _is_in_flight(ticket):
    return ticket.status.lower() in _IN_FLIGHT


def build_rows(tickets):
    """Filter + sort tickets for mini's list.

    Two sections, newest `created:` first within each (missing `created`
    (0.0) sinks via -created negation; ties broken by id): in-flight
    (active/review) above DIVIDER, the rest below. The divider only appears
    when both sections are non-empty.

    Standalone done/cancelled tickets are hidden. A visible epic groups: the
    epic row leads, children follow indented (`is_epic_child`), created desc.
    Done children stay listed while any sibling is unfinished — the group
    shows epic progression — and the whole group (epic included) drops once
    every child is done/cancelled. Cancelled children never render. A group
    sorts by its newest displayed member and lands in the in-flight section
    when any displayed member is in-flight."""
    epics = {t.path.parent: t for t in tickets if t.is_epic}
    units = []
    for t in tickets:
        if t.is_epic or t.path.parent in epics or _is_doneish(t):
            continue
        t.is_epic_child = False
        units.append((-t.created, t.id, [t]))
    for epic_dir, epic in epics.items():
        children = [t for t in tickets if not t.is_epic and t.path.parent == epic_dir]
        epic_finished = (all(_is_doneish(c) for c in children) if children
                         else _is_doneish(epic))
        if epic_finished:
            continue
        shown = sorted(
            (c for c in children if c.status.lower() not in _CANCELLED),
            key=lambda t: (-t.created, t.id),
        )
        epic.is_epic_child = False
        for child in shown:
            child.is_epic_child = True
        members = [epic] + shown
        newest = max(m.created for m in members)
        units.append((-newest, epic.id, members))
    units.sort(key=lambda unit: unit[:2])
    in_flight = [t for _, _, members in units
                 if any(_is_in_flight(m) for m in members) for t in members]
    backlog = [t for _, _, members in units
               if not any(_is_in_flight(m) for m in members) for t in members]
    if in_flight and backlog:
        return in_flight + [DIVIDER] + backlog
    return in_flight + backlog


def _created_stamp(ticket):
    """`created:` as `MM/DD HH:MM` for the right-aligned column. Empty when
    created is missing (0.0) or out of fromtimestamp's range."""
    if not ticket.created:
        return ""
    try:
        return datetime.fromtimestamp(ticket.created).strftime("%m/%d %H:%M")
    except (OSError, ValueError, OverflowError):
        return ""


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


def _step(rows, sel, delta):
    """One selection step, skipping DIVIDER. Stays put at list edges."""
    i = sel + delta
    while 0 <= i < len(rows) and rows[i] is DIVIDER:
        i += delta
    return i if 0 <= i < len(rows) else sel


def _nearest_ticket(rows, i):
    """Clamp i into range, then nudge off DIVIDER (up first, then down)."""
    if not rows:
        return 0
    i = max(0, min(i, len(rows) - 1))
    if rows[i] is not DIVIDER:
        return i
    for j in (*range(i - 1, -1, -1), *range(i + 1, len(rows))):
        if rows[j] is not DIVIDER:
            return j
    return 0


def _find_path(rows, path, fallback):
    """Index of the row holding `path`; else fallback nudged off DIVIDER."""
    for i, t in enumerate(rows):
        if t is not DIVIDER and t.path == path:
            return i
    return _nearest_ticket(rows, fallback)


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
        if t is DIVIDER:
            try:
                stdscr.addstr(i, 0, "─" * (w - 1),
                              colors.get("muted", 0) | curses.A_DIM)
            except curses.error:
                pass
            continue
        icon, color_name, _ = _status_meta(t)
        color_attr = colors.get(color_name, 0)
        stamp_pad = f"{_created_stamp(t):>11}"
        label_tag = f"#{t.label[:14]}" if t.label else ""
        # Layout: [indent] icon + title, then optional label + right-aligned
        # created stamp. Children sit 2 cols deep under their epic row
        # (grouping is build_rows' job — adjacency makes the indent readable).
        indent = 2 if getattr(t, "is_epic_child", False) else 0
        stamp_x = max(0, w - len(stamp_pad) - 1)
        title_x = indent + 2
        label_x = stamp_x - len(label_tag) - 1 if label_tag else stamp_x
        if label_tag and label_x <= title_x:
            label_tag = ""
            label_x = stamp_x
        title_w = max(0, label_x - title_x - 1)
        sel_attr = curses.A_REVERSE if idx == sel else 0
        title_attr = sel_attr | color_attr | (curses.A_BOLD if t.is_epic else 0)
        try:
            if idx == sel:
                stdscr.addstr(i, 0, " " * (w - 1), sel_attr)
            stdscr.addstr(i, indent, icon, sel_attr | color_attr | curses.A_BOLD)
            stdscr.addstr(i, title_x, t.title[:title_w], title_attr)
            if label_tag:
                stdscr.addstr(
                    i, label_x, label_tag,
                    sel_attr | colors.get("muted", 0) | curses.A_DIM,
                )
            stdscr.addstr(
                i, stamp_x, stamp_pad,
                sel_attr | colors.get("muted", 0) | curses.A_DIM,
            )
        except curses.error:
            pass
    # Footer hint. Surfaces the agent `p` will spawn for the selected ticket
    # (per TIX_PICKUP_AGENTS) so routing is visible in the narrow reader too.
    if h >= 1:
        has_sel = rows and rows[sel] is not DIVIDER
        agent = pickup_agent_label(rows[sel].path) if has_sel else "pi"
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
    sel = _nearest_ticket(rows, 0)
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
                prev_path = rows[sel].path if rows and rows[sel] is not DIVIDER else None
                # Capture sig BEFORE load_tickets — writes during load bump
                # next poll instead of being missed.
                dir_sig = dir_signature()
                rows = build_rows(load_tickets())
                if prev_path is not None:
                    sel = _find_path(rows, prev_path, sel)
                else:
                    sel = _nearest_ticket(rows, 0)
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
                sel = _find_path(rows, ticket.path, sel)
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
            sel = _step(rows, sel, 1)
        elif ch in (curses.KEY_UP,):
            sel = _step(rows, sel, -1)
        elif ch == curses.KEY_NPAGE:
            sel = _nearest_ticket(rows, sel + body_h)
        elif ch == curses.KEY_PPAGE:
            sel = _nearest_ticket(rows, sel - body_h)
        elif ch == curses.KEY_HOME:
            sel = _nearest_ticket(rows, 0)
        elif ch == curses.KEY_END:
            sel = _nearest_ticket(rows, len(rows) - 1)
        elif ch in (curses.KEY_ENTER, 10, 13):
            open_in_pager(stdscr, rows[sel].path)
        elif ch == ord("p"):
            ticket = rows[sel]
            pickup_ticket(stdscr, ticket)
            dir_sig = dir_signature()
            rows = build_rows(load_tickets())
            # Re-find the same path to keep cursor steady; else clamp.
            sel = _find_path(rows, ticket.path, sel)
        elif ch == ord("l"):
            label_ticket = rows[sel]
            label_buffer = label_ticket.label
        elif ch in (ord("i"), ord("d"), ord("x")):
            ticket = rows[sel]
            _toggle_status(ticket, ch)
            dir_sig = dir_signature()
            rows = build_rows(load_tickets())
            # Ticket may have dropped from view (now done/cancelled).
            sel = _find_path(rows, ticket.path, sel)


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
