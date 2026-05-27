# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- Brief-tree precedence extended: centralized `~/.claude/tickets/<proj>` →
  repo-local `$TIX_CODE_DIR/<proj>/.claude/tickets` → cwd-legacy
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

[0.1.0]: https://github.com/gitpancake/tix/releases/tag/v0.1.0
