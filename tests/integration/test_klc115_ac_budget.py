"""KLC-115 step-5: per-node time budget in ac_test_coverage, with the
existing pytest-outcome parser re-homed into a shared helper (AC-10, AC-11,
plus the F-1/D-201 addendum: a skipped node is never a pass).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import ac_test_coverage as acov  # noqa: E402
import verify_runner  # noqa: E402


def _write(root: Path, name: str, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    p.write_text(body, encoding="utf-8")
    return p


def test_per_node_budget_isolates_slow_node_from_siblings(tmp_path, monkeypatch):
    tests_dir = tmp_path / "tests"
    _write(tests_dir, "test_x.py", (
        "import time\n"
        "def test_ac1_a():\n    assert True\n"
        "def test_ac1_b():\n    assert True\n"
        "def test_ac1_slow():\n    time.sleep(2)\n    assert True\n"
    ))
    monkeypatch.setattr(acov.settings, "verify_node_budget", lambda: 1)
    nodes = ["tests/test_x.py::test_ac1_a", "tests/test_x.py::test_ac1_b",
            "tests/test_x.py::test_ac1_slow"]
    states = acov._verify_nodes(nodes, repo=None, tests_root=tests_dir)
    assert states["tests/test_x.py::test_ac1_a"] == (verify_runner.PASSED, "")
    assert states["tests/test_x.py::test_ac1_b"] == (verify_runner.PASSED, "")
    assert states["tests/test_x.py::test_ac1_slow"][0] == verify_runner.UNVERIFIED
    assert states["tests/test_x.py::test_ac1_slow"][1] == "slow"


def test_single_node_request_still_applies_per_node_budget(tmp_path, monkeypatch):
    tests_dir = tmp_path / "tests"
    _write(tests_dir, "test_y.py", (
        "import time\n"
        "def test_ac1_slow():\n    time.sleep(2)\n    assert True\n"
    ))
    monkeypatch.setattr(acov.settings, "verify_node_budget", lambda: 1)
    states = acov._verify_nodes(["tests/test_y.py::test_ac1_slow"], repo=None,
                                tests_root=tests_dir)
    assert states["tests/test_y.py::test_ac1_slow"] == (verify_runner.UNVERIFIED, "slow")


def _setup_check(monkeypatch, tmp_path, ticket, spec_text, test_plan_text, tests_dir):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(spec_text, encoding="utf-8")
    (ticket_dir / "test-plan.md").write_text(test_plan_text, encoding="utf-8")
    monkeypatch.setattr(acov, "_tests_root", lambda: tests_dir)
    monkeypatch.setattr(acov, "_changed_test_files", lambda repo=None: set())
    monkeypatch.setattr(acov.settings, "verify_node_budget", lambda: 1)


def _spec(*ac_ids: str) -> str:
    lines = ["---", "ticket: KLC-AB", "kind: feature", "---", "", "## Acceptance Criteria"]
    for ac in ac_ids:
        lines.append(f"- [ ] {ac}: subject · acts · object · when a thing happens")
    return "\n".join(lines)


def _test_plan(*rows: tuple[str, str]) -> str:
    lines = ["---", "ticket: KLC-AB", "kind: test-plan", "---", "",
            "## Acceptance coverage", "", "| AC | Type | Test location |",
            "| --- | --- | --- |"]
    for ac, loc in rows:
        lines.append(f"| {ac} | unit | {loc} |")
    return "\n".join(lines)


def test_slow_node_classified_unverified_slow_not_weak(tmp_path, monkeypatch):
    tests_dir = tmp_path / "tests"
    _write(tests_dir, "test_x.py", (
        "import time\n"
        "def test_ac1_slow():\n    time.sleep(2)\n    assert True\n"
    ))
    ticket = "KLC-AB01"
    _setup_check(monkeypatch, tmp_path, ticket, _spec("AC-1"),
                _test_plan(("AC-1", "tests/test_x.py::test_ac1_slow")), tests_dir)
    rep = acov.check(ticket, "M", repo=str(tmp_path), run_tests=True)
    assert rep.block_reason is None
    states = {f.ac_id: f.state for f in rep.findings}
    assert states.get("AC-1") == acov.UNVERIFIED
    assert not any("referencing test is a placeholder" in f.message for f in rep.findings)


def test_unverified_slow_excluded_from_weak_count(tmp_path, monkeypatch):
    tests_dir = tmp_path / "tests"
    _write(tests_dir, "test_x.py", (
        "import time, pytest\n"
        "def test_ac1_slow():\n    time.sleep(2)\n    assert True\n"
        "@pytest.mark.skip(reason='not ready')\n"
        "def test_ac2_skip():\n    assert True\n"
    ))
    ticket = "KLC-AB02"
    _setup_check(monkeypatch, tmp_path, ticket, _spec("AC-1", "AC-2"),
                _test_plan(("AC-1", "tests/test_x.py::test_ac1_slow"),
                          ("AC-2", "tests/test_x.py::test_ac2_skip")), tests_dir)
    rep = acov.check(ticket, "M", repo=str(tmp_path), run_tests=True)
    states = {f.ac_id: f.state for f in rep.findings}
    assert states.get("AC-1") == acov.UNVERIFIED
    assert states.get("AC-2") == acov.WEAK
    weak_acs = {f.ac_id for f in rep.findings if f.state == acov.WEAK}
    assert "AC-1" not in weak_acs
    assert "AC-2" in weak_acs


def test_skipped_node_is_unverified_and_still_counts_weak(tmp_path, monkeypatch):
    tests_dir = tmp_path / "tests"
    _write(tests_dir, "test_z.py", (
        "import pytest\n"
        "@pytest.mark.skip(reason='not ready')\n"
        "def test_ac1_skip():\n    assert True\n"
    ))
    states = acov._verify_nodes(["tests/test_z.py::test_ac1_skip"], repo=None,
                                tests_root=tests_dir)
    assert states["tests/test_z.py::test_ac1_skip"] == (verify_runner.UNVERIFIED, "skipped")
    passing = acov._verify_passing(["tests/test_z.py::test_ac1_skip"], repo=None,
                                   tests_root=tests_dir)
    assert passing["tests/test_z.py::test_ac1_skip"] is False


def test_attribute_outcomes_is_the_single_parser_shared_by_both_paths(monkeypatch, tmp_path):
    """F-1 structural guard: `_attribute_outcomes` is the ONLY place a pytest
    outcome token is read; `_verify_passing` and `_verify_nodes` reach the
    SAME verdict for the SAME captured output because they call it, once."""
    node = "tests/test_x.py::test_ac1_a"
    monkeypatch.setattr(acov, "_collect_existing",
                        lambda node_ids, repo, tests_root: set(node_ids))

    def fake_run(cmd, *, budget_s, cwd=None, **kw):
        return verify_runner.Verdict(verify_runner.PASSED, "", "", 0.01,
                                     f"{node} SKIPPED\n1 skipped in 0.01s\n", 0)

    monkeypatch.setattr(acov.verify_runner, "run", fake_run)
    passing = acov._verify_passing([node])
    states = acov._verify_nodes([node])
    assert passing[node] is False
    assert states[node] == (verify_runner.UNVERIFIED, "skipped")
