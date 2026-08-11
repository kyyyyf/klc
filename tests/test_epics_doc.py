"""KLC-101 (repoints KLC-080): the epic-layer guide was absorbed into the
`## Epics` section of `docs/process.md` (it is no longer a standalone
`docs/epics.md`).

These are substring checks on the section's OWN text — they pin its content and
vocabulary (the `board --epic` view, the `--epic` / `--blocked-by` flags, the
three dependency points, a link to the spec) so an accidental deletion or rename
inside the doc is caught. They are not code-drift detection. A separate check
guards against the retired `decompose` indexing-agent phrasing reappearing
(KLC-074 replaced it with the deterministic `modules_build`).
"""
from pathlib import Path

# tests/test_epics_doc.py → parents[1] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS = _REPO_ROOT / "docs"
_PROCESS = _DOCS / "process.md"


def test_old_standalone_epics_doc_is_gone():
    assert not (_DOCS / "epics.md").exists(), (
        "docs/epics.md was absorbed into docs/process.md#epics and must be gone"
    )


def test_process_doc_has_epics_section():
    text = _PROCESS.read_text(encoding="utf-8")
    assert "## Epics" in text, "docs/process.md must carry an ## Epics section"


def test_epics_section_covers_the_view_and_flags():
    text = _PROCESS.read_text(encoding="utf-8")
    for needle in ("board --epic", "--epic", "--blocked-by", "meta.epic",
                   "meta.blocked_by"):
        assert needle in text, f"process.md #epics must document {needle!r}"


def test_epics_section_lists_the_three_points():
    text = _PROCESS.read_text(encoding="utf-8")
    for point in ("design-accepted", "integrated", "archived"):
        assert point in text, f"process.md #epics must document the point {point!r}"
    assert "passed" in text, "process.md #epics must document the `passed` condition"


def test_epics_section_links_the_spec():
    text = _PROCESS.read_text(encoding="utf-8")
    assert "20260724_epic_feature_impl_plan.md" in text, (
        "process.md #epics must link the epic spec "
        "(docs/20260724_epic_feature_impl_plan.md)"
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
