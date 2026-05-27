"""tix CLI entry point.

  tix                browse $TICKETS_DIR (default ~/.claude/tickets)
  tix <project>      browse ~/.claude/tickets/<project>/ (centralized layout)
                     and chdir into the project's code repo so pickup works.
  tix --mini         narrow-pane reverse-chrono reader (composes with <project>).

Code-repo lookup root defaults to ~/Documents/code; override with $TIX_CODE_DIR.
"""
import os
import sys
from pathlib import Path


def resolve_project(proj):
    """Wire up `tix <project>`: chdir into the project's git repo and point
    TICKETS_DIR at its brief tree. Returns True on success, False (after
    printing) when no brief tree can be found.

    chdir matters because pickup (`p` → `wt`) operates on the *current* repo —
    if cwd isn't a repo root, wt fails silently and no lane spawns. The code
    repo is looked up under $TIX_CODE_DIR (default ~/Documents/code).

    Brief-tree precedence: centralized ~/.claude/tickets/<proj> (preferred) →
    the repo's own ./.claude/tickets → the cwd-relative ./<proj>/.claude/tickets
    (legacy)."""
    code_root = Path(
        os.environ.get("TIX_CODE_DIR", Path.home() / "Documents" / "code")
    ).expanduser()
    code_dir = code_root / proj
    centralized = Path.home() / ".claude" / "tickets" / proj
    repo_local = code_dir / ".claude" / "tickets"
    legacy = Path.cwd() / proj / ".claude" / "tickets"

    if centralized.is_dir():
        tickets_dir = centralized
    elif repo_local.is_dir():
        tickets_dir = repo_local
    elif legacy.is_dir():
        tickets_dir = legacy
    else:
        print(
            f"tix: no ticket directory for '{proj}' "
            f"(looked in {centralized}, {repo_local}, {legacy})",
            file=sys.stderr,
        )
        return False

    # Prefer the configured code dir; fall back to the legacy ./<proj> repo so
    # pickup keeps working with the old per-repo layout.
    if (code_dir / ".git").exists():
        os.chdir(code_dir)
    elif (Path.cwd() / proj / ".git").exists():
        os.chdir(Path.cwd() / proj)

    os.environ["TICKETS_DIR"] = str(tickets_dir)
    return True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and not argv[0].startswith("-"):
        proj = argv.pop(0)
        if not resolve_project(proj):
            return 1

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
