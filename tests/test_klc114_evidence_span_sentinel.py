"""KLC-114 step-15 (review round 2, HIGH; AC-7 / D-114-11): the ledger's own
`<!-- klc-ledger:begin/end -->` span markers are a SECOND injection surface
`_sanitize_for_fence` (D-114-11) did not close. It stripped backticks and
neutralised `AC-<n>` tokens, but not `<!--`/`-->` — so a VERIFY whose
COMMAND text or captured OUTPUT carries the literal
`<!-- klc-ledger:end -->` string survives sanitisation intact and lands
inside the rendered fence. `_splice_evidence`'s non-greedy
`BEGIN.*?END` regex then matches from the REAL begin marker to this FAKE,
embedded end marker, deleting only up to it and leaving the REAL end
marker (plus its now-unpaired closing fence) as orphaned top-level text.
Every subsequent `verify_build_steps` call repeats this: `build-log.md`
grows without bound, and the stray fence flips
`evidence_gate.parse_evidence`'s fence parity for everything after it,
eventually erasing builder AND machine Evidence entries alike
(`by_ac == {}` after enough iterations — the external reviewer's repro).
"""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import evidence_gate as evg  # noqa: E402
import klc114_helpers as h  # noqa: E402
import step_ledger as sl  # noqa: E402

_BUILD_LOG = (
    "# Build log — KLC-SENTINEL\n\n"
    "## Evidence\n\n"
    "AC-1: builder's own entry\n\n"
    "```\n$ echo hi\nhi\n```\n"
)


def _setup(tmp_path, monkeypatch, ticket, sentinel: str):
    """A step whose VERIFY command text AND captured stdout both carry the
    literal *sentinel* (one of the module's own span markers)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    verify = f"`sh -c \"echo '2 passed {sentinel}'\"`"
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify=verify, expected="`2 passed`", addresses="AC-1")
    h.make_ticket(tmp_path, ticket, "M", plan, build_log=_BUILD_LOG)
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")
    return repo


def _run_twice_and_check(tmp_path, ticket, repo):
    log_path = tmp_path / ".klc" / "tickets" / ticket / "build-log.md"

    sl.verify_build_steps(ticket, str(repo))
    first = log_path.read_text(encoding="utf-8")

    sl.verify_build_steps(ticket, str(repo))
    second = log_path.read_text(encoding="utf-8")

    assert first == second, "a second ack must not grow or mutate build-log.md"
    assert first.count(sl._EVID_BEGIN) == 1, "exactly one begin marker must exist"
    assert first.count(sl._EVID_END) == 1, "exactly one end marker must exist"
    assert "builder's own entry" in first  # the builder's own text survives

    by_ac, malformed = evg.parse_evidence(first, ["AC-1"])
    assert "AC-1" in by_ac
    assert by_ac["AC-1"].verdict == evg.PASS
    assert malformed == []


def test_end_sentinel_in_command_and_output_cannot_terminate_the_span_early(tmp_path, monkeypatch):
    """AC-7: a VERIFY whose command text and stdout both carry the literal
    `<!-- klc-ledger:end -->` sentinel must not let a fake end marker
    truncate the real span — two consecutive `verify_build_steps` calls
    leave build-log.md byte-identical, with exactly one begin/end pair and
    a clean, still-parsing AC-1 PASS entry."""
    ticket = "KLC-SENTINEL01"
    repo = _setup(tmp_path, monkeypatch, ticket, sl._EVID_END)
    _run_twice_and_check(tmp_path, ticket, repo)


def test_begin_sentinel_in_output_cannot_terminate_the_span_early(tmp_path, monkeypatch):
    """AC-7 twin: the same attack using the literal `<!-- klc-ledger:begin
    -->` sentinel instead — the fix must neutralise both markers, not just
    the end one."""
    ticket = "KLC-SENTINEL02"
    repo = _setup(tmp_path, monkeypatch, ticket, sl._EVID_BEGIN)
    _run_twice_and_check(tmp_path, ticket, repo)
