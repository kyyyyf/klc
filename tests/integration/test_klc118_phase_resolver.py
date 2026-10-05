#!/usr/bin/env python3
"""KLC-118 step-4 — AC-3: `phase_resolver` publishes the card mode and path
from one call, so the interactive orchestrator (Task-tool) and the headless
runner read the SAME decision, with no second place deriving the mode
(C-001).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))


def _make_ticket(tmp_path: Path, ticket: str, track: str) -> None:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True, exist_ok=True)
    meta = {"ticket": ticket, "track": track, "phase": "placeholder:work"}
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_resolved_phase_publishes_card_mode_and_path_from_one_call(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import phase_resolver as pr
    import artefacts as _artefacts

    _make_ticket(tmp_path, "KLC-PR1", "S")

    headless = pr.resolve_phase("KLC-PR1", "review", executor=pr.EXECUTOR_HEADLESS)
    assert headless.card_mode == _artefacts.CARD_MODE_PASTE, headless

    task = pr.resolve_phase("KLC-PR1", "review", executor=pr.EXECUTOR_TASK)
    assert task.card_mode == _artefacts.CARD_MODE_DISPATCH, task

    # the default (no executor given) must stay the SAFE value — every
    # unconverted caller (e.g. runner.py, which calls resolve_phase with no
    # executor kwarg) keeps getting paste, never dispatch (D-006).
    default = pr.resolve_phase("KLC-PR1", "review")
    assert default.card_mode == _artefacts.CARD_MODE_PASTE, default

    # the published card_path is the EXACT path the writer would produce —
    # not independently re-derived.
    meta = json.loads((tmp_path / ".klc" / "tickets" / "KLC-PR1" / "meta.json")
                       .read_text())
    written = _artefacts.card_path("KLC-PR1", "review")
    assert str(written.resolve()) == str(Path(task.card_path).resolve())
    assert str(written.resolve()) == str(Path(headless.card_path).resolve())


def test_no_second_source_of_truth_for_the_mode_string(tmp_path):
    """C-001: neither the orchestrator skill nor the headless-side wiring
    hardcodes a mode string outside a `resolve_phase` call."""
    skill = (_FW_ROOT / "klc-plugin" / "skills" / "go" / "SKILL.md").read_text(
        encoding="utf-8")
    autorunner_src = (_FW_ROOT / "core" / "skills" / "autorunner.py").read_text(
        encoding="utf-8")

    # autorunner must never assign the literal mode strings itself — it only
    # ever reads `resolved.card_mode` (or the artefacts.CARD_MODE_* symbols).
    assert not re.search(r'mode\s*=\s*["\'](dispatch|paste)["\']', autorunner_src), \
        "autorunner.py hardcodes a mode string outside resolve_phase"

    # the orchestrator skill's prose must route the mode decision through
    # resolve_phase's executor kwarg, not hardcode "dispatch" as a literal
    # mode= assignment.
    assert not re.search(r'mode\s*=\s*["\']dispatch["\']', skill), \
        "SKILL.md hardcodes mode=\"dispatch\" instead of deriving it from resolve_phase"
    assert "executor=" in skill or 'executor="task"' in skill, \
        "SKILL.md must resolve with the Task executor, not guess the mode"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
