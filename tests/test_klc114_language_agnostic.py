"""KLC-114 step-1: the step ledger pass judges VERIFY by exit status plus
the Expected token alone, with no test-framework name anywhere in its own
logic (AC-13, C-003)."""
from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc114_helpers as h  # noqa: E402
import step_ledger as sl  # noqa: E402

_FRAMEWORK_NAMES = ("pytest", "unittest", "jest", "mocha", "junit", "rspec",
                    "gotest", "cargotest")


def test_non_pytest_shell_verify_command_runs_green_through_the_pass(tmp_path, monkeypatch):
    """AC-13: a bare shell VERIFY with no pytest installed or invoked still
    yields green through the pass."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-LA01"
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="`sh -c \"echo 2 passed\"`", expected="`2 passed`")
    h.make_ticket(tmp_path, ticket, "M", plan)
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")

    v = sl.judge_step(ticket, 1, repo=str(repo))

    assert v.state == sl.GREEN, v.reason


def test_no_pytest_or_framework_name_anywhere_in_pass_logic():
    """AC-13/C-003: step_ledger's own CODE (comments and docstrings excluded,
    since those may legitimately explain the VERIFY vocabulary) names no
    test-framework identifier anywhere — the pass must stay opaque to what
    kind of command it re-runs."""
    src_path = Path(sl.__file__)
    src = src_path.read_text(encoding="utf-8")
    code_tokens = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code_tokens.append(tok.string)
    code_text = "".join(code_tokens).lower()
    for name in _FRAMEWORK_NAMES:
        assert name not in code_text, f"framework name {name!r} found in step_ledger code logic"
