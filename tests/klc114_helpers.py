"""klc114_helpers.py — shared fixtures for KLC-114 step-ledger tests.

Two things nearly every KLC-114 test needs: a throwaway PROJECT_ROOT ticket
(impl-plan.md / meta.json / build-log.md written under
tmp_path/.klc/tickets/<KEY>, mirroring KLC-115's `_make_ticket`) and a
fabricated git repository whose commit subjects carry the `KLC-NNN step-N`
key `tdd_order.step_commits` selects on (promoted from KLC-039's
`test_tdd_order.py::_make_repo`/`_commit`, so this ticket's ~9 tests share
one implementation instead of re-inventing it per file).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def step_plan(step_id: str, *, goal: str = "do the thing",
             verify: str = "`sh -c \"echo 2 passed\"`",
             expected: str = "`2 passed`",
             affected: str = "`core/skills/x.py`",
             addresses: str = "") -> str:
    """One '## step-N — title' block carrying every required field
    (`impl_plan_check.REQUIRED_STEP_FIELDS`) plus a non-empty code sketch."""
    addr = f"- Addresses: {addresses}\n" if addresses else ""
    return (
        f"## {step_id} — a step\n\n"
        f"- Goal: {goal}\n"
        f"- RED: `tests/test_x.py::test_thing`\n"
        f"- GREEN: implement it\n"
        f"- VERIFY: {verify}\n"
        f"- COMMIT: `KLC-XXX {step_id}: do the thing`\n"
        f"- Affected: {affected}\n"
        f"- Interfaces: none\n"
        f"- Expected: {expected}\n"
        f"{addr}"
        f"- Depends on: none\n\n"
        f"```python\n# sketch\npass\n```\n\n"
    )


def make_ticket(tmp_path: Path, ticket: str, track: str, plan_text: str,
               *, build_log: str = "", meta_extra: dict | None = None) -> Path:
    """Write a throwaway ticket under tmp_path/.klc/tickets/<ticket>.

    The caller must `monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))`
    before any `step_state` call that resolves `_paths.klc_ticket_dir`.
    """
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:ack-needed",
        "track": track,
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    meta.update(meta_extra or {})
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "impl-plan.md").write_text(plan_text, encoding="utf-8")
    if build_log:
        (ticket_dir / "build-log.md").write_text(build_log, encoding="utf-8")
    return ticket_dir


def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, capture_output=True, text=True, cwd=str(cwd))
    return result.stdout.strip()


def make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """A fresh, isolated git repo (promoted from KLC-039's `_make_repo`)."""
    repo = tmp_path / name
    repo.mkdir(exist_ok=True)
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@test.com"], repo)
    _run(["git", "config", "user.name", "Test User"], repo)
    return repo


def commit(repo: Path, files: dict[str, str], subject: str) -> str:
    """Write *files*, stage, commit; return the SHA (KLC-039's `_commit`)."""
    for relpath, content in files.items():
        p = repo / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _run(["git", "add", relpath], repo)
    _run(["git", "commit", "-m", subject], repo)
    return _run(["git", "rev-parse", "HEAD"], repo)


def seed_steps(ticket_dir: Path, repo: Path | None = None, *, exit_code: int = 0,
               skip: tuple[int, ...] = ()) -> None:
    """KLC-174: write build/steps.json with a valid recorded verify for every
    impl-plan step (command == the plan VERIFY, `ran_at` a minute ahead so it is
    never earlier than a green commit). The ack READS this file, so ack-driven
    fixtures seed it instead of building an Evidence section. Pass *repo* (after the
    step commits exist): the verify is then tied to its HEAD and a clean tree, as
    `step_state.record_verify` does (KLC-174 review F-003)."""
    import sys
    from datetime import datetime, timedelta, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core" / "skills"))
    import impl_plan_check
    import step_state

    text = (ticket_dir / "impl-plan.md").read_text(encoding="utf-8")
    ran = (datetime.now(timezone.utc) + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    head = _run(["git", "rev-parse", "HEAD"], repo) if repo else None
    steps = {}
    for s in impl_plan_check.parse_impl_plan_steps(text):
        n = int(s["id"].split("-")[1])
        if n in skip:
            continue
        steps[str(n)] = {"step": n, "verify": {
            "command": step_state._plan_command(s), "exit_code": exit_code,
            "summary_line": "ok", "ran_at": ran, "runner": "agent",
            "head": head or None, "dirty": False}}
    (ticket_dir / "build").mkdir(exist_ok=True)
    (ticket_dir / "build" / "steps.json").write_text(json.dumps({"steps": steps}), encoding="utf-8")


class FakeStepState:
    """KLC-174: a stateful stand-in for `step_state.derive` / `record_verify`, for
    suites that exercise the orchestrator's DISPATCH LOOP with fake dispatches that
    never commit. `record_verify` marks a step green unless it is in *fail*."""

    def __init__(self, steps, green=(), fail=()):
        self.steps = list(steps)
        self.green = set(green)
        self.fail = set(fail)
        self.recorded: list[int] = []
        self.reviews: list[tuple[int, str]] = []

    def derive(self, ticket, repo=None):
        return [{"step": n, "state": "green" if n in self.green else "pending",
                 "reason": "" if n in self.green else "no recorded verify",
                 "verify": None, "green_commit": None, "red_commit": None,
                 "addresses": []} for n in self.steps]

    def record_verify(self, ticket, step, *, runner="agent", repo=None):
        self.recorded.append(step)
        if step not in self.fail:
            self.green.add(step)
        return {"command": "x", "exit_code": 1 if step in self.fail else 0,
                "summary_line": "", "ran_at": "", "runner": runner}

    def mark_review(self, ticket, step, state, *, round=1, repo=None):
        self.reviews.append((step, state))
        return {"state": state, "round": round}


def pin_step_state(monkeypatch, steps, *, green=(), fail=()) -> FakeStepState:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core" / "skills"))
    import step_state
    fake = FakeStepState(steps, green=green, fail=fail)
    monkeypatch.setattr(step_state, "derive", fake.derive)
    monkeypatch.setattr(step_state, "record_verify", fake.record_verify)
    monkeypatch.setattr(step_state, "mark_review", fake.mark_review)
    return fake
