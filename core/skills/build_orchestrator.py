"""build_orchestrator.py — dispatch each impl-plan step to a fresh subagent.

Public API:
    run_build(ticket, *, dispatch=runner.run_agent, judge_step=None) -> int
        Walk the steps that `step_state.derive` reports as not green. For each:
          1. Generate + save the dependency-resolved brief.
          2. Resolve the build model; print MODEL_NOTE if it fell back.
          3. Dispatch, then record the step's VERIFY (`step_state.record_verify`)
             and read the state back.
        Returns 0 when all steps are green, non-zero on the first step that is not.

Why no ledger (KLC-174): progress is DERIVED from git and `build/steps.json`
(`step_state`), so there is no `build/progress.md` to drift from the truth. A
step is green only when `step_state` says so, never because a dispatch returned 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
_PROJECT_ROOT_DIR = _SKILLS.parent.parent
for _p in (str(_PROJECT_ROOT_DIR), str(_SKILLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lifecycle import read_meta  # noqa: E402
from model_guard import check_subagent_dispatch, require_subagent_model  # noqa: E402
from models import load_models  # noqa: E402
from task_brief import build_step_brief  # noqa: E402
from per_step_review import should_review, route_findings  # noqa: E402
import runner  # noqa: E402
import settings  # noqa: E402
import step_state  # noqa: E402

PER_STEP_REREVIEW_CAP = 2



def _judge_step(ticket: str, step_num: int) -> dict:
    """Record the step's VERIFY (the only place the orchestrator runs one) and
    return the step's freshly derived record. A module-level seam so
    `run_build`'s `judge_step=` override has a real default to fall back to.

    The dispatched agent runs `klc step verify` itself, so when the step is already
    green (a fresh valid verify for its green commit) the VERIFY is not repeated."""
    def _rec():
        return next((r for r in step_state.derive(ticket) if r["step"] == step_num),
                    {"step": step_num, "state": "pending", "reason": "step missing from plan"})
    rec = _rec()
    if rec["state"] == "green":
        return rec
    step_state.record_verify(ticket, step_num, runner="agent")
    return _rec()


def _next_rec(ticket: str) -> dict | None:
    """First plan step record that is not green (derived from git + steps.json)."""
    for rec in step_state.derive(ticket):
        if rec["state"] != "green":
            return rec
    return None


def _next_step(ticket: str) -> int | None:
    rec = _next_rec(ticket)
    return rec["step"] if rec else None


def _per_step_prompt() -> Path:
    from _paths import framework_root
    return framework_root() / "core" / "agents" / "review" / "per-step.md"


def _brief_path(ticket: str, step_num: int) -> Path:
    from _paths import transient_dir
    return transient_dir(ticket) / "build" / f"step-{step_num}-brief.md"


def _report_path(ticket: str, step_num: int) -> Path:
    from _paths import transient_dir
    return transient_dir(ticket) / "build" / f"step-{step_num}-impl-report.md"


def _fix_brief_path(ticket: str, step_num: int) -> Path:
    from _paths import transient_dir
    return transient_dir(ticket) / "build" / f"step-{step_num}-fix-brief.md"


def _impl_prompt() -> Path:
    from _paths import framework_root
    return framework_root() / "core" / "agents" / "impl.md"


_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbf2e15"


def _step_diff(ticket: str, step_num: int, repo: Path | None = None) -> str:
    """KLC-172: the diff of the step's own commits (`tdd_order.step_commits`),
    each diffed against ITS parent and concatenated — never one first..last
    range, which would pull in other steps' commits interleaved between them.
    A root commit is diffed against the empty tree. "" when the step has no
    commits or the VCS call fails."""
    import subprocess
    import tdd_order
    commits = tdd_order.step_commits(ticket, step_num, repo)
    if not commits:
        return ""

    def _run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              cwd=str(repo) if repo else None, timeout=30)
    parts: list[str] = []
    try:
        for c in commits:
            sha = c["sha"]
            has_parent = _run(["rev-parse", "--verify", "-q", f"{sha}^"]).returncode == 0
            base = f"{sha}^" if has_parent else _EMPTY_TREE
            res = _run(["diff", base, sha])
            if res.returncode == 0:
                parts.append(res.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return "".join(parts)


def _telemetry_dispatch(ticket: str):
    """KLC-133 D-106: the default dispatch installed by `run_build` when the
    caller injects none — the ONLY dispatch that receives telemetry tags
    (`step`/`run_pass`), via the `klc_telemetry` marker `_call` checks
    below. An injected test/caller dispatch keeps today's plain call shape
    untouched."""
    def _dispatch(phase_id, prompt_path, out_path, *, inputs=None, track=None,
                  step=None, run_pass=None):
        return runner.run_agent(phase_id, prompt_path, out_path, inputs=inputs,
                                track=track, telemetry_ticket=ticket,
                                telemetry_phase="build", step=step,
                                run_pass=run_pass)
    _dispatch.klc_telemetry = True
    return _dispatch


def _call(dispatch, *args, step, run_pass, **kwargs):
    """KLC-133 AC-6: add the `step`/`run_pass` tags only for the default
    telemetry dispatch (marked `klc_telemetry`) — an injected dispatch
    without that marker receives exactly its pre-KLC-133 arguments."""
    if getattr(dispatch, "klc_telemetry", False):
        kwargs = dict(kwargs, step=step, run_pass=run_pass)
    return dispatch(*args, **kwargs)


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

    review_input = compose_review_input(ticket, step_num,
                                        step_diff=_step_diff(ticket, step_num))
    review_input_path = _brief_path(ticket, step_num).parent / f"step-{step_num}-review-input.md"
    review_input_path.parent.mkdir(parents=True, exist_ok=True)
    review_input_path.write_text(review_input, encoding="utf-8")

    review_output_path = _brief_path(ticket, step_num).parent / f"step-{step_num}-findings.json"
    rc = _call(dispatch, "per-step-review", _per_step_prompt(), review_output_path,
              inputs={"step package": review_input_path}, track=track,
              step=step_num, run_pass="per-step-review")
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
        fix_brief = compose_review_input(ticket, step_num, step_diff=_step_diff(ticket, step_num)) + f"\n\n## Blocking findings\n\n{blocking_summary}\n"
        fix_path = _fix_brief_path(ticket, step_num)
        fix_path.write_text(fix_brief, encoding="utf-8")
        _call(dispatch, "build", _impl_prompt(), _report_path(ticket, step_num),
             inputs={"brief": fix_path}, step=step_num, run_pass="per-step-fix")

    return False


def _dispatch_step(ticket, n, track, mc, dispatch, judge):
    """Brief, dispatch and judge one step. `(rc, rec)`: rc != 0 is a dispatch error
    (the step simply stays not green); `rec` is None when the verdict is not green."""
    resolved = mc.resolve("build", track=track)
    require_subagent_model(resolved)
    note = check_subagent_dispatch(resolved)

    brief = build_step_brief(ticket, n)
    brief_path = _brief_path(ticket, n)
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(brief, encoding="utf-8")
    if note:
        print(note)

    rc = _call(dispatch, "build", _impl_prompt(), _report_path(ticket, n),
              inputs={"brief": brief_path}, track=track, step=n, run_pass="step")
    if rc != 0:
        return rc, None

    # KLC-174: green only on step_state's verdict, never on `dispatch` returning 0.
    rec = judge(ticket, n)
    if rec["state"] != "green":
        sys.stderr.write(f"klc build-run: step-{n}: {rec['state']} — {rec.get('reason', '')}\n")
        if settings.build_per_step_review_on_verify():
            _run_reviewer(ticket, n, dispatch)
        return 0, None
    return 0, rec


def run_build(ticket: str, *, dispatch=None, judge_step=None) -> int:
    """Dispatch each not-yet-green impl-plan step to a fresh subagent."""
    if dispatch is None:
        dispatch = _telemetry_dispatch(ticket)
    judge = judge_step or _judge_step

    if not step_state.derive(ticket):
        sys.stderr.write(f"klc build-run: {ticket}: impl-plan.md has no steps\n")
        return 1
    meta = read_meta(ticket)
    track = meta["track"]
    mc = load_models()

    max_reviews = settings.build_max_reviews_per_step()
    reviews: dict[int, int] = {}

    while (nxt := _next_rec(ticket)) is not None:
        n = nxt["step"]
        if nxt["state"] == "blocked" and nxt.get("verify_stale"):
            # Only the recorded verify is out of date (a later commit): re-run it,
            # do not pay for a whole new step agent.
            rec = judge(ticket, n)
            if rec["state"] != "green":
                sys.stderr.write(f"klc build-run: step-{n}: {rec['state']} — {rec.get('reason', '')}\n")
                return 1
        else:
            rc, rec = _dispatch_step(ticket, n, track, mc, dispatch, judge)
            if rc != 0:
                return rc
            if rec is None:
                return 1

        # Per-step review gate (M/L always; S only with risk_tags; XS never).
        # A commit already reviewed and passed is never reviewed again: the gate's
        # own fix commit makes the verify stale, not the review.
        review = step_state.read(ticket).get(n, {}).get("review")
        if (isinstance(review, dict) and review.get("state") == "passed"
                and review.get("commit") and review.get("commit") == rec.get("green_commit")):
            continue
        if reviews.get(n, 0) >= max_reviews:
            step_state.mark_review(ticket, n, "blocked", round=reviews[n])
            sys.stderr.write(f"klc build-run: step-{n}: blocked — build.max_reviews_per_step "
                             f"({max_reviews}) reached\n")
            return 1
        reviews[n] = reviews.get(n, 0) + 1
        if not _per_step_gate(ticket, n, meta, dispatch):
            step_state.mark_review(ticket, n, "blocked", round=PER_STEP_REREVIEW_CAP + 1)
            return 1
        if should_review(meta):
            step_state.mark_review(ticket, n, "passed")

    return 0
