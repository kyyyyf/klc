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
    before any `step_ledger` call that resolves `_paths.klc_ticket_dir`.
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
