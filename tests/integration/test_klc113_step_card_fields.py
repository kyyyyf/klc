#!/usr/bin/env python3
"""tests/integration/test_klc113_step_card_fields.py — KLC-113 step-6.

AC-12: `klc step` on a fixture plan written in the `- Affected:` / `- RED:` /
`- VERIFY:` / `- COMMIT:` syntax renders all four fields into the card,
matching the plan's literal values (KLC-102's card renders both lists empty
today). A second fixture mixes that dash syntax with the real historical
`**Affected files**:`/`**Expected tests**:` inline-value spelling (27
archived tickets use it — see `.klc/tickets/KLC-001/impl-plan.md`) to prove
one parser, not two forks, handles both.

AC-13: `core/templates/impl-step.md.j2` never emits the dangling
`# see test-framework.json` fallback and its sections are named for the
plan's own vocabulary.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

FW_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(FW_ROOT / "core" / "shared"))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import artefacts  # noqa: E402 — core.shared.paths resolves PROJECT_ROOT
# lazily per call, not at import time (verified), so this import needs no
# PROJECT_ROOT default ahead of it


@pytest.fixture(autouse=True, scope="module")
def _default_project_root_for_module():
    """KLC-136 step-8: a module-scoped, properly-undone replacement for a
    bare `os.environ.setdefault("PROJECT_ROOT", ...)`, which leaked into
    every later test for the rest of the pytest process (see
    test_jira_core.py's fixture of the same name for the full story)."""
    mp = pytest.MonkeyPatch()
    if "PROJECT_ROOT" not in os.environ:
        mp.setenv("PROJECT_ROOT", str(tempfile.mkdtemp(prefix="klc-t113-test-")))
    yield
    mp.undo()


_DASH_PLAN = """\
## step-1 — new step

- Goal: build the new thing
- RED: tests/test_new.py::test_thing
- Affected: `src/new.py`, `tests/test_new.py`
- VERIFY: pytest tests/test_new.py -q
- COMMIT: KLC-DASH step-1: build the new thing
"""

_MIXED_PLAN = """\
## step-1 — legacy step

- **Goal**: old-style step
- **Affected files**: `src/old.py`
- **Expected tests**: `tests/test_old.py`
- **VERIFY**: pytest tests/test_old.py -q
- **COMMIT**: KLC-MIXED step-1: old-style step

## step-2 — new step

- Goal: new-style step
- RED: tests/test_new.py::test_thing
- Affected: `src/new.py`
- VERIFY: pytest tests/test_new.py -q
- COMMIT: KLC-MIXED step-2: new-style step
"""


def _make_ticket_env(scratch: Path, ticket: str, plan_text: str) -> dict:
    tdir = scratch / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "spec.md").write_text(
        f"---\nticket: {ticket}\nkind: tech\nauthority: agent\n---\n"
        "## Goals\nFake.\n## Acceptance Criteria\n- [ ] AC-1\n"
        "## Estimate\ntotal: 1\n",
        encoding="utf-8",
    )
    (tdir / "impl-plan.md").write_text(plan_text, encoding="utf-8")
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": "build:work", "phase_history": [],
        "track": "S", "estimate": None, "layer": "code",
        "affected_modules": [], "created": "2026-06-04T00:00:00Z",
        "owner": "test", "jira_url": None, "links": [],
        "rework_count": {}, "metrics": {},
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(scratch)
    env.pop("KLC_CARD_INLINE", None)
    return env, meta


def test_step_card_renders_dash_syntax_fields() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        env, meta = _make_ticket_env(scratch, "T-DASH-001", _DASH_PLAN)
        with patch.dict(os.environ, env, clear=True):
            card = artefacts.write_step_card("T-DASH-001", 1, meta)
        content = card.read_text(encoding="utf-8")

    assert "src/new.py" in content
    assert "tests/test_new.py" in content
    assert "tests/test_new.py::test_thing" in content  # RED
    assert "pytest tests/test_new.py -q" in content     # VERIFY
    assert "KLC-DASH step-1: build the new thing" in content  # COMMIT


def test_step_card_renders_both_legacy_and_dash_syntax_in_one_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        env, meta = _make_ticket_env(scratch, "T-MIXED-001", _MIXED_PLAN)
        with patch.dict(os.environ, env, clear=True):
            card1 = artefacts.write_step_card("T-MIXED-001", 1, meta)
            card2 = artefacts.write_step_card("T-MIXED-001", 2, meta)
        content1 = card1.read_text(encoding="utf-8")
        content2 = card2.read_text(encoding="utf-8")

    # step-1 (legacy inline-value spelling, matching real archived tickets
    # like KLC-001) is parsed by the SAME extractor — not a second fork.
    assert "src/old.py" in content1
    assert "tests/test_old.py" in content1
    assert "KLC-MIXED step-1: old-style step" in content1

    # step-2 (dash syntax) renders independently and correctly in the same plan.
    assert "src/new.py" in content2
    assert "KLC-MIXED step-2: new-style step" in content2


def test_step_card_template_no_test_framework_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        env, meta = _make_ticket_env(scratch, "T-NOTF-001", _DASH_PLAN)
        with patch.dict(os.environ, env, clear=True):
            card = artefacts.write_step_card("T-NOTF-001", 1, meta)
        content = card.read_text(encoding="utf-8")

    assert "# see test-framework.json" not in content
    assert "run the failing test added by the test agent" not in content
