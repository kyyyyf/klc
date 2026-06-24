"""build_orchestrator.py — dispatch each impl-plan step to a fresh subagent.

Public API:
    run_build(ticket, *, dispatch=runner.run_agent) -> int
        Iterate the pending ledger steps. For each pending step:
          1. Generate + save the dependency-resolved brief.
          2. Resolve the build model; print MODEL_NOTE if it fell back.
          3. Mark the step running, dispatch, mark green or blocked.
        Returns 0 when all steps are green, non-zero on first blocked step.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
_PROJECT_ROOT_DIR = _SKILLS.parent.parent
for _p in (str(_PROJECT_ROOT_DIR), str(_SKILLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from build_ledger import Ledger  # noqa: E402
from lifecycle import read_meta  # noqa: E402
from model_guard import check_subagent_dispatch  # noqa: E402
from models import load_models  # noqa: E402
from task_brief import build_step_brief  # noqa: E402
import runner  # noqa: E402


def _brief_path(ticket: str, step_num: int) -> Path:
    from _paths import klc_ticket_dir
    return klc_ticket_dir(ticket) / "build" / f"step-{step_num}-brief.md"


def _report_path(ticket: str, step_num: int) -> Path:
    from _paths import klc_ticket_dir
    return klc_ticket_dir(ticket) / "build" / f"step-{step_num}-impl-report.md"


def run_build(ticket: str, *, dispatch=None) -> int:
    """Dispatch each pending impl-plan step to a fresh subagent."""
    if dispatch is None:
        dispatch = runner.run_agent

    led = Ledger.load(ticket) or Ledger.from_plan(ticket)
    track = read_meta(ticket)["track"]
    mc = load_models()

    while (n := led.first_pending()) is not None:
        brief = build_step_brief(ticket, n)
        brief_path = _brief_path(ticket, n)
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(brief, encoding="utf-8")

        resolved = mc.resolve("build", track=track)
        note = check_subagent_dispatch(resolved)
        if note:
            print(note)

        step_id = f"step-{n}"
        led.mark(step_id, "running", model=resolved.model)
        led.save()

        rc = dispatch("build", brief_path, _report_path(ticket, n), track=track)

        led.mark(step_id, "green" if rc == 0 else "blocked",
                 reason=None if rc == 0 else f"dispatch rc={rc}")
        led.save()

        if rc != 0:
            return rc

    return 0
