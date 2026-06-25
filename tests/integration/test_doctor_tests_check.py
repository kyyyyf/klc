"""Integration tests for `klc doctor --tests` suite-green gate. (KLC-049 step-5)"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))

from core.phases import doctor  # noqa: E402


def _write_passing_test(tmp_path: Path) -> None:
    (tmp_path / "test_pass.py").write_text("def test_ok(): assert True\n", encoding="utf-8")


def _write_failing_test(tmp_path: Path) -> None:
    (tmp_path / "test_fail.py").write_text("def test_bad(): assert False\n", encoding="utf-8")


def test_doctor_tests_check_fail(tmp_path):
    """doctor --tests returns non-zero when the selected test path has a failing test."""
    _write_passing_test(tmp_path)
    _write_failing_test(tmp_path)
    rc = doctor.run(["--tests", "--tests-path", str(tmp_path)])
    assert rc != 0, "expected non-zero exit when failing test is present"


def test_doctor_tests_check_pass(tmp_path):
    """doctor --tests returns 0 when all selected tests pass."""
    _write_passing_test(tmp_path)
    rc = doctor.run(["--tests", "--tests-path", str(tmp_path)])
    assert rc == 0, "expected exit 0 when all tests pass"


def test_doctor_tests_flag_in_help(capsys):
    """--tests flag must appear in klc doctor --help output."""
    with pytest.raises(SystemExit):
        doctor.run(["--help"])
    out = capsys.readouterr().out
    assert "--tests" in out, "--tests flag missing from doctor --help"
