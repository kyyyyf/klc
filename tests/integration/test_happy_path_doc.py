"""KLC-101 (repoints KLC-048): the newcomer happy-path walkthrough now lives IN
the consolidated docs, not a standalone `docs/happy-path.md`.

The one-screen intake→archived walk for a clean S-track ticket was absorbed into
the root README (the end-to-end usage scenario) and the `## Verbs` "Happy path"
block of `docs/process.md`. These checks pin that quickstart's new home so the
newcomer path stays documented and links to the full process contract.
"""
from pathlib import Path

# tests/integration/test_happy_path_doc.py → parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_README = _REPO_ROOT / "README.md"
_PROCESS = _REPO_ROOT / "docs" / "process.md"


def test_old_standalone_happy_path_doc_is_gone():
    """The standalone one-screen guide was absorbed and deleted."""
    assert not (_REPO_ROOT / "docs" / "happy-path.md").exists(), (
        "docs/happy-path.md was absorbed into README + docs/process.md and must be gone"
    )


def test_readme_carries_the_quickstart_walk():
    """The intake→go quickstart walk lives in the README."""
    text = _README.read_text(encoding="utf-8")
    assert "klc intake" in text and "klc go" in text, (
        "README must carry the intake→go quickstart walk"
    )
    assert "docs/process.md" in text, "README must link the full contract in process.md"


def test_process_doc_carries_the_happy_path_block():
    """docs/process.md carries the ack-only happy-path block for a clean S ticket."""
    text = _PROCESS.read_text(encoding="utf-8")
    assert "Happy path" in text, "process.md must carry the Happy path block"
    # The load-bearing rule: a forward ack also advances, so the walk is ack-only.
    assert "ack-only" in text, "the happy-path block must state the ack-only rule"
