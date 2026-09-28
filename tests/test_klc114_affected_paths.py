"""KLC-114 step-2: impl_plan_check.affected_allows — a normalising matcher
for the `Affected:` surface so an annotation, a glob, a directory or a bare
basename entry is never reported as scope drift (AC-2)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import impl_plan_check as ipc  # noqa: E402


def test_annotation_is_stripped_inside_and_outside_backticks():
    """AC-2/F-1: a trailing `(new)`/`(modified)` annotation is stripped the
    same way whether it sits INSIDE the backtick-captured group (the common
    real spelling) or outside it — revision-1 only stripped the latter."""
    inside = ipc._split_paths("`core/skills/step_ledger.py (new)`")
    outside = ipc._split_paths("`core/skills/step_ledger.py` (new)")
    assert inside == ["core/skills/step_ledger.py"]
    assert outside == ["core/skills/step_ledger.py"]


def test_glob_directory_and_basename_entries_allow_the_paths_they_name():
    """AC-2: a glob, a directory prefix and a bare basename entry each allow
    the paths they name."""
    assert ipc.affected_allows("core/skills/step_ledger.py", ["`core/skills/*.py`"])
    assert ipc.affected_allows("tests/fixtures/klc114-dogfood/KLC-113/impl-plan.md",
                               ["`tests/fixtures/klc114-dogfood/`"])
    assert ipc.affected_allows("core/skills/settings.py", ["`settings.py`"])


def test_a_genuinely_undeclared_path_is_still_rejected():
    """AC-2 gate-bites twin: the matcher must discriminate, not accept
    everything — a path nothing declares is still rejected."""
    assert not ipc.affected_allows(
        "core/skills/drift_review.py",
        ["`core/skills/spec_selfcheck.py`", "`core/skills/ac_test_coverage.py`"])
