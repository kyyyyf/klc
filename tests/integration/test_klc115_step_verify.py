"""KLC-115 step-4: core/skills/step_verify.py — re-execute each impl-plan
step's VERIFY command and compare only the isolated Expected token (AC-8,
AC-9, plus the F-2/D-202 token-isolation addendum).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import step_verify as sv  # noqa: E402
import verify_runner as vr  # noqa: E402


def _plan(verify: str, expected: str, step_id: str = "step-1") -> str:
    return (
        f"# Implementation plan\n\n"
        f"## {step_id} — a step\n\n"
        f"- Goal: do the thing\n"
        f"- RED: `tests/test_x.py::test_thing`\n"
        f"- GREEN: implement it\n"
        f"- VERIFY: {verify}\n"
        f"- COMMIT: `KLC-XXX {step_id}: do the thing`\n"
        f"- Affected: `core/skills/x.py`\n"
        f"- Interfaces: none\n"
        f"- Expected: {expected}\n"
        f"- Depends on: none\n"
    )


def _make_ticket(tmp_path, ticket, track, plan_text, meta_extra=None):
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": track,
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    meta.update(meta_extra or {})
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "impl-plan.md").write_text(plan_text, encoding="utf-8")
    return ticket_dir


def test_verify_output_matching_expected_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-SV01"
    _make_ticket(tmp_path, ticket, "M",
                _plan("`python3 -c \"print('1 passed in 0.01s')\"`", "`1 passed`"))
    rep = sv.check_steps(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason, rep.block_reason


def test_verify_output_not_matching_expected_blocks_on_m(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-SV02"
    _make_ticket(tmp_path, ticket, "M",
                _plan("`python3 -c \"print('1 passed in 0.01s')\"`", "`4 passed`"))
    rep = sv.check_steps(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert rep.block_reason
    assert "step-1" in rep.block_reason


def test_placeholder_verify_blocks_on_m(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-SV03"
    _make_ticket(tmp_path, ticket, "M", _plan("TBD", "TBD"))
    rep = sv.check_steps(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert rep.block_reason
    assert "step-1" in rep.block_reason


def test_placeholder_verify_surfaces_on_s(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-SV04"
    _make_ticket(tmp_path, ticket, "S", _plan("TBD", "TBD"))
    rep = sv.check_steps(ticket, "S", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason
    assert rep.surfaced
    assert "step-1" in rep.surfaced[0].message


def test_missing_impl_plan_surfaces_not_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-SV05"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    rep = sv.check_steps(ticket, "M", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason
    assert rep.surfaced
    assert rep.surfaced[0].code == "no-impl-plan"


def test_expected_token_isolation_ignores_prose_and_backticks():
    expected = "`10 passed, 2 skipped` (2 pre-existing skips)"
    token = sv.expected_token(expected)
    assert token == "10 passed, 2 skipped"
    assert sv._token_in_output(token, "10 passed, 2 skipped in 0.51s")


def test_count_prefix_is_not_matched_inside_a_longer_number():
    token = sv.expected_token("`4 passed`")
    assert token == "4 passed"
    assert not sv._token_in_output(token, "24 passed in 0.10s")


def test_budget_exceeded_step_surfaces_but_launch_error_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket_slow = "KLC-SV06"
    _make_ticket(tmp_path, ticket_slow, "M",
                _plan("`python3 -c \"import time; time.sleep(2)\"`", "`1 passed`"))
    monkeypatch.setattr(sv.settings, "verify_step_budget", lambda: 1)
    rep = sv.check_steps(ticket_slow, "M", repo=str(tmp_path), run_commands=True)
    assert not rep.block_reason, rep.block_reason
    text = " ".join(f.message for f in rep.surfaced)
    assert "unverified" in text and "budget-exceeded" in text

    ticket_unlaunchable = "KLC-SV07"
    _make_ticket(tmp_path, ticket_unlaunchable, "M",
                _plan("`___this_executable_does_not_exist___ --flag`", "`1 passed`"))

    def fake_run(command, *, budget_s, cwd=None, **kw):
        return vr.Verdict(vr.UNVERIFIED, vr.LAUNCH_ERROR,
                          "could not launch the command (FileNotFoundError)")

    monkeypatch.setattr(sv.verify_runner, "run", fake_run)
    rep2 = sv.check_steps(ticket_unlaunchable, "M", repo=str(tmp_path), run_commands=True)
    assert rep2.block_reason
    assert "step-1" in rep2.block_reason


# --- F-2/D-202 fail-closed twin: all 25 real Expected fields this project has
# actually written, read through the SAME parser `check_steps` uses. See
# impl-plan.md step-4 for the source table. 13 yield a token and must be
# found in a synthetic pytest tail built from that token; 12 are prose and
# must classify `expected-unmatchable`; none may produce a mismatch.
_REAL_EXPECTED_FIELDS = [
    # (raw Expected field text, isolated token or "" when prose/unmatchable)
    ("`14 passed` — 6 in `test_klc103_shared_accessor.py` (2 more than "
     "originally sketched: `test_accessor_load_raises_on_wrong_shape_regardless_of_required` "
     "and `test_accessor_load_absent_degrades_only_when_not_required`, both baseline "
     "coverage for D-2's degrade/raise split), 2 in `test_klc103_schema_canonical.py`, "
     "6 pre-existing in `test_deterministic_inventory.py`", "14 passed"),
    ("`28 passed`", "28 passed"),
    ("`10 passed, 2 skipped` (2 pre-existing `@unittest.skip` rows — profile.yml "
     "detection override, removed before this ticket — not 1 as originally estimated)",
     "10 passed, 2 skipped"),
    ("`16 passed`", "16 passed"),
    ("`14 passed` — 6 from `test_rules_typescript.py` (the 4 originally planned "
     "plus the two F-1 additions), 1 nesting floor, and 7 parametrised AC-1 cases "
     "(`typescript/.ts`, `tsx/.tsx`, `javascript/.js`, `python/.py`, `rust/.rs`, "
     "`cpp/.cpp`, `cpp-unreal/.h`)", "14 passed"),
    ("`4 passed` from the executor file, then the full suite exits 0 with 0 failed",
     "4 passed"),
    ("the first command reports all new cases passed; the second reports the "
     "pre-existing doctor suites still passing unmodified.", ""),
    ("the first reports both cases passed; the second reports the pre-existing "
     "`test_doctor_without_project_deps` and `test_doctor_default_mode_missing_tools` "
     "still passing (both assert exit 0 and `DOCTOR_OK`, which a warn-only check "
     "preserves).", ""),
    ("the first reports all five lock cases passed, including the two-process race; "
     "the second reports the pre-existing update and init suites still passing "
     "unmodified.", ""),
    ("all five groups pass, including the grandchild-kill assertion and the "
     "boundary pair.", ""),
    ("the first reports the whole refresh file passing, including the three "
     "ordering assertions; the second reports every pre-existing intake, next and "
     "ack suite still passing — in particular that the new \"uninitialised\" "
     "stderr line does not break their substring-based output assertions.", ""),
    ("the first reports both the positive and the invalid-value case passed; the "
     "second reports the pre-existing settings and config-hygiene suites still "
     "passing.", ""),
    ("all six detection cases and the worktree resolution case pass.", ""),
    ("the first reports the whole install file passing, including the fail-open "
     "shim case, the chaining, the idempotency and the manager-files-untouched "
     "assertions; the second reports the pre-existing install and hook suites "
     "still passing.", ""),
    ("the first reports the whole doctor file passing, including all three "
     "recorded-mode branches and the JSON schema assertion over the five new "
     "checks; the second reports the pre-existing doctor suites still passing.", ""),
    ("the new stale file passes and all three pre-existing `_compute_stale` "
     "callers pass, with only the two closure assertions in `test_update_stale.py` "
     "changed.", ""),
    ("both the two-count case and the old-schema case pass.", ""),
    ("the two new files pass; the coverage probe prints `BLOCK_REASON None` and "
     "reports AC-20 to AC-24 as non-blocking undetermined findings; and the full "
     "suite is green.", ""),
    ("`27 passed` (4 new include tests, 12 drift-guard tests, 11 pre-commit gate "
     "tests). No prompt carries a directive yet, so the regenerated bytes are "
     "identical to the committed ones and the drift-guard stays green.", "27 passed"),
    ("`30 passed` (7 include tests, 12 drift-guard tests, 11 pre-commit gate "
     "tests).", "30 passed"),
    ("`20 passed` (8 include tests, 12 drift-guard tests).", "20 passed"),
    ("`13 passed` (1 prompt-honesty test, 12 drift-guard tests).", "13 passed"),
    ("`10 passed`.", "10 passed"),
    ("`55 passed` (2 parser tests, 3 card tests, 8 existing card-compression "
     "tests, 23 existing task-brief tests, 19 existing impl-plan-check tests).",
     "55 passed"),
    ("`26 passed` (2 byte-budget tests, 13 existing docs-consolidation tests, "
     "11 existing precommit-plugin-sync tests).", "26 passed"),
]


def test_real_expected_fields_never_falsely_block():
    assert len(_REAL_EXPECTED_FIELDS) == 25
    compared = [row for row in _REAL_EXPECTED_FIELDS if row[1]]
    surfaced = [row for row in _REAL_EXPECTED_FIELDS if not row[1]]
    assert len(compared) == 13
    assert len(surfaced) == 12

    for raw_expected, tabulated_token in compared:
        token = sv.expected_token(raw_expected)
        assert token == tabulated_token, (raw_expected, token, tabulated_token)
        synthetic_output = f"...\n{token} in 0.42s\n"
        assert sv._token_in_output(token, synthetic_output), (
            f"{token!r} must be found in a synthetic pytest tail")

    for raw_expected, _empty in surfaced:
        assert sv.expected_token(raw_expected) == "", (
            f"expected prose to classify expected-unmatchable: {raw_expected!r}")
