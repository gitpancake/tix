#!/usr/bin/env python3
"""tix — terminal ticket explorer for ~/.pi/agent/tickets.

Keyboard-driven, Linear-like TUI over the local ticket briefs. The list
view groups tickets by their on-disk folder; Enter opens the full
markdown in glow's pager. Zero deps beyond the stdlib + glow on PATH.
"""
import curses
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

TICKETS_DIR = Path(os.environ.get("TICKETS_DIR", Path.home() / ".pi" / "agent" / "tickets"))
_EXTRA_TICKETS_DIRS = [
    Path(raw).expanduser()
    for raw in os.environ.get("TIX_EXTRA_TICKETS_DIRS", "").split(os.pathsep)
    if raw
]
TICKET_DIRS = []
for _ticket_dir in [TICKETS_DIR, *_EXTRA_TICKETS_DIRS]:
    if _ticket_dir not in TICKET_DIRS:
        TICKET_DIRS.append(_ticket_dir)
LANES_FILE = Path(os.environ.get("ACTIVE_LANES_FILE",
                                 Path.home() / ".claude" / "active-lanes.json"))

# Per-ticket-dir agent launcher for pickup. Format (TIX_PICKUP_AGENTS):
#   <ticket-root>=<agent-cmd>[<pathsep><ticket-root>=<agent-cmd>...]
# When a picked-up ticket lives under <ticket-root>, `wt` is invoked with
# WT_AGENT_CMD=<agent-cmd> instead of its own default. Lets one board route
# Pi-home tickets to Pi (no entry → wt default) and Claude-home tickets to a
# Claude lane launcher. Longest-ancestor match wins, so project-scoped roots
# (e.g. ~/.claude/tickets/<project>) still resolve against ~/.claude/tickets.
_PICKUP_AGENTS = []
for _raw in os.environ.get("TIX_PICKUP_AGENTS", "").split(os.pathsep):
    if "=" in _raw:
        _root, _cmd = _raw.split("=", 1)
        _PICKUP_AGENTS.append((Path(_root).expanduser(), _cmd))


def ticket_dir_for_path(path):
    for ticket_dir in TICKET_DIRS:
        try:
            path.relative_to(ticket_dir)
            return ticket_dir
        except ValueError:
            continue
    return TICKETS_DIR


def pickup_agent_cmd(path):
    """Agent launch command for a ticket at `path`, or None for wt's default.
    Picks the TIX_PICKUP_AGENTS entry whose root is the deepest ancestor."""
    best_root = None
    best_cmd = None
    for root, cmd in _PICKUP_AGENTS:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if best_root is None or len(root.parts) > len(best_root.parts):
            best_root, best_cmd = root, cmd
    return best_cmd


def pickup_agent_label(path):
    """Short name of the agent `p` will spawn for a ticket: the basename of the
    launcher in its TIX_PICKUP_AGENTS command (skipping VAR=val env prefixes),
    or 'pi' when no entry matches (wt's own default)."""
    cmd = pickup_agent_cmd(path)
    if not cmd:
        return "pi"
    for tok in shlex.split(cmd):
        if "=" in tok and not tok.startswith("/") and " " not in tok.split("=", 1)[0]:
            continue
        return Path(tok).name
    return "pi"


def pickup_env(ticket):
    env = {**os.environ, "WT_NO_WATCH": os.environ.get("WT_NO_WATCH", "1")}
    env["TICKETS_DIR"] = str(ticket.ticket_dir)
    if "WT_AGENT_CMD" not in os.environ:
        cmd = pickup_agent_cmd(ticket.path)
        if cmd:
            env["WT_AGENT_CMD"] = cmd
    return env

# Linear workspace slug — used to derive a ticket URL from its `linear:` id.
# Set LINEAR_WORKSPACE in the environment; unset → no derived URL.
LINEAR_WORKSPACE = os.environ.get("LINEAR_WORKSPACE", "")


def claude_argv(prompt):
    """Build the argv for an interactive claude dispatch (rescope/scope/new).
    Mirrors `wt`'s lane launch so these match pickup permission-wise: bypass
    the permission prompt. WT_CLAUDE overrides the binary+flags (same env var
    wt honors); default is `claude --dangerously-skip-permissions`."""
    base = os.environ.get("WT_CLAUDE", "claude --dangerously-skip-permissions")
    return [*shlex.split(base), prompt]

# Files under TICKETS_DIR that are not tickets — skipped by the loader.
META_FILES = {"README.md", "_TEMPLATE.md", "_EPIC-TEMPLATE.md", "_CHILD-TEMPLATE.md"}

# status label -> (icon, color name, sort rank). Lowercase keys are the current
# schema ($TICKETS_DIR/README.md); title-case keys are legacy (pre-migration).
STATUS_META = {
    "active":      ("◐", "inprogress", 0),
    "review":      ("◑", "inreview", 1),
    "open":        ("○", "todo", 2),
    "draft":       ("◌", "backlog", 3),
    "done":        ("●", "done", 4),
    "merged":      ("●", "done", 4),
    "cancelled":   ("✕", "muted", 6),
    "canceled":    ("✕", "muted", 6),
    "In Progress": ("◐", "inprogress", 0),
    "In Review":   ("◑", "inreview", 1),
    "Todo":        ("○", "todo", 2),
    "Backlog":     ("○", "backlog", 3),
    "Done":        ("●", "done", 4),
    "Canceled":    ("✕", "muted", 5),
    "Cancelled":   ("✕", "muted", 5),
}
DEFAULT_STATUS_META = ("·", "muted", 9)
FILTER_ORDER = ["active", "review", "open", "draft", "done", "cancelled",
                "In Progress", "In Review", "Todo", "Backlog"]
CANCELLED_STATUSES = {"cancelled", "canceled", "Cancelled", "Canceled"}
# Read-only done aliases (lowercase compare) — reconcilers/PR tooling may
# write `merged`; tix treats it as `done` everywhere but never rewrites it.
DONE_STATUSES = {"done", "merged"}


def filter_chip(status):
    """Fold status aliases onto their canonical filter chip so done-ish
    (`merged`, `Done`) and cancelled-ish (`canceled`, `Cancelled`) tickets
    ride the `done`/`cancelled` chips instead of vanishing."""
    if status.lower() in DONE_STATUSES:
        return "done"
    if status in CANCELLED_STATUSES:
        return "cancelled"
    return status

# Split-pane thresholds. Below the combined minimum, preview is hidden and
# the list reclaims the full width.
LIST_MIN_W = 38
PREVIEW_MIN_W = 32

# Priority bucket → (sort rank, color name). Missing/blank priorities sort last
# with rank 9 so prioritized work bubbles to the top of each group.
PRIORITY_META = {
    "P0": (0, "p0"),
    "P1": (1, "p1"),
    "P2": (2, "p2"),
    "P3": (3, "p3"),
}
PRIORITY_ORDER = ["P0", "P1", "P2", "P3"]
PRIORITY_DEFAULT_RANK = 9

# Sort modes — extend `SORT_MODES` and `App.sort_within_group` together. The
# picker (`s` keystroke) cycles this list; `priority` preserves the long-time
# default ordering, `created` surfaces freshly written briefs.
SORT_MODES = ["priority", "created"]
SORT_LABELS = {"priority": "priority", "created": "date"}

