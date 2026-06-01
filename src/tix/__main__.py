"""tix CLI entry point.

  tix                browse $TICKETS_DIR (default ~/.pi/agent/tickets)
  tix <project>      browse ~/.pi/agent/tickets/<project>/ plus legacy
                     ~/.claude/tickets/<project>/, and chdir into the project's
                     code repo so pickup works.
  tix --mini         narrow-pane reverse-chrono reader (composes with <project>).

Code-repo lookup root defaults to ~/Documents/code; override with $TIX_CODE_DIR.
"""
import os
import sys
from pathlib import Path


def _set_ticket_dirs(primary, *extras):
    os.environ["TICKETS_DIR"] = str(primary)
    extra_dirs = [str(path) for path in extras if path.is_dir() and path != primary]
    if extra_dirs:
        os.environ["TIX_EXTRA_TICKETS_DIRS"] = os.pathsep.join(extra_dirs)
    else:
        os.environ.pop("TIX_EXTRA_TICKETS_DIRS", None)


def _project_from_env_tickets_dir():
    tickets_dir = os.environ.get("TICKETS_DIR")
    if not tickets_dir:
        return None
    parts = Path(tickets_dir).expanduser().parts
    for marker in ((".claude", "tickets"), (".pi", "agent", "tickets")):
        marker_len = len(marker)
        for i in range(len(parts) - marker_len):
            if parts[i : i + marker_len] == marker and len(parts) > i + marker_len:
                return parts[i + marker_len]
    return None


def configure_current_project_dirs():
    """When a shell hook exported one side of a project's ticket tree, add the
    other side too. Pi-created and Claude-created briefs intentionally live in
    separate roots, but readers should show both for the active project."""
    proj = _project_from_env_tickets_dir()
    if not proj:
        return
    pi_dir = Path.home() / ".pi" / "agent" / "tickets" / proj
    claude_dir = Path.home() / ".claude" / "tickets" / proj
    current = Path(os.environ["TICKETS_DIR"]).expanduser()
    if current == pi_dir and claude_dir.is_dir():
        _set_ticket_dirs(pi_dir, claude_dir)
    elif current == claude_dir and pi_dir.is_dir():
        _set_ticket_dirs(claude_dir, pi_dir)


def resolve_project(proj):
    """Wire up `tix <project>`: chdir into the project's git repo and point
    TICKETS_DIR at its brief tree(s). Returns True on success, False (after
    printing) when no brief tree can be found.

    chdir matters because pickup (`p` → `wt`) operates on the *current* repo —
    if cwd isn't a repo root, wt fails silently and no lane spawns. The code
    repo is looked up under $TIX_CODE_DIR (default ~/Documents/code).

    Brief-tree precedence for the primary write root: centralized
    ~/.pi/agent/tickets/<proj> (preferred) → legacy centralized
    ~/.claude/tickets/<proj> → the repo's own ./.claude/tickets → the
    cwd-relative ./<proj>/.claude/tickets. Other existing project roots are
    exposed as extra read roots."""
    code_root = Path(
        os.environ.get("TIX_CODE_DIR", Path.home() / "Documents" / "code")
    ).expanduser()
    code_dir = code_root / proj
    centralized = Path.home() / ".pi" / "agent" / "tickets" / proj
    legacy_centralized = Path.home() / ".claude" / "tickets" / proj
    repo_local = code_dir / ".claude" / "tickets"
    legacy = Path.cwd() / proj / ".claude" / "tickets"

    candidates = [centralized, legacy_centralized, repo_local, legacy]
    existing = [path for path in candidates if path.is_dir()]

    if existing:
        tickets_dir = existing[0]
    else:
        print(
            f"tix: no ticket directory for '{proj}' "
            f"(looked in {centralized}, {legacy_centralized}, {repo_local}, {legacy})",
            file=sys.stderr,
        )
        return False

    # Prefer the configured code dir; fall back to the legacy ./<proj> repo so
    # pickup keeps working with the old per-repo layout.
    if (code_dir / ".git").exists():
        os.chdir(code_dir)
    elif (Path.cwd() / proj / ".git").exists():
        os.chdir(Path.cwd() / proj)

    _set_ticket_dirs(tickets_dir, *existing[1:])
    return True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and not argv[0].startswith("-"):
        proj = argv.pop(0)
        if not resolve_project(proj):
            return 1
    else:
        configure_current_project_dirs()

    if "--mini" in argv:
        argv = [a for a in argv if a != "--mini"]
        from . import mini
        sys.argv = ["tix", *argv]
        return mini.main()

    from . import tui
    sys.argv = ["tix", *argv]
    return tui.main()


if __name__ == "__main__":
    sys.exit(main())
