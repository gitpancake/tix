# CLAUDE.md

## Project

`tix` is a keyboard-driven curses TUI over a tree of markdown ticket briefs. Stdlib-only Python. Single surface:

- `src/tix/tui.py` — curses reader. Renders, filters, navigates, pickups.
- `src/tix/__main__.py` — CLI router (default → TUI; `tix <project>` → resolve `~/.pi/agent/tickets/<project>/` as primary when present, include legacy `~/.claude/tickets/<project>/` / repo-local `.claude/tickets/` as extra read roots when present; sets `TICKETS_DIR`/`TIX_EXTRA_TICKETS_DIRS` before the TUI imports).

**tix is a pure reader.** It does not write `status:` frontmatter. Users who want status auto-derived wire up their own script via `TIX_PRELOAD_HOOK`. That contract is load-bearing — do not bundle a reconciler.

## Invariants

1. **No *derived* status writes from tix.** The only frontmatter mutations are direct user actions: `i`/`d`/`x` sticky pins and `p` pickup (writes `active`). None of these derive state from external signals — that stays the reconciler's job (`TIX_PRELOAD_HOOK`). Don't add filesystem/git inspection to tix's write paths.
2. **Stdlib-only.** No PyYAML, no `rich`, no `prompt_toolkit`. Adds startup latency we don't accept. Frontmatter parser is intentionally line-based; preserve that contract.
3. **Filename = slug.** Never derive a slug from frontmatter `id:` or filename munging. `path.stem` is authoritative.
4. **Filesystem = DB.** No `.tix-cache`, no SQLite. `ACTIVE_LANES_FILE` is an *optional read-only* sidecar — tix consumes it if present (a preload hook might populate it) but never writes it itself.
5. **Claude dispatch goes through `claude_argv()`.** `R` rescope / `n`,`N` new all hand off to interactive claude via `claude_argv(prompt)`, which defaults to `claude --dangerously-skip-permissions` (parity with `p` pickup, whose `wt` lane runs the same bypass). `WT_CLAUDE` overrides binary+flags — same env var `wt` honors. Don't reintroduce a bare `["claude", prompt]`: it drops the user into a permission-prompting session, breaking parity with pickup.
6. **Pickup uses the ticket's owning root.** When a ticket was loaded from `TIX_EXTRA_TICKETS_DIRS`, `p` must pass that root as `TICKETS_DIR` to `wt`; otherwise `wt <slug>` creates a lane with no brief and Pi starts with no kickoff prompt.

## Status vocab (pinned)

`active`, `open`, `draft`, `done`, `cancelled`. Adding one requires changes in two places:

- `tui.py` → `STATUS_META`, `FILTER_ORDER`
- `docs/ticket-schema.md` → contract update

Pre-migration title-case variants (`In Progress`, `Todo`, etc.) are kept as read-only aliases — don't extend that set.

## TICKETS_DIR resolution

Order: `$TICKETS_DIR` (explicit) → `~/.pi/agent/tickets` (fallback). If `$TICKETS_DIR` names a project under `~/.pi/agent/tickets/<project>` or `~/.claude/tickets/<project>`, `__main__.py` adds the matching other-side project root as `TIX_EXTRA_TICKETS_DIRS` before importing the TUI. No broader in-binary project autodiscovery from cwd.

The `tix <project>` form (`resolve_project` in `__main__.py`) does two things:

**Picks the primary brief tree** (sets `TICKETS_DIR`) and any extra read roots (`TIX_EXTRA_TICKETS_DIRS`). The list may render tickets from either root, but pickup rewrites `TICKETS_DIR` per ticket to the root that actually contains the selected brief:

1. `~/.pi/agent/tickets/<project>/` if it exists (centralized — preferred)
2. else `~/.claude/tickets/<project>/` (legacy centralized)
3. else `$TIX_CODE_DIR/<project>/.claude/tickets/` (repo-local)
4. else `./<project>/.claude/tickets/` (cwd-relative legacy)
5. else error

Every other existing project tree from that same candidate list is included as an extra read root, so Pi-created and Claude-created tickets both appear while writes still target the primary tree.

**chdirs into the project's git repo** so pickup (`p` → `wt`) operates on the right repo — wt fails silently when cwd isn't a repo root. Lookup root is `$TIX_CODE_DIR` (default `~/Documents/code`); falls back to a cwd-relative `./<project>` repo for the legacy layout. The chdir is independent of which brief tree was chosen — centralized tickets + chdir into the code repo is the common case.

Per-project autoswitch on `cd` lives in the user's shell, not tix. The README documents a zsh `chpwd` hook recipe for the centralized layout.

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
