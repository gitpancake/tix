# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
