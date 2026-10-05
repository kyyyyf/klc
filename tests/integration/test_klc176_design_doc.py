"""KLC-176 step-2 (AC-3, AC-11): the design phase writes ONE design.md.

Old tickets keep design/options.md; every reader looks at design.md first and
falls back to the legacy path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW))
sys.path.insert(0, str(_FW / "core" / "skills"))

from core.shared import yaml as project_yaml  # noqa: E402
import items_verify  # noqa: E402
import provenance  # noqa: E402
from core.shared import paths as shared_paths  # noqa: E402
from core.skills.phase_completion import can_complete  # noqa: E402

_NEW_DOC = """\
# Design

## Options

### Option A - inline
> [!DECISION D-A] evidence=assumed if-false=x
> a decision made only inside the rejected option

### Option B - hook (recommended)

Picked: Option B

## Design
The chosen design.

## Consequences
Status: Proposed. Good: simple. Bad: one more hook.

## Decisions
> [!DECISION D-B] evidence=assumed if-false=y
> the picked decision
"""

_LEGACY_DOC = (
    "## Option A - do X\n\n> [!DECISION D-A] evidence=assumed if-false=x\n> a\n\n"
    "## Option B - do Y (recommended: true)\n\n"
    "> [!DECISION D-B] evidence=assumed if-false=y\n> b\n"
)

_PLAN = (
    "## step-1 - do the thing\n- **Goal:** implement\n- RED: not applicable\n"
    "- **Interfaces:** `def f() -> None`\n- **Expected:** f runs\n"
    "- **VERIFY:** pytest\n- **COMMIT:** KLC-X step-1: do the thing\n"
    "- **Affected:** src/x.py\n- **Code sketch:**\n```python\npass\n```\n"
)


def _seed(tmp_path: Path, ticket: str, files: dict[str, str]) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "design:ack-needed",
        "track": "M", "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1,
                                   "manual": 0, "total": 4},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (tdir / "spec.md").write_text(
        f"---\nticket: {ticket}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
        "## Goals\nDo M thing.\n## Acceptance Criteria\n- [ ] AC-1: does thing.\n"
        "## Affected\ntest_module: core/test.py, src=core/test.py:1\n"
        "## Estimate\ncomplexity: 2\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 4\n",
        encoding="utf-8")
    for rel, body in files.items():
        p = tdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tdir


def test_design_outputs_are_design_md_and_impl_plan():
    phases = project_yaml.load(_FW / "config" / "phases.yml")
    by_id = {p["id"]: p for p in phases["phases"]}
    assert by_id["design"]["outputs"] == ["design.md", "impl-plan.md"]
    # KLC-179: detailed-test-plan was dropped; build reads the design's impl-plan.
    assert "detailed-test-plan" not in by_id
    assert "design/options.md" not in by_id["build"]["inputs"]
    jira = project_yaml.load(_FW / "config" / "jira.yml")
    assert jira["artifacts"]["paths"]["design"] == "design.md"


def test_design_doc_path_prefers_new_then_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = _seed(tmp_path, "KLC-960", {"design/options.md": _LEGACY_DOC})
    assert shared_paths.design_doc_path("KLC-960") == tdir / "design" / "options.md"
    (tdir / "design.md").write_text(_NEW_DOC, encoding="utf-8")
    assert shared_paths.design_doc_path("KLC-960") == tdir / "design.md"
    # nothing at all: the legacy path, which the generic gate reports as missing design.md
    empty = _seed(tmp_path, "KLC-961", {})
    assert shared_paths.design_doc_path("KLC-961") == empty / "design" / "options.md"


def test_readers_prefer_design_md_then_fall_back_to_options(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-962", {"design.md": _NEW_DOC})
    channels, _ = provenance.load_bearing("KLC-962")
    assert channels == {"D-B": "document"}      # D-A sits in the rejected ### option
    _seed(tmp_path, "KLC-963", {"design/options.md": _LEGACY_DOC})
    channels, _ = provenance.load_bearing("KLC-963")
    assert channels == {"D-B": "document"}      # archived layout still read
    assert "design.md" in items_verify.FACT_SOURCE_ARTIFACTS
    assert "design/options.md" in items_verify.FACT_SOURCE_ARTIFACTS


def test_design_ack_blocked_without_design_md(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-964", {"impl-plan.md": _PLAN})
    ok, msg = can_complete("KLC-964", "design")
    assert not ok and "design.md" in msg


def test_design_ack_needs_two_options_and_a_pick_in_design_md(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    no_dec = _NEW_DOC.split("## Decisions")[0] + "## Decisions\nnone\n"
    _seed(tmp_path, "KLC-965", {"impl-plan.md": _PLAN, "design.md": no_dec})
    ok, msg = can_complete("KLC-965", "design")
    assert ok, msg
    one = _NEW_DOC.replace("### Option A - inline", "### Plain A")
    _seed(tmp_path, "KLC-966", {"impl-plan.md": _PLAN, "design.md": one})
    ok, msg = can_complete("KLC-966", "design")
    assert not ok and "Options" in msg
    nopick = _NEW_DOC.replace("Picked: Option B", "")
    _seed(tmp_path, "KLC-967", {"impl-plan.md": _PLAN, "design.md": nopick})
    ok, msg = can_complete("KLC-967", "design")
    assert not ok and "Picked" in msg


def test_legacy_options_md_still_satisfies_design_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed(tmp_path, "KLC-968", {"impl-plan.md": _PLAN,
                                "design/options.md": "# options\n\n## Option A\nx\n"})
    ok, msg = can_complete("KLC-968", "design")
    assert ok, msg


def test_jira_links_use_design_md_then_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import jira_artifacts

    class Cfg:
        artifact_paths = {"design": "design.md"}
        comment_links = True

        @staticmethod
        def artifact_link_url(p):
            return "http://x/" + p

    _seed(tmp_path, "KLC-969", {"design/options.md": _LEGACY_DOC})
    assert "design/options.md" in jira_artifacts.build_artifact_links("KLC-969", Cfg)
    _seed(tmp_path, "KLC-970", {"design.md": _NEW_DOC})
    assert "design.md" in jira_artifacts.build_artifact_links("KLC-970", Cfg)


def test_design_prompts_name_design_md_and_adr_agent_is_retired():
    agents = _FW / "core" / "agents"
    design = (agents / "design.md").read_text(encoding="utf-8")
    assert "design.md" in design and "## Consequences" in design
    assert "design/options.md" not in design and "adr.md" not in design
    assert len(design.encode("utf-8")) <= 12000
    assert not (agents / "adr.md").exists()
    assert not (_FW / "core" / "templates" / "ADR.md.j2").exists()
    assert not (_FW / "klc-plugin" / "agents" / "adr.md").exists()
    for name in ("impl", "retrospective", "test-planner", "design-scout"):
        text = (agents / f"{name}.md").read_text(encoding="utf-8")
        assert "design/adr.md" not in text, name
        assert "design/options.md" not in text, name
    retro = (agents / "retrospective.md").read_text(encoding="utf-8")
    assert "design.md" in retro
