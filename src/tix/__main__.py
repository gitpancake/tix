"""tix CLI entry point.

  tix                browse $TICKETS_DIR (default ~/.claude/tickets)
  tix <project>      browse ~/.claude/tickets/<project>/ (centralized layout).
                     Legacy fallback: ./<project>/.claude/tickets/
"""
import os
import sys
from pathlib import Path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and not argv[0].startswith("-"):
        proj = argv.pop(0)
        home_proj = Path.home() / ".claude" / "tickets" / proj
        if home_proj.is_dir():
            os.environ["TICKETS_DIR"] = str(home_proj)
        else:
            legacy = Path.cwd() / proj / ".claude" / "tickets"
            if legacy.is_dir():
                os.chdir(Path.cwd() / proj)
                os.environ["TICKETS_DIR"] = str(legacy)
            else:
                print(
                    f"tix: no ticket directory at {home_proj} (or {legacy})",
                    file=sys.stderr,
                )
                return 1

    from . import tui
    sys.argv = ["tix", *argv]
    return tui.main()


if __name__ == "__main__":
    sys.exit(main())
