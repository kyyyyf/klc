"""per_step_review.py — coverage decision, severity routing, step-package composition.

Public API:
    should_review(meta: dict) -> bool
        True for M/L always; True for S only when meta.risk_tags is non-empty;
        False for XS.

    route_findings(findings) -> RouteResult
        Partition findings into blocking (CRITICAL/HIGH), logged (MEDIUM/LOW),
        and info (INFO). Unknown severity falls into blocking (fail-closed).

    compose_review_input(ticket, step) -> str
        Concatenate step-N-brief.md + step-N-impl-report.md for the reviewer.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
_PROJECT_ROOT_DIR = _SKILLS.parent.parent
for _p in (str(_PROJECT_ROOT_DIR), str(_SKILLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from findings import Finding  # noqa: E402
from _paths import klc_ticket_dir, framework_root  # noqa: E402
import lint_review_prompts  # noqa: E402

_BLOCKING = {"CRITICAL", "HIGH"}
_LOGGED = {"MEDIUM", "LOW"}


@dataclass
class RouteResult:
    blocking: list[Finding] = field(default_factory=list)
    logged: list[Finding] = field(default_factory=list)
    info: list[Finding] = field(default_factory=list)


def should_review(meta: dict) -> bool:
    """Return True when per-step review should run for this ticket."""
    track = meta.get("track", "")
    if track in ("M", "L"):
        return True
    if track == "S":
        return bool(meta.get("risk_tags"))
    return False


def route_findings(findings: list[Finding]) -> RouteResult:
    """Partition findings by severity. Unknown severity → blocking (fail-closed)."""
    result = RouteResult()
    for f in findings:
        sev = (f.severity or "").upper()
        if sev in _LOGGED:
            result.logged.append(f)
        elif sev == "INFO":
            result.info.append(f)
        else:
            result.blocking.append(f)
    return result


def _lint_reasons(reasons: list[str]) -> None:
    """Raise ValueError if any reason contains a pre-judgment directive."""
    hits = lint_review_prompts.lint_text("\n".join(reasons))
    if hits:
        phrases = ", ".join(repr(h["phrase"]) for h in hits)
        raise ValueError(f"pre-judgment directive in injected reason: {phrases}")


def _write_review(ticket: str, step: int, result: "RouteResult") -> None:
    """Render step-N-review.md from the routed findings."""
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        sys.stderr.write("per_step_review: jinja2 not installed\n")
        return

    fw = framework_root()
    env = Environment(
        loader=FileSystemLoader(str(fw / "core" / "templates")),
        keep_trailing_newline=True,
    )
    all_findings = result.blocking + result.logged + result.info
    verdict = "NEEDS_FIX" if result.blocking else "PASS"
    rendered = env.get_template("step-review.md.j2").render(
        ticket=ticket,
        step=step,
        findings=all_findings,
        verdict=verdict,
    )

    build = klc_ticket_dir(ticket) / "build"
    build.mkdir(parents=True, exist_ok=True)
    (build / f"step-{step}-review.md").write_text(rendered, encoding="utf-8")


def compose_review_input(ticket: str, step: int, *, step_diff: str = "") -> str:
    """Return brief + impl-report + optional step diff as the reviewer's input package.

    step_diff: the git diff for this step's commit(s). Callers that know the
    commit range should pass it; omitting it produces a valid but diff-less package.
    """
    build = klc_ticket_dir(ticket) / "build"
    brief_path = build / f"step-{step}-brief.md"
    report_path = build / f"step-{step}-impl-report.md"

    parts = []
    if brief_path.exists():
        parts.append(f"## step-{step} brief\n\n{brief_path.read_text(encoding='utf-8')}")
    if report_path.exists():
        parts.append(f"## step-{step} impl-report\n\n{report_path.read_text(encoding='utf-8')}")
    if step_diff:
        parts.append(f"## step-{step} diff\n\n```diff\n{step_diff}\n```")
    return "\n\n".join(parts)
