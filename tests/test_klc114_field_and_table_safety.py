"""KLC-114 step-14 (review round 1): two independent parsing/rendering
safety fixes found by the same review round.

(a) MEDIUM, AC-13 — `impl_plan_check.extract_step_fields` strips fenced
regions with `_ANY_FENCE_RE` before extracting fields; the old regex had
no line-anchor, so a `` ``` `` occurring MID-LINE inside a one-line field
value (e.g. a VERIFY command that echoes a literal triple-backtick) paired
up with the step's own REAL code-sketch fence later in the body, erasing
every field in between (Expected, Affected, Interfaces, Rollback, Depends
on, COMMIT — all silently emptied).

(b) LOW, AC-6 — `build_ledger.Ledger._render`'s markdown table embeds a
step's `reason` raw; a reason containing a literal `|` corrupts the
table's column count (the YAML frontmatter stays the authoritative source
either way, so this is cosmetic, not a parsing defect — still worth
fixing).
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import re as _re

import build_ledger as bl  # noqa: E402
import impl_plan_check as ipc  # noqa: E402
import klc114_helpers as h  # noqa: E402

_UNESCAPED_PIPE_RE = _re.compile(r"(?<!\\)\|")


def test_verify_field_backtick_fence_mid_line_does_not_erase_later_fields():
    """AC-13: a VERIFY value containing a literal triple-backtick MID-LINE
    (the reviewer's repro) must not be treated as a fence boundary —
    Expected/Affected/Interfaces/Rollback/Depends-on/COMMIT are all still
    correctly extracted, and the VERIFY value itself is preserved intact."""
    body = textwrap.dedent('''
        - Goal: do the thing
        - RED: `tests/test_x.py::test_thing`
        - GREEN: implement it
        - VERIFY: `sh -c "echo '```' && echo 2 passed"`
        - COMMIT: `KLC-XXX step-1: do the thing`
        - Affected: `core/skills/x.py`
        - Interfaces: none
        - Expected: `2 passed`
        - Rollback: none
        - Depends on: none

        ```python
        # sketch
        pass
        ```
    ''')
    fields = ipc.extract_step_fields(body)
    assert fields["expected"] == "`2 passed`"
    assert fields["affected"] == ["core/skills/x.py"]
    assert fields["interfaces"] == "none"
    assert fields["rollback"] == "none"
    assert fields["depends_on"] == "none"
    assert fields["commit"] == "`KLC-XXX step-1: do the thing`"
    assert "2 passed" in fields["verify"]
    assert "```" in fields["verify"]  # the literal backtick survives verbatim


def test_reason_containing_pipe_round_trips_and_keeps_table_column_count(tmp_path, monkeypatch):
    """LOW/AC-6: a reason containing a literal `|` must not corrupt the
    progress.md markdown table's column count, and must still round-trip
    exactly through the YAML frontmatter via `Ledger.load`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-PIPE01"
    plan = "# Implementation plan\n\n" + h.step_plan("step-1")
    h.make_ticket(tmp_path, ticket, "M", plan)

    reason_with_pipe = "expected token '2 passed' not found | actual: 1 passed"
    led = bl.Ledger.from_plan(ticket)
    led.mark("step-1", "red", reason=reason_with_pipe)
    led.save()

    progress = tmp_path / ".klc" / "tickets" / ticket / "build" / "progress.md"
    text = progress.read_text(encoding="utf-8")
    row_line = next(l for l in text.splitlines() if l.strip().startswith("| step-1"))
    unescaped = len(_UNESCAPED_PIPE_RE.findall(row_line))
    assert unescaped == 6, row_line  # 5 columns => 6 UNESCAPED pipe delimiters, no more
    assert "\\|" in row_line, "the literal pipe must be escaped, not merely present"

    reloaded = bl.Ledger.load(ticket)
    assert reloaded.steps[0].reason == reason_with_pipe
