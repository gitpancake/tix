#!/usr/bin/env python3
"""ticket-status-sync — the one writer of `status:` in ~/.claude/tickets.

`status:` is a cache, not a workflow you hand-drive — that drift is exactly
what killed the old field. This script is its sole writer: it recomputes
every ticket's status from filesystem + git signals and overwrites the
frontmatter line. Hand edits are clobbered on the next run, by design.

States (contract: ~/.claude/tickets/README.md):
  done       — a PR was merged OR user pinned it from tix (`d`); sticky
  active     — a live worktree or branch exists for the slug
  open       — refined, ready, no active lane
  draft      — freshly /scope'd, not yet refined or picked up
  cancelled  — user dropped the ticket; terminal, trumps every derived signal

`draft` is a sticky seed: pre-migration it was the `_drafts/` folder, but that
folder is dead — draft is a status, not a location. Nothing on the filesystem
distinguishes a draft from an open ticket, so this script never *produces*
draft; it only *preserves* it when no live signal exists. `/scope` plants
`draft`; the first worktree flips it to `active`; from then on it is derived.

`cancelled` is the second sticky carve-out, but with stronger semantics: it
trumps every derived signal. The reconciler never produces `cancelled` either;
`tix` writes it on `x`, and from then on it is preserved regardless of whether
a branch or PR still exists. Reopen with `x` again from tix.

Usage:
  ticket-status-sync.py            full sweep — every ticket, all signals
  ticket-status-sync.py <slug>     fast path — one ticket, worktree/branch
                                   signal only (skips `gh`); `wt` calls this
                                   on spawn so a picked-up ticket flips to
                                   `active` immediately and cheaply.

Exit code is always 0 — this runs as a `wt`/`tix` hook and must never block.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

TICKETS_DIR = Path(os.environ.get("TICKETS_DIR", Path.home() / ".claude" / "tickets"))
HOME = Path.home()
# Sidecar consumed by tix: slug -> {path, branch, repo, last_commit}. Written
# only on full sweeps; the fast path (`wt <slug>`) is too narrow to refresh
# the whole map and would leave stale entries for other lanes.
LANES_FILE = Path(os.environ.get("ACTIVE_LANES_FILE",
                                 HOME / ".claude" / "active-lanes.json"))

# Files under TICKETS_DIR that are not single tickets. `_epic.md` and the
# templates are `_`-prefixed; epics are containers, not units of change, so
# their status is left to the author — this script owns *ticket* status only.
META_NAMES = {"README.md"}

# Branch names that are not lane branches — never a ticket slug.
NON_LANE_BRANCHES = {"main", "master", "HEAD"}


# ---- frontmatter -----------------------------------------------------------
# Line-based, matching tix's parser in tui.py — the tickets
# tree has no PyYAML dependency and the frontmatter is deliberately flat.

def read_status(lines):
    """Return (status_value, status_lineno, fm_end_lineno) for a ticket's
    frontmatter. status_lineno is None if there is no `status:` line;
    fm_end_lineno is the index of the closing `---`. Returns None if the
    file has no frontmatter block at all."""
    if not lines or lines[0].rstrip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            fm_end = i
            break
    else:
        return None
    status_line = None
    status_val = ""
    for i in range(1, fm_end):
        stripped = lines[i].strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        if key.strip() == "status":
            status_line = i
            status_val = val.strip()
            break
    return status_val, status_line, fm_end


def write_status(path, new_status):
    """Overwrite (or insert) the `status:` line in path's frontmatter.
    Touches only that one line — the rest of the file is preserved byte
    for byte."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    parsed = read_status(lines)
    if parsed is None:
        return  # no frontmatter — not a well-formed ticket, leave it be
    _, status_line, fm_end = parsed
    newline = "\n"
    if status_line is not None:
        lines[status_line] = f"status: {new_status}{newline}"
    else:
        # No status line yet — insert just before the closing `---`.
        lines.insert(fm_end, f"status: {new_status}{newline}")
    path.write_text("".join(lines), encoding="utf-8")


# ---- ticket discovery ------------------------------------------------------

def is_tombstone(path):
    """A tombstone is a redirect left behind by a moved ticket — its only
    content is `moved -> <path>`. It is not a live ticket."""
    head = path.read_text(encoding="utf-8", errors="replace").strip()
    return head.startswith("moved ->")


