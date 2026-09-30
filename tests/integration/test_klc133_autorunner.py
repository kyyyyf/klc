"""AC-7: the autorunner's dispatch of a non-build phase keeps recording the
run through `run_agent` as today, now with the KLC-133 fields, while the
card's estimated attempt from `render_card` stays a SEPARATE attempt.
"""
from __future__ import annotations

import json

import pytest

from _klc133_support import (  # noqa: E402
    FakeAnthropic,
    all_attempts,
    fixture_text,
    seed_ticket,
    klc133_hermetic,  # noqa: F401  (autouse fixture, must be in module namespace)
)

# `core/skills/task_brief.py` (build_step_brief, imported by build_orchestrator)
# and `core/phases/task_brief.py` (the `klc task-brief` CLI, unrelated) share a
# bare module name. `autorunner`'s own sys.path bootstrap can put `core/phases`
# ahead of `core/skills`, so an `import autorunner` done cold (this module run
# on its own, before anything else has imported the right one) resolves
# `task_brief` to the WRONG file and crashes with an unrelated ImportError.
# Pinning the correct module into `sys.modules` here, at collection time,
# before `autorunner` (transitively, `build_orchestrator`) ever imports it,
# makes this module order-independent regardless of what else is collected
# alongside it — a pre-existing landmine, not a KLC-133 regression.
import task_brief as _klc133_task_brief_pin  # noqa: E402
assert hasattr(_klc133_task_brief_pin, "build_step_brief"), (
    "core/skills/task_brief.py must be the module that loads under the bare "
    "name 'task_brief', not core/phases/task_brief.py")


def _seed_review_ticket(project, ticket):
    """An S-track ticket at review:work, good enough for
    `phase_resolver`/`artefacts.render_card` to render a real review card
    (mirrors test_autorunner.py's ticket shape)."""
    tdir = seed_ticket(project, ticket, track="S", phase="review:work")
    spec = (
        f"---\nticket: {ticket}\nkind: feature\nauthority: agent\nrisk_tags: []\n---\n"
        "## Goals\nDo thing.\n## Acceptance Criteria\n- [ ] AC-1: does thing.\n"
        "## Affected\nm: core/x.py, src=core/x.py:1\n"
        "## Estimate\ncomplexity: 1\nuncertainty: 1\nrisk: 1\nmanual: 0\ntotal: 3\n"
    )
    (tdir / "spec.md").write_text(spec, encoding="utf-8")
    idx = project / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "modules.json").write_text(
        json.dumps({"modules": [{"name": "m", "src": ["core/x.py"], "tests": [],
                                 "phase": "stable"}]}),
        encoding="utf-8")
    return tdir


def test_one_estimated_card_attempt_and_one_provider_run_attempt_for_the_same_phase(
        klc133_hermetic, monkeypatch):
    """AC-7: a real autorunner._dispatch of review:work finds one estimated
    card attempt from render_card and one provider attempt (carrying
    cost_usd) for the same phase — two distinct attempts, not one."""
    import runner
    import autorunner

    project = klc133_hermetic
    _seed_review_ticket(project, "KLC-A7")
    fake = FakeAnthropic(
        lambda resolved, prompt: (0, fixture_text("envelope-single.json"), ""))
    monkeypatch.setitem(runner._DISPATCH, "anthropic", fake)

    rc = autorunner._dispatch("KLC-A7", "review", None)
    assert rc == 0

    attempts = all_attempts("KLC-A7", "review")
    assert len(attempts) == 2
    by_source = {a["source"]: a for a in attempts}
    assert "estimated" in by_source and "provider" in by_source
    assert "card_bytes" in by_source["estimated"]
    assert by_source["provider"]["cost_usd"] == pytest.approx(0.0088403)
