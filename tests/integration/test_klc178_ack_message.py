"""KLC-178 step-2 — AC-5: the integrate scope-expansion refusal names `klc fix`."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone, _branch_with_commits, _merge, _run_ack, _seed_ticket, _set_phase,
)

_MODULES = [{"name": "widgets", "path": "widgets/"}, {"name": "gadgets", "path": "gadgets/"},
            {"name": "gizmos", "path": "gizmos/"}]


def test_scope_expansion_message_points_at_klc_fix(tmp_path, monkeypatch, capsys):
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-950"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
        ("gadgets/extra.py", "b = 1\n", f"{ticket} step-1: add an unplanned file"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                 affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
    _merge(clone, ticket, "ff-only")
    _set_phase(clone, ticket, "integrate:work")

    capsys.readouterr()
    rc = _run_ack(clone, ticket, "integrate", monkeypatch=monkeypatch, pick=1)
    err = capsys.readouterr().err

    assert rc == 1
    assert f'klc fix {ticket} modules --add gadgets --reason "<why>"' in err
    assert "scope-fix" not in err


def test_review_scope_expansion_message_names_klc_fix_and_keeps_klc_back(
        tmp_path, monkeypatch, capsys):
    """Operator addition: the review-path refusal also teaches `klc fix`."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-951"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
        ("gadgets/extra.py", "b = 1\n", f"{ticket} step-1: add an unplanned file"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M",
                 affected_modules=["widgets"], modules=_MODULES)
    assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
    _set_phase(clone, ticket, "review:work")

    capsys.readouterr()
    rc = _run_ack(clone, ticket, "review", monkeypatch=monkeypatch, pick=1)
    err = capsys.readouterr().err

    assert rc == 1
    assert f'klc fix {ticket} modules --add gadgets --reason "<why>"' in err
    assert f"klc back {ticket} review --reason" in err
    assert "scope-fix" not in err


def _paste_remedy(clone: Path, err: str) -> subprocess.CompletedProcess:
    """Take the printed `klc fix ...` command exactly as shown and run it."""
    m = re.search(r"`(klc fix [^`]+)`", err)
    assert m, err
    argv = shlex.split(m.group(1))[1:]
    env = {**os.environ, "PROJECT_ROOT": str(clone)}
    env.pop("KLC_TICKETS_DIR", None)
    return subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "klc"),
                           *argv], capture_output=True, text=True, env=env)


def test_two_unplanned_modules_remedy_is_comma_joined_and_pastes(tmp_path, monkeypatch, capsys):
    """F-001: more than one unplanned module -> ONE comma list that `klc fix` accepts."""
    for phase_after, ticket in (("integrate", "KLC-952"), ("review", "KLC-953")):
        _bare_and_clone(tmp_path / ticket)
        clone = tmp_path / ticket / "clone"
        _branch_with_commits(clone, ticket, [
            ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
            ("gadgets/extra.py", "b = 1\n", f"{ticket} step-1: unplanned one"),
            ("gizmos/extra.py", "c = 1\n", f"{ticket} step-1: unplanned two"),
        ])
        _seed_ticket(clone, ticket, phase="build:work", track="M",
                     affected_modules=["widgets"], modules=_MODULES)
        assert _run_ack(clone, ticket, "build", monkeypatch=monkeypatch, pick=1) == 0
        if phase_after == "integrate":
            _merge(clone, ticket, "ff-only")
            _set_phase(clone, ticket, "integrate:work")
        else:
            _set_phase(clone, ticket, "review:work")
        capsys.readouterr()
        assert _run_ack(clone, ticket, phase_after, monkeypatch=monkeypatch, pick=1) == 1
        err = capsys.readouterr().err
        assert f"klc fix {ticket} modules --add gadgets,gizmos --reason" in err, err
        r = _paste_remedy(clone, err.replace("<why>", "scope grew"))
        assert r.returncode == 0, r.stderr
        meta = json.loads((clone / ".klc" / "tickets" / ticket / "meta.json").read_text())
        assert meta["affected_modules"] == ["widgets", "gadgets", "gizmos"]