def find_tickets():
    """Every single-ticket brief under TICKETS_DIR. Skips meta/template files,
    `_`-prefixed files (`_epic.md`, `_*-TEMPLATE.md`), and tombstones."""
    tickets = []
    for path in sorted(TICKETS_DIR.rglob("*.md")):
        name = path.name
        if name in META_NAMES or name.startswith("_"):
            continue
        if is_tombstone(path):
            continue
        tickets.append(path)
    return tickets


def slug_of(path):
    return path.stem


# ---- git signals -----------------------------------------------------------

def run(cmd, cwd=None, any_exit=False):
    """Run a command, return stdout (stripped) or '' on failure. Never raises
    — a missing repo or missing `gh` must not crash a hook. `any_exit=True`
    keeps stdout even on a non-zero exit: `find` over $HOME exits non-zero on
    the first permission-denied dir but its printed results are still valid."""
    try:
        out = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0 and not any_exit:
        return ""
    return out.stdout.strip()


def discover_repos():
    """Repo roots the user works in. `wt` lanes live at <repo>/.claude/worktrees/
    <slug>, so to know whether a worktree exists for a ticket we must know the
    repos. There is no registry — but every repo Claude has run in leaves a
    dir under ~/.claude/projects/, and `find` over $HOME is bounded and fast
    enough at maxdepth 4. We take the union and dedupe."""
    repos = set()
    # Prune the big permission-denied / churn dirs so the walk stays fast;
    # any_exit keeps results despite find's non-zero exit on a denied dir.
    raw = run([
        "find", str(HOME), "-maxdepth", "4",
        "(", "-name", "Library", "-o", "-name", "node_modules",
        "-o", "-name", ".Trash", ")", "-prune",
        "-o", "-name", ".git", "-print",
    ], any_exit=True)
    for line in raw.splitlines():
        git_path = Path(line)
        parts = git_path.parts
        # A worktree's `.git` is a file pointing back at its main repo, and it
        # lives under `.claude/worktrees/` — skip it; the main repo's
        # `git worktree list` enumerates it for us.
        if ".claude" in parts and "worktrees" in parts:
            continue
        if "node_modules" in parts:
            continue
        repos.add(str(git_path.parent))
    return sorted(repos)


def branch_to_slug(branch):
    """A lane branch is `<type>/<slug>` (feature/fix/refactor). Strip the
    first segment; everything after it is the slug. Bare branches like `main`
    are not lanes."""
    if branch in NON_LANE_BRANCHES or "/" not in branch:
        return None
    return branch.split("/", 1)[1]


def active_signals(repos):
    """slugs with a live worktree or branch, plus the per-repo branch->slug
    map (so the `gh` pass can target only repos that actually have a lane
    branch). Worktree dir present == lane live: `git worktree remove` and
    `wt` teardown both delete the dir."""
    active = set()
    repo_slugs = {}  # repo -> set of slugs with a branch in that repo
    for repo in repos:
        slugs_here = set()

        wt_raw = run(["git", "-C", repo, "worktree", "list", "--porcelain"])
        for line in wt_raw.splitlines():
            if not line.startswith("worktree "):
                continue
            wt_path = Path(line[len("worktree "):])
            parts = wt_path.parts
            if ".claude" in parts and "worktrees" in parts:
                active.add(wt_path.name)  # basename == slug
                slugs_here.add(wt_path.name)

        ref_raw = run([
            "git", "-C", repo, "for-each-ref",
            "--format=%(refname:short)", "refs/heads",
        ])
        for branch in ref_raw.splitlines():
            slug = branch_to_slug(branch)
            if slug:
                active.add(slug)
                slugs_here.add(slug)

        if slugs_here:
            repo_slugs[repo] = slugs_here
    return active, repo_slugs


def lane_info(repos):
    """slug -> {path, branch, repo, last_commit} for every live worktree under
    `<repo>/.claude/worktrees/`. tix consumes the JSON sidecar to render
    in-progress state in its preview pane (lane path, agent-state, last commit)
    without re-walking every repo on every keystroke."""
    lanes = {}
    for repo in repos:
        wt_raw = run(["git", "-C", repo, "worktree", "list", "--porcelain"])
        current = {}
        for line in wt_raw.splitlines() + [""]:
            if not line.strip():
                wt_path = current.get("path", "")
                parts = Path(wt_path).parts if wt_path else ()
                if wt_path and ".claude" in parts and "worktrees" in parts:
                    slug = Path(wt_path).name
                    branch = current.get("branch", "")
                    if branch.startswith("refs/heads/"):
                        branch = branch[len("refs/heads/"):]
                    last = run([
                        "git", "-C", wt_path, "log", "-1",
                        "--format=%s · %cr",
                    ])
                    lanes[slug] = {
                        "path": wt_path,
                        "branch": branch,
                        "repo": repo,
                        "last_commit": last,
                    }
                current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[len("worktree "):]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):]
    return lanes


