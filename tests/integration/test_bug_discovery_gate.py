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


# ---------------------------------------------------------------------------
# step-2: kind=bug discovery gate
# ---------------------------------------------------------------------------

@pytest.fixture()
def bug_ticket_dir(tmp_path, monkeypatch):
    """Minimal bug ticket directory — repro.md present and valid."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc" / "tickets" / "KLC-T4"
    tdir.mkdir(parents=True)
    import json
    meta = {
        "ticket": "KLC-T4", "kind": "bug", "track": "M",
        "phase": "discovery:work", "layer": "core",
        "affected_modules": ["src"],
        "estimate": {"complexity": 2, "uncertainty": 1, "risk": 1, "manual": 0, "total": 4},
        "risk_tags": [],
    }
    (tdir / "meta.json").write_text(json.dumps(meta))
    (tdir / "repro.md").write_text(_VALID_REPRO)
    return tmp_path


def test_bug_blocked_without_repro(bug_ticket_dir):
    """kind=bug without repro.md: _bug_discovery_gate returns (False, msg with 'repro')."""
    (bug_ticket_dir / ".klc" / "tickets" / "KLC-T4" / "repro.md").unlink()
    from phase_completion import _bug_discovery_gate
    ok, msg = _bug_discovery_gate("KLC-T4", "", {"kind": "bug"})
    assert not ok
    assert "repro" in msg.lower()


def test_bug_blocked_without_marker(bug_ticket_dir):
    """kind=bug with repro.md but no FAILING-TEST marker: gate returns (False, msg)."""
    repro_no_marker = _VALID_REPRO.replace(
        "FAILING-TEST: tests/test_auth.py::test_login_redirects\n", "")
    (bug_ticket_dir / ".klc" / "tickets" / "KLC-T4" / "repro.md").write_text(repro_no_marker)
    from phase_completion import _bug_discovery_gate
    ok, msg = _bug_discovery_gate("KLC-T4", "", {"kind": "bug"})
    assert not ok
    assert "FAILING-TEST" in msg


def test_feature_gate_is_noop(bug_ticket_dir):
    """Non-bug tickets: _bug_discovery_gate is a no-op (AC-3)."""
    # Even without repro.md, feature meta passes straight through
    (bug_ticket_dir / ".klc" / "tickets" / "KLC-T4" / "repro.md").unlink()
    from phase_completion import _bug_discovery_gate
    ok, msg = _bug_discovery_gate("KLC-T4", "", {"kind": "feature"})
    assert ok
    assert msg == ""


def test_bug_passes_with_valid_repro_and_marker(bug_ticket_dir):
    """kind=bug with valid repro.md + FAILING-TEST marker: gate passes."""
    from phase_completion import _bug_discovery_gate
    ok, msg = _bug_discovery_gate("KLC-T4", "", {"kind": "bug"})
    assert ok, msg


# ---------------------------------------------------------------------------
# step-3: repro.md scaffold template
# ---------------------------------------------------------------------------

def test_repro_template_renders_all_sections():
    """Rendered repro.md.j2 carries all four REPRO_SECTIONS headings."""
    from jinja2 import Environment, FileSystemLoader
    from repro_check import REPRO_SECTIONS, validate_repro
    templates_dir = _FW_ROOT / "core" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), keep_trailing_newline=True)
    rendered = env.get_template("repro.md.j2").render(ticket="KLC-TEST")
    for sec in REPRO_SECTIONS:
        assert f"## {sec}" in rendered, f"Missing section: {sec}"


def test_repro_template_has_failing_test_placeholder():
    """Rendered repro.md.j2 contains a FAILING-TEST: placeholder line."""
    from jinja2 import Environment, FileSystemLoader
    templates_dir = _FW_ROOT / "core" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), keep_trailing_newline=True)
    rendered = env.get_template("repro.md.j2").render(ticket="KLC-TEST")
    assert "FAILING-TEST:" in rendered


def test_repro_template_filled_passes_validation():
    """A repro.md.j2 rendered and filled with content passes validate_repro."""
    from repro_check import validate_repro
    filled = _VALID_REPRO  # _VALID_REPRO is a correctly filled repro.md
    assert validate_repro(filled) == []


# ---------------------------------------------------------------------------
# step-5: ARCH_REVIEW escalation at red-fix limit
# ---------------------------------------------------------------------------

def test_red_fix_limit_emits_arch_review(tmp_path, monkeypatch):
    """Bumping red_test_fix_attempts to the limit emits ARCH_REVIEW advisory."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc" / "tickets" / "KLC-T5"
    tdir.mkdir(parents=True)
    import json
    meta = {
        "ticket": "KLC-T5", "kind": "bug", "track": "S",
        "phase": "build:work", "affected_modules": ["src"],
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "risk_tags": [], "budgets": {"red_test_fix_attempts": 2},
    }
    (tdir / "meta.json").write_text(json.dumps(meta))

    from budget import cmd_bump, DEFAULT_LIMITS
    import argparse
    limit = DEFAULT_LIMITS["red_test_fix_attempts"]

    # Bump to the limit
    args = argparse.Namespace(ticket="KLC-T5", counter="red_test_fix_attempts", by=1)
    import io, contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_bump(args)

    output = out.getvalue()
    assert "ARCH_REVIEW" in output
    assert "KLC-T5" in output


def test_pre_limit_bump_no_arch_review(tmp_path, monkeypatch):
    """Bumping below the limit must NOT emit ARCH_REVIEW."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc" / "tickets" / "KLC-T5"
    tdir.mkdir(parents=True)
    import json
    meta = {
        "ticket": "KLC-T5", "kind": "bug", "track": "S",
        "phase": "build:work", "affected_modules": ["src"],
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
        "risk_tags": [], "budgets": {"red_test_fix_attempts": 0},
    }
    (tdir / "meta.json").write_text(json.dumps(meta))

    from budget import cmd_bump
    import argparse, io, contextlib
    args = argparse.Namespace(ticket="KLC-T5", counter="red_test_fix_attempts", by=1)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_bump(args)
    assert "ARCH_REVIEW" not in out.getvalue()
