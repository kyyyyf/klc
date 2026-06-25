"""plan_quality.py — API-existence gate for impl-plan code sketches.

Extracts ``module.attr(`` references from fenced code blocks in an impl-plan
and flags any where ``module`` is a real core/skills module but ``attr`` is
not defined there. Ignores stdlib/third-party/pseudocode prefixes and symbols
introduced by the plan's own sketches.

Public API:
    unresolved_api_refs(impl_plan_text: str) -> list[str]
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent


def _known_modules() -> set[str]:
    return {p.stem for p in _SKILLS.glob("*.py") if p.stem != "__init__"}


def _defined(module: str) -> set[str]:
    src = _SKILLS / f"{module}.py"
    try:
        tree = ast.parse(src.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return names


def unresolved_api_refs(impl_plan_text: str) -> list[str]:
    """Return sorted list of unresolved API ref messages for the given impl-plan text.

    Each message has the form:
        "unresolved API ref: <module>.<attr> (not defined in core/skills/<module>.py)"
    """
    known = _known_modules()

    # Extract only code inside fenced blocks (``` ... ```)
    fenced_blocks = re.findall(r"```[^\n]*\n([\s\S]*?)```", impl_plan_text)
    fenced = "\n".join(fenced_blocks)

    # Module-level names introduced by the plan's own sketches (def/class at any indent).
    # These exempt calls where the MODULE PREFIX itself was locally defined — e.g. an
    # inline helper class. They do NOT exempt attr names, because a plan-local `def scan`
    # cannot be an attribute of a real core/skills module like scan_sentinels.
    introduced = set(re.findall(r"(?m)^\s*(?:def|class)\s+(\w+)", fenced))

    out: set[str] = set()
    for mod, attr in re.findall(r"(?<![\w.])(\w+)\.(\w+)\s*\(", fenced):
        if mod not in known:
            continue
        if mod in introduced:
            continue
        if attr not in _defined(mod):
            out.add(
                f"unresolved API ref: {mod}.{attr}"
                f" (not defined in core/skills/{mod}.py)"
            )
    return sorted(out)
