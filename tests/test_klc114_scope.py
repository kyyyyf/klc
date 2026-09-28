"""KLC-114 step-2/step-6: step_ledger._out_of_scope — a step's commits are
compared against its declared `Affected:` surface, git-derived rather than
builder-reported (AC-2); and the Q-004 negative twin, wired at step-6 —
a scope-violation verdict is report-only and never a new build-ack hard
breach (AC-11)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc114_helpers as h  # noqa: E402
import step_ledger as sl  # noqa: E402
import tdd_order as td  # noqa: E402


def test_commit_outside_affected_and_not_tests_is_scope_violation(tmp_path):
    """AC-2: a step's commit touches a path outside its declared `Affected:`
    list that carries no `tests` segment → recorded scope-violation naming
    that exact path, derived from the commit's own touched files, not from
    any builder-reported list."""
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, "KLC-SC01 step-1: add test")
    h.commit(repo, {"core/skills/x.py": "# impl",
                    "core/skills/undeclared_helper.py": "# stray"},
             "KLC-SC01 step-1: add impl")

    commits = td.step_commits("KLC-SC01", 1, repo)
    touched = sl._touched_paths(commits, repo)
    declared = ["`core/skills/x.py`"]

    stray = sl._out_of_scope(touched, declared)

    assert stray == ["core/skills/undeclared_helper.py"]


def test_ack_still_passes_when_scope_violation_report_only(tmp_path, monkeypatch):
    """AC-11/Q-004 negative twin: a step whose commits produce a
    scope-violation verdict still leaves `can_complete_build` returning a
    truthy verdict — the pass is report-only, not a new hard breach."""
    import json
    from core.skills.phase_completion import can_complete_build

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-SV01"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:ack-needed",
        "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        "---\nticket: KLC-SV01\nkind: tech\n---\n\n## Acceptance Criteria\n\n"
        "## Estimate\n- total: 1\n", encoding="utf-8")
    (ticket_dir / "test-plan.md").write_text(
        "---\nticket: KLC-SV01\nkind: test-plan\n---\n\n## Acceptance coverage\n\n"
        "## Edge cases\n- n/a\n", encoding="utf-8")
    (ticket_dir / "build-log.md").write_text(
        "# Build log — KLC-SV01\n\n## Evidence\n\n"
        "```\n$ sh -c \"echo 2 passed\"\n2 passed\n```\n", encoding="utf-8")
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="`sh -c \"echo 2 passed\"`", expected="`2 passed`",
        affected="`core/skills/x.py`")
    (ticket_dir / "impl-plan.md").write_text(plan, encoding="utf-8")

    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")
    h.commit(repo, {"core/skills/x.py": "# impl",
                    "core/skills/undeclared_helper.py": "# stray"},
             f"{ticket} step-1: add impl")

    ok, msg = can_complete_build(ticket, repo=str(repo))

    assert ok, msg


def test_bare_sibling_none_basename_outside_a_test_directory_is_scope_violation(tmp_path):
    """AC-2/AC-13 (review round 1, MEDIUM; drift F-1): a `conftest.py`/
    `tests.rs`/`test.rs`-shaped basename OUTSIDE any declared test
    directory still carries no `tests` path segment, so it must still be
    a scope-violation — `test_conventions.is_test_path`'s "sibling: none"
    NAME signal (D-114-8) unconditionally trusts these basenames even
    outside a test directory, which is broader than AC-2/AC-13's literal
    "has no tests path segment" wording (D-114-10 supersedes D-114-8:
    `_out_of_scope` now uses the new, directory-only
    `test_conventions.in_test_directory`, not `is_test_path`)."""
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, "KLC-SC02 step-1: add test")
    h.commit(repo, {"core/skills/x.py": "# impl",
                    "core/skills/conftest.py": "# stray, sibling-none, outside tests/",
                    "src/tests.rs": "# stray, sibling-none, outside tests/"},
             "KLC-SC02 step-1: add impl")

    commits = td.step_commits("KLC-SC02", 1, repo)
    touched = sl._touched_paths(commits, repo)
    declared = ["`core/skills/x.py`"]

    stray = sl._out_of_scope(touched, declared)

    assert set(stray) == {"core/skills/conftest.py", "src/tests.rs"}
