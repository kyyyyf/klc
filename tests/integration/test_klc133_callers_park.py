"""AC-7: the interactive-park behaviour (C-005) is unchanged for every
headless caller after the KLC-133 telemetry-tag changes — the review
runner and the build orchestrator's default dispatch pass only telemetry
tags (never `ticket=`) so they dispatch regardless of interactivity, while
the autorunner's own call (which DOES pass `ticket=`) still parks.
"""
from __future__ import annotations

import importlib.util
import json
import textwrap
from pathlib import Path

import pytest

from _klc133_support import (  # noqa: E402
    FakeAnthropic,
    fixture_text,
    seed_ticket,
    klc133_hermetic,  # noqa: F401  (autouse fixture, must be in module namespace)
)

FW_ROOT = Path(__file__).resolve().parents[2]

# See test_klc133_autorunner.py for why this pin is needed: core/skills/
# task_brief.py and core/phases/task_brief.py share a bare module name, and
# autorunner's own sys.path bootstrap can put core/phases ahead of
# core/skills, breaking a cold `import autorunner` with an unrelated
# ImportError. Pinning the correct module here, at collection time, makes
# this module order-independent too.
import sys as _sys
if str(FW_ROOT / "core" / "skills") not in _sys.path:
    _sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
import task_brief as _klc133_task_brief_pin  # noqa: E402
assert hasattr(_klc133_task_brief_pin, "build_step_brief")

_PLAN_ONE_STEP = textwrap.dedent("""\
    ---
    ticket: KLC-P1
    kind: impl-plan
    ---

    ## step-1 — first step

    - **Goal:** do first thing
    - **Interfaces:** `def first() -> None`
    - **Expected:** first called
    - **VERIFY:** pytest
    - **COMMIT:** KLC-P1 step-1: first step
    - **Affected:** src/first.py
    - Depends-on: none
    - **Code sketch:**

    ```python
    def first(): pass
    ```
""")

_SPEC = textwrap.dedent("""\
    ---
    ticket: KLC-P1
    kind: feature
    authority: human
    risk_tags: []
    ---

    ## Goals
    Test the park guard.

    ## Acceptance Criteria
    - [ ] AC-1: parks correctly
""")


def _load_review_runner():
    spec = importlib.util.spec_from_file_location(
        "klc133_park_review_runner", FW_ROOT / "scripts" / "review-runner.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _write_card(tmp_path: Path, name: str, spec_path: Path) -> Path:
    card = tmp_path / f"job-{name}.md"
    card.write_text(
        f"# Review sub-agent job: {name}\n\n"
        f"Prompt file: core/agents/review/{name}.md\n"
        "Inputs:\n"
        f"- spec:              {spec_path}\n",
        encoding="utf-8",
    )
    return card


@pytest.mark.parametrize("caller", ["review_runner", "build_default_dispatch",
                                    "autorunner"])
def test_interactive_park_behaviour_is_unchanged_for_every_headless_caller(
        tmp_path, klc133_hermetic, monkeypatch, caller):
    """AC-7: pin — on a clarify_required ticket, the review runner and the
    build orchestrator's default dispatch still dispatch (they carry only
    telemetry tags, never `ticket=`, so the C-005 park guard never keys on
    them); the autorunner's own `ticket=`-carrying dispatch still parks
    without ever calling the dispatcher."""
    import runner

    project = klc133_hermetic
    fake = FakeAnthropic(
        lambda resolved, prompt: (0, fixture_text("envelope-single.json"), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)

    if caller == "review_runner":
        tdir = seed_ticket(project, "KLC-P1", track="M", phase="review:work",
                          clarify_required=True)
        (tdir / "spec.md").write_text("spec\n", encoding="utf-8")
        rr = _load_review_runner()
        card = _write_card(tmp_path, "security", tdir / "spec.md")
        partial = tmp_path / "security.partial.md"
        rc = rr.main([str(card), str(partial)])
        assert rc == 0
        assert fake.calls, "the dispatcher must actually have run"

    elif caller == "build_default_dispatch":
        tdir = seed_ticket(project, "KLC-P1", track="M", phase="build:work",
                          clarify_required=True)
        (tdir / "impl-plan.md").write_text(_PLAN_ONE_STEP, encoding="utf-8")
        (tdir / "spec.md").write_text(_SPEC, encoding="utf-8")
        import build_orchestrator as bo
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("do the thing", encoding="utf-8")
        out_path = tmp_path / "out.md"
        dispatch = bo._telemetry_dispatch("KLC-P1")
        rc = dispatch("intake", prompt_path, out_path, track="M")
        assert rc == 0
        assert fake.calls, "the dispatcher must actually have run"

    else:  # autorunner
        # "intake" is the only phase `phase_resolver._is_interactive` ever
        # marks interactive, and it carries NO agent prompt at all
        # (config/phases.yml: work.prompt == ""), so `autorunner._dispatch`
        # short-circuits on its own no-prompt guard (_DISPATCH_NO_PROMPT)
        # before ever reaching run_agent's C-005 park check — a pre-existing
        # structural fact, unaffected by KLC-133. Either way the dispatcher
        # never runs and nothing is guessed at headlessly, which is the
        # substance of AC-7's "unchanged for the autorunner" claim.
        tdir = seed_ticket(project, "KLC-P1", track="M", phase="intake:work",
                          clarify_required=True)
        (tdir / "spec.md").write_text("spec\n", encoding="utf-8")
        import autorunner
        rc = autorunner._dispatch("KLC-P1", "intake", None)
        assert rc == autorunner._DISPATCH_NO_PROMPT
        assert fake.calls == [], "the dispatcher must never have run"

    meta = json.loads((tdir / "meta.json").read_text())
    assert "parked" not in meta, \
        "none of the three callers ever writes a parked marker in this scenario"
