"""KLC-174 step-3: behaviours pinned by deleted KLC-114/KLC-115 tests that do NOT
die with the Evidence replay and the progress ledger.

Where each assertion came from (the source files are deleted in this step):
- impl_plan_check `Affected:` matcher  <- tests/test_klc114_affected_paths.py
- VERIFY field extraction with a mid-line fence <- tests/test_klc114_field_and_table_safety.py
- directory-only test-path classification, language agnostic
  <- tests/test_klc114_scope.py (via step_ledger._out_of_scope) and
     tests/test_klc114_language_agnostic.py
- TDD-order verdict text carried verbatim, no-commit is not red
  <- tests/test_klc114_tdd_order_verdict.py, tests/test_klc114_unverified_reasons.py
  (now asserted on `step_state.derive`, which replaced `step_ledger.judge_step`)
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
for _p in (str(FW / "core" / "skills"), str(FW / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import impl_plan_check as ipc  # noqa: E402
import klc114_helpers as h  # noqa: E402
import tdd_order as td  # noqa: E402
import test_conventions as tc  # noqa: E402


# ---- impl_plan_check: the Affected notation (annotation stripping) --------

def test_affected_annotation_is_stripped_inside_and_outside_backticks():
    assert ipc._split_paths("`core/skills/x.py (new)`") == ["core/skills/x.py"]
    assert ipc._split_paths("`core/skills/x.py` (new)") == ["core/skills/x.py"]



# ---- impl_plan_check: VERIFY field with a literal fence mid-line (AC-13) ----

def test_verify_field_backtick_fence_mid_line_does_not_erase_later_fields():
    body = textwrap.dedent('''
        - Goal: do the thing
        - RED: `tests/test_x.py::test_thing`
        - GREEN: implement it
        - VERIFY: `sh -c "echo '```' && echo 2 passed"`
        - COMMIT: `KLC-XXX step-1: do the thing`
        - Affected: `core/skills/x.py`
        - Interfaces: none
        - Expected: `2 passed`
        - Rollback: none
        - Depends on: none

        ```python
        # sketch
        pass
        ```
    ''')
    fields = ipc.extract_step_fields(body)
    assert fields["expected"] == "`2 passed`"
    assert fields["affected"] == ["core/skills/x.py"]
    assert fields["commit"] == "`KLC-XXX step-1: do the thing`"
    assert "```" in fields["verify"] and "2 passed" in fields["verify"]


# ---- test_conventions: directory-only, language-agnostic classification ----

def test_in_test_directory_is_directory_only_and_language_agnostic():
    for path in ("tests/test_x.py", "src/test/java/FooTest.java", "web/__tests__/a.ts",
                 "app/src/androidTest/Foo.kt", "spec/foo_spec.rb"):
        assert tc.in_test_directory(path), path
    # a bare sibling-none basename OUTSIDE a test directory carries no test segment
    for path in ("core/skills/conftest.py", "src/tests.rs", "core/skills/x.py"):
        assert not tc.in_test_directory(path), path


# ---- step_state.derive: TDD verdict text and absence of commits ----

def _plan(ticket: str) -> str:
    return "# Implementation plan\n\n" + h.step_plan("step-1", affected="`core/skills/x.py`")


def test_impl_before_red_commit_is_blocked_with_tdd_orders_own_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-TO01"
    h.make_ticket(tmp_path, ticket, "M", _plan(ticket))
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"core/skills/x.py": "# impl, no test committed first"},
             f"{ticket} step-1: add impl")
    ok, expected_reason = td.verify_step(ticket, 1, repo)
    assert not ok, "fixture must actually violate red-before-green"

    import step_state
    rec = step_state.derive(ticket, repo)[0]
    assert rec["state"] == "blocked"
    assert expected_reason in rec["reason"]       # verbatim, never re-paraphrased


def test_no_attributable_commits_is_pending_never_red_or_green(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-UR03"
    h.make_ticket(tmp_path, ticket, "M", _plan(ticket))
    repo = h.make_repo(tmp_path, "repo3")
    h.commit(repo, {"README.md": "unrelated"}, "unrelated commit, no step key")

    import step_state
    assert step_state.derive(ticket, repo)[0]["state"] == "pending"


def test_non_python_test_commit_counts_as_red(tmp_path, monkeypatch):
    """Language agnostic: a Go `_test.go` file under a test-less directory name is
    still classified as the step's test commit (red), not as implementation."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-LA01"
    h.make_ticket(tmp_path, ticket, "M", _plan(ticket))
    repo = h.make_repo(tmp_path, "repo4")
    h.commit(repo, {"pkg/foo_test.go": "package foo\n"}, f"{ticket} step-1: add test")

    import step_state
    rec = step_state.derive(ticket, repo)[0]
    assert rec["state"] == "red" and rec["red_commit"]
