"""KLC-139 step-6 — the `klc skeleton` verb (AC-1).

`skeleton()` prints its outline or refusal, `klc --help` lists the verb,
`skeleton` is in `NO_DRAIN_CMDS`, a call with no path or two paths prints the
exact usage line and exits 2, and a successful call (Python or not) prints
the same text in-process and as a `klc skeleton` subprocess.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
KLC = REPO / "scripts" / "klc"
for _p in (str(SKILLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import skeleton as sk  # noqa: E402


def _load_klc_module():
    loader = importlib.machinery.SourceFileLoader("klc139_cli_module", str(KLC))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _run_klc(argv, project_root: Path) -> tuple:
    proc = subprocess.run(
        [sys.executable, str(KLC), *argv],
        env={**os.environ, "PROJECT_ROOT": str(project_root),
             "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_skeleton_function_returns_outline_or_refusal(tmp_path, monkeypatch):
    """AC-1: in-process, a good .py gives an outline, a directory a
    refusal, and neither raises."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    good = tmp_path / "good.py"
    good.write_text("def f():\n    pass\n", encoding="utf-8")
    result = sk.skeleton(str(good))
    assert not result.refused

    directory = tmp_path / "adir"
    directory.mkdir()
    result_dir = sk.skeleton(str(directory))
    assert result_dir.refused


def test_klc_help_lists_skeleton_verb():
    """AC-1: `klc --help` lists the `skeleton` verb."""
    proc = subprocess.run([sys.executable, str(KLC), "--help"],
                           capture_output=True, text=True, timeout=30)
    assert "skeleton" in proc.stdout


def test_skeleton_in_no_drain_cmds():
    """AC-1/C-004: `skeleton` is a no-drain (read-only) verb."""
    module = _load_klc_module()
    assert "skeleton" in module.NO_DRAIN_CMDS


def test_klc_skeleton_no_path_prints_usage_and_exits_2(tmp_path):
    """AC-1: no path -> the exact usage line on stderr, exit 2 (review F-5:
    today's unknown-subcommand path already exits 2, so this must check the
    exact text, not just the exit code)."""
    rc, out, err = _run_klc(["skeleton"], tmp_path)
    assert rc == 2
    assert err.strip() == "usage: klc skeleton <file>"
    assert "unknown subcommand" not in err


def test_klc_skeleton_two_paths_prints_usage_and_exits_2(tmp_path):
    """AC-1: two paths -> the exact usage line on stderr, exit 2."""
    rc, out, err = _run_klc(["skeleton", "a.py", "b.py"], tmp_path)
    assert rc == 2
    assert err.strip() == "usage: klc skeleton <file>"
    assert "unknown subcommand" not in err


@pytest.mark.parametrize("case", ["python", "nonpython"])
def test_klc_skeleton_success_path_prints_outline(tmp_path, monkeypatch, case):
    """AC-1: subprocess exit 0, stdout equal to the in-process
    `skeleton(path).text` for the same absolute path and PROJECT_ROOT."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    if case == "python":
        fixture = tmp_path / "f.py"
        fixture.write_text("def f():\n    pass\n", encoding="utf-8")
    else:
        fixture = tmp_path / "f.ts"
        fixture.write_text("export function f() {}\n", encoding="utf-8")

    expected = sk.skeleton(str(fixture)).text
    rc, out, err = _run_klc(["skeleton", str(fixture)], tmp_path)
    assert rc == 0, err
    assert out == expected
