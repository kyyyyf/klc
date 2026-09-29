"""KLC-136 step-2 — the live `.klc/` guard: per-test failure, session diff,
subprocess coverage (AC-6, AC-7, AC-8).

Real-substrate: every scenario here drives a genuine `sys.addaudithook`
Guard or a genuine inner `pytest` subprocess against a tmp stand-in root —
no mocked filesystem, no mocked audit hook. None of these tests writes to a
real guarded root; the stand-in directories are the ONLY roots any inner
session or `Guard` instance in this file ever watches.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GUARD_DIR = REPO_ROOT / "tests" / "shared" / "live_guard"
for _p in (str(GUARD_DIR), str(REPO_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc_live_guard as klg  # noqa: E402
import klc_live_guard_plugin  # noqa: E402
import _paths  # noqa: E402


# --------------------------------------------------------------- helpers

def _inner_env(stand_in, extra=None):
    env = os.environ.copy()
    env["KLC_LIVE_GUARD_ROOTS"] = str(stand_in)
    existing_pp = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join([str(GUARD_DIR)] + existing_pp)
    if extra:
        env.update(extra)
    return env


def _run_inner(test_file, stand_in, extra_env=None, timeout=60):
    env = _inner_env(stand_in, extra=extra_env)
    return subprocess.run(
        # D-219 follow-up: no --rootdir pin here (unlike the audit test's
        # inner run) — pytest's NATURAL rootdir discovery gives a nodeid
        # that always ENDS with "test_x.py::test_y" (possibly with a
        # ".."-traversal or absolute-feeling prefix before it, depending on
        # whether this whole repo lives under /tmp (a scratch copy) or
        # /home (an interactive checkout)); pinning --rootdir explicitly
        # instead produces a DEGENERATE "::test_y" nodeid for a file outside
        # that rootdir (confirmed empirically), which the suffix-only
        # assertions below could never match. So: no pin, suffix-only match.
        [sys.executable, "-m", "pytest", str(test_file),
         "-p", "klc_live_guard_plugin", "-p", "no:cacheprovider", "-q"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=timeout,
    )


_INPROC_SRC = '''
import os
from pathlib import Path

STAND_IN = Path(os.environ["KLC_LIVE_GUARD_ROOTS"].split(os.pathsep)[0])

def test_create():
    (STAND_IN / "created.txt").write_text("x")

def test_modify():
    (STAND_IN / "existing.txt").write_text("changed")

def test_rename():
    (STAND_IN / "rn_src.txt").rename(STAND_IN / "rn_dst.txt")

def test_delete():
    os.remove(STAND_IN / "del_me.txt")

def test_no_write_control():
    assert STAND_IN.exists()
'''

_SUBPROC_SRC = '''
import os
import sys
import subprocess
from pathlib import Path

STAND_IN = Path(os.environ["KLC_LIVE_GUARD_ROOTS"].split(os.pathsep)[0])


def _do(code):
    r = subprocess.run([sys.executable, "-c", code], env=os.environ.copy(),
                        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_create():
    _do(f"from pathlib import Path; Path({str(STAND_IN / 'created.txt')!r}).write_text('x')")

def test_modify():
    _do(f"from pathlib import Path; Path({str(STAND_IN / 'existing.txt')!r}).write_text('changed')")

def test_rename():
    _do(f"from pathlib import Path; Path({str(STAND_IN / 'rn_src.txt')!r})"
        f".rename({str(STAND_IN / 'rn_dst.txt')!r})")

def test_delete():
    _do(f"import os; os.remove({str(STAND_IN / 'del_me.txt')!r})")

def test_no_write_control():
    assert STAND_IN.exists()
'''


def _seed_op_targets(stand_in: Path) -> None:
    (stand_in / "existing.txt").write_text("orig")
    (stand_in / "rn_src.txt").write_text("orig")
    (stand_in / "del_me.txt").write_text("orig")


# ------------------------------------------------------- AC-6: in-process

@pytest.fixture(scope="module")
def _inproc_run(tmp_path_factory):
    stand_in = tmp_path_factory.mktemp("standin_inproc")
    _seed_op_targets(stand_in)
    inner_dir = tmp_path_factory.mktemp("inner_inproc")
    (inner_dir / "test_inner_inproc.py").write_text(_INPROC_SRC)
    return _run_inner(inner_dir / "test_inner_inproc.py", stand_in)


@pytest.mark.parametrize("op", ["create", "modify", "rename", "delete"])
def test_guard_fails_test_that_writes_under_guarded_root_in_process(op, _inproc_run):
    """AC-6: each of create/modify/rename/delete is planted independently
    and independently fails its inner test, naming the test id and path."""
    out = _inproc_run.stdout
    # matches the nodeid's SUFFIX only (never a full prefix — see _run_inner)
    assert f"test_inner_inproc.py::test_{op}:" in out, out
    assert "4 failed, 1 passed" in out, out


# ---------------------------------------------------------- AC-6: subprocess

@pytest.fixture(scope="module")
def _subproc_run(tmp_path_factory):
    stand_in = tmp_path_factory.mktemp("standin_subproc")
    _seed_op_targets(stand_in)
    inner_dir = tmp_path_factory.mktemp("inner_subproc")
    (inner_dir / "test_inner_subproc.py").write_text(_SUBPROC_SRC)
    return _run_inner(inner_dir / "test_inner_subproc.py", stand_in)


@pytest.mark.parametrize("op", ["create", "modify", "rename", "delete"])
def test_guard_fails_test_that_writes_under_guarded_root_in_subprocess(op, _subproc_run):
    """AC-6: the same four operations, each performed by the inner test in a
    REAL Python subprocess that inherits the environment; the guard still
    reports exactly one failure per operation, and no teardown error (one
    subprocess write is reported once, impl-plan-review F-3)."""
    out = _subproc_run.stdout
    assert f"test_inner_subproc.py::test_{op}:" in out, out
    assert f"ERROR at teardown of test_{op}" not in out, out
    assert "4 failed, 1 passed" in out, out


# ------------------------------------------------------------- AC-6: roots

def test_guard_watches_all_three_roots(tmp_path, pytestconfig):
    """AC-6: `default_roots` names the three guarded roots (deduplicating
    when the project root is the framework root's parent); a planted write
    under each of a stand-in triple is reported; and the running (real)
    session's roots equal `default_roots(_paths.framework_root(),
    <session-start project_root()>)` (F-016's order-dependence guard)."""
    fake_fw = tmp_path / "fw"
    fake_proj = tmp_path / "proj"
    fake_fw.mkdir()
    fake_proj.mkdir()

    distinct = klg.default_roots(fake_fw, fake_proj)
    assert len(distinct) == 3

    deduped = klg.default_roots(fake_fw, fake_fw.parent)
    assert len(deduped) == 2

    # a planted write under each of the three (distinct) roots is reported
    roots = [Path(r) for r in distinct]
    for r in roots:
        r.mkdir(parents=True, exist_ok=True)
    guard = klg.Guard(roots=[str(r) for r in roots], report_path=None)
    klg.activate(guard)
    try:
        os.environ["PYTEST_CURRENT_TEST"] = "probe_three_roots (call)"
        try:
            for r in roots:
                (r / "planted.txt").write_text("x")
        finally:
            os.environ.pop("PYTEST_CURRENT_TEST", None)
        violations = guard.violations("probe_three_roots")
    finally:
        klg.deactivate(guard)
    assert len(violations) == 3
    for r in roots:
        assert any(v.startswith(os.path.realpath(str(r))) for v in violations), violations

    real_roots = {os.path.realpath(r) for r in klc_live_guard_plugin.resolved_roots(pytestconfig)}
    expected = {os.path.realpath(r) for r in klg.default_roots(_paths.framework_root(), _paths.project_root())}
    assert real_roots == expected


# --------------------------------------------------------- AC-6: degrade

def test_guard_degrades_to_warning_when_audithook_unavailable(tmp_path_factory):
    """AC-6, assumption error-handling: when `sys.addaudithook` cannot be
    installed, the guard never skips silently — it degrades to the
    session-end diff alone, prints exactly one warning line, and the run
    still exits 0."""
    stand_in = tmp_path_factory.mktemp("standin_degrade")
    inner_dir = tmp_path_factory.mktemp("inner_degrade")
    (inner_dir / "test_inner_degrade.py").write_text('''
import os
from pathlib import Path
STAND_IN = Path(os.environ["KLC_LIVE_GUARD_ROOTS"].split(os.pathsep)[0])

def test_writes_in_process():
    (STAND_IN / "degraded_write.txt").write_text("x")
''')
    result = _run_inner(inner_dir / "test_inner_degrade.py", stand_in,
                         extra_env={"KLC_LIVE_GUARD_NO_AUDITHOOK": "1"})
    assert result.returncode == 0, result.stdout
    degrade_line = "klc live guard: audit hooks unavailable; per-test guard off, session diff only"
    assert result.stdout.count(degrade_line) == 1, result.stdout
    assert "live .klc change during session (advisory): ADDED" in result.stdout
    assert str(stand_in / "degraded_write.txt") in result.stdout


# ------------------------------------------------------------- AC-7: diff

@pytest.fixture(scope="module")
def _escape_run(tmp_path_factory):
    stand_in = tmp_path_factory.mktemp("standin_escape")
    (stand_in / "to_remove.txt").write_text("orig")
    (stand_in / "to_modify.txt").write_text("orig")
    inner_dir = tmp_path_factory.mktemp("inner_escape")
    (inner_dir / "test_inner_escape.py").write_text(f'''
import os
import sys
import subprocess
from pathlib import Path

STAND_IN = Path({str(stand_in)!r})

def test_escapes_the_guard_via_dropped_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    code = (
        "from pathlib import Path; "
        "Path(" + repr(str(STAND_IN / "added.txt")) + ").write_text('x'); "
        "Path(" + repr(str(STAND_IN / "to_modify.txt")) + ").write_text('changed'); "
        "import os; os.remove(" + repr(str(STAND_IN / "to_remove.txt")) + ")"
    )
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
''')
    return stand_in, _run_inner(inner_dir / "test_inner_escape.py", stand_in)


def test_session_end_diff_reports_every_added_removed_modified_path(_escape_run):
    """AC-7: a subprocess launched with a hand-built env that drops
    PYTHONPATH (the documented escape) is invisible to the per-test guard,
    but the session-end snapshot diff still lists every path it touched."""
    stand_in, result = _escape_run
    out = result.stdout
    assert f"live .klc change during session (advisory): ADDED {stand_in / 'added.txt'}" in out, out
    assert f"live .klc change during session (advisory): REMOVED {stand_in / 'to_remove.txt'}" in out, out
    assert f"live .klc change during session (advisory): MODIFIED {stand_in / 'to_modify.txt'}" in out, out


def test_session_end_diff_never_changes_exit_status(_escape_run):
    """AC-7 NEGATIVE/fail-open twin: the same session exits 0 for the diff
    step itself — a concurrent agent write (F-014) cannot fail the run
    through this path."""
    _stand_in, result = _escape_run
    assert result.returncode == 0, result.stdout
    assert "1 passed" in result.stdout, result.stdout


# --------------------------------------------------------------- AC-8

def test_fail_closed_plants_genuine_and_false_positive_events_together(tmp_path, monkeypatch):
    """AC-8: with a Guard on a stand-in root active in THIS process under
    the test id `probe`, plant (1) an in-process write, (2) a Python
    subprocess write, (3) a write to an unguarded tmp path, (4) an idempotent
    `os.makedirs(exist_ok=True)` on an existing guarded directory
    (spec-review F-3), and (5) a `shutil.copytree` whose SOURCE (not
    destination) is under the guarded stand-in (spec-review F-3) — all five
    in the SAME run. The guard's report must be exactly the two genuine
    writes (1)-(2); the no-op/read-tagged events (3)-(5) must not appear."""
    stand_in = tmp_path / "standin"
    sub = stand_in / "sub"
    sub.mkdir(parents=True)
    (sub / "f.txt").write_text("x")
    unguarded = tmp_path / "unguarded"
    unguarded.mkdir()
    report_path = tmp_path / "report.jsonl"

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "probe (call)")

    guard = klg.Guard(roots=[str(stand_in)], report_path=str(report_path))
    klg.activate(guard)
    try:
        # (1) in-process write
        (stand_in / "inproc_new.txt").write_text("x")

        # (2) subprocess write
        env = os.environ.copy()
        env["KLC_LIVE_GUARD_ROOTS"] = str(stand_in)
        env["KLC_LIVE_GUARD_REPORT"] = str(report_path)
        existing_pp = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
        env["PYTHONPATH"] = os.pathsep.join([str(GUARD_DIR)] + existing_pp)
        code = (
            "from pathlib import Path; "
            f"Path({str(stand_in / 'subproc_new.txt')!r}).write_text('x'); "
            "import sitecustomize; print('CHAINED=', sitecustomize._klc_chained)"
        )
        r = subprocess.run([sys.executable, "-c", code], env=env,
                            capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr

        # (3) write to an unguarded tmp path
        (unguarded / "unguarded.txt").write_text("x")

        # (4) idempotent mkdir(exist_ok=True) on an existing guarded dir
        os.makedirs(sub, exist_ok=True)

        # (5) shutil.copytree whose SOURCE is under the guarded stand-in
        shutil.copytree(sub, unguarded / "sub_copy")

        violations = guard.violations("probe")
    finally:
        klg.deactivate(guard)

    expected = sorted([
        os.path.realpath(str(stand_in / "inproc_new.txt")),
        os.path.realpath(str(stand_in / "subproc_new.txt")),
    ])
    assert violations == expected, violations

    system_sitecustomize_exists = _has_system_sitecustomize()
    assert ("CHAINED= True" in r.stdout) == system_sitecustomize_exists, r.stdout


def _has_system_sitecustomize() -> bool:
    import importlib.machinery
    search_path = [p for p in sys.path if os.path.abspath(p or ".") != str(GUARD_DIR)]
    return importlib.machinery.PathFinder.find_spec("sitecustomize", search_path) is not None


# ------------------------------------------- step-10: review round 1 follow-ons

def test_guard_fails_outer_test_when_nested_session_without_plugin_writes(tmp_path, monkeypatch):
    """AC-6, review round 1 ext MEDIUM: a nested pytest session launched
    with `-p no:klc_live_guard_plugin` still relays its writes to the
    SPAWNING (outer) test. Before the fix, the shim installed the Guard
    with the outer's report path, but the inner pytest overwrote
    `$PYTEST_CURRENT_TEST` with its own node ids for the whole life of that
    process (a core pytest behaviour, independent of any plugin) — so
    every relayed report line was tagged with an INNER id the outer test
    never asked about, and nothing in the (plugin-less) inner session ever
    evaluated them either. The fix tags every report line with a STATIC
    "owner" id too (captured once, at process start, before pytest could
    ever overwrite the env var) and matches on either field."""
    stand_in = tmp_path / "standin"
    stand_in.mkdir()
    inner_dir = tmp_path / "inner"
    inner_dir.mkdir()
    (inner_dir / "test_inner_no_plugin.py").write_text('''
import os
from pathlib import Path
STAND_IN = Path(os.environ["KLC_LIVE_GUARD_ROOTS"].split(os.pathsep)[0])

def test_writes_without_plugin():
    (STAND_IN / "written.txt").write_text("x")
''', encoding="utf-8")

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "probe_nested_no_plugin (call)")
    report_path = tmp_path / "report.jsonl"
    guard = klg.Guard(roots=[str(stand_in)], report_path=str(report_path))
    klg.activate(guard)
    try:
        env = _inner_env(stand_in, extra={"KLC_LIVE_GUARD_REPORT": str(report_path)})
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(inner_dir / "test_inner_no_plugin.py"),
             "-p", "no:klc_live_guard_plugin", "-p", "no:cacheprovider", "-q"],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, r.stdout  # the inner test itself has no plugin, so IT passes
        violations = guard.violations("probe_nested_no_plugin")
    finally:
        klg.deactivate(guard)

    assert violations == [str((stand_in / "written.txt").resolve())], (violations, r.stdout)


def test_guard_reports_chmod_only_change_to_a_guarded_file(tmp_path, monkeypatch):
    """AC-6, code-review MEDIUM: `os.chmod` is explicitly in the
    write-candidate event table (`_WRITE_BOTH`), but `path_state()`'s FILE
    tuple never included the permission bits, so a chmod-only change (no
    size/mtime change) to a guarded FILE was invisible to both the
    per-test guard and the AC-7 advisory diff. Plants exactly that and
    asserts it IS reported (directories keep D-204's identity-only
    exclusion — this is deliberately file-only)."""
    stand_in = tmp_path / "standin"
    stand_in.mkdir()
    target = stand_in / "f.txt"
    target.write_text("x", encoding="utf-8")
    target.chmod(0o644)

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "probe_chmod (call)")
    guard = klg.Guard(roots=[str(stand_in)], report_path=None)
    klg.activate(guard)
    try:
        target.chmod(0o600)
        violations = guard.violations("probe_chmod")
    finally:
        klg.deactivate(guard)

    assert violations == [str(target.resolve())], violations
