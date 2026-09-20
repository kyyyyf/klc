"""tests/integration/test_klc109_ac_coverage.py — KLC-109 step-5: the
AC-coverage gate discovers candidate test files through the shared
test_conventions module, so a colocated non-python test is admitted on a
project with no top-level tests/ directory.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ac_test_coverage as acov  # noqa: E402


def _run(args: list[str], cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    return r.stdout.strip()


def test_admits_colocated_test_with_no_top_level_tests_dir(tmp_path):
    """AC-9: a changed src/Foo.test.tsx is admitted as an AC-coverage
    candidate on a project with NO top-level tests/ directory."""
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    _run(["init"], proj)
    _run(["config", "user.email", "t@t"], proj)
    _run(["config", "user.name", "t"], proj)
    (proj / "src" / "Foo.tsx").write_text("export const Foo = () => null;\n")
    _run(["add", "-A"], proj)
    _run(["commit", "-m", "base"], proj)
    _run(["branch", "-M", "main"], proj)
    # A brand-new, colocated (no tests/ dir) test file.
    (proj / "src" / "Foo.test.tsx").write_text("test('renders', () => {});\n")

    files = acov._changed_test_files(proj)
    assert files is not None
    assert "src/Foo.test.tsx" in files

    candidates = acov._candidate_files({}, repo=proj)
    assert "src/Foo.test.tsx" in candidates


def test_shared_module_own_basename_change_is_not_admitted_as_a_test_candidate(tmp_path):
    """Drift review round 2, F-4: a future ticket's diff that touches ONLY
    `core/skills/test_conventions.py` (a real production module — its own
    top-level `test_signal` function coincidentally satisfies the AC-id
    body-token scan) must NOT have that path admitted into
    `_changed_test_files` — closing the exact self-referential collision the
    drift reviewer demonstrated end to end. No `conventions.py` sibling
    exists anywhere in this fixture repo's HEAD tree, so the conservative
    exists= gate (D-109-10) correctly excludes it."""
    proj = tmp_path / "proj"
    (proj / "core" / "skills").mkdir(parents=True)
    _run(["init"], proj)
    _run(["config", "user.email", "t@t"], proj)
    _run(["config", "user.name", "t"], proj)
    (proj / "core" / "skills" / "test_conventions.py").write_text(
        "def test_signal(path):\n    '''AC-1 AC-3 AC-6'''\n    return None\n")
    _run(["add", "-A"], proj)
    _run(["commit", "-m", "base"], proj)
    _run(["branch", "-M", "main"], proj)
    # A real, tracked change to the shared module (no conventions.py sibling
    # anywhere in the repo).
    (proj / "core" / "skills" / "test_conventions.py").write_text(
        "def test_signal(path):\n    '''AC-1 AC-3 AC-6 — widened'''\n    return None\n")

    files = acov._changed_test_files(proj)
    assert files is not None
    assert "core/skills/test_conventions.py" not in files, files


def test_non_python_candidate_is_admitted_but_never_scanned_or_node_id_verified(tmp_path):
    """AC-9 fail-closed: a .tsx candidate is admitted for coverage but never
    parsed, never enters `scanned`, never yields a node-id — so it can never
    substantiate a block, even though its body literally contains the
    canonical AC-<n> token."""
    (tmp_path / "Foo.test.tsx").write_text("test('AC-1 covers rendering', () => {});\n")
    implemented, scanned = acov._scan_tests_for_ac_ids(
        tmp_path / "tests", ["AC-1"], {"Foo.test.tsx"}, repo=tmp_path)
    assert implemented == {"AC-1": []}
    assert scanned == set()
