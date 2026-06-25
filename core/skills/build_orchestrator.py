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
from model_guard import check_subagent_dispatch, require_subagent_model  # noqa: E402
from models import load_models  # noqa: E402
from task_brief import build_step_brief  # noqa: E402
from per_step_review import should_review, route_findings  # noqa: E402
import runner  # noqa: E402

PER_STEP_REREVIEW_CAP = 2


def _brief_path(ticket: str, step_num: int) -> Path:
    from _paths import klc_ticket_dir
    return klc_ticket_dir(ticket) / "build" / f"step-{step_num}-brief.md"


def _report_path(ticket: str, step_num: int) -> Path:
    from _paths import klc_ticket_dir
    return klc_ticket_dir(ticket) / "build" / f"step-{step_num}-impl-report.md"


def _fix_brief_path(ticket: str, step_num: int) -> Path:
    from _paths import klc_ticket_dir
    return klc_ticket_dir(ticket) / "build" / f"step-{step_num}-fix-brief.md"


def _run_reviewer(ticket: str, step_num: int, dispatch) -> list:
    """Dispatch the per-step reviewer and return a list of Finding objects."""
    from per_step_review import compose_review_input
    import json as _json
    from findings import Finding

    review_input = compose_review_input(ticket, step_num)
    review_input_path = _brief_path(ticket, step_num).parent / f"step-{step_num}-review-input.md"
    review_input_path.parent.mkdir(parents=True, exist_ok=True)
    review_input_path.write_text(review_input, encoding="utf-8")

    review_output_path = _brief_path(ticket, step_num).parent / f"step-{step_num}-findings.json"
    rc = dispatch("per-step-review", review_input_path, review_output_path)
    if rc != 0:
        # Dispatch error → synthetic CRITICAL (fail-closed)
        from findings import Finding
        return [Finding(rule_name="dispatch-error", severity="CRITICAL",
                        file="(reviewer)", line=0,
                        title="Reviewer dispatch failed",
                        body=f"dispatch rc={rc}", fix=None, reviewer="orchestrator")]

    if not review_output_path.exists():
        return []
    try:
        raw = _json.loads(review_output_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [Finding.from_dict(d) for d in raw]
    except Exception:
        pass
    return []


def _per_step_gate(ticket: str, step_num: int, meta: dict, dispatch,
                   *, reasons: list[str] | None = None) -> bool:
    """Run per-step review after a green step. Returns True if step can advance.

    reasons: optional per-ticket context strings to validate via lint before dispatch.
    """
    if not should_review(meta):
        return True

    from per_step_review import compose_review_input, _lint_reasons, _write_review

    if reasons:
        _lint_reasons(reasons)  # raises ValueError on pre-judgment directive

    for attempt in range(PER_STEP_REREVIEW_CAP + 1):
        findings = _run_reviewer(ticket, step_num, dispatch)
        result = route_findings(findings)

        # Always persist all findings (logged/info go to step-N-review.md)
        _write_review(ticket, step_num, result)

        if not result.blocking:
            return True

        if attempt == PER_STEP_REREVIEW_CAP:
            return False

        # Dispatch a fix subagent with the blocking findings as context
        blocking_summary = "\n".join(
            f"- [{f.severity}] {f.title} ({f.file}:{f.line})" for f in result.blocking
        )
        fix_brief = compose_review_input(ticket, step_num) + f"\n\n## Blocking findings\n\n{blocking_summary}\n"
        fix_path = _fix_brief_path(ticket, step_num)
        fix_path.write_text(fix_brief, encoding="utf-8")
        dispatch("build", fix_path, _report_path(ticket, step_num))

    return False


def run_build(ticket: str, *, dispatch=None) -> int:
    """Dispatch each pending impl-plan step to a fresh subagent."""
    if dispatch is None:
        dispatch = runner.run_agent

    led = Ledger.load(ticket) or Ledger.from_plan(ticket)
    meta = read_meta(ticket)
    track = meta["track"]
    mc = load_models()

    while (n := led.first_pending()) is not None:
        brief = build_step_brief(ticket, n)
        brief_path = _brief_path(ticket, n)
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(brief, encoding="utf-8")

        resolved = mc.resolve("build", track=track)
        require_subagent_model(resolved)
        note = check_subagent_dispatch(resolved)
        if note:
            print(note)

        step_id = f"step-{n}"
        led.mark(step_id, "running", model=resolved.model)
        led.save()

        rc = dispatch("build", brief_path, _report_path(ticket, n), track=track)

        if rc == 0:
            led.mark(step_id, "green", model=resolved.model)
            led.save()
            # Per-step review gate (M/L always; S only with risk_tags; XS never)
            if not _per_step_gate(ticket, n, meta, dispatch):
                led.mark(step_id, "blocked", reason="per-step review: blocking findings not resolved")
                led.save()
                return 1
        else:
            led.mark(step_id, "blocked", reason=f"dispatch rc={rc}")
            led.save()
            return rc

    return 0
