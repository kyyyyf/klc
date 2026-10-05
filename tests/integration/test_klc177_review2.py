"""KLC-177 step-6: review round 2 fixes.

Clarify stop precedes the Pick bullet in the run skill and names no --pick; the
messages go reaches through ack.py/next.py teach go/back; `go --until --pick N`
prints one line per stop; `--dry` is an argparse error; regression-test refs are
detected through test_conventions.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (_FW, _FW / "core" / "skills", _FW / "core" / "phases"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tests.integration.test_klc177_review1 import (  # noqa: E402,F401
    _go, _ticket, proj, _string_literals)


def test_clarify_render_names_no_pick(proj):
    _ticket(proj, "C-2", "intake:ack-needed", clarify_required=True, route_confidence="low")
    import next_move
    text = next_move.render(next_move.compute("C-2"))
    assert "clarify needed" in text and "--pick" not in text
    assert "klc go C-2" in text
    rc, out, err = _go(["C-2", "--until", "integrate"])
    assert rc == 2 and "--pick" not in out


def test_go_skill_lists_clarify_before_pick():
    t = (_FW / "klc-plugin" / "skills" / "go" / "SKILL.md").read_text(encoding="utf-8")
    assert t.index("**Clarify**") < t.index("**Pick**")


_RUNTIME_OLD = re.compile(r"\bklc (?:ack|next|ship|jump|abort|work)(?![\w:-])")


def test_ack_and_next_runtime_messages_teach_go_and_back():
    bad = []
    for name in ("ack.py", "next.py"):
        f = _FW / "core" / "phases" / name
        for lineno, s in _string_literals(f):
            if s.strip() in ("klc ack", "klc next"):      # argparse prog / note labels
                continue
            for ln in s.splitlines():
                if "deprecat" not in ln.lower() and _RUNTIME_OLD.search(ln):
                    bad.append(f"{name}:{lineno}: {ln.strip()[:90]}")
    assert not bad, "\n".join(bad)


def test_until_with_pick_prints_exactly_one_line_on_a_stop(proj):
    _ticket(proj, "U-1", "discovery:ack-needed", track="M")
    rc, out, err = _go(["U-1", "--until", "build", "--pick", "1"])
    assert rc in (0, 2), err
    assert len([ln for ln in out.splitlines() if ln.strip()]) == 1, out
    assert "klc ack" not in out and "klc next" not in out


def test_dry_abbreviation_is_an_argparse_error(proj):
    _ticket(proj, "D-1", "review:ack")
    with pytest.raises(SystemExit) as e:
        _go(["D-1", "--dry"])
    assert e.value.code == 2


def test_looks_like_test_ref_lives_in_test_conventions():
    import test_conventions as tc
    assert tc.looks_like_test_ref("add tests/x.py::test_y")
    assert tc.looks_like_test_ref("see foo_test.py")
    assert not tc.looks_like_test_ref("latest build")
    assert not tc.looks_like_test_ref("a bare test_name")
