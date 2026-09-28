"""KLC-114 step-9: a 4-step fixture ticket with a fabricated git history
reproduces all four verdicts (`green`, `red`, `unverified`,
`scope-violation`) in one run, and the resulting Evidence rows are accepted
by `evidence_gate.check_evidence` with zero malformed or missing-entry
findings — not only the happy path (AC-12; A-202/C-102: the fixture is
4-step, one step per verdict; the test node id is kept exactly as
test-plan.md spells it)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import klc114_helpers as h  # noqa: E402

_FIXTURE_DIR = _FW_ROOT / "tests" / "fixtures" / "klc114-ledger"
_TICKET = "KLC-114-LEDGER"


def _make_ticket(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket_dir = tmp_path / ".klc" / "tickets" / _TICKET
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": _TICKET, "kind": "tech", "phase": "build:ack-needed", "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        "---\nticket: KLC-114-LEDGER\nkind: tech\n---\n\n"
        "## Acceptance Criteria\n"
        "- [ ] AC-1: the green step · produces · a passing VERIFY · when re-run\n\n"
        "## Estimate\n- total: 1\n", encoding="utf-8")
    (ticket_dir / "test-plan.md").write_text(
        "---\nticket: KLC-114-LEDGER\nkind: test-plan\n---\n\n"
        "## Acceptance coverage\n\n| AC | Type | Test location |\n| --- | --- | --- |\n"
        "| AC-1 | unit | tests/test_x.py::test_thing |\n\n## Edge cases\n- n/a\n",
        encoding="utf-8")
    (ticket_dir / "impl-plan.md").write_text(
        (_FIXTURE_DIR / "impl-plan.md").read_text(encoding="utf-8"), encoding="utf-8")
    (ticket_dir / "build-log.md").write_text(
        (_FIXTURE_DIR / "build-log.md").read_text(encoding="utf-8"), encoding="utf-8")
    return ticket_dir


def _build_fixture_history(tmp_path):
    repo = h.make_repo(tmp_path, "ledger-repo")
    # step-1: GREEN — test-only commit, then a well-scoped impl commit.
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{_TICKET} step-1: add test")
    h.commit(repo, {"core/skills/green.py": "# impl"}, f"{_TICKET} step-1: implement")
    # step-2: RED — an impl commit with NO preceding test commit for step-2.
    h.commit(repo, {"core/skills/red.py": "# impl, no test committed first"},
             f"{_TICKET} step-2: implement")
    # step-3: UNVERIFIED — no commit anywhere carries the step-3 key at all.
    # step-4: SCOPE-VIOLATION — test commit, then an impl commit that touches
    # an extra, undeclared file alongside the declared one.
    h.commit(repo, {"tests/test_w.py": "# test"}, f"{_TICKET} step-4: add test")
    h.commit(repo, {"core/skills/scoped.py": "# impl",
                    "core/skills/undeclared_stray.py": "# stray"},
             f"{_TICKET} step-4: implement")
    return repo


def test_three_step_fixture_yields_green_red_unverified_scope_violation_and_clean_evidence(
        tmp_path, monkeypatch):
    """AC-12: one run over one fabricated history reproduces all four
    verdicts, `progress.md` carries exactly 4 rows, and the machine Evidence
    row `evidence_gate.check_evidence` reads is clean."""
    import step_ledger as sl
    import evidence_gate as evg

    ticket_dir = _make_ticket(tmp_path, monkeypatch)
    repo = _build_fixture_history(tmp_path)

    rep = sl.verify_build_steps(_TICKET, str(repo), write=True)

    states = {v.step_id: v.state for v in rep.verdicts}
    assert states == {
        "step-1": sl.GREEN,
        "step-2": sl.RED,
        "step-3": sl.UNVERIFIED,
        "step-4": sl.SCOPE_VIOLATION,
    }, states

    progress_text = (ticket_dir / "build" / "progress.md").read_text(encoding="utf-8")
    row_count = len(re.findall(r"^\s*-\s+id:\s*step-\d+", progress_text, re.MULTILINE))
    assert row_count == 4, progress_text

    log_text = (ticket_dir / "build-log.md").read_text(encoding="utf-8")
    assert "step ledger pass" in log_text
    assert "builder's own manual re-run" in log_text  # builder's entry survives

    erep = evg.check_evidence(_TICKET, "M", str(repo), run_commands=True)
    assert not erep.block_reason, erep.block_reason
    assert not erep.surfaced or all("arm-budget" not in f.code for f in erep.surfaced)