# Fixed area bucket set (kept in sync with $TICKETS_DIR/README.md). The
# minibuffer move picker indexes into this list — extend with care.
AREAS = ["integrations", "ops", "platform", "spikes", "tooling"]

HELP_TEXT = """tix — keyboard reference

NAVIGATION
  ↑ / k          move up
  ↓ / j          move down
  PgUp / Ctrl-U  page (half) up
  PgDn / Ctrl-D  page (half) down
  g              jump to top
  G              jump to bottom
  ← / h          collapse current group
  → / ⏎          open ticket in glow (or expand group)
  space          toggle current group
  C / z          collapse / expand all groups

FILTER + SEARCH
  tab / shift-tab  cycle status filter chip
  1-9              jump to filter chip N
  /                start text search (esc to cancel, ⏎ to commit)
  s                sort picker → ↑/↓ select, ⏎ apply, esc cancel
                   modes: priority (default), date (newest first)

TICKET ACTIONS
  p              pickup → mark active + wt <slug> (agent per TIX_PICKUP_AGENTS)
                 (suspend curses, run, return)
  e              edit brief in $EDITOR; reload after
  R              rescope → $EDITOR scratch → claude "/rescope <slug> <text>"
  n              new ticket → $EDITOR scratch → claude "/scope <text>"
  N              new from clipboard (pbpaste) → $EDITOR → claude "/scope"
  +/= / -        raise / lower priority (P0..P3, blank); writes frontmatter
  i              toggle in-progress (sticky: pins `active` without a lane)
  d              toggle done   (sticky: trumps reconciler)
  x              toggle cancel (sticky terminal; ticket hides from default views)
  l              set/clear label (type label, ⏎ save, blank clears)
  m              move ticket to a different area (numeric pick)
  o              open the ticket's URL (legacy linear: field)
  r              force reload (also auto-reloads every 2s on tickets-dir change)
  ?              this help
  q / esc        quit

HIDE RULES
  cancelled  hidden everywhere except `cancelled` chip
  done       hidden everywhere except `done` chip
  merged     read-only alias of done — same icon, same hiding, same chip
  All chip shows every in-flight state (active / review / open; legacy draft).

STATUS LIFECYCLE
  open → birth state; /scope plants it (draft is retired)
  active → derived from live worktree / branch, OR sticky `i` mark in tix
  review → derived from an open, unmerged PR for the slug's branch
  done → derived from merged PR OR sticky `d` mark in tix
  cancelled → sticky `x` mark; trumps every derived signal

The reconciler runs on every tix launch (background) + every `wt` spawn.
"""


