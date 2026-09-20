"""tests/integration/test_klc126_sweep_regression.py — KLC-126 step-2 AC-7:
a regression sweep over every real `<TICKET> step-<N>` commit group already
in this repository's own git history, proving the step-1 fix produces the
SAME `classify()` verdict as the pre-fix `--name-only` logic for every real
commit — 0 behavioural flips, mirroring KLC-109 round-4's own 195-group
sweep (recorded in `.klc/tickets/KLC-109/review/code-review.md`'s "Evidence
re-run" section, not itself committed to the repo).

Skip-if-unavailable discipline follows `tests/integration/test_klc124_dogfood_no_c_language.py`
(degrades to `pytest.skip`, never a false regression, when the live
checkout cannot answer the question — e.g. a shallow clone with no history).

`_old_classify` below is a FROZEN copy of the pre-fix (`9da9889`)
`--name-only` + tree-absence commit-listing logic, kept LOCAL to this test
file for comparison purposes only — it must never be imported from
production code, so step-1's fix cannot regress by this test accidentally
re-importing stale logic.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.tdd_order import classify as _new_classify  # noqa: E402
import test_conventions as _tc  # noqa: E402

_REPO = Path(os.environ.get("PROJECT_ROOT", _FW_ROOT))
_GROUP_RE = re.compile(r"^([A-Za-z]+-\d+)\s+step-(\d+)")


def _git(args, repo):
    r = subprocess.run(["git"] + args, capture_output=True, text=True,
                        cwd=str(repo), timeout=30)
    return r.stdout if r.returncode == 0 else ""


def _old_classify(sha: str, repo: Path) -> str:
    """Frozen copy of the PRE-FIX (9da9889) commit-listing logic — comparison
    baseline only, never imported from production code."""
    out = _git(["show", "--name-only", "--format=", sha], repo)
    files = [f.strip() for f in out.splitlines() if f.strip()]
    if not files:
        return "impl"
    table = _tc.active_table()
    from core.skills.tdd_order import _commit_tree_members, _commit_parent_sha
    repo_str = str(repo)
    own_tree = _commit_tree_members(sha, repo_str)
    parent_sha = _commit_parent_sha(sha, repo_str)
    parent_tree = _commit_tree_members(parent_sha, repo_str)
    exists_set = own_tree | parent_tree
    added = lambda p: p not in parent_tree  # noqa: E731
    has_test = any(_tc.is_test_path(f, table=table, exists=exists_set.__contains__,
                                    added=added) for f in files)
    has_impl = any(not _tc.is_test_path(f, table=table, exists=exists_set.__contains__,
                                        added=added) for f in files)
    if has_test and has_impl:
        return "mixed"
    return "test" if has_test else "impl"


def test_old_vs_new_classify_agree_across_all_real_step_groups():
    """AC-7: over every real `<TICKET> step-<N>` commit group already in
    this repository's own git history, the new `classify()` (git-status-aware,
    post step-1) and the frozen pre-fix `_old_classify()` (`--name-only` +
    tree-absence) reach the SAME verdict for every single commit — 0
    behavioural flips against real, already-built history."""
    if not (_REPO / ".git").exists():
        pytest.skip("not a real git checkout")
    out = _git(["log", "--all", "--format=%H\t%s"], _REPO)
    if not out:
        pytest.skip("no git history available (shallow or empty checkout)")
    groups: dict[tuple[str, str], None] = {}
    for line in out.splitlines():
        if "\t" not in line:
            continue
        _, subject = line.split("\t", 1)
        m = _GROUP_RE.match(subject.strip())
        if m:
            groups[(m.group(1), m.group(2))] = None

    checked = 0
    flips = []
    for ticket, step in groups:
        pattern = f"{ticket} step-{step}"
        exact_re = re.compile(rf"{re.escape(ticket)}\s+step-{step}(?!\d)")
        log = _git(["log", "--format=%H\t%s", "--reverse", f"--grep={pattern}"], _REPO)
        for line in log.splitlines():
            if "\t" not in line:
                continue
            sha, subject = line.split("\t", 1)
            if not exact_re.search(subject.strip()):
                continue
            checked += 1
            old = _old_classify(sha.strip(), _REPO)
            new = _new_classify(sha.strip(), _REPO)
            if old != new:
                flips.append((ticket, step, sha.strip(), old, new))

    assert checked > 0, "expected at least one real step-group commit to check"
    assert flips == [], f"{len(flips)} classification flip(s) vs pre-fix logic: {flips[:5]}"