def write_lanes(lanes):
    """Best-effort. tix's lane-state section is a courtesy — if the write
    fails, tix simply hides the section, status sync is unaffected."""
    try:
        LANES_FILE.parent.mkdir(parents=True, exist_ok=True)
        LANES_FILE.write_text(json.dumps(lanes, indent=2), encoding="utf-8")
    except OSError:
        pass


def merged_slugs(repo_slugs):
    """slugs whose PR was merged, via `gh`. `gh` is the authority on `done` —
    a deleted branch is not proof of a merge. Only repos that have a lane
    branch are queried, so the network cost scales with in-flight work, not
    repo count. Returns None if `gh` is unavailable — `done` is then simply
    not derived this run (the next run with `gh` present will catch up)."""
    if not run(["gh", "--version"]):
        return None
    merged = set()
    for repo in repo_slugs:
        # cwd=repo lets `gh` auto-detect the repo — no --repo needed.
        raw = run([
            "gh", "pr", "list", "--state", "merged",
            "--limit", "100", "--json", "headRefName",
            "--jq", ".[].headRefName",
        ], cwd=repo)
        for branch in raw.splitlines():
            slug = branch_to_slug(branch.strip())
            if slug:
                merged.add(slug)
    return merged


# ---- reconcile -------------------------------------------------------------

def compute_status(slug, current, active, merged):
    """The derivation. Precedence: cancelled > done (sticky-or-derived) > active
    > sticky draft > open. Both `cancelled` and `done` are sticky terminal
    states the user can pin from tix (`x`/`d`); they trump every live signal so
    a closed-out ticket whose branch still exists stays closed until reopened."""
    if current.lower() in ("cancelled", "canceled"):
        return "cancelled"  # normalises legacy `Cancelled`/`Canceled` too
    if current.lower() == "done":
        return "done"       # sticky — user marked it (no PR required)
    if merged is not None and slug in merged:
        return "done"
    if slug in active:
        return "active"
    if current.lower() == "active":
        return "active"  # sticky — user pinned it from tix (`i`), no lane required
    if current.lower() == "draft":
        return "draft"  # sticky seed — see module docstring (also normalises
        # a legacy capitalised `Draft` to the lowercase vocab)
    return "open"


def reconcile(only_slug=None):
    tickets = find_tickets()
    if only_slug is not None:
        tickets = [t for t in tickets if slug_of(t) == only_slug]
        if not tickets:
            print(f"ticket-status-sync: no ticket for slug '{only_slug}'",
                  file=sys.stderr)
            return

    repos = discover_repos()
    active, repo_slugs = active_signals(repos)
    # Fast path (`wt` spawn): skip the `gh` network pass — a freshly spawned
    # lane is becoming `active`, never `done`.
    merged = None if only_slug is not None else merged_slugs(repo_slugs)
    # Full sweep also refreshes the lane sidecar tix consumes for in-progress
    # state. Fast path skips it to avoid stale entries (one slug touched, others
    # would diverge).
    if only_slug is None:
        write_lanes(lane_info(repos))

    changed = []
    unchanged = 0
    for path in tickets:
        slug = slug_of(path)
        parsed = read_status(path.read_text(encoding="utf-8").splitlines(keepends=True))
        if parsed is None:
            continue
        current = parsed[0]
        new = compute_status(slug, current, active, merged)
        if new != current:
            write_status(path, new)
            changed.append((new, current or "(none)", path))
        else:
            unchanged += 1

    rel = lambda p: p.relative_to(TICKETS_DIR)
    if changed:
        print(f"ticket-status-sync: {len(changed)} changed")
        for new, old, path in changed:
            print(f"  {new:<7} ← {old:<8} {rel(path)}")
    else:
        print("ticket-status-sync: no changes")
    if unchanged and only_slug is None:
        print(f"ticket-status-sync: {unchanged} unchanged")
    if merged is None and only_slug is None:
        print("ticket-status-sync: note — `gh` unavailable, `done` not derived "
              "this run")


def main():
    only_slug = sys.argv[1] if len(sys.argv) > 1 else None
    if not TICKETS_DIR.is_dir():
        print(f"ticket-status-sync: no ticket directory at {TICKETS_DIR}",
              file=sys.stderr)
        return 0  # never block the hook
    try:
        reconcile(only_slug)
    except Exception as exc:  # a hook must never crash its host
        print(f"ticket-status-sync: skipped ({exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
