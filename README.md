# tix

[![PyPI](https://img.shields.io/pypi/v/tix-cli.svg)](https://pypi.org/project/tix-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/tix-cli.svg)](https://pypi.org/project/tix-cli/)
[![License](https://img.shields.io/pypi/l/tix-cli.svg)](https://github.com/gitpancake/tix/blob/main/LICENSE)

Keyboard-driven terminal ticket explorer for a tree of markdown briefs. Linear-like TUI, zero deps beyond the Python stdlib + an optional markdown pager.

```
LANES                         STATE              CTX
◐ P1 teams-error-mapping      active              74K
○ P0 oauth-rotation-plan      open                —
●    audit-logs-rollout       done                —
```

## Why

- **The filesystem is the database.** A ticket *is* a markdown file. `grep`, `git log`, and `ls` all keep working.
- **No SaaS, no auth, no network.** Runs entirely against a local tree.
- **Linear-like keys.** `j/k`, `/` to filter, `Enter` to open, `p` to pick up into a `wt` lane.
- **Pure reader.** tix never writes `status:` for you. If you want auto-status derivation, wire up your own preload hook (see below).

## Install

```bash
pipx install tix-cli
# or, in a venv:
pip install tix-cli
```

Installs one console script: `tix`.

### From source

```bash
git clone https://github.com/gitpancake/tix
cd tix
pipx install --editable .
```

## Quickstart

```bash
mkdir -p ~/.claude/tickets/spikes
cp $(python -c 'import tix, pathlib; print(pathlib.Path(tix.__file__).parent / "templates" / "_TEMPLATE.md")') \
   ~/.claude/tickets/spikes/my-first-ticket.md
tix
```

Or point at a project tree:

```bash
cd ~/code
tix my-project           # browses ~/code/my-project/.claude/tickets
TICKETS_DIR=./docs/tickets tix
```

## Keys

| Key | Action |
|---|---|
| `↑` `↓` / `j` `k` | Move |
| `Ctrl-U` `Ctrl-D` | Half page |
| `g` `G` | Top / bottom |
| `Enter` `→` `l` | Open in `glow` (or `$PAGER`) |
| `Esc` `←` `h` | Collapse / back |
| `/` | Filter |
| `e` | Edit in `$EDITOR` |
| `p` | Pickup → `wt <slug>` |
| `i` | Pin status `active` |
| `d` | Pin status `done` |
| `x` | Pin status `cancelled` |
| `m` | Move ticket to area |
| `y` | Copy slug to clipboard |
| `o` | Open Linear URL (if `linear:` set) |
| `r` | Reload (re-runs preload hook if set) |
| `?` | Help |
| `q` | Quit |

## Schema

A ticket is a markdown file with YAML-ish line-based frontmatter:

```markdown
---
status: open
priority: P1
area: integrations
linear: PROJ-123
---

# teams-error-mapping

## Context
…

## Acceptance criteria
- [ ] …
```

Full contract: [`docs/ticket-schema.md`](docs/ticket-schema.md).

- **Filename is the slug.** `teams-error-mapping.md`, never `PROJ-123.md`.
- **Epic = folder.** A directory containing `_epic.md` is an epic; numbered children (`01-foo.md`, `02-bar.md`) are its stories.
- **Status vocab is pinned:** `active`, `open`, `draft`, `done`, `cancelled`.

## Configuration

| Env | Default | Purpose |
|---|---|---|
| `TICKETS_DIR` | `~/.claude/tickets` | Root of the ticket tree |
| `ACTIVE_LANES_FILE` | `~/.claude/active-lanes.json` | Optional sidecar map: slug → `{path, branch, repo, last_commit}`. Read by the TUI; tix never writes it. |
| `LINEAR_WORKSPACE` | *(unset)* | Slug used to derive `linear:` URLs (`o` key) |
| `TIX_PRELOAD_HOOK` | *(unset)* | Shell command run before launch. See below. |
| `EDITOR` | `vi` | Used by `e` |
| `PAGER` | `less` | Fallback when `glow` is absent |

`TICKETS_DIR` resolves in this order: explicit env var → `~/.claude/tickets`. There is no project-local autodiscovery; pass `tix <project>` or set `TICKETS_DIR` explicitly.

## Preload hook

tix doesn't write `status:` — that's deliberate. If you want statuses derived from external signals (live worktrees, feature branches, merged PRs, calendar events, anything), put a script on disk and point at it:

```bash
export TIX_PRELOAD_HOOK=~/bin/my-status-sync
tix
```

The hook runs once before the TUI is drawn. Its stdout/stderr are discarded — curses is about to claim the screen, so the *next render* is the feedback, not the printed diff. The hook is best-effort: a missing or failing command never blocks launch.

The `r` key in the TUI re-runs the hook and reloads.

A reference implementation (filesystem + git + `gh`) lives in [gitpancake/.dotfiles](https://github.com/gitpancake/.dotfiles) as `claude/scripts/ticket-status-sync.py` — it derives `active` from live worktrees and `done` from merged PRs. Copy it, fork it, replace it.

## Optional integrations

- **`wt`** — if a `wt` command is on PATH, the `p` key suspends curses, runs `git fetch && git checkout main && git merge --ff-only && wt <slug>`, then resumes.
- **`glow`** — preferred markdown pager for ticket preview. Falls back to `$PAGER` (default `less`).
- **`gh`** — used by some preload hooks (not by tix itself).

## Non-goals

- No remote sync, no auth, no web UI.
- No mouse support.
- No notifications.
- No bundled status reconciler — wire your own via `TIX_PRELOAD_HOOK`.

## License

MIT.
