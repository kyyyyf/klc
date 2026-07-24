"""KLC-080: docs/epics.md must exist and accurately describe the epic layer.

The guide is the user-facing entry for the KLC-077/078/079 epic feature. These
are substring checks on the doc's OWN text — they pin its content and vocabulary
(the `board --epic` view, the `--epic` / `--blocked-by` flags, the three
dependency points, a link to the spec) so an accidental deletion or rename inside
the doc is caught. They are not code-drift detection: they would still pass if a
point were renamed in the code but not here. A separate check guards against the
retired `decompose` indexing-agent phrasing reappearing (KLC-074 replaced it with
the deterministic `modules_build`).
"""
from pathlib import Path

# tests/test_epics_doc.py → parents[1] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS = _REPO_ROOT / "docs"
_EPICS = _DOCS / "epics.md"


def test_epics_doc_exists():
    assert _EPICS.is_file(), f"missing guide: {_EPICS}"


def test_epics_doc_covers_the_view_and_flags():
    text = _EPICS.read_text(encoding="utf-8")
    for needle in ("board --epic", "--epic", "--blocked-by", "meta.epic",
                   "meta.blocked_by"):
        assert needle in text, f"epics.md must document {needle!r}"


def test_epics_doc_lists_the_three_points():
    text = _EPICS.read_text(encoding="utf-8")
    for point in ("design-accepted", "integrated", "archived"):
        assert point in text, f"epics.md must document the point {point!r}"
    assert "passed" in text, "epics.md must document the `passed` condition"


def test_epics_doc_links_the_spec():
    text = _EPICS.read_text(encoding="utf-8")
    assert "20260724_epic_feature_impl_plan.md" in text, (
        "epics.md must link the epic spec (docs/20260724_epic_feature_impl_plan.md)"
    )


def test_no_doc_lists_the_retired_decompose_indexing_agent():
    """KLC-074 retired the LLM `decompose` agent; the module SET is now built
    deterministically by modules_build. No doc should still list it as an
    `init --auto` indexing agent (the old `inventory / decompose / docgen`
    phrasing)."""
    stale = ("decompose / docgen", "inventory / decompose")
    for md in _DOCS.glob("*.md"):
        body = md.read_text(encoding="utf-8")
        for phrase in stale:
            assert phrase not in body, (
                f"{md.name} still lists the retired decompose indexing agent "
                f"({phrase!r}); KLC-074 replaced it with modules_build"
            )
    readme = _REPO_ROOT / "README.md"
    for phrase in stale:
        assert phrase not in readme.read_text(encoding="utf-8"), (
            f"README.md still lists the retired decompose indexing agent ({phrase!r})"
        )
