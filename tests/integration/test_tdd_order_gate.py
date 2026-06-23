"""KLC-039 step-3: TDD ordering gate wired into build ack.

The build ack gate must surface a sanction for any behaviour step whose
git history shows an implementation commit before a failing-test commit.
Steps marked `RED: not applicable` must be exempt.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

from core.skills.phase_completion import can_complete_build  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers: synthetic git repo + ticket fixtures
# ---------------------------------------------------------------------------

def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, capture_output=True, text=True, cwd=str(cwd))
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "tdd@test.com"], repo)
    _run(["git", "config", "user.name", "TDD Test"], repo)
    return repo


def _commit(repo: Path, files: dict[str, str], subject: str) -> str:
    for relpath, content in files.items():
        p = repo / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _run(["git", "add", relpath], repo)
    _run(["git", "commit", "-m", subject], repo)
    return _run(["git", "rev-parse", "HEAD"], repo)


_EVIDENCE_BUILD_LOG = """\
---
ticket: {ticket}
kind: build-log
---

# Build log — {ticket}

## Step 1 — 2026-06-23
**Attempt**: write the feature
**Outcome**: green

## Evidence

```
$ python3 -m pytest tests/ -q
5 passed in 0.04s
```
"""

_BEHAVIOUR_IMPL_PLAN = """\
# Implementation plan — {ticket}

## step-1 — implement the feature

**Goal:** implement the feature
**RED:** `tests/test_x.py::test_feature` — failing today
**GREEN:** add feature in core/x.py
**VERIFY:** `python3 -m pytest tests/ -q`
**Expected:** 5 passed
**COMMIT:** `{ticket} step-1: implement the feature`
**Affected files:** `core/x.py`
**Interfaces:** none
**Depends on:** none
**Code sketch:**
```python
def feature():
    pass
```
"""

_NOT_APPLICABLE_IMPL_PLAN = """\
# Implementation plan — {ticket}

## step-1 — update prompt

- Goal: update the agent prompt
- RED: not applicable — prompt-only edit
- GREEN: edit core/agents/impl.md
- VERIFY: `grep -n Evidence core/agents/impl.md`
- Expected: line found
- COMMIT: `{ticket} step-1: update prompt`
- Affected files: `core/agents/impl.md`
- Interfaces: none
- Depends on: none
"""


def _make_build_ticket(
    tmp_path: Path,
    ticket: str,
    build_log: str,
    impl_plan: str,
) -> Path:
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket,
        "kind": "feature",
        "phase": "build:ack-needed",
        "track": "S",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"],
        "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "build-log.md").write_text(
        build_log.format(ticket=ticket), encoding="utf-8"
    )
    (ticket_dir / "impl-plan.md").write_text(
        impl_plan.format(ticket=ticket), encoding="utf-8"
    )
    return ticket_dir


# ---------------------------------------------------------------------------
# TDD01: misordered history (impl first) → blocked
# ---------------------------------------------------------------------------

def test_misordered_commits_block_build_ack(tmp_path, monkeypatch):
    """AC-3: impl commit before test commit → build ack blocked with TDD sanction."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    repo = _make_repo(tmp_path)
    # Impl commit first — violation
    _commit(repo, {"core/x.py": "# impl first"}, "KLC-TG01 step-1: impl")
    _commit(repo, {"tests/test_x.py": "# test after"}, "KLC-TG01 step-1: add test")
    _make_build_ticket(tmp_path, "KLC-TG01", _EVIDENCE_BUILD_LOG, _BEHAVIOUR_IMPL_PLAN)

    ok, msg = can_complete_build("KLC-TG01", repo=repo)
    assert not ok, "expected False: impl-first history must block build ack"
    assert "KLC-TG01 step-1" in msg, f"expected step reference in msg, got: {msg!r}"


# ---------------------------------------------------------------------------
# TDD02: correctly ordered history → passes
# ---------------------------------------------------------------------------

def test_ordered_commits_pass_build_ack(tmp_path, monkeypatch):
    """AC-3: test commit before impl commit → build ack passes TDD check."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    repo = _make_repo(tmp_path)
    # Test commit first — correct order
    _commit(repo, {"tests/test_x.py": "# failing test"}, "KLC-TG02 step-1: add test")
    _commit(repo, {"core/x.py": "# impl"}, "KLC-TG02 step-1: make it pass")
    _make_build_ticket(tmp_path, "KLC-TG02", _EVIDENCE_BUILD_LOG, _BEHAVIOUR_IMPL_PLAN)

    ok, msg = can_complete_build("KLC-TG02", repo=repo)
    assert ok, f"expected True for correctly ordered history, got: {msg!r}"


# ---------------------------------------------------------------------------
# TDD03: RED: not applicable step → exempt from TDD check
# ---------------------------------------------------------------------------

def test_not_applicable_step_exempt_from_tdd_check(tmp_path, monkeypatch):
    """AC-3: steps with RED: not applicable are not sanctioned for ordering."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    repo = _make_repo(tmp_path)
    # Only impl commit — would normally sanction, but RED: not applicable
    _commit(repo, {"core/agents/impl.md": "# updated prompt"}, "KLC-TG03 step-1: update prompt")
    _make_build_ticket(tmp_path, "KLC-TG03", _EVIDENCE_BUILD_LOG, _NOT_APPLICABLE_IMPL_PLAN)

    ok, msg = can_complete_build("KLC-TG03", repo=repo)
    assert ok, f"expected True: RED: not applicable step must be exempt, got: {msg!r}"
