"""KLC-114 step-9: `/klc:run`'s SKILL.md gains a new post-build sub-step 5f,
inserted after the existing 5e and before step 6 (Advance) — sub-steps 5a
through 5e survive verbatim (AC-12; D-204/F-4: a NEW 5f, never a second 5d
or a relettering of the existing dispatch/parse/stop contract)."""
from __future__ import annotations

from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "klc-plugin" / "skills" / "run" / "SKILL.md"

# Distinctive substrings from each existing sub-step, captured before this
# ticket's edit — proves 5a-5e are untouched, not merely present in spirit.
_SUBSTEP_MARKERS = {
    "5a": "re-render the card in",
    "5b": "do the phase's work",
    "5c": "Take the subagent's returned text as `result`",
    "5d": "Parse: `core.skills.run_signal.parse_signal(result, expected_phase",
    "5e": "Blocking questions — STOP.",
}


def test_run_skill_keeps_substeps_5b_5d_5e_verbatim():
    """AC-12/D-204: sub-steps 5a through 5e survive byte-for-byte — the new
    5f is an ADDITION, not a rewrite of the existing dispatch/parse/stop
    contract."""
    text = _SKILL.read_text(encoding="utf-8")
    for label, marker in _SUBSTEP_MARKERS.items():
        assert marker in text, f"sub-step {label} text changed or missing"


def test_ledger_substep_5f_sits_after_5e_and_before_advance():
    """AC-12/D-204: the new ledger sub-step 5f is placed strictly after 5e
    and strictly before step 6 (Advance)."""
    text = _SKILL.read_text(encoding="utf-8")
    pos_5e = text.index(_SUBSTEP_MARKERS["5e"])
    pos_5f = text.index("Record step verifies")
    pos_6 = text.index("**Advance.**")
    assert pos_5e < pos_5f < pos_6
