"""tix CLI entry point.

  tix                browse $TICKETS_DIR (default ~/.claude/tickets)
  tix <project>      cd into ./<project>, set TICKETS_DIR=<project>/.claude/tickets
"""
import os
import sys
from pathlib import Path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and not argv[0].startswith("-"):
        proj = argv.pop(0)
        proj_dir = Path.cwd() / proj
        if not proj_dir.is_dir():
            print(f"tix: no project directory at {proj_dir}", file=sys.stderr)
            return 1
        os.chdir(proj_dir)
        os.environ["TICKETS_DIR"] = str(proj_dir / ".claude" / "tickets")

    from . import tui
    sys.argv = ["tix", *argv]
    return tui.main()


if __name__ == "__main__":
    sys.exit(main())
