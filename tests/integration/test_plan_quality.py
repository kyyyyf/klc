"""KLC-051: plan_quality.unresolved_api_refs extractor and gate integration."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

# ---------------------------------------------------------------------------
# Step-1: unresolved_api_refs extractor
# ---------------------------------------------------------------------------

_PLAN_BAD_REF = """\
## step-1 — example
**Code sketch:**
```python
result = scan_sentinels.scan(ticket_dir)
```
"""

_PLAN_GOOD_REF = """\
## step-1 — example
**Code sketch:**
```python
result = scan_sentinels.scan_diff(ticket_dir)
```
"""

_PLAN_STDLIB_REF = """\
## step-1 — example
**Code sketch:**
```python
import os
os.path.join("a", "b")
re.compile(r"foo")
```
"""

_PLAN_SELF_INTRODUCED = """\
## step-1 — example
**Code sketch:**
```python
def my_helper(x):
    return x

result = my_helper(1)
```
"""


def test_unresolved_api_refs_flags_missing():
    from plan_quality import unresolved_api_refs
    refs = unresolved_api_refs(_PLAN_BAD_REF)
    assert any("scan_sentinels.scan" in r for r in refs), f"expected flag for scan_sentinels.scan, got {refs}"


def test_unresolved_api_refs_ignores_unknown_and_self():
    from plan_quality import unresolved_api_refs
    # Good ref (real attribute) should not be flagged
    assert unresolved_api_refs(_PLAN_GOOD_REF) == []
    # stdlib refs (os, re) not in core/skills — should be ignored
    assert unresolved_api_refs(_PLAN_STDLIB_REF) == []
    # self-introduced symbol should not be flagged
    assert unresolved_api_refs(_PLAN_SELF_INTRODUCED) == []


# ---------------------------------------------------------------------------
# Step-2: gate wiring (added below after step-2 implementation)
# ---------------------------------------------------------------------------

_VALID_S_SPEC = """\
---
ticket: {ticket}
kind: feature
track: S
risk_tags: []
---
## Goals
test
## Problem / Context
test
## Acceptance Criteria
- [ ] AC-1: something
## Non-goals
none
## Constraints
none
## Affected
- `some/module.py` [!ASSUMPTION if-false=scope-may-expand]
## Open questions
none
## Estimate
| complexity | 1 |
| uncertainty | 1 |
| risk | 0 |
| manual | 0 |
| total | 2 |
"""

_VALID_STEP = """\
## step-1 — do something
**Goal:** implement the feature
**RED:** not applicable — config-only change
**GREEN:** update the config file
**VERIFY:** `pytest tests/ -q`
**Expected:** 1 passed
**COMMIT:** `{ticket} step-1: do something`
**Affected:** some/module.py
**Interfaces:** none
**Depends-on:** none
**Code sketch:**
```python
pass
```
"""

_BAD_API_STEP = """\
## step-1 — do something
**Goal:** implement the feature
**RED:** not applicable — config-only change
**GREEN:** update the config file
**VERIFY:** `pytest tests/ -q`
**Expected:** 1 passed
**COMMIT:** `{ticket} step-1: do something`
**Affected:** some/module.py
**Interfaces:** none
**Depends-on:** none
**Code sketch:**
```python
result = scan_sentinels.scan(ticket_dir)
```
"""

_GOOD_API_STEP = """\
## step-1 — do something
**Goal:** implement the feature
**RED:** not applicable — config-only change
**GREEN:** update the config file
**VERIFY:** `pytest tests/ -q`
**Expected:** 1 passed
**COMMIT:** `{ticket} step-1: do something`
**Affected:** some/module.py
**Interfaces:** none
**Depends-on:** none
**Code sketch:**
```python
result = scan_sentinels.scan_diff(ticket_dir)
```
"""


def _make_ticket(tmp_path, ticket, spec_text, impl_plan_text):
    td = tmp_path / ".klc" / "tickets" / ticket
    td.mkdir(parents=True)
    (td / "spec.md").write_text(spec_text.format(ticket=ticket), encoding="utf-8")
    (td / "impl-plan.md").write_text(impl_plan_text.format(ticket=ticket), encoding="utf-8")
    (td / "test-plan.md").write_text(
        "# test plan\n## Acceptance coverage\n| AC | Test |\n|---|---|\n| AC-1 | test_foo |\n",
        encoding="utf-8",
    )
    (td / "options-lite.md").write_text(
        "# Options\n## Option A\nDo it this way.\n## Option B\nDo it another way.\nPicked: Option A\n",
        encoding="utf-8",
    )
    (td / "meta.json").write_text(json.dumps({
        "ticket": ticket, "phase": "discovery-lite:ack-needed",
        "track": "S", "kind": "feature",
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 0, "manual": 0, "total": 2},
        "affected_modules": ["some/module"],
        "risk_tags": [],
    }), encoding="utf-8")
    return td


def test_plan_quality_gate_blocks_bad_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from core.skills.phase_completion import can_complete_discovery_lite
    _make_ticket(tmp_path, "TST-001", _VALID_S_SPEC, _BAD_API_STEP)
    ok, msg = can_complete_discovery_lite("TST-001")
    assert not ok, "bad API ref should block ack"
    assert "scan_sentinels.scan" in msg


def test_plan_quality_gate_passes_good_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from core.skills.phase_completion import can_complete_discovery_lite
    _make_ticket(tmp_path, "TST-002", _VALID_S_SPEC, _GOOD_API_STEP)
    ok, _msg = can_complete_discovery_lite("TST-002")
    assert ok, f"good API ref should pass ack, got: {_msg}"


# ---------------------------------------------------------------------------
# Step-5: self-review runs the API check
# ---------------------------------------------------------------------------

def test_self_review_runs_api_check():
    """plan_quality.unresolved_api_refs is callable and surfaces a planted bad ref."""
    from plan_quality import unresolved_api_refs
    bad_plan = _PLAN_BAD_REF
    refs = unresolved_api_refs(bad_plan)
    assert refs, "self-review must surface the unresolved ref"
    assert all("unresolved API ref" in r for r in refs)
    # clean plan surfaces nothing
    assert unresolved_api_refs(_PLAN_GOOD_REF) == []
