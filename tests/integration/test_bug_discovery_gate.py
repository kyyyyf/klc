"""KLC-044: kind=bug discovery gate tests — repro validation, bug gate, template, escalation."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

# ---------------------------------------------------------------------------
# step-1: repro_check module
# ---------------------------------------------------------------------------

_VALID_REPRO = textwrap.dedent("""\
    ## Problem
    The login button does nothing when clicked.

    ## Environment
    OS: Ubuntu 22.04, Python 3.11, browser: Chrome 120.

    ## Steps
    1. Open /login.
    2. Enter credentials.
    3. Click "Login".
    4. Observe no navigation.

    ## Expected vs actual
    Expected: redirect to /dashboard. Actual: page stays on /login.

    FAILING-TEST: tests/test_auth.py::test_login_redirects
""")


def test_repro_check_valid_passes():
    from repro_check import validate_repro
    assert validate_repro(_VALID_REPRO) == []


def test_repro_check_missing_section():
    from repro_check import validate_repro
    text = _VALID_REPRO.replace("## Steps\n", "")
    errors = validate_repro(text)
    assert any("Steps" in e for e in errors), errors


def test_repro_check_empty_problem():
    from repro_check import validate_repro
    text = textwrap.dedent("""\
        ## Problem

        ## Environment
        OS: Ubuntu 22.04.

        ## Steps
        1. Reproduce.

        ## Expected vs actual
        Expected X. Actual Y.
    """)
    errors = validate_repro(text)
    assert any("Problem" in e for e in errors), errors


def test_has_failing_test_ref_present():
    from repro_check import has_failing_test_ref
    assert has_failing_test_ref(_VALID_REPRO, "") is True


def test_has_failing_test_ref_in_spec():
    from repro_check import has_failing_test_ref
    repro = _VALID_REPRO.replace("FAILING-TEST: tests/test_auth.py::test_login_redirects\n", "")
    spec = "FAILING-TEST: tests/test_auth.py::test_login_redirects"
    assert has_failing_test_ref(repro, spec) is True


def test_has_failing_test_ref_absent():
    from repro_check import has_failing_test_ref
    repro = _VALID_REPRO.replace("FAILING-TEST: tests/test_auth.py::test_login_redirects\n", "")
    assert has_failing_test_ref(repro, "") is False
