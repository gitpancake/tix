# Ticket System — the contract

Tickets live here. **The filesystem is the database.** There is no external tracker —
the brief file *is* the ticket.

This file is the contract between humans and `wt` lanes. Read it before hand-editing
anything under `~/.claude/tickets/`.

## The one rule

**Filename is a descriptive slug. Never an ID.**

`teams-error-mapping.md`, not `AE-1692.md`, not `DRAFT-7.md`. You can read a slug and
know what the ticket is; `tix` and `ls` stay legible without opening files. The `linear:`
frontmatter field is an optional historical breadcrumb — a cross-reference on tickets that
predate the local-only move. New tickets leave it empty; nothing ever syncs.

## Two kinds of thing

| Kind | Lives at | Is |
|---|---|---|
| **Single ticket** | `<area>/<slug>.md` | one unit of change with acceptance criteria |
| **Epic** | `<area>/<epic-slug>/` | a folder: `_epic.md` + ordered `NN-<child>.md` children |

A ticket lives in its area from creation — there is no `_drafts/` staging folder. "Draft"
is a *status*, not a location: a freshly-`/scope`d ticket is `status: draft` until it's
refined or picked up.

**Epic-ness is structural.** A folder containing an `_epic.md` *is* an epic. There is no
registry — `find ~/.claude/tickets -name _epic.md` is the epic index, and it is never
stale. (The old `.epics.json` is dead.)

## Areas

The root is a small, fixed set of area buckets — this is what keeps the tree browsable
instead of sprawling into one folder per epic. Current set:

- `integrations/` — vendor adapters, L3 work, webhooks, channel plumbing
- `platform/` — shared services, visibility, core infra-facing work
- `ops/` — consolidations, cleanups, eng-ops, migrations
- `tooling/` — the cockpit, `wt`/`ralph`/`tix`, this ticket system itself
- `spikes/` — exploratory, time-boxed, may never ship

Edit this list deliberately. If you reach for a sixth bucket, ask whether it's really an
area or just an epic that belongs inside an existing one.

## Frontmatter

```yaml
---
linear:                       # optional historical breadcrumb; empty on new tickets
title: <≤80 chars, action-oriented>
status: draft                 # draft | open | active | done — a CACHE, not hand-edited
priority:                     # optional: P0 | P1 | P2 | P3 — blank = unprioritized
epic:                         # parent epic folder slug, or empty
area: integrations            # one of the buckets above
labels: []
created: <ISO-8601>
---
```

**Stored:** `linear`, `title`, `priority`, `epic`, `area`, `labels`, `created`.
**Derived — do not store:** the slug (it's the filename), the Linear URL (built from
`linear:`), whether the ticket is in flight (a worktree/branch exists for it).

`status` is a **cache**, not a workflow you hand-drive. Local lifecycle is five states;
three are derived from filesystem + git, two (`draft`, `cancelled`) are sticky user intent:

- `draft` — created, not yet refined or picked up. The *sticky seed*: nothing on disk
  distinguishes a draft from an open ticket, so the reconciler never *produces* `draft` —
  `/scope` plants it and it is preserved until a live lane appears.
- `open` — refined, ready, no active lane
- `active` — a live worktree or branch exists for the slug
- `done` — a PR for the ticket's branch was merged **or** the user pinned it from `tix`
  with `d`. Sticky: a manual mark survives reconciliation so spikes/ops/research tickets
  without a PR signal can still be closed out.
- `cancelled` — user dropped the ticket. **Terminal**, trumps every derived signal — a
  cancelled ticket whose branch still exists stays cancelled until reopened. Set/cleared
  from `tix` with `x`.

`~/.claude/scripts/ticket-status-sync.py` is the **one and only writer** of `status:`.
It recomputes every ticket on a full sweep (run by hand, or automatically when `tix`
launches) and flips a single ticket to `active` on its fast path (run by `wt` on lane
spawn). Do not edit `status:` by hand to "track progress" — the reconciler clobbers it on
the next run, and that drift is exactly what killed the old `status:` field.

`priority` is **hand-driven**, unlike `status`. Buckets are `P0` (drop everything) → `P3`
(eventually); blank = unprioritized and sorts last. Within each group `tix` sorts by
priority then status, so P0/P1 work bubbles to the top. Bump from `tix` with `+`/`−`, or
edit the frontmatter directly. The reconciler never touches this field.

## Epic shape

```
<area>/<epic-slug>/
  _epic.md                 # the durable, Ralph-ready PRD. tix renders it; Ralph reads it.
  01-<child-slug>.md       # ordered deep-context — the expansion Ralph opens per story
  02-<child-slug>.md
```

- **`_epic.md` is the source of truth.** It carries context, goal, epic-level acceptance
  criteria, constraints, and — in the `<!-- epic-stories:start -->` block — the
  authoritative ordered story list plus dependency DAG. A human reviews and confirms this
  block before any lane spawns. Ralph never decomposes; it executes a confirmed list.
- **`NN-<child>.md` children are context, not the primary input.** Each is the deep
  per-story detail Ralph opens when it picks that story. The `NN-` prefix encodes
  execution order so `ls` and `tix` show the sequence.
- **`prd.json` is generated, never authored.** At lane-spawn, `epic-parse.sh` projects the
  `epic-stories` block in `_epic.md` into `scripts/ralph/prd.json` *inside the worktree*.
  It never lives in the tickets tree. `_epic.md` changes → re-project; the markdown is
  always the truth.

## Picking up

`wt <arg>` and `/pickup <arg>` resolve `<arg>`, in order:

1. frontmatter `linear:` match (a real Linear ID)
2. filename slug match
3. epic folder name match

So `wt teams-error-mapping`, `wt AE-1692`, and `wt teams-l3-adapter` all work.

## Conventions

- **Tombstone** — a file whose only content is `moved -> <path>` is a redirect left behind
  when a ticket was relocated. Readers follow it; `/epic` skips it.
- **`_` prefix** — meta/generated, not a real ticket: `_epic.md`, `_TEMPLATE.md`,
  `_EPIC-TEMPLATE.md`, `_CHILD-TEMPLATE.md`.
- **Moving a ticket** — misfiled? `git mv` it to the right `<area>/`. The slug is stable,
  so `wt` resolves it wherever it lands.

## Templates

- `_TEMPLATE.md` — single ticket
- `_EPIC-TEMPLATE.md` — epic root (`_epic.md`)
- `_CHILD-TEMPLATE.md` — epic child (`NN-<slug>.md`)

Copy them. Do not freehand the frontmatter.
