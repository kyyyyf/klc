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
from _paths import klc_ticket_dir  # noqa: E402

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


def compose_review_input(ticket: str, step: int) -> str:
    """Return brief + impl-report concatenated as the reviewer's input package."""
    build = klc_ticket_dir(ticket) / "build"
    brief_path = build / f"step-{step}-brief.md"
    report_path = build / f"step-{step}-impl-report.md"

    parts = []
    if brief_path.exists():
        parts.append(f"## step-{step} brief\n\n{brief_path.read_text(encoding='utf-8')}")
    if report_path.exists():
        parts.append(f"## step-{step} impl-report\n\n{report_path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)
