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
import settings  # noqa: E402
import step_ledger as _step_ledger  # noqa: E402

PER_STEP_REREVIEW_CAP = 2

# D-202: a module-level seam so a test can pin a verdict without faking git
# history, and so `run_build`'s own `judge_step=` override has a real default
# to fall back to.
_judge_step = _step_ledger.judge_step


def _per_step_prompt() -> Path:
    from _paths import framework_root
    return framework_root() / "core" / "agents" / "review" / "per-step.md"


def _brief_path(ticket: str, step_num: int) -> Path:
    from _paths import klc_ticket_dir
    return klc_ticket_dir(ticket) / "build" / f"step-{step_num}-brief.md"


def _report_path(ticket: str, step_num: int) -> Path:
    from _paths import klc_ticket_dir
    return klc_ticket_dir(ticket) / "build" / f"step-{step_num}-impl-report.md"


def _fix_brief_path(ticket: str, step_num: int) -> Path:
    from _paths import klc_ticket_dir
    return klc_ticket_dir(ticket) / "build" / f"step-{step_num}-fix-brief.md"


def _run_reviewer(ticket: str, step_num: int, dispatch, *, track: str | None = None) -> list:
    """Dispatch the per-step reviewer — AS THE ROLE PROMPT it actually is
    (`core/agents/review/per-step.md`), with the composed review package as
    a labelled input, under the explicit `per-step-review` role (AC-9).

    D-203: kept as a 3-positional-argument call from `_per_step_gate`
    (unchanged) plus a keyword-only `track`, so the existing monkeypatched
    3-arg stubs keep working; when the caller doesn't supply `track`, it is
    resolved here from the ticket's own meta."""
    from per_step_review import compose_review_input
    import json as _json
    from findings import Finding

    if track is None:
        try:
            track = read_meta(ticket).get("track")
        except Exception:
            track = None

    review_input = compose_review_input(ticket, step_num)
    review_input_path = _brief_path(ticket, step_num).parent / f"step-{step_num}-review-input.md"
    review_input_path.parent.mkdir(parents=True, exist_ok=True)
    review_input_path.write_text(review_input, encoding="utf-8")

    review_output_path = _brief_path(ticket, step_num).parent / f"step-{step_num}-findings.json"
    rc = dispatch("per-step-review", _per_step_prompt(), review_output_path,
                  inputs={"step package": review_input_path}, track=track)
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


def _finish(ticket: str, rc: int, verify_on: bool) -> int:
    """D-205: EVERY exit path runs the whole-build ledger pass once, so
    `klc build-run`'s final `progress.md` goes through the SAME function
    `can_complete_build` and a future CLI/`/klc:run` sub-step use — which is
    what makes AC-1's byte-identity real."""
    if verify_on:
        _step_ledger.verify_build_steps(ticket, None, write=True)
    return rc


def run_build(ticket: str, *, dispatch=None, judge_step=None) -> int:
    """Dispatch each pending impl-plan step to a fresh subagent."""
    if dispatch is None:
        dispatch = runner.run_agent
    judge = judge_step or _judge_step
    verify_on = settings.build_verify_steps()

    led = Ledger.load(ticket) or Ledger.from_plan(ticket)
    meta = read_meta(ticket)
    track = meta["track"]
    mc = load_models()

    while (n := led.first_pending()) is not None:
        resolved = mc.resolve("build", track=track)
        require_subagent_model(resolved)
        note = check_subagent_dispatch(resolved)

        brief = build_step_brief(ticket, n)
        brief_path = _brief_path(ticket, n)
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(brief, encoding="utf-8")
        if note:
            print(note)

        step_id = f"step-{n}"
        led.mark(step_id, "running", model=resolved.model)
        led.save()

        rc = dispatch("build", brief_path, _report_path(ticket, n), track=track)

        if rc != 0:
            led.mark(step_id, "blocked", reason=f"dispatch rc={rc}")
            led.save()
            return _finish(ticket, rc, verify_on)

        # KLC-114 AC-8: a step is green only on the LEDGER PASS's verdict for
        # it — never on `dispatch` returning 0 alone. `verify_on=False`
        # (build.verify_steps: false) restores today's ack byte-for-byte.
        verdict = judge(ticket, n) if verify_on else None
        state = verdict.state if verdict else "green"
        led.mark(step_id, state, model=resolved.model,
                reason=(verdict.reason or None) if verdict else None)
        led.save()

        if state != "green":
            if settings.build_per_step_review_on_verify():
                _run_reviewer(ticket, n, dispatch)
            return _finish(ticket, 1, verify_on)

        # Per-step review gate (M/L always; S only with risk_tags; XS never)
        if not _per_step_gate(ticket, n, meta, dispatch):
            led.mark(step_id, "blocked", reason="per-step review: blocking findings not resolved")
            led.save()
            return _finish(ticket, 1, verify_on)

    return _finish(ticket, 0, verify_on)
