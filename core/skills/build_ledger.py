"""build_ledger.py — durable build progress ledger for the step orchestrator.

Public API:
    Ledger.from_plan(ticket) -> Ledger
        Derive step list from impl-plan.md, preserving any recorded green
        outcomes by step id (handles a plan edited after partial build).

    Ledger.load(ticket) -> Ledger | None
        Load from build/progress.md; returns None when the file is absent.
        Raises ValueError on malformed frontmatter.

    ledger.save()
        Write build/progress.md — YAML frontmatter (source of truth) +
        regenerated markdown table.

    ledger.first_pending() -> int | None
        Return the 1-based step number of the first non-green step, or None
        when all steps are green.

    ledger.mark(step_id, state, *, model=None, reason=None)
        Update a step's state in-memory (call save() to persist).
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_SKILLS = Path(__file__).resolve().parent
_PROJECT_ROOT_DIR = _SKILLS.parent.parent
for _p in (str(_PROJECT_ROOT_DIR), str(_SKILLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from impl_plan_check import parse_impl_plan_steps  # noqa: E402
from _paths import klc_ticket_dir  # noqa: E402

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_STEP_NUM_RE = re.compile(r"step-(\d+)")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_plan(ticket: str) -> str:
    plan = klc_ticket_dir(ticket) / "impl-plan.md"
    if not plan.exists():
        raise ValueError(f"impl-plan.md not found for ticket {ticket!r}")
    return plan.read_text(encoding="utf-8")


def _progress_path(ticket: str) -> Path:
    return klc_ticket_dir(ticket) / "build" / "progress.md"


def _parse_simple_yaml(text: str) -> dict:
    """Parse a minimal YAML subset: top-level key:value and list items."""
    result: dict = {}
    current_key: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith("  - "):
            val = line[4:].strip()
            if current_key and isinstance(result.get(current_key), list):
                result[current_key].append(val)
        elif ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if v == "":
                result[k] = []
                current_key = k
            elif v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                result[k] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
                current_key = k
            else:
                result[k] = v.strip("'\"")
                current_key = k
    return result


def _parse_step_blocks(frontmatter: str) -> list[dict]:
    """Parse the 'steps:' block from YAML frontmatter into a list of dicts.

    Handles block-style list entries:
        steps:
          - id: step-1
            state: green
            model: claude-sonnet-4-6
    """
    lines = frontmatter.splitlines()
    in_steps = False
    current: dict | None = None
    blocks: list[dict] = []
    for line in lines:
        stripped = line.rstrip()
        if stripped == "steps:":
            in_steps = True
            continue
        if not in_steps:
            continue
        # New list item
        if re.match(r"^\s{0,2}-\s+", stripped):
            if current is not None:
                blocks.append(current)
            current = {}
            # Key-value on same line as dash: "  - id: step-1"
            kv = re.sub(r"^\s*-\s+", "", stripped)
            if ":" in kv:
                k, _, v = kv.partition(":")
                current[k.strip()] = v.strip()
        elif re.match(r"^\s{4}", stripped) and current is not None:
            # Continuation key-value under current item
            if ":" in stripped:
                k, _, v = stripped.strip().partition(":")
                current[k.strip()] = v.strip()
        else:
            # Dedented or empty — end of steps block
            if stripped and not stripped.startswith(" "):
                in_steps = False
    if current is not None:
        blocks.append(current)
    return blocks


def _step_num(step_id: str) -> int:
    m = _STEP_NUM_RE.search(step_id)
    return int(m.group(1)) if m else 0


@dataclass
class Step:
    id: str
    state: str = "pending"
    model: Optional[str] = None
    reason: Optional[str] = None
    ts: Optional[str] = None


@dataclass
class Ledger:
    ticket: str
    steps: list[Step] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_plan(cls, ticket: str) -> "Ledger":
        """Derive step list from impl-plan.md, preserving recorded green outcomes."""
        plan_text = _read_plan(ticket)
        parsed = parse_impl_plan_steps(plan_text)
        ids = [s["id"] for s in parsed]

        # Preserve green outcomes from existing ledger (if any)
        existing = cls.load(ticket)
        green: dict[str, Step] = {}
        if existing:
            green = {s.id: s for s in existing.steps if s.state == "green"}

        steps = []
        for sid in ids:
            if sid in green:
                steps.append(green[sid])
            else:
                steps.append(Step(id=sid))
        return cls(ticket=ticket, steps=steps)

    @classmethod
    def load(cls, ticket: str) -> Optional["Ledger"]:
        """Load from progress.md; None if absent, ValueError if malformed."""
        path = _progress_path(ticket)
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            raise ValueError(f"progress.md for {ticket!r} has no valid YAML frontmatter")
        try:
            step_blocks = _parse_step_blocks(m.group(1))
        except Exception as exc:
            raise ValueError(f"progress.md frontmatter parse error: {exc}") from exc

        steps = []
        for block in step_blocks:
            sid = block.get("id", "")
            state = block.get("state", "pending")
            # Crash recovery: treat running as pending
            if state == "running":
                state = "pending"
            steps.append(Step(
                id=sid,
                state=state,
                model=block.get("model") or None,
                reason=block.get("reason") or None,
                ts=block.get("ts") or None,
            ))

        return cls(ticket=ticket, steps=steps)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def mark(self, step_id: str, state: str, *, model: str | None = None, reason: str | None = None) -> None:
        for s in self.steps:
            if s.id == step_id:
                s.state = state
                if model is not None:
                    s.model = model
                if reason is not None:
                    s.reason = reason
                s.ts = _now()
                return
        raise ValueError(f"step {step_id!r} not found in ledger")

    def first_pending(self) -> int | None:
        for s in self.steps:
            if s.state != "green":
                n = _step_num(s.id)
                return n if n > 0 else None
        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        path = _progress_path(self.ticket)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render(), encoding="utf-8")

    def _render(self) -> str:
        lines = ["---", f"ticket: {self.ticket}", "steps:"]
        for s in self.steps:
            lines.append(f"  - id: {s.id}")
            lines.append(f"    state: {s.state}")
            if s.model:
                lines.append(f"    model: {s.model}")
            if s.ts:
                lines.append(f"    ts: {s.ts}")
            if s.reason:
                lines.append(f"    reason: {s.reason}")
        lines.append("---")
        lines.append(f"# Build progress — {self.ticket}")
        lines.append("| step | state | model | ts |")
        lines.append("|------|-------|-------|----|")
        for s in self.steps:
            model = s.model or ""
            ts = s.ts or ""
            lines.append(f"| {s.id} | {s.state} | {model} | {ts} |")
        return "\n".join(lines) + "\n"
