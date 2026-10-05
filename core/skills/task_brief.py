"""task_brief.py — dependency-resolved step brief for fresh-subagent dispatch.

Public API:
    build_step_brief(ticket: str, step: int, *, findings=None) -> str
        Renders a Markdown brief for one impl-plan step containing:
          - spec Goals + ACs (global constraints; full for step 1, a pointer later)
          - the review findings that concern this step
          - target step's full body
          - only the Interfaces + COMMIT surface of each Depends-on step
          - recorded DECISION lines from the plan

    _render_report_skeleton(ticket: str, step: int) -> str
        Render an empty step-N-impl-report.md scaffold.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
_PROJECT_ROOT_DIR = _SKILLS.parent.parent
for _p in (str(_PROJECT_ROOT_DIR), str(_SKILLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from impl_plan_check import parse_impl_plan_steps, extract_step_fields  # noqa: E402
from artefacts import _extract_goals_acs  # noqa: E402
from _paths import klc_ticket_dir, framework_root  # noqa: E402
import findings_store  # noqa: E402

_DEPENDS_RE = re.compile(r"(?im)^\s*-?\s*\*{0,2}Depends-on\*{0,2}:\s*(.+)$")
_DECISION_RE = re.compile(r"(?m)^.*\bDECISION\s+D-\d+\b.*$")
_ANY_FENCE_RE = re.compile(r"```[^\n]*\n[\s\S]*?```")
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
    """The Interfaces + COMMIT surface of a depended-on step, via the ONE
    shared field extractor (KLC-113, D-003) — no second Interfaces/COMMIT
    regex fork. Re-labelled here (not by `extract_step_fields`, which
    returns bare values) so the brief still reads as a labelled surface,
    matching this function's pre-KLC-113 output shape (C-005: a
    de-duplication, not a behaviour change — the dependency's interface
    signature and COMMIT subject must still appear in the rendered brief)."""
    fields = extract_step_fields(step["body"])
    iface = f"**Interfaces:** {fields['interfaces']}" if fields.get("interfaces") else ""
    commit = f"**COMMIT:** {fields['commit']}" if fields.get("commit") else ""
    return {"id": step["id"], "title": step["title"], "interfaces": iface, "commit": commit}


def _decisions(plan_text: str) -> str:
    text_outside_fences = _ANY_FENCE_RE.sub("", plan_text)
    lines = _DECISION_RE.findall(text_outside_fences)
    return "\n".join(lines).strip()


_FINDINGS_KINDS = ("spec-review", "test-plan-review", "impl-plan-review", "layer0")


def _mentions(text: str, step_num: int, addresses: set[str]) -> bool:
    """True when free text names `step-N` (word-bounded, so step-2 never
    matches step-20) or any AC id in *addresses* (so AC-1 never matches AC-12)."""
    if re.search(rf"\bstep-{step_num}\b", text, re.IGNORECASE):
        return True
    return any(ac_id in addresses for ac_id in re.findall(r"\bAC-\d+\b", text))


def step_findings(ticket: str, step_num: int) -> list[dict]:
    """KLC-172: the review findings that concern one step. Stored findings carry
    their step / AC reference as free text in `ref` (`ac` is "" and there is no
    `step` key), so a finding matches when its `ref` — or, when `ref` is empty,
    its `title` + `body` — names `step-N` or one of the step's `Addresses:` ACs;
    an explicit integer `step == N` matches too. The brief lists them so the
    build agent no longer reads the three findings files."""
    tdir = klc_ticket_dir(ticket)
    steps = parse_impl_plan_steps(_read_plan(ticket))
    addresses = set(_by_id(steps, f"step-{step_num}").get("addresses") or [])
    out: list[dict] = []
    for kind in _FINDINGS_KINDS:
        for d in findings_store.read_dicts(tdir, kind=kind)[0]:
            ref = " ".join(str(d.get(k) or "") for k in ("ref", "ac")).strip()
            text = ref or f"{d.get('title') or ''} {d.get('body') or ''}"
            if (type(d.get("step")) is int and d["step"] == step_num) \
                    or _mentions(text, step_num, addresses):
                out.append(d)
    return out


def _finding_line(d: dict) -> str:
    return (f"- [{d.get('severity', '?')}] {d.get('rule_name', '?')} — "
            f"{d.get('title', '')} ({d.get('file', '?')}:{d.get('line', '?')})")


def _render(goals_acs: str, target: dict, dep_surfaces: list[dict], decisions: str, ticket: str, step: int,
            findings_lines: list[str] | None = None) -> str:
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
        findings_lines=findings_lines or [],
    )


def build_step_brief(ticket: str, step: int, *, findings: list[dict] | None = None) -> str:
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
    if goals_acs.startswith("_("):
        raise ValueError(f"spec.md for ticket {ticket!r} is missing or unparseable: {goals_acs}")
    # KLC-172: full Goals+ACs once (step 1, or a one-step plan); later steps
    # get a pointer: the spec is one `Read` away and the ACs were already
    # assessed at step 1, so repeating them in every brief is waste.
    if step != 1 and len(steps) > 1:
        goals_acs = (f"Goals and ACs: see .klc/tickets/{ticket}/spec.md "
                     f"(sent with step 1)")
    if findings is None:
        findings = step_findings(ticket, step)
    decisions = _decisions(plan_text)
    return _render(goals_acs, target, dep_surfaces, decisions, ticket, step,
                   [_finding_line(d) for d in findings])


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
