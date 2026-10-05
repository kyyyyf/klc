"""KLC-176 step-1 (AC-4): specs of kind bug need the four bug sections and a regression-test AC."""
import json
import subprocess
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills import spec_selfreview  # noqa: E402
from core.skills.phase_completion import (  # noqa: E402
    can_complete_discovery,
    can_complete_discovery_lite,
)

_BUG_SECTIONS = """\
## Reproduction
Run `klc ack KLC-X` twice in a row.

## Observed vs expected
Observed: the second ack crashes. Expected: it is a no-op.

## Root cause
The ack handler re-reads a cleared lock.

## Why existing tests missed it
No test acked twice.

"""

_AC_OK = "- [ ] AC-1: ack · twice · once · no crash, proven by a new regression test test_double_ack\n"
_AC_NO_REG = "- [ ] AC-1: ack · twice · once · no crash\n"

_APPROACHES = """\
## Approaches
- Option A: guard the lock — small
- Option B: rewrite the handler — large

Picked: Option A — smaller diff

"""


def _spec(kind, sections=_BUG_SECTIONS, ac=_AC_OK, approaches=_APPROACHES, key="KLC-B"):
    return (f"---\nticket: {key}\nkind: {kind}\nauthority: agent\nrisk_tags: []\n---\n\n"
            f"## Goals\nFix the double ack crash in the handler.\n\n"
            f"## Acceptance Criteria\n{ac}\n{sections}{approaches}"
            "## Affected\ntest_module: core/test.py, src=core/test.py:1\n\n"
            "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n")


_PLAN = """\
## step-1 — do the thing

- **Goal:** implement the feature
- RED: not applicable
- **Interfaces:** `def f() -> None`
- **Expected:** f runs
- **VERIFY:** pytest
- **COMMIT:** KLC-X step-1: do the thing
- **Affected:** src/x.py
"""


def _ticket(tmp_path, key, kind, spec, track="S"):
    d = tmp_path / ".klc" / "tickets" / key
    d.mkdir(parents=True)
    est = ({"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3}
           if track == "S" else
           {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4})
    meta = {"ticket": key, "kind": kind, "track": track, "route_hint": track,
            "phase": "discovery:work", "estimate": est,
            "affected_modules": ["test_module"], "layer": "code"}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "spec.md").write_text(spec.replace("ticket: KLC-B\n", f"ticket: {key}\n", 1), encoding="utf-8")
    if track == "S":
        (d / "impl-plan.md").write_text(_PLAN, encoding="utf-8")
    return d


def _names(vs):
    return " | ".join(v["phrase"] for v in vs)


def test_detector_flags_each_missing_section_and_the_regression_ac():
    assert spec_selfreview.bug_shape_violations(_spec("bug")) == []
    for head in ("Reproduction", "Observed vs expected", "Root cause",
                 "Why existing tests missed it"):
        text = _spec("bug").replace(f"## {head}", "## Other")
        assert head in _names(spec_selfreview.bug_shape_violations(text)), head
    vs = spec_selfreview.bug_shape_violations(_spec("bug", ac=_AC_NO_REG))
    assert "regression" in _names(vs).lower()


def test_detector_edge_cases():
    empty = _BUG_SECTIONS.replace("The ack handler re-reads a cleared lock.\n", "")
    assert "Root cause" in _names(spec_selfreview.bug_shape_violations(_spec("bug", sections=empty)))
    lower = _BUG_SECTIONS.replace("## Root cause", "## ROOT CAUSE")
    assert spec_selfreview.bug_shape_violations(_spec("bug", sections=lower)) == []
    fenced = "```\n" + _BUG_SECTIONS + "```\n"
    assert spec_selfreview.bug_shape_violations(_spec("bug", sections=fenced))


def test_bug_spec_missing_sections_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket(tmp_path, "KLC-B01", "bug", _spec("bug", sections=""))
    ok, msg = can_complete_discovery_lite("KLC-B01")
    assert not ok and "reproduction" in msg.lower()
    _ticket(tmp_path, "KLC-B02", "bug", _spec("bug", sections=""), track="M")
    ok, msg = can_complete_discovery("KLC-B02")
    assert not ok and "reproduction" in msg.lower()


def test_bug_spec_without_regression_ac_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket(tmp_path, "KLC-B03", "bug", _spec("bug", ac=_AC_NO_REG))
    ok, msg = can_complete_discovery_lite("KLC-B03")
    assert not ok and "regression" in msg.lower()


def test_tech_spec_is_not_affected(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket(tmp_path, "KLC-B04", "tech", _spec("tech", sections="", ac=_AC_NO_REG))
    ok, msg = can_complete_discovery_lite("KLC-B04")
    assert ok, msg
    _ticket(tmp_path, "KLC-B05", "feature", _spec("feature", sections="", ac=_AC_NO_REG))
    ok, msg = can_complete_discovery_lite("KLC-B05")
    assert ok, msg


def test_complete_bug_spec_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _ticket(tmp_path, "KLC-B06", "bug", _spec("bug"))
    ok, msg = can_complete_discovery_lite("KLC-B06")
    assert ok, msg
    _ticket(tmp_path, "KLC-B07", "bug", _spec("bug"), track="M")
    ok, msg = can_complete_discovery("KLC-B07")
    assert ok, msg


def test_cli_prints_bug_shape_as_warning(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(_spec("bug", sections=""), encoding="utf-8")
    r = subprocess.run([sys.executable, str(_FW_ROOT / "core/skills/spec_selfreview.py"),
                        "--file", str(f)], capture_output=True, text=True)
    assert r.returncode == 0  # scan_spec exit code unchanged; bug shape is warn-only in the CLI
    assert "bug_shape" in r.stdout


# ---------------------------------------------------------------- round 2
def test_bare_test_identifier_is_not_a_regression_test_ref():
    assert not spec_selfreview._names_regression_test("uses test_mode flag")
    assert spec_selfreview._names_regression_test("covered by tests/foo/test_bar.py::test_x")
    assert spec_selfreview._names_regression_test("see test_bar_test.py or foo_test.py")
    assert spec_selfreview._names_regression_test("add a regression test for it")


def test_spec_kind_reads_quoted_commented_and_only_frontmatter():
    assert spec_selfreview.spec_kind('---\nkind: "bug"\n---\nbody') == "bug"
    assert spec_selfreview.spec_kind("---\nkind: bug # c\n---\nbody") == "bug"
    assert spec_selfreview.spec_kind("---\nkind: 'Bug'\n---\n") == "bug"
    assert spec_selfreview.spec_kind("# Title\nkind: bug\n") == ""
    assert spec_selfreview.spec_kind("---\nid: x\n---\nkind: bug\n") == ""
