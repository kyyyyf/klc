"""KLC-048: docs/happy-path.md must exist, fit one screen, and link process.md.

The guide is a one-screen newcomer walkthrough (intake → archived) for a clean
S-track ticket. These checks enforce AC-3: body ≤ 60 lines and a link to the
full contract in docs/process.md.
"""
from pathlib import Path

# tests/integration/test_happy_path_doc.py → parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "docs" / "happy-path.md"

# Body = every line after the leading H1 title line.
_MAX_BODY_LINES = 60


def _body_lines(text: str) -> list[str]:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[1:]
    return lines


def test_happy_path_doc_exists():
    assert _DOC.is_file(), f"missing guide: {_DOC}"


def test_happy_path_body_within_one_screen():
    body = _body_lines(_DOC.read_text(encoding="utf-8"))
    assert len(body) <= _MAX_BODY_LINES, (
        f"happy-path.md body is {len(body)} lines; must be <= {_MAX_BODY_LINES}"
    )


def test_happy_path_links_process_doc():
    text = _DOC.read_text(encoding="utf-8")
    assert "process.md" in text, "happy-path.md must link to docs/process.md"
