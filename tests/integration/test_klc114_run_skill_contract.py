"""KLC-114 step-9: `/klc:run`'s SKILL.md gains a new post-build sub-step 5f,
inserted after the existing 5e and before step 6 (Advance) — sub-steps 5a
through 5e survive verbatim (AC-12; D-204/F-4: a NEW 5f, never a second 5d
or a relettering of the existing dispatch/parse/stop contract)."""
from __future__ import annotations

from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "klc-plugin" / "skills" / "go" / "SKILL.md"

# KLC-177 step-5: the loop was rewritten around `klc go --until integrate`; the
# dispatch/parse/stop contract now lives in step 3 (a-h). These markers pin it.
_SUBSTEP_MARKERS = {
    "render": "re-render the card with",
    "inline": "do the work yourself",
    "task": "Task(subagent_type=<agent>, model=<model>, prompt=<card text>)",
    "dispatch_line": "`dispatch: agent=<klc-…> model=<alias> card=<path>`",
    "parse": "core.skills.run_signal.parse_signal(result, expected_phase=",
    "blocking": "Non-empty `blocking_questions`: STOP",
}


def test_run_skill_keeps_dispatch_parse_stop_contract():
    """The dispatch/parse/stop contract survives the KLC-177 rewrite."""
    text = _SKILL.read_text(encoding="utf-8")
    for label, marker in _SUBSTEP_MARKERS.items():
        assert marker in " ".join(text.split()), f"{label} text changed or missing"


def test_step_verify_sits_after_blocking_questions_and_before_the_next_go():
    """The build step-verify sub-step comes after the blocking-question stop and
    before the loop returns to `klc go`."""
    text = " ".join(_SKILL.read_text(encoding="utf-8").split())
    pos_block = text.index(_SUBSTEP_MARKERS["blocking"])
    pos_verify = text.index("klc step verify <KEY> N")
    pos_loop = text.index("Go to step 1")
    assert pos_block < pos_verify < pos_loop
