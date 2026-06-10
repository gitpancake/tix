# Ticket schema

The contract between tix and your ticket tree. Read this before hand-editing
anything under `$TICKETS_DIR` (default `~/.pi/agent/tickets`).

## The one rule

**Filename is the slug.** A ticket file's stem *is* its identifier — never an
external tracker ID, never an arbitrary number.

```
good:  oauth-rotation-plan.md
bad:   PROJ-123.md
bad:   DRAFT-7.md
```

`tix` and `ls` stay legible without opening any file. External IDs go in the
optional `linear:` frontmatter field as a historical breadcrumb; nothing ever
syncs.

## Two kinds of thing

| Kind | Lives at | Is |
|---|---|---|
| **Single ticket** | `<area>/<slug>.md` | One unit of change with acceptance criteria. |
| **Epic** | `<area>/<epic-slug>/` | A folder: `_epic.md` plus ordered `NN-<child>.md` children. |

A ticket lives in its area from creation — there is no staging folder. "Draft"
is a *status*, not a location: a freshly-scoped ticket is `status: draft` until
it's refined or picked up.

**Epic-ness is structural.** A directory containing `_epic.md` *is* an epic.
There is no separate registry — `find $TICKETS_DIR -name _epic.md` is the
epic index, and it is never stale.

## Areas

The root is a small, fixed set of area buckets. This is what keeps the tree
browsable instead of sprawling into one folder per epic.

The default areas baked into `tix` are:

- `integrations/`
- `ops/`
- `platform/`
- `spikes/`
- `tooling/`

These names are intentionally generic. Pick whatever set suits your project — a
future release will make `AREAS` configurable via env or a config file. For now
edit `src/tix/tui.py`'s `AREAS` list if you fork.

Add buckets deliberately. If you reach for a sixth, ask whether it's really an
area or just an epic that belongs inside an existing one.

## Frontmatter

```yaml
---
status: open               # active | open | draft | done | cancelled
priority: P1               # P0 | P1 | P2 | P3 (blank = unprioritized)
label: backend             # optional one-line display/filter tag
area: integrations         # one of the configured areas
linear: PROJ-123           # optional external-tracker breadcrumb
parent: <epic-slug>        # only on epic children
---
```

The parser is intentionally line-based — no PyYAML, no nesting. Keep each value
on a single line.

### Status vocab

- `draft` — scoped, not yet refined. The cheapest possible "I might want this."
- `open` — refined and ready to be picked up. Default for new well-formed tickets.
- `active` — being worked. A reconciler can derive this from live worktrees or
  branches; you can also pin it manually with `tix`'s `i` key.
- `done` — shipped. A reconciler can derive it from merged PRs containing the
  slug; you can also pin it with `d`. Sticky: a manual mark survives the next
  reconciliation pass so research/ops tickets without a PR signal can still
  close out.
- `cancelled` — dropped. **Terminal** — trumps every derived signal until you
  reopen it. Set/cleared with `x`.

Read-only aliases: `merged` is treated as `done` everywhere (some reconcilers
and PR tooling write it); the pre-migration title-case variants (`Done`,
`Canceled`, …) likewise fold onto their lowercase status. `tix` never rewrites
an alias — toggling `d` on a `merged` ticket flips it to `open` like any done
ticket.

`tix` itself is a **pure reader** — it never writes `status:` for you. If you
want statuses derived from external signals, wire your own reconciler via the
`TIX_PRELOAD_HOOK` env var; it runs once before each TUI launch. A reference
implementation (filesystem + git + `gh`) lives in
[gitpancake/.dotfiles](https://github.com/gitpancake/.dotfiles) as
`claude/scripts/ticket-status-sync.py` — derives `active` from worktrees and
`done` from merged PRs. Fork, replace, or skip entirely.

### Priority

Hand-driven, unlike status. Buckets are `P0` (drop everything) → `P3`
(eventually); blank sorts last. Within each group `tix` sorts by priority then
status, so P0/P1 work bubbles to the top. Edit the frontmatter directly or use
`+`/`−` from the TUI.

### Label

Optional free-text tag for lightweight grouping/filtering. Keep it one line.
Set or clear it from the TUI with `l` (blank input clears the field). Labels
render as `#label` in the list and preview pane.

## Epic shape

```
<area>/<epic-slug>/
  _epic.md                # the durable, expansive brief
  01-<child-slug>.md      # ordered child stories
  02-<child-slug>.md
```

- **`_epic.md`** carries context, goal, epic-level acceptance criteria,
  constraints, and an ordered story list.
- **`NN-<child>.md` children** are the deep per-story detail. The `NN-` prefix
  encodes execution order so `ls` and `tix` show the sequence.

## Slug conventions

Use a descriptive, kebab-cased phrase. Short enough to type, long enough to
read at a glance. Avoid encoding state in the name — that's what `status:` is
for.

```
good:  oauth-rotation-plan
good:  webhook-replay-on-failure
bad:   fix-the-thing
bad:   work-in-progress-stuff
```
