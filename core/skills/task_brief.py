"""task_brief.py — dependency-resolved step brief for fresh-subagent dispatch.

Public API:
    build_step_brief(ticket: str, step: int) -> str
        Renders a Markdown brief for one impl-plan step containing:
          - spec Goals + ACs (global constraints)
          - target step's full body
          - only the Interfaces + COMMIT surface of each Depends-on step
          - recorded DECISION lines from the plan

    _render_report_skeleton(ticket: str, step: int) -> str
        Render an empty step-N-impl-report.md scaffold.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
_PROJECT_ROOT_DIR = _SKILLS.parent.parent
for _p in (str(_PROJECT_ROOT_DIR), str(_SKILLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from impl_plan_check import parse_impl_plan_steps  # noqa: E402
from artefacts import _extract_goals_acs  # noqa: E402
from _paths import klc_ticket_dir, framework_root  # noqa: E402

_DEPENDS_RE = re.compile(r"(?im)^\s*-?\s*\*{0,2}Depends-on\*{0,2}:\s*(.+)$")
_INTERFACES_RE = re.compile(
    r"(?im)(\*{0,2}Interfaces\*{0,2}:.*?)(?=\n\s*[-*]?\s*\*{0,2}"
    r"(?:Expected|VERIFY|COMMIT|Affected|Code sketch|Goal|Depends-on)\*{0,2}:|\Z)",
    re.DOTALL,
)
_COMMIT_RE = re.compile(
    r"(?im)(\*{0,2}COMMIT\*{0,2}:.*?)(?=\n\s*[-*]?\s*\*{0,2}"
    r"(?:Affected|Interfaces|Expected|VERIFY|Goal|Code sketch|Depends-on)\*{0,2}:|\Z)",
    re.DOTALL,
)
_DECISION_RE = re.compile(r"(?m)^.*\bDECISION\s+D-\d+\b.*$")
_STEP_REF_RE = re.compile(r"\bstep-(\d+)\b", re.IGNORECASE)


def _read_plan(ticket: str) -> str:
    plan = klc_ticket_dir(ticket) / "impl-plan.md"
    if not plan.exists():
        raise ValueError(f"impl-plan.md not found for ticket {ticket!r}")
    return plan.read_text(encoding="utf-8")


def _by_id(steps: list[dict], step_id: str) -> dict:
    for s in steps:
        if s["id"] == step_id:
            return s
    raise ValueError(f"{step_id} not found in impl-plan")


def _parse_depends(body: str) -> list[str]:
    ids: list[str] = []
    for m in _DEPENDS_RE.finditer(body):
        for ref in _STEP_REF_RE.finditer(m.group(1)):
            ids.append(f"step-{ref.group(1)}")
    return ids


def _interface_surface(step: dict) -> dict:
    body = step["body"]
    iface = ""
    m = _INTERFACES_RE.search(body)
    if m:
        iface = m.group(1).strip()

    commit = ""
    m = _COMMIT_RE.search(body)
    if m:
        commit = m.group(1).strip()

    return {"id": step["id"], "title": step["title"], "interfaces": iface, "commit": commit}


def _decisions(plan_text: str) -> str:
    lines = _DECISION_RE.findall(plan_text)
    return "\n".join(lines).strip()


def _render(goals_acs: str, target: dict, dep_surfaces: list[dict], decisions: str, ticket: str, step: int) -> str:
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        sys.stderr.write("task_brief: jinja2 not installed (pip install jinja2)\n")
        sys.exit(1)

    fw = framework_root()
    env = Environment(
        loader=FileSystemLoader(str(fw / "core" / "templates")),
        keep_trailing_newline=True,
    )
    tmpl = env.get_template("task-brief.md.j2")
    return tmpl.render(
        ticket=ticket,
        step=step,
        goals_acs=goals_acs,
        target=target,
        dep_surfaces=dep_surfaces,
        decisions=decisions,
    )


def build_step_brief(ticket: str, step: int) -> str:
    """Render a dependency-resolved brief for impl-plan step N."""
    plan_text = _read_plan(ticket)
    steps = parse_impl_plan_steps(plan_text)
    target = _by_id(steps, f"step-{step}")
    dep_ids = _parse_depends(target["body"])
    dep_surfaces = []
    for dep_id in dep_ids:
        try:
            dep = _by_id(steps, dep_id)
            dep_surfaces.append(_interface_surface(dep))
        except ValueError:
            sys.stderr.write(f"task-brief: warning: dependency {dep_id!r} not found in plan — skipped\n")

    goals_acs = _extract_goals_acs(klc_ticket_dir(ticket) / "spec.md")
    decisions = _decisions(plan_text)
    return _render(goals_acs, target, dep_surfaces, decisions, ticket, step)


def _render_report_skeleton(ticket: str, step: int) -> str:
    """Render an empty impl-report scaffold from the template."""
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        sys.stderr.write("task_brief: jinja2 not installed\n")
        sys.exit(1)

    fw = framework_root()
    env = Environment(
        loader=FileSystemLoader(str(fw / "core" / "templates")),
        keep_trailing_newline=True,
    )
    tmpl = env.get_template("step-impl-report.md.j2")
    return tmpl.render(ticket=ticket, step=step)
