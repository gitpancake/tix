# CLAUDE.md

## Project

`tix` is a keyboard-driven curses TUI over a tree of markdown ticket briefs. Stdlib-only Python. Two surfaces:

- `src/tix/tui.py` — curses reader. Renders, filters, navigates, pickups.
- `src/tix/sync.py` — the **sole writer** of `status:` frontmatter. Invoked by the TUI on launch and by external tools (e.g. `wt`).

The TUI shells out to `sync.py` as a subprocess so its stdout/stderr can't bleed onto the curses screen.

## Invariants

1. **One writer.** No code path outside `sync.py` mutates `status:` frontmatter. The TUI's `i`/`d`/`x` keys write *sticky pins* via `sync.py` calls — never direct writes.
2. **Stdlib-only.** No PyYAML, no `rich`, no `prompt_toolkit`. Adds startup latency we don't accept. Frontmatter parser is intentionally line-based; preserve that contract.
3. **Filename = slug.** Never derive a slug from frontmatter `id:` or filename munging. `path.stem` is authoritative.
4. **Filesystem = DB.** No `.tix-cache`, no SQLite, no JSON state beyond `active-lanes.json` (which is itself rebuilt every full sync and treated as cache).

## Status vocab (pinned)

`active`, `open`, `draft`, `done`, `cancelled`. Adding one requires changes in three places:

- `tui.py` → `STATUS_META`, `FILTER_ORDER`
- `sync.py` → `compute_status` derivation
- `docs/ticket-schema.md` → contract update

Pre-migration title-case variants (`In Progress`, `Todo`, etc.) are kept as read-only aliases — don't extend that set.

## Editing rules

- `tui.py` runs inside `curses.wrapper`. Anything that prints or raises can wreck the terminal. Wrap subprocess calls in `try/except (OSError, subprocess.SubprocessError)`.
- Status bar rendering is hot. Don't read filesystem inside the render loop — `App.rebuild_rows()` is the bulk-read step.
- `gh pr list` is the slowest call in sync. The full sweep already batches it; never call it per-ticket.
- `subprocess.run` w/ `wt`/`git`/`gh` returns are mostly best-effort. Keep them that way — surfacing transient failures into the TUI is worse than hiding them.

## Tests

Fixture-driven under `tests/fixtures/tickets/`. No network. `gh` is mocked by setting `PATH` to a stub. Run:

```bash
TICKETS_DIR=tests/fixtures/tickets python -m tix.sync
pytest
```

## Distribution

- PyPI distribution name: `tix-cli`. Import name + executable: `tix`.
- Console scripts: `tix` (TUI router), `tix-sync` (sync.py direct).
- No native deps. `pipx install tix-cli` is the recommended install.
- Templates ship in `src/tix/templates/` and are accessed via `importlib.resources` (or `tix.__file__`-relative paths) — never hardcode an install prefix.

## Org-specific bits to keep configurable

- `AREAS` in `tui.py` is currently a fixed list. **Don't hardcode org-specific area names** when extending — make it configurable via env or a config file before any new area lands.
- `LINEAR_WORKSPACE` is the only external-tracker breadcrumb. No GitHub Issues / Jira integration creep.

## Non-goals

- No remote sync.
- No mouse support.
- No realtime collab.
- No bundled markdown renderer — defer to `glow` / `$PAGER`.