def load_lanes():
    """slug -> {path, branch, repo, last_commit} sidecar emitted by
    ticket-status-sync.py. Best-effort: missing/corrupt → empty dict, tix
    just hides the lane-state section."""
    try:
        return json.loads(LANES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_agent_state(wt_path):
    """Single-file read — the state machine writes one line per transition,
    so this is the live agent indicator. Empty / missing → just hide."""
    try:
        return (Path(wt_path) / ".claude" / "agent-state").read_text(
            encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


AGENT_STATE_COLORS = {
    "ACTIVE":  "inprogress",
    "WAITING": "p1",
    "IDLE":    "todo",
    "RUNNING": "inreview",
    "DONE":    "done",
    "FAILED":  "p0",
}


def agent_state_color(state):
    """Map the leading token of an agent-state line (`ACTIVE:tool`,
    `WAITING:code:detail`, …) onto a tix color name."""
    head = state.split(":", 1)[0] if state else ""
    return AGENT_STATE_COLORS.get(head, "muted")


def dir_signature():
    """Sum of every brief's mtime_ns under TICKETS_DIR. Order-independent —
    a single bumped/added/removed file changes the sum, so tix can poll this
    cheaply on idle ticks and reload only when something actually changed."""
    total = 0
    for ticket_dir in TICKET_DIRS:
        try:
            for path in ticket_dir.rglob("*.md"):
                try:
                    total += path.stat().st_mtime_ns
                except OSError:
                    continue
        except OSError:
            pass
    return total


def is_tombstone(path):
    """A tombstone is a brief whose only content is `moved -> <path>`. The
    contract ($TICKETS_DIR/README.md) defines them as redirects; tix
    should not surface them as tickets. We sniff only the first non-empty
    line so the check stays cheap on the rglob hot path."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                return stripped.startswith("moved -> ")
    except OSError:
        return False
    return False


def write_frontmatter_field(path, key_name, value):
    """Insert, replace, or remove a frontmatter field. value="" clears the line.
    No-op if the file has no frontmatter. Mirrors the line-edit pattern in
    ticket-status-sync.py — flat key:value, no PyYAML."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    if not text.startswith("---"):
        return
    lines = text.splitlines(keepends=True)
    fm_end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm_end = i
            break
    if fm_end is None:
        return
    field_idx = None
    for i in range(1, fm_end):
        key, sep, _ = lines[i].partition(":")
        if sep and key.strip() == key_name:
            field_idx = i
            break
    if value:
        new_line = f"{key_name}: {value}\n"
        if field_idx is not None:
            lines[field_idx] = new_line
        else:
            lines.insert(fm_end, new_line)
    elif field_idx is not None:
        del lines[field_idx]
    path.write_text("".join(lines), encoding="utf-8")


def write_priority(path, new_priority):
    write_frontmatter_field(path, "priority", new_priority)


def write_label(path, new_label):
    write_frontmatter_field(path, "label", new_label)


def write_status(path, new_status):
    write_frontmatter_field(path, "status", new_status)


def parse_frontmatter(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = {}
    if not text.startswith("---"):
        return fm
    end = text.find("\n---", 3)
    if end == -1:
        return fm
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        fm[key] = val
    return fm


def clean_title(title, ticket_id):
    title = re.sub(r"^\[[A-Za-z]+-\d+\]\s*", "", title.strip())
    return title or ticket_id


def parse_created(fm, path):
    """Epoch seconds for ticket creation. Frontmatter `created:` wins so users
    can override; falls back to filesystem birthtime (macOS) or ctime so legacy
    briefs without the field still sort. Returns 0.0 only when both fail."""
    raw = (fm.get("created") or "").strip() if fm else ""
    # Date-only `created:` (no `T`) is not an instant — treating it as
    # midnight (any tz) skews relative ages by up to a day. Fall through to
    # filesystem birthtime so a freshly-written ticket reads as fresh.
    if raw and "T" in raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
    try:
        st = path.stat()
    except OSError:
        return 0.0
    return getattr(st, "st_birthtime", None) or st.st_ctime or st.st_mtime


def relative_age(epoch):
    """Compact age string for the list view (≤3 chars where possible).
    Empty when epoch is missing — caller renders nothing."""
    if not epoch:
        return ""
    delta = max(0, int(time.time() - epoch))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 86400 * 30:
        return f"{delta // 86400}d"
    if delta < 86400 * 365:
        return f"{delta // (86400 * 30)}mo"
    return f"{delta // (86400 * 365)}y"


def format_created(epoch):
    """ISO date for the preview pane. Empty when epoch is missing."""
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")
    except (OSError, ValueError, OverflowError):
        return ""


class Ticket:
    def __init__(self, path):
        fm = parse_frontmatter(path)
        self.path = path
        self.ticket_dir = ticket_dir_for_path(path)
        self.is_epic = path.name == "_epic.md"
        # Legacy = pre-migration schema: carried `id:`, no `linear:`/`area:`.
        self.legacy = "id" in fm and "linear" not in fm and "area" not in fm
        # An _epic.md represents its folder; everything else is its own slug.
        self.slug = path.parent.name if self.is_epic else path.stem
        self.linear = fm.get("linear", "").strip()
        # Display identifier: Linear id if synced, else the slug (legacy: `id:`).
        self.id = self.linear or fm.get("id") or self.slug
        self.epic = fm.get("epic", "") or fm.get("parent", "")
        self.area = fm.get("area", "")
        self.status = fm.get("status", "").strip() or ("open" if self.is_epic else "")
        # Priority is optional; missing = unprioritized (sorted last).
        self.priority = fm.get("priority", "").strip().upper()
        self.label = fm.get("label", "").strip()
        # URL is derived from `linear:` when LINEAR_WORKSPACE is set; a legacy
        # stored `url:` is the fallback.
        self.url = (f"https://linear.app/{LINEAR_WORKSPACE}/issue/{self.linear}"
                    if self.linear and LINEAR_WORKSPACE else fm.get("url", ""))
        self.title = clean_title(fm.get("title", self.slug), self.slug)
        self.group = path.parent.name
        self.created = parse_created(fm, path)

    @property
    def meta(self):
        if self.is_epic:
            return ("▸", "accent", -1)
        return STATUS_META.get(self.status, DEFAULT_STATUS_META)

    def body(self):
        """Brief body text with frontmatter stripped. Cached per Ticket — the
        preview pane re-reads on every keystroke, so paying disk I/O once is the
        right trade for a ~50-ticket tree."""
        if hasattr(self, "_body"):
            return self._body
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end >= 0:
                text = text[end + 4:]
        self._body = text.lstrip("\n")
        return self._body


def load_tickets():
    tickets = []
    for ticket_dir in TICKET_DIRS:
        if not ticket_dir.is_dir():
            continue
        for path in sorted(ticket_dir.rglob("*.md")):
            if path.name in META_FILES:
                continue
            # Skip other _*.md meta files, but keep _epic.md (the epic PRD).
            if path.name.startswith("_") and path.name != "_epic.md":
                continue
            if is_tombstone(path):
                continue
            try:
                tickets.append(Ticket(path))
            except Exception:
                continue
    return tickets


def group_sort_key(name):
    # underscore groups (_loose etc.) sink to the bottom
    return (name.startswith("_"), name.lower())


MD_LIST_RE = re.compile(r"^(\s*)(?:([-*+])|(\d+[.)]))\s+")
MD_FENCE_RE = re.compile(r"^\s*(```|~~~)")
MD_BREAK_RE = re.compile(r"(-{3,}|\*{3,}|_{3,})")


def reflow_markdown(text):
    """Join soft-wrapped lines inside paragraphs and list items.

    Glamour (glow's renderer) keeps source newlines, so a brief hard-wrapped
    at one width re-wraps ragged at any other. Frontmatter, code fences,
    headings, quotes, tables, and blank lines pass through untouched."""
    out = []
    buf = []

    def flush():
        if buf:
            out.append(" ".join(buf))
            buf.clear()

    lines = text.splitlines()
    in_front = bool(lines) and lines[0].rstrip() == "---"
    in_fence = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if in_front:
            out.append(line)
            if i > 0 and stripped == "---":
                in_front = False
            continue
        if MD_FENCE_RE.match(line):
            flush()
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        is_block = (not stripped
                    or stripped.startswith(("#", ">", "|"))
                    or MD_BREAK_RE.fullmatch(stripped))
        if is_block:
            flush()
            out.append(line)
            continue
        if MD_LIST_RE.match(line):
            flush()
            buf.append(line.rstrip())
            continue
        buf.append(stripped if buf else line.rstrip())
    flush()
    return "\n".join(out) + "\n"


def preview_lines(body, width):
    """Body markdown → (kind, text) display rows wrapped to `width`.

    kind ∈ {"heading", "code", "text"}. Inline `code` spans keep their
    backticks — the draw side colors them in place, so wrapping stays a
    plain-text problem here."""
    rows = []
    in_fence = False
    for line in reflow_markdown(body).splitlines():
        stripped = line.strip()
        if MD_FENCE_RE.match(line):
            in_fence = not in_fence
            rows.append(("code", line[:width]))
            continue
        if in_fence:
            rows.append(("code", line[:width]))
            continue
        if stripped.startswith("#"):
            rows.append(("heading", stripped.lstrip("#").strip()[:width]))
            continue
        if not stripped:
            rows.append(("text", ""))
            continue
        bullet = MD_LIST_RE.match(line)
        if bullet and bullet.group(2):
            line = f"{bullet.group(1)}• {line[bullet.end():]}"
        indent = " " * (len(bullet.group(1)) + 2 if bullet else 0)
        for chunk in textwrap.wrap(line, width=max(8, width),
                                   subsequent_indent=indent):
            rows.append(("text", chunk))
    return rows


def open_in_pager(stdscr, path):
    """Suspend curses, open `path` in glow/$PAGER/less, restore curses.
    Shared between default tix (Enter) and mini (Enter). Same fallback chain.

    Glow gets reflowed markdown on stdin, word-wrapped at the live terminal
    width — overrides any narrower `width:` in glow.yml, which otherwise
    re-wraps hard-wrapped briefs into orphan fragments."""
    glow = shutil.which("glow")
    width = min(max(shutil.get_terminal_size().columns, 40), 120)
    curses.def_prog_mode()
    curses.endwin()
    try:
        if glow:
            try:
                text = reflow_markdown(
                    Path(path).read_text(encoding="utf-8", errors="replace"))
                subprocess.run([glow, "-p", "-w", str(width), "-"],
                               input=text.encode("utf-8"))
            except OSError:
                subprocess.run([glow, "-p", "-w", str(width), str(path)])
        else:
            subprocess.run([os.environ.get("PAGER", "less"), str(path)])
    except (OSError, subprocess.SubprocessError):
        pass
    curses.reset_prog_mode()
    if stdscr is not None:
        stdscr.refresh()


def run_pickup_git_sync():
    """Best-effort fetch+ff main before spawning `wt`.

    Empty/new repos have an unborn HEAD and often no origin/main yet; pickup must
    still work there, so skip the sync unless both local HEAD and origin/main are
    valid revisions. Keep git noise out of the suspended curses screen.
    """
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    subprocess.run(["git", "fetch", "--quiet", "origin"], **quiet)

    has_head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], **quiet
    ).returncode == 0
    has_origin_main = subprocess.run(
        ["git", "rev-parse", "--verify", "refs/remotes/origin/main"], **quiet
    ).returncode == 0
    has_local_main = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/main"], **quiet
    ).returncode == 0
    if not (has_head and has_origin_main and has_local_main):
        return

    checkout = subprocess.run(["git", "checkout", "main"], **quiet)
    if checkout.returncode == 0:
        subprocess.run(["git", "merge", "--ff-only", "origin/main"], **quiet)


