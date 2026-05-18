# CLAUDE.md

## Project

`tix` is a keyboard-driven curses TUI over a tree of markdown ticket briefs. Stdlib-only Python. Single surface:

- `src/tix/tui.py` — curses reader. Renders, filters, navigates, pickups.
- `src/tix/__main__.py` — CLI router (default → TUI; `tix <project>` → cd-and-set-TICKETS_DIR).

**tix is a pure reader.** It does not write `status:` frontmatter. Users who want status auto-derived wire up their own script via `TIX_PRELOAD_HOOK`. That contract is load-bearing — do not bundle a reconciler.

## Invariants

1. **No status writes from tix.** `i`/`d`/`x` sticky pins are the only mutation path, and even those just edit the ticket file's frontmatter directly — they never derive state from external signals.
2. **Stdlib-only.** No PyYAML, no `rich`, no `prompt_toolkit`. Adds startup latency we don't accept. Frontmatter parser is intentionally line-based; preserve that contract.
3. **Filename = slug.** Never derive a slug from frontmatter `id:` or filename munging. `path.stem` is authoritative.
4. **Filesystem = DB.** No `.tix-cache`, no SQLite. `ACTIVE_LANES_FILE` is an *optional read-only* sidecar — tix consumes it if present (a preload hook might populate it) but never writes it itself.

## Status vocab (pinned)

`active`, `open`, `draft`, `done`, `cancelled`. Adding one requires changes in two places:

- `tui.py` → `STATUS_META`, `FILTER_ORDER`
- `docs/ticket-schema.md` → contract update

Pre-migration title-case variants (`In Progress`, `Todo`, etc.) are kept as read-only aliases — don't extend that set.

## TICKETS_DIR resolution

Order: `$TICKETS_DIR` (explicit) → `~/.claude/tickets` (fallback). No project-local autodiscovery. The `tix <project>` form is sugar that does `chdir` + sets `TICKETS_DIR` to `<project>/.claude/tickets` before the TUI imports.

## Preload hook

`run_preload_hook()` reads `TIX_PRELOAD_HOOK` and runs it as a shell command before curses takes over. Output is captured. Failures are swallowed. This is the only extension point tix exposes — keep it minimal. Do not add an "after" hook or per-action hooks; users with that level of need should fork.

## Editing rules

- `tui.py` runs inside `curses.wrapper`. Anything that prints or raises can wreck the terminal. Wrap subprocess calls in `try/except (OSError, subprocess.SubprocessError)`.
- Status bar rendering is hot. Don't read filesystem inside the render loop — `App.rebuild_rows()` is the bulk-read step.
- `subprocess.run` w/ `wt`/`git` returns are mostly best-effort. Keep them that way — surfacing transient failures into the TUI is worse than hiding them.

## Tests

Fixture-driven under `tests/fixtures/tickets/`. No network. Run:

```bash
pytest -q
```

## Distribution

- PyPI distribution name: `tix-cli`. Import name + executable: `tix`.
- One console script: `tix`.
- No native deps. `pipx install tix-cli` is the recommended install.
- Templates ship in `src/tix/templates/` and are accessed via `importlib.resources` (or `tix.__file__`-relative paths) — never hardcode an install prefix.

## Org-specific bits to keep configurable

- `AREAS` in `tui.py` is currently a fixed list. **Don't hardcode org-specific area names** when extending — make it configurable via env or a config file before any new area lands.
- `LINEAR_WORKSPACE` is the only external-tracker breadcrumb. No GitHub Issues / Jira integration creep — that belongs in a preload hook.

## Non-goals

- No remote sync.
- No mouse support.
- No realtime collab.
- No bundled markdown renderer — defer to `glow` / `$PAGER`.
- No bundled status reconciler — defer to `TIX_PRELOAD_HOOK`.
