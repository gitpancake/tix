# tix

Keyboard-driven terminal ticket explorer for a tree of markdown briefs. Linear-like TUI, zero deps beyond the Python stdlib + an optional markdown pager.

```
LANES                         STATE              CTX
◐ P1 teams-error-mapping      active              74K
○ P0 shopify-variant-meta     open                —
●    audit-logs-rollout       done                —
```

## Why

- **The filesystem is the database.** A ticket *is* a markdown file. `grep`, `git log`, and `ls` all keep working.
- **No SaaS, no auth, no network.** Runs entirely against a local tree. Optional `gh` for "merged → done" derivation.
- **Linear-like keys.** `j/k`, `/` to filter, `Enter` to open, `p` to pick up into a `wt` lane.
- **One writer.** Only `tix sync` writes the `status:` frontmatter. Everything else (TUI, hooks, lane spawns) is a reader.

## Install

```bash
pipx install tix-cli
# or, in a venv:
pip install tix-cli
```

That installs two console scripts: `tix` (the TUI) and `tix-sync` (the status reconciler).

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
| `r` | Reload + run `tix sync` |
| `?` | Help |
| `q` | Quit |

## Schema

A ticket is a markdown file with YAML-ish line-based frontmatter:

```markdown
---
status: open
priority: P1
area: integrations
linear: AE-1692
---

# teams-error-mapping

## Context
…

## Acceptance criteria
- [ ] …
```

Full contract: [`docs/ticket-schema.md`](docs/ticket-schema.md).

- **Filename is the slug.** `teams-error-mapping.md`, never `AE-1692.md`.
- **Epic = folder.** A directory containing `_epic.md` is an epic; numbered children (`01-foo.md`, `02-bar.md`) are its stories.
- **Status vocab is pinned:** `active`, `open`, `draft`, `done`, `cancelled`.

## Configuration

| Env | Default | Purpose |
|---|---|---|
| `TICKETS_DIR` | `~/.claude/tickets` | Root of the ticket tree |
| `ACTIVE_LANES_FILE` | `~/.claude/active-lanes.json` | Sidecar map: slug → active lane info, written by `tix sync` |
| `LINEAR_WORKSPACE` | *(unset)* | Slug used to derive `linear:` URLs (`o` key) |
| `EDITOR` | `vi` | Used by `e` |
| `PAGER` | `less` | Fallback when `glow` is absent |

## `tix sync` — the status writer

`tix sync` is the **only** thing that writes the `status:` field. The TUI invokes it as a subprocess on launch. You can also call it directly:

```bash
tix sync                  # full sweep: every ticket, all signals
tix sync <slug>           # fast path: one ticket (skips `gh`)
```

Derivation rules (in priority order):

1. **Sticky pins** set from the TUI (`i`, `d`, `x`) win over everything.
2. **Active** ← a `wt` worktree or matching feature branch exists for the slug.
3. **Done** ← `gh pr list --state merged` reports a merged PR whose title or branch contains the slug. Requires `gh` on PATH; otherwise this signal is skipped.
4. Otherwise: keep the file's current status, or `open` if it has none.

## Optional integrations

- **`wt`** — if a `wt` command is on PATH, the `p` key suspends curses, runs `git fetch && git checkout main && git merge --ff-only && wt <slug>`, then resumes.
- **`gh`** — used by `tix sync` to derive "merged PR → done". Without it the rest of sync still runs; `done` is just never auto-set.
- **`glow`** — preferred markdown pager for ticket preview. Falls back to `$PAGER` (default `less`).

## Non-goals

- No remote sync, no auth, no web UI.
- No mouse support.
- No notifications.
- No issue tracker integration beyond an optional `linear:` URL breadcrumb.

## License

MIT.