def pickup_ticket(stdscr, ticket):
    """Suspend curses, fetch+ff main, spawn `wt <slug>`, restore curses.
    Writes status=active on the ticket brief. Shared between default tix (`p`)
    and mini (`p`)."""
    wt = shutil.which("wt") or "wt"
    curses.def_prog_mode()
    curses.endwin()
    try:
        in_repo = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        if in_repo.returncode != 0:
            print("tix: cwd is not a git repo — run tix from a repo root.")
            input("press enter to return…")
        else:
            write_status(ticket.path, "active")
            ticket.status = "active"
            run_pickup_git_sync()
            subprocess.run([wt, ticket.slug], env=pickup_env(ticket))
    except (OSError, subprocess.SubprocessError):
        pass
    curses.reset_prog_mode()
    if stdscr is not None:
        stdscr.refresh()


class App:
    def __init__(self):
        self.tickets = load_tickets()
        self.collapsed = set()
        self.filter_idx = 0
        self.query = ""
        self.search_mode = False
        # move_mode is None or the Ticket awaiting an area pick from the footer
        # minibuffer (`m` enters; 1-N commits; esc cancels).
        self.move_mode = None
        # label_mode is None or the Ticket awaiting free-text label input.
        self.label_mode = None
        self.label_buffer = ""
        # sort_pick_idx is None outside the sort picker; while picking, holds the
        # candidate index into SORT_MODES (↑↓ adjusts, ⏎ commits, esc cancels).
        self.sort_mode = "priority"
        self.sort_pick_idx = None
        self.sel = 0
        self.top = 0
        self.colors = {}
        self._dir_sig = dir_signature()
        self.lanes = load_lanes()
        self.rebuild()

    # ---- data ---------------------------------------------------------
    def sort_within_group(self, tickets):
        if self.sort_mode == "created":
            # Newest first. Negate the epoch so missing-created (0.0) sinks.
            return sorted(tickets, key=lambda t: (-t.created, t.id))
        return sorted(tickets, key=lambda t: (
            PRIORITY_META.get(t.priority, (PRIORITY_DEFAULT_RANK, None))[0],
            t.meta[2],
            t.id,
        ))

    def rebuild(self):
        by_group = {}
        for t in self.tickets:
            by_group.setdefault(t.group, []).append(t)
        for g in by_group:
            by_group[g] = self.sort_within_group(by_group[g])
        self.by_group = by_group
        self.groups = sorted(by_group, key=group_sort_key)
        # group_meta[g] = (is_epic_group, area). Epic groups live one level deeper
        # than area groups, so we prefix the header with the area path for context.
        self.group_meta = {}
        for g, ts in by_group.items():
            epic_t = next((t for t in ts if t.is_epic), None)
            if epic_t:
                parents = epic_t.path.parents
                area = parents[1].name if len(parents) >= 2 else ""
                self.group_meta[g] = (True, area)
            else:
                self.group_meta[g] = (False, "")
        present = [s for s in FILTER_ORDER
                   if any(filter_chip(t.status) == s for t in self.tickets)]
        self.filters = ["All"] + present
        if self.filter_idx >= len(self.filters):
            self.filter_idx = 0
        self.rebuild_rows()

    def passes(self, t):
        f = self.filters[self.filter_idx]
        chip = filter_chip(t.status)
        # Cancelled + done tickets are hidden from every view except their
        # explicit filter chip — the working list is for in-flight work.
        if chip == "cancelled" and f != "cancelled":
            return False
        if chip == "done" and f != "done":
            return False
        if f != "All" and chip != f:
            return False
        if self.query:
            q = self.query.lower()
            hay = (t.id + " " + t.title + " " + t.group + " " + t.area + " " + t.label).lower()
            if q not in hay:
                return False
        return True

    def rebuild_rows(self):
        rows = []
        for g in self.groups:
            visible = [t for t in self.by_group[g] if self.passes(t)]
            if not visible:
                continue
            rows.append({"type": "group", "group": g,
                         "count": len(visible), "total": len(self.by_group[g])})
            if g not in self.collapsed:
                for t in visible:
                    rows.append({"type": "ticket", "ticket": t})
        self.rows = rows
        if self.sel >= len(rows):
            self.sel = max(0, len(rows) - 1)

    # ---- colors -------------------------------------------------------
    def init_colors(self):
        if not curses.has_colors():
            return
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
            "group": curses.COLOR_WHITE,
            "accent": curses.COLOR_CYAN,
            "code": curses.COLOR_RED,
            "p0": curses.COLOR_RED,
            "p1": curses.COLOR_YELLOW,
            "p2": curses.COLOR_CYAN,
            "p3": curses.COLOR_BLUE,
        }
        for i, (name, fg) in enumerate(spec.items(), start=1):
            try:
                curses.init_pair(i, fg, -1)
            except curses.error:
                curses.init_pair(i, fg, curses.COLOR_BLACK)
            self.colors[name] = curses.color_pair(i)

    def attr(self, name, extra=0):
        return self.colors.get(name, 0) | extra

    # ---- rendering ----------------------------------------------------
    @staticmethod
    def _put(win, y, x, text, attr=0, maxx=None):
        if y < 0:
            return
        h, w = win.getmaxyx()
        if y >= h or x >= w:
            return
        limit = w if maxx is None else min(w, maxx)
        text = text[: max(0, limit - x)]
        if not text:
            return
        try:
            win.addstr(y, x, text, attr)
        except curses.error:
            pass

    def panes(self, w):
        """Return (list_w, preview_w). preview_w == 0 means hidden — the list
        gets the full width back on narrow terminals."""
        if w < LIST_MIN_W + PREVIEW_MIN_W + 1:
            return w, 0
        list_w = max(LIST_MIN_W, int(w * 0.48))
        preview_w = w - list_w - 1
        if preview_w < PREVIEW_MIN_W:
            list_w = w - PREVIEW_MIN_W - 1
            preview_w = PREVIEW_MIN_W
        return list_w, preview_w

    def draw(self, stdscr):
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        self.draw_header(stdscr, w)
        body_h = max(0, h - 2)
        self.clamp_viewport(body_h)
        list_w, preview_w = self.panes(w)
        for i in range(body_h):
            idx = self.top + i
            if idx >= len(self.rows):
                break
            self.draw_row(stdscr, 1 + i, list_w, idx, self.rows[idx])
        if preview_w > 0:
            sep_x = list_w
            sep_attr = self.attr("muted", curses.A_DIM)
            for i in range(body_h):
                self._put(stdscr, 1 + i, sep_x, "│", sep_attr)
            self.draw_preview(stdscr, sep_x + 2, 1, preview_w - 2, body_h)
        self.draw_footer(stdscr, h, w)
        stdscr.refresh()

    def draw_preview(self, stdscr, x0, y0, w, h):
        if w <= 0 or h <= 0:
            return
        row = self.current()
        if not row:
            return
        if row["type"] == "group":
            is_epic_g, area = self.group_meta.get(row["group"], (False, ""))
            heading = f"{area} / {row['group']}" if is_epic_g and area else row["group"]
            kind = "epic group" if is_epic_g else "area group"
            self._put(stdscr, y0, x0, heading[:w], self.attr("accent", curses.A_BOLD), maxx=x0 + w)
            sub = f"{row['count']}/{row['total']} tickets · {kind}"
            self._put(stdscr, y0 + 1, x0, sub[:w], self.attr("muted", curses.A_DIM), maxx=x0 + w)
            return

        t = row["ticket"]
        y = y0
        # Title — bold, single line, truncated.
        self._put(stdscr, y, x0, t.title[:w], curses.A_BOLD, maxx=x0 + w)
        y += 1
        # Pickup slug — exact arg for `wt`/`/pickup`. Surfaces what `p` will run.
        if y - y0 < h:
            self._put(stdscr, y, x0, f"pickup: wt {t.slug} → {pickup_agent_label(t.path)}"[:w],
                      self.attr("accent", curses.A_DIM), maxx=x0 + w)
            y += 1
        meta_bits = [b for b in (t.area, t.status, t.priority, f"#{t.label}" if t.label else "") if b]
        if meta_bits:
            color = t.meta[1] if not t.is_epic else "accent"
            self._put(stdscr, y, x0, (" · ".join(meta_bits))[:w],
                      self.attr(color), maxx=x0 + w)
            y += 1
        kv = []
        if t.id and t.id != t.slug:
            kv.append(("id", t.id))
        if t.epic:
            kv.append(("epic", t.epic))
        if t.linear:
            kv.append(("linear", t.linear))
        created_iso = format_created(t.created)
        if created_iso:
            age = relative_age(t.created)
            kv.append(("created", f"{created_iso} ({age} ago)" if age else created_iso))
        for key, val in kv:
            if y - y0 >= h:
                break
            line = f"{key}: {val}"
            self._put(stdscr, y, x0, line[:w], self.attr("muted", curses.A_DIM),
                      maxx=x0 + w)
            y += 1
        # In-progress block: only for tickets the reconciler marked `active`.
        # Sidecar lookup is O(1); agent-state is one tiny file read per draw.
        if t.status == "active" and t.slug in self.lanes and y - y0 < h:
            lane = self.lanes[t.slug]
            y += 1
            if y - y0 >= h:
                return
            self._put(stdscr, y, x0, "── lane ─────────────"[:w],
                      self.attr("muted", curses.A_DIM), maxx=x0 + w)
            y += 1
            wt_path = lane.get("path", "")
            home = str(Path.home())
            rel = wt_path.replace(home, "~", 1) if wt_path.startswith(home) else wt_path
            for label, val, color in (
                ("path",   rel, "muted"),
                ("branch", lane.get("branch", ""), "muted"),
            ):
                if not val or y - y0 >= h:
                    continue
                self._put(stdscr, y, x0, f"{label}: {val}"[:w],
                          self.attr(color, curses.A_DIM), maxx=x0 + w)
                y += 1
            state = read_agent_state(wt_path)
            if state and y - y0 < h:
                self._put(stdscr, y, x0, f"state: {state}"[:w],
                          self.attr(agent_state_color(state), curses.A_BOLD),
                          maxx=x0 + w)
                y += 1
            last = lane.get("last_commit", "")
            if last and y - y0 < h:
                self._put(stdscr, y, x0, f"last: {last}"[:w],
                          self.attr("muted"), maxx=x0 + w)
                y += 1
        if y - y0 >= h:
            return
        # Visual gap before body.
        y += 1
        body_rows = preview_lines(t.body(), w) or [("text", "(empty)")]
        code_attr = self.attr("code")
        in_span = False
        for kind, text in body_rows:
            if y - y0 >= h:
                break
            if kind == "heading":
                self._put(stdscr, y, x0, text, self.attr("accent", curses.A_BOLD),
                          maxx=x0 + w)
            elif kind == "code":
                self._put(stdscr, y, x0, text, code_attr, maxx=x0 + w)
            else:
                in_span = self._put_spans(stdscr, y, x0, text, w,
                                          code_attr, in_span)
            y += 1

    def _put_spans(self, stdscr, y, x0, text, w, code_attr, in_span):
        """Draw a text row, coloring `inline code` spans (backticks kept so
        column math stays trivial). Returns span parity at end of row — a
        span wrapped mid-line keeps its color on the next row."""
        x = x0
        limit = x0 + w
        for i, seg in enumerate(text.split("`")):
            if i:
                self._put(stdscr, y, x, "`", code_attr, maxx=limit)
                x += 1
                in_span = not in_span
            if seg:
                self._put(stdscr, y, x, seg,
                          code_attr if in_span else 0, maxx=limit)
                x += len(seg)
        return in_span

    def draw_header(self, stdscr, w):
        x = 0
        self._put(stdscr, 0, x, " tix ", self.attr("accent", curses.A_REVERSE | curses.A_BOLD))
        x += 6
        for i, f in enumerate(self.filters):
            label = f" {f} "
            if i == self.filter_idx:
                self._put(stdscr, 0, x, label, curses.A_REVERSE | curses.A_BOLD)
            else:
                self._put(stdscr, 0, x, label, curses.A_DIM)
            x += len(label) + 1
        matched = sum(1 for t in self.tickets if self.passes(t))
        total = len(self.tickets)
        summary = f"{matched}/{total} tickets"
        self._put(stdscr, 0, max(x, w - len(summary) - 1), summary, self.attr("accent"))

    def draw_row(self, stdscr, y, w, idx, row):
        selected = idx == self.sel
        if row["type"] == "group":
            arrow = "▶" if row["group"] in self.collapsed else "▼"
            is_epic_g, area = self.group_meta.get(row["group"], (False, ""))
            if is_epic_g and area:
                text = f"{arrow} {area} / {row['group']}  (epic)"
            else:
                text = f"{arrow} {row['group']}"
            count = f"({row['count']}/{row['total']})"
            attr = curses.A_BOLD | (curses.A_REVERSE if selected else 0)
            if selected:
                self._put(stdscr, y, 0, " " * (w - 1), curses.A_REVERSE, maxx=w)
            self._put(stdscr, y, 0, text, attr, maxx=w)
            self._put(stdscr, y, max(0, w - len(count) - 1), count,
                      attr if selected else self.attr("muted", curses.A_DIM),
                      maxx=w)
            return

        t = row["ticket"]
        icon, color, _ = t.meta
        status = t.status
        # Legacy tickets get a `~` marker; slugs are wider than Linear ids.
        disp_id = (t.id + "~") if t.legacy else t.id
        id_col = f"{disp_id[:13]:<13}"
        prio_tag = t.priority if t.priority in PRIORITY_META else "  "
        prio_color = PRIORITY_META.get(t.priority, (None, "muted"))[1]
        age = relative_age(t.created)
        age_pad = f"{age:>4}"  # fixed-width so the status column stays aligned
        label_tag = f"#{t.label[:16]}" if t.label else ""
        # Right-aligned layout: status flush right, then age, then label.
        status_x = max(0, w - len(status) - 1)
        age_x = max(0, status_x - len(age_pad) - 1)
        title_x = 7 + len(id_col) + 1
        label_x = age_x - len(label_tag) - 1 if label_tag else age_x
        if label_tag and label_x <= title_x:
            label_tag = ""
            label_x = age_x
        avail = max(0, label_x - title_x - 1)
        if selected:
            self._put(stdscr, y, 0, " " * (w - 1), curses.A_REVERSE, maxx=w)
            base = curses.A_REVERSE
            self._put(stdscr, y, 2, icon, base | curses.A_BOLD, maxx=w)
            self._put(stdscr, y, 4, f"{prio_tag:<2}",
                      base | curses.A_BOLD, maxx=w)
            self._put(stdscr, y, 7, id_col, base | curses.A_BOLD, maxx=w)
            self._put(stdscr, y, title_x, t.title[:avail], base, maxx=w)
            if label_tag:
                self._put(stdscr, y, label_x, label_tag, base | curses.A_DIM, maxx=w)
            self._put(stdscr, y, age_x, age_pad, base | curses.A_DIM, maxx=w)
            self._put(stdscr, y, status_x, status,
                      base | curses.A_DIM, maxx=w)
        else:
            self._put(stdscr, y, 2, icon, self.attr(color, curses.A_BOLD), maxx=w)
            self._put(stdscr, y, 4, f"{prio_tag:<2}",
                      self.attr(prio_color, curses.A_BOLD), maxx=w)
            self._put(stdscr, y, 7, id_col, curses.A_DIM, maxx=w)
            self._put(stdscr, y, title_x, t.title[:avail], maxx=w)
            if label_tag:
                self._put(stdscr, y, label_x, label_tag,
                          self.attr("accent", curses.A_DIM), maxx=w)
            self._put(stdscr, y, age_x, age_pad,
                      self.attr("muted", curses.A_DIM), maxx=w)
            self._put(stdscr, y, status_x, status,
                      self.attr(color), maxx=w)

    def draw_footer(self, stdscr, h, w):
        y = h - 1
        if self.move_mode is not None:
            items = "  ".join(f"{i+1}) {a}" for i, a in enumerate(AREAS))
            text = f" move `{self.move_mode.slug}` → {items}   esc cancel "
            self._put(stdscr, y, 0, " " * (w - 1), curses.A_REVERSE)
            self._put(stdscr, y, 0, text[:w],
                      self.attr("accent", curses.A_REVERSE | curses.A_BOLD))
            return
        if self.label_mode is not None:
            prompt = f" label `{self.label_mode.slug}`: {self.label_buffer}"
            self._put(stdscr, y, 0, " " * (w - 1), curses.A_REVERSE)
            self._put(stdscr, y, 0, prompt[:w], curses.A_REVERSE)
            try:
                stdscr.move(y, min(len(prompt), w - 1))
            except curses.error:
                pass
            return
        if self.sort_pick_idx is not None:
            self._put(stdscr, y, 0, " " * (w - 1), curses.A_REVERSE)
            self._put(stdscr, y, 0, " sort: ",
                      self.attr("accent", curses.A_REVERSE | curses.A_BOLD))
            x = 7
            for i, mode in enumerate(SORT_MODES):
                label = SORT_LABELS.get(mode, mode)
                token = f"[{label}]" if i == self.sort_pick_idx else f" {label} "
                attr = (self.attr("accent", curses.A_REVERSE | curses.A_BOLD)
                        if i == self.sort_pick_idx
                        else curses.A_REVERSE | curses.A_DIM)
                self._put(stdscr, y, x, token, attr, maxx=w)
                x += len(token) + 1
            hint = "  ↑↓ select · ⏎ apply · esc cancel "
            self._put(stdscr, y, max(x, w - len(hint) - 1), hint,
                      curses.A_REVERSE | curses.A_DIM, maxx=w)
            return
        if self.search_mode:
            prompt = f"/{self.query}"
            self._put(stdscr, y, 0, " " * (w - 1), curses.A_REVERSE)
            self._put(stdscr, y, 0, prompt, curses.A_REVERSE)
            try:
                stdscr.move(y, min(len(prompt), w - 1))
            except curses.error:
                pass
            return
        sort_label = SORT_LABELS.get(self.sort_mode, self.sort_mode)
        hints = (f"⏎ open · p pickup · e edit · R rescope · n new · l label · m move · "
                 f"+/− prio · i wip · d done · x cancel · s sort({sort_label}) "
                 f"· ? help · q quit")
        if self.query:
            hints = f"filter:/{self.query}   " + hints
        self._put(stdscr, y, 0, hints, self.attr("muted", curses.A_DIM))

    # ---- viewport -----------------------------------------------------
    def clamp_viewport(self, body_h):
        if body_h <= 0:
            return
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + body_h:
            self.top = self.sel - body_h + 1
        self.top = max(0, min(self.top, max(0, len(self.rows) - body_h)))

    def move(self, delta, body_h):
        if not self.rows:
            return
        self.sel = max(0, min(len(self.rows) - 1, self.sel + delta))

    # ---- actions ------------------------------------------------------
    def current(self):
        if 0 <= self.sel < len(self.rows):
            return self.rows[self.sel]
        return None

    def toggle_group(self, name):
        if name in self.collapsed:
            self.collapsed.discard(name)
        else:
            self.collapsed.add(name)
        self.rebuild_rows()

    def toggle_all(self):
        if len(self.collapsed) < len(self.groups):
            self.collapsed = set(self.groups)
        else:
            self.collapsed.clear()
        self.rebuild_rows()

    def show_help(self, stdscr):
        pager = shutil.which("less") or os.environ.get("PAGER", "less")
        fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="tix-help-")
        os.close(fd)
        tmp_path = Path(tmp)
        try:
            tmp_path.write_text(HELP_TEXT, encoding="utf-8")
            curses.def_prog_mode()
            curses.endwin()
            try:
                subprocess.run([pager, str(tmp_path)])
            except OSError:
                pass
            curses.reset_prog_mode()
            stdscr.refresh()
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def open_ticket(self, stdscr, ticket):
        open_in_pager(stdscr, ticket.path)

    def open_url(self, ticket):
        if not ticket.url:
            return
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        if not shutil.which(opener):
            return
        try:
            subprocess.Popen([opener, ticket.url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def reload(self):
        keep = self.selected_path()
        self.tickets = load_tickets()
        self.lanes = load_lanes()
        self._dir_sig = dir_signature()
        self.rebuild()
        if keep:
            self.reselect_path(keep)

    def selected_path(self):
        row = self.current()
        if row and row["type"] == "ticket":
            return row["ticket"].path
        return None

    def reselect_path(self, path):
        for i, row in enumerate(self.rows):
            if row["type"] == "ticket" and row["ticket"].path == path:
                self.sel = i
                return

    # ---- external dispatch -------------------------------------------
    @staticmethod
    def in_tmux():
        return bool(os.environ.get("TMUX"))

    def run_external(self, stdscr, argv, name=None):
        """Run an external command. In tmux: spawn a new window so tix keeps
        running. Otherwise: suspend curses, run in the foreground, restore.
        argv is a list — no shell interpolation, free-text safe."""
        if self.in_tmux() and shutil.which("tmux"):
            quoted = " ".join(shlex.quote(a) for a in argv)
            cmd = ["tmux", "new-window"]
            if name:
                cmd += ["-n", name]
            cmd.append(quoted)
            try:
                subprocess.run(cmd, check=False)
            except OSError:
                pass
            return
        curses.def_prog_mode()
        curses.endwin()
        try:
            subprocess.run(argv)
        except OSError:
            pass
        curses.reset_prog_mode()
        stdscr.refresh()

    def capture_buffer(self, stdscr, seed=""):
        """Open $EDITOR on a tmpfile (pre-seeded). Return stripped contents.
        Empty string = user cleared / aborted — caller should noop."""
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix="tix-")
        os.close(fd)
        tmp = Path(tmp_path)
        try:
            if seed:
                tmp.write_text(seed, encoding="utf-8")
            curses.def_prog_mode()
            curses.endwin()
            try:
                subprocess.run([editor, str(tmp)])
            except OSError:
                pass
            curses.reset_prog_mode()
            stdscr.refresh()
            try:
                return tmp.read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass

    # ---- ticket actions ----------------------------------------------
    def pickup_ticket(self, stdscr, ticket):
        path = ticket.path
        pickup_ticket(stdscr, ticket)
        self.rebuild()
        self.reselect_path(path)

    def edit_brief(self, stdscr, ticket):
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        curses.def_prog_mode()
        curses.endwin()
        try:
            subprocess.run([editor, str(ticket.path)])
        except OSError:
            pass
        curses.reset_prog_mode()
        stdscr.refresh()
        self.reload()

    def rescope_ticket(self, stdscr, ticket):
        seed = (f"# Rescope notes for `{ticket.slug}` — claude reads everything below.\n"
                f"# Lines beginning with # are passed through; delete them if you don't\n"
                f"# want them sent. Save & quit to dispatch, or leave empty to cancel.\n\n")
        text = self.capture_buffer(stdscr, seed=seed)
        if not text:
            return
        prompt = f"/rescope {ticket.slug} {text}"
        self.run_external(stdscr, claude_argv(prompt), name=f"rescope:{ticket.slug[:10]}")

    def new_ticket(self, stdscr, seed=""):
        if not seed:
            seed = ("# New ticket — describe the problem. Claude will run /scope on this\n"
                    "# text: it'll ask up to 3 clarifying questions, then engineer the brief.\n"
                    "# Save & quit to dispatch, or leave empty to cancel.\n\n")
        text = self.capture_buffer(stdscr, seed=seed)
        if not text:
            return
        prompt = f"/scope {text}"
        self.run_external(stdscr, claude_argv(prompt), name="scope")

    def new_from_clipboard(self, stdscr):
        clip = ""
        clip_cmd = "pbpaste" if sys.platform == "darwin" else "xclip"
        if shutil.which(clip_cmd):
            args = [clip_cmd] if clip_cmd == "pbpaste" else [clip_cmd, "-o", "-selection", "clipboard"]
            try:
                clip = subprocess.run(args, capture_output=True, text=True,
                                      timeout=5).stdout
            except (OSError, subprocess.SubprocessError):
                clip = ""
        seed = ("# New ticket from clipboard paste (Granola, notes, etc).\n"
                "# Trim or annotate — claude will /scope this. Empty = cancel.\n\n")
        seed += clip
        self.new_ticket(stdscr, seed=seed)

    def toggle_cancel(self, ticket):
        """Flip cancelled ↔ open in place — no confirm prompt. Cancelled is
        sticky in the reconciler, so the write survives subsequent syncs."""
        new_status = "open" if ticket.status in CANCELLED_STATUSES else "cancelled"
        write_status(ticket.path, new_status)
        ticket.status = new_status
        path = ticket.path
        self.rebuild()
        self.reselect_path(path)

    def move_ticket(self, ticket, new_area):
        """Move a single area-level brief to a different area folder. Uses
        `git mv` when the tree is a git repo so history follows; falls back
        to plain rename when it isn't. Also rewrites the stored `area:`
        frontmatter so it matches the new location."""
        if ticket.area == new_area:
            return
        src = ticket.path
        dest_dir = TICKETS_DIR / new_area
        dest = dest_dir / src.name
        if dest.exists():
            return  # slug collision in target area — bail rather than clobber
        dest_dir.mkdir(parents=True, exist_ok=True)
        moved = False
        try:
            result = subprocess.run(
                ["git", "-C", str(TICKETS_DIR), "mv",
                 str(src.relative_to(TICKETS_DIR)),
                 str(dest.relative_to(TICKETS_DIR))],
                capture_output=True, text=True, timeout=10,
            )
            moved = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            moved = False
        if not moved:
            try:
                src.rename(dest)
                moved = True
            except OSError:
                return
        write_frontmatter_field(dest, "area", new_area)
        self.reload()
        self.reselect_path(dest)

    def toggle_done(self, ticket):
        """Flip done ↔ open in place. Sticky in the reconciler so a manual
        mark survives even without a merged PR — useful for spikes, ops, or
        research tickets whose 'completion' has no PR signal."""
        new_status = "open" if ticket.status.lower() in DONE_STATUSES else "done"
        write_status(ticket.path, new_status)
        ticket.status = new_status
        path = ticket.path
        self.rebuild()
        self.reselect_path(path)

    def toggle_inprogress(self, ticket):
        """Flip active ↔ open in place. Sticky in the reconciler so a manual
        mark survives without a live worktree — useful when work is happening
        outside a `wt` lane (direct branch checkout, paired work, etc)."""
        new_status = "open" if ticket.status.lower() == "active" else "active"
        write_status(ticket.path, new_status)
        ticket.status = new_status
        path = ticket.path
        self.rebuild()
        self.reselect_path(path)

    def set_label(self, ticket, label):
        label = label.strip()
        write_label(ticket.path, label)
        ticket.label = label
        path = ticket.path
        self.rebuild()
        self.reselect_path(path)

    def bump_priority(self, ticket, delta):
        """delta > 0 raises priority (toward P0); delta < 0 lowers it toward
        cleared. Writes frontmatter, then rebuilds so the new sort takes."""
        seq = [""] + PRIORITY_ORDER
        idx = (PRIORITY_ORDER.index(ticket.priority) + 1
               if ticket.priority in PRIORITY_ORDER else 0)
        new_idx = max(0, min(len(seq) - 1, idx - delta))
        new_pri = seq[new_idx]
        if new_pri == ticket.priority:
            return
        write_priority(ticket.path, new_pri)
        ticket.priority = new_pri
        path = ticket.path
        self.rebuild()
        self.reselect_path(path)

    # ---- main loop ----------------------------------------------------
    def run(self, stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        # 2 s idle timeout so getch() periodically returns -1 even with no
        # keystroke — we use that tick to detect external writes (claude /scope
        # finishing in a tmux window, sync.py running, hand edits) and reload.
        stdscr.timeout(2000)
        self.init_colors()
        while True:
            h, _ = stdscr.getmaxyx()
            body_h = max(1, h - 2)
            curses.curs_set(1 if self.search_mode or self.label_mode is not None else 0)
            self.draw(stdscr)
            ch = stdscr.getch()
            if ch == -1:
                new_sig = dir_signature()
                if new_sig != self._dir_sig:
                    self.reload()
                continue
            if self.label_mode is not None:
                if ch == 27:  # esc — cancel
                    self.label_mode = None
                    self.label_buffer = ""
                elif ch in (curses.KEY_ENTER, 10, 13):
                    ticket = self.label_mode
                    label = self.label_buffer
                    self.label_mode = None
                    self.label_buffer = ""
                    self.set_label(ticket, label)
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    self.label_buffer = self.label_buffer[:-1]
                elif 32 <= ch < 127:
                    self.label_buffer += chr(ch)
                continue
            if self.move_mode is not None:
                ticket = self.move_mode
                if ch == 27:  # esc — cancel
                    self.move_mode = None
                elif ord("1") <= ch <= ord("9"):
                    idx = ch - ord("1")
                    self.move_mode = None
                    if idx < len(AREAS):
                        self.move_ticket(ticket, AREAS[idx])
                continue
            if self.sort_pick_idx is not None:
                if ch == 27:  # esc — cancel
                    self.sort_pick_idx = None
                elif ch in (curses.KEY_UP, ord("k"), curses.KEY_LEFT, ord("h")):
                    self.sort_pick_idx = (self.sort_pick_idx - 1) % len(SORT_MODES)
                elif ch in (curses.KEY_DOWN, ord("j"), curses.KEY_RIGHT, ord("l"),
                            ord("\t")):
                    self.sort_pick_idx = (self.sort_pick_idx + 1) % len(SORT_MODES)
                elif ch in (curses.KEY_ENTER, 10, 13):
                    new_mode = SORT_MODES[self.sort_pick_idx]
                    self.sort_pick_idx = None
                    if new_mode != self.sort_mode:
                        keep = self.selected_path()
                        self.sort_mode = new_mode
                        self.rebuild()
                        if keep:
                            self.reselect_path(keep)
                continue
            if self.search_mode:
                self.handle_search_key(ch)
                continue
            if ch in (ord("q"), 27):
                return
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.move(1, body_h)
            elif ch in (curses.KEY_UP, ord("k")):
                self.move(-1, body_h)
            elif ch == curses.KEY_NPAGE or ch == 4:  # PgDn / Ctrl-D
                self.move(body_h // 2 if ch == 4 else body_h, body_h)
            elif ch == curses.KEY_PPAGE or ch == 21:  # PgUp / Ctrl-U
                self.move(-(body_h // 2) if ch == 21 else -body_h, body_h)
            elif ch == ord("g"):
                self.sel = 0
            elif ch == ord("G"):
                self.sel = max(0, len(self.rows) - 1)
            elif ch in (curses.KEY_ENTER, 10, 13, curses.KEY_RIGHT):
                self.activate(stdscr)
            elif ch == ord(" "):
                row = self.current()
                if row:
                    name = row["group"] if row["type"] == "group" else row["ticket"].group
                    self.toggle_group(name)
            elif ch in (curses.KEY_LEFT, ord("h")):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.toggle_group(row["ticket"].group)
                elif row and row["type"] == "group" and row["group"] not in self.collapsed:
                    self.toggle_group(row["group"])
            elif ch == ord("\t"):
                self.filter_idx = (self.filter_idx + 1) % len(self.filters)
                self.rebuild_rows()
            elif ch == curses.KEY_BTAB:
                self.filter_idx = (self.filter_idx - 1) % len(self.filters)
                self.rebuild_rows()
            elif ord("1") <= ch <= ord("9"):
                i = ch - ord("1")
                if i < len(self.filters):
                    self.filter_idx = i
                    self.rebuild_rows()
            elif ch == ord("/"):
                self.search_mode = True
            elif ch == ord("o"):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.open_url(row["ticket"])
            elif ch == ord("r"):
                self.reload()
            elif ch == ord("p"):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.pickup_ticket(stdscr, row["ticket"])
            elif ch == ord("e"):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.edit_brief(stdscr, row["ticket"])
            elif ch == ord("R"):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.rescope_ticket(stdscr, row["ticket"])
            elif ch == ord("n"):
                self.new_ticket(stdscr)
            elif ch == ord("N"):
                self.new_from_clipboard(stdscr)
            elif ch in (ord("+"), ord("=")):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.bump_priority(row["ticket"], 1)
            elif ch == ord("-"):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.bump_priority(row["ticket"], -1)
            elif ch == ord("x"):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.toggle_cancel(row["ticket"])
            elif ch == ord("d"):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.toggle_done(row["ticket"])
            elif ch == ord("i"):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.toggle_inprogress(row["ticket"])
            elif ch == ord("l"):
                row = self.current()
                if row and row["type"] == "ticket":
                    self.label_mode = row["ticket"]
                    self.label_buffer = row["ticket"].label
            elif ch == ord("m"):
                row = self.current()
                if row and row["type"] == "ticket":
                    t = row["ticket"]
                    # Only area-level briefs (parent is the area dir). Epic
                    # children stay with their epic; epic folders need their
                    # whole tree moved, which is out of scope for now.
                    if not t.is_epic and t.path.parent.parent == TICKETS_DIR:
                        self.move_mode = t
            elif ch == ord("s"):
                self.sort_pick_idx = (SORT_MODES.index(self.sort_mode)
                                      if self.sort_mode in SORT_MODES else 0)
            elif ch == ord("?"):
                self.show_help(stdscr)
            elif ch in (ord("C"), ord("z")):
                self.toggle_all()

    def activate(self, stdscr):
        row = self.current()
        if not row:
            return
        if row["type"] == "group":
            self.toggle_group(row["group"])
        else:
            self.open_ticket(stdscr, row["ticket"])

    def handle_search_key(self, ch):
        if ch in (27,):  # ESC — cancel
            self.search_mode = False
            self.query = ""
            self.rebuild_rows()
        elif ch in (curses.KEY_ENTER, 10, 13):  # commit
            self.search_mode = False
            self.rebuild_rows()
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.query = self.query[:-1]
            self.rebuild_rows()
        elif 32 <= ch < 127:
            self.query += chr(ch)
            self.rebuild_rows()


def run_preload_hook():
    """Run $TIX_PRELOAD_HOOK as a shell command before the TUI takes over.

    tix is a pure reader — it never writes `status:` frontmatter. Users who
    want status auto-derived (from worktrees, branches, merged PRs, etc.)
    point this env var at their own reconciler script. Output is captured:
    tix is about to claim the terminal with curses, so any printed diff
    would be wiped anyway. Best-effort — unset/missing/erroring hook never
    blocks launch."""
    hook = os.environ.get("TIX_PRELOAD_HOOK")
    if not hook:
        return
    try:
        subprocess.run(
            hook, shell=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def main():
    if not any(ticket_dir.is_dir() for ticket_dir in TICKET_DIRS):
        roots = ", ".join(str(ticket_dir) for ticket_dir in TICKET_DIRS)
        print(f"tix: no ticket directory at {roots}", file=sys.stderr)
        return 1
    run_preload_hook()
    app = App()
    if not app.tickets:
        roots = ", ".join(str(ticket_dir) for ticket_dir in TICKET_DIRS)
        print(f"tix: no tickets found under {roots}", file=sys.stderr)
        return 1
    curses.wrapper(app.run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
