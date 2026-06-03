# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.7] — 2026-06-03

### Added
- Main TUI tickets now support an optional `label:` frontmatter field. Press
  `l`, type a one-line label, and press Enter to save; blank input clears it.
- Labels render as `#label` in the list and preview, and text search matches
  label values.

## [0.3.6] — 2026-06-01

### Changed
- Readers can now show both Pi-created and Claude-created project tickets at
  once via `TIX_EXTRA_TICKETS_DIRS`.
- `tix <project>` includes the matching Pi/Claude project tree as an extra read
  root when both exist.

### Fixed
- Mini/main pickup now passes the selected ticket's owning root as `TICKETS_DIR`
  to `wt`, so Pi tickets loaded from an extra root spawn with the brief prompt
  instead of opening an idle lane.

## [0.3.5] — 2026-06-01

### Changed
- Default ticket tree moved from `~/.claude/tickets` to `~/.pi/agent/tickets`.
- `tix <project>` now prefers `~/.pi/agent/tickets/<project>`, while retaining
  legacy fallbacks for `~/.claude/tickets/<project>` and repo-local
  `.claude/tickets` trees.
- Epic templates now describe Pi's direct child-brief pickup flow instead of the
  old Ralph projection flow.
- Epic pickup now uses plain `wt <slug>` instead of `wt --ralph <slug>`.

### Fixed
- Pickup's best-effort git sync now suppresses git noise and skips checkout/merge
  in unborn or origin-less repositories instead of blocking lane spawn.

## [0.3.2] — 2026-05-27

### Added
- `tix --mini` now binds `i`/`d`/`x` to toggle in-progress / done /
  cancelled — same sticky semantics as the main TUI. Marked done/cancelled
  tickets drop from the mini list (hidden by default).

## [0.3.1] — 2026-05-27

### Changed
- `tix --mini` now colorizes status icon + title (parity with main TUI
  palette) and pins `active` tickets to the top of the list; remaining
  tickets keep the newest-`created`-first order.

## [0.3.0] — 2026-05-27

### Added
- `tix --mini` — flat reverse-chrono mini reader for narrow sidecars (≥20
  cols). Single signal: what was filed recently, can I pick one up. Hides
  done/cancelled; `↑/↓` move, `Enter` opens in `glow`/`$PAGER`, `p` spawns
  `wt`, `q` quits. Combines with `tix <project> --mini` for scoped browsing.

## [0.2.1] — 2026-05-24

### Fixed
- `R` rescope / `n`,`N` new now launch claude with
  `--dangerously-skip-permissions` (via new `claude_argv()` helper, `WT_CLAUDE`
  overridable) — parity with `p` pickup. Previously they dropped into a
  permission-prompting session while pickup's `wt` lane bypassed.

## [0.2.0] — 2026-05-20

### Added
- `tix <project>` now **chdirs into the project's git repo** (under
  `$TIX_CODE_DIR`, default `~/Documents/code`) so the pickup key (`p` → `wt`)
  runs against the right repo. Previously the centralized layout never
  chdir'd and pickup silently no-op'd outside a repo root.
- `TIX_CODE_DIR` env var — overrides the code-repo lookup root.
- Brief-tree precedence extended: centralized `~/.pi/agent/tickets/<proj>` →
  legacy centralized `~/.claude/tickets/<proj>` → repo-local
  `$TIX_CODE_DIR/<proj>/.claude/tickets` → cwd-legacy
  `./<proj>/.claude/tickets`.

### Changed
- Pickup (`p`) marks the ticket `active` immediately rather than waiting for
  the reconciler, forces `WT_NO_WATCH=1` for a single-pane lane, and
  rebuilds/reselects the row on return.

## [0.1.0] — 2026-05-18

Initial public release.

### Added
- Curses TUI over a tree of markdown ticket briefs.
- Keyboard-driven navigation, filter (`/`), edit (`e`), pickup → `wt` (`p`).
- Sticky status pins: `i` (active), `d` (done), `x` (cancelled).
- Move ticket between areas (`m`), copy slug (`y`), open Linear URL (`o`).
- Split-pane preview with `glow` / `$PAGER` fallback.
- `tix <project>` form: `chdir` into `./<project>` and set
  `TICKETS_DIR=<project>/.claude/tickets`.
- `TIX_PRELOAD_HOOK` env var — runs a user-supplied shell command before the
  TUI launches so external tooling can derive `status:`. tix itself is a pure
  reader.
- Bundled `_TEMPLATE.md`, `_EPIC-TEMPLATE.md`, `_CHILD-TEMPLATE.md` accessible
  via `importlib.resources` at `tix/templates/`.

### Schema
- Filename is the slug.
- Epic = folder containing `_epic.md`.
- Status vocab pinned: `active`, `open`, `draft`, `done`, `cancelled`.
- Frontmatter parser is line-based (no PyYAML).

[0.3.6]: https://github.com/gitpancake/tix/releases/tag/v0.3.6
[0.3.5]: https://github.com/gitpancake/tix/releases/tag/v0.3.5
[0.3.2]: https://github.com/gitpancake/tix/releases/tag/v0.3.2
[0.3.1]: https://github.com/gitpancake/tix/releases/tag/v0.3.1
[0.3.0]: https://github.com/gitpancake/tix/releases/tag/v0.3.0
[0.2.1]: https://github.com/gitpancake/tix/releases/tag/v0.2.1
[0.2.0]: https://github.com/gitpancake/tix/releases/tag/v0.2.0
[0.1.0]: https://github.com/gitpancake/tix/releases/tag/v0.1.0
