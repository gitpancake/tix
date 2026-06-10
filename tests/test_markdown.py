"""reflow_markdown / preview_lines — pure-function tests, no curses."""
from tix.tui import preview_lines, reflow_markdown


def test_reflow_joins_paragraph_lines():
    src = "The consumer runs prefetch=1, one task\nin-flight per worker.\n"
    assert reflow_markdown(src) == (
        "The consumer runs prefetch=1, one task in-flight per worker.\n"
    )


def test_reflow_keeps_blank_line_separated_paragraphs():
    src = "first para\nstill first\n\nsecond para\n"
    assert reflow_markdown(src) == "first para still first\n\nsecond para\n"


def test_reflow_joins_bullet_continuations_but_not_siblings():
    src = "- one bullet that\n  wraps onto a second line\n- two\n"
    assert reflow_markdown(src) == (
        "- one bullet that wraps onto a second line\n- two\n"
    )


def test_reflow_passes_fences_verbatim():
    src = "```bash\npytest -q\n  indented\n```\n"
    assert reflow_markdown(src) == src


def test_reflow_passes_frontmatter_headings_quotes_verbatim():
    src = "---\ntitle: x\n---\n## Context\n> quoted\nline one\nline two\n"
    assert reflow_markdown(src) == (
        "---\ntitle: x\n---\n## Context\n> quoted\nline one line two\n"
    )


def test_reflow_keeps_thematic_break():
    src = "before\n\n---\n\nafter\n"
    assert reflow_markdown(src) == src


def test_preview_heading_drops_hashes():
    rows = preview_lines("## Context\n", 40)
    assert ("heading", "Context") in rows


def test_preview_bullet_marker_and_hanging_indent():
    rows = preview_lines("- " + "word " * 12 + "\n", 30)
    texts = [t for kind, t in rows if t]
    assert texts[0].startswith("• word")
    assert all(t.startswith("  ") for t in texts[1:])
    assert all(len(t) <= 30 for t in texts)


def test_preview_fence_rows_are_code():
    rows = preview_lines("```\npytest -q\n```\n", 40)
    assert rows == [("code", "```"), ("code", "pytest -q"), ("code", "```")]


def test_preview_wraps_reflowed_paragraph_to_width():
    src = "alpha beta gamma\ndelta epsilon zeta\n"
    rows = preview_lines(src, 20)
    assert all(kind == "text" and len(t) <= 20 for kind, t in rows)
    assert " ".join(t for _, t in rows).split() == src.split()
