"""KLC-114 step-4: `verify_build_steps` walks every impl-plan step, marks the
ledger with its verdict, and degrades to a stated note instead of raising
when its inputs are missing (AC-6)."""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_ledger as bl  # noqa: E402
import klc114_helpers as h  # noqa: E402
import step_ledger as sl  # noqa: E402


def test_progress_md_roundtrips_all_four_verdicts_and_reasons(tmp_path, monkeypatch):
    """AC-6: build/progress.md carries one of green|red|unverified|
    scope-violation plus a reason per step, the reason is visible in the
    rendered markdown table as well as the frontmatter, and a `Ledger.load`
    round-trip preserves every verdict and reason exactly."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-PL01"
    plan = "# Implementation plan\n\n" + "".join(
        h.step_plan(f"step-{n}") for n in (1, 2, 3, 4))
    h.make_ticket(tmp_path, ticket, "M", plan)

    led = bl.Ledger.from_plan(ticket)
    led.mark("step-1", sl.GREEN)
    led.mark("step-2", sl.RED, reason="VERIFY exited 1")
    led.mark("step-3", sl.UNVERIFIED, reason="no-commits")
    led.mark("step-4", sl.SCOPE_VIOLATION,
             reason="core/skills/x.py outside the declared surface of step-4")
    led.save()

    progress = tmp_path / ".klc" / "tickets" / ticket / "build" / "progress.md"
    text = progress.read_text(encoding="utf-8")
    assert "VERIFY exited 1" in text
    assert "no-commits" in text
    assert "outside the declared surface" in text

    reloaded = bl.Ledger.load(ticket)
    by_id = {s.id: s for s in reloaded.steps}
    assert by_id["step-1"].state == sl.GREEN
    assert by_id["step-2"].state == sl.RED
    assert by_id["step-2"].reason == "VERIFY exited 1"
    assert by_id["step-3"].state == sl.UNVERIFIED
    assert by_id["step-3"].reason == "no-commits"
    assert by_id["step-4"].state == sl.SCOPE_VIOLATION
    assert by_id["step-4"].reason == "core/skills/x.py outside the declared surface of step-4"


def test_missing_impl_plan_or_zero_steps_degrades_to_report_line_without_raising(tmp_path, monkeypatch):
    """AC-6 boundary: an absent impl-plan.md, or a plan that parses to zero
    steps, each degrade `verify_build_steps` to a stated report line and
    write nothing — never an unhandled exception on the ack path."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    ticket = "KLC-PL02"
    (tmp_path / ".klc" / "tickets" / ticket).mkdir(parents=True)
    rep = sl.verify_build_steps(ticket, str(tmp_path))
    assert rep.verdicts == []
    assert rep.note
    assert not rep.wrote
    progress = tmp_path / ".klc" / "tickets" / ticket / "build" / "progress.md"
    assert not progress.exists()

    ticket2 = "KLC-PL03"
    h.make_ticket(tmp_path, ticket2, "M", "# Implementation plan\n\nno steps here.\n")
    rep2 = sl.verify_build_steps(ticket2, str(tmp_path))
    assert rep2.verdicts == []
    assert rep2.note
    assert not rep2.wrote
