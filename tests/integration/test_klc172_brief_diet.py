"""KLC-172 step-3: the step brief carries only its own context."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

_KEY = "KLC-T8"


def _step(n, addresses):
    return textwrap.dedent(f"""\
        ## step-{n} — step {n}

        - **Goal:** do thing {n}
        - **Interfaces:** `def f{n}() -> None`
        - **Expected:** f{n} called
        - **VERIFY:** pytest
        - **COMMIT:** KLC-T8 step-{n}: thing {n}
        - **Affected:** src/f{n}.py
        - **Addresses:** {addresses}
        - Depends-on: none

        """)


_HEAD = "---\nticket: KLC-T8\nkind: impl-plan\n---\n\n"
_SPEC = textwrap.dedent("""\
    ---
    ticket: KLC-T8
    kind: feature
    authority: human
    risk_tags: []
    ---

    ## Goals
    Diet the brief.

    ## Acceptance Criteria
    - [ ] AC-1: first criterion
    - [ ] AC-2: second criterion
    - [ ] AC-3: third criterion
""")
_AC_BLOCK = "- [ ] AC-1: first criterion"


def _seed(tmp_path, monkeypatch, n_steps=3):
    tdir = tmp_path / ".klc" / "tickets" / _KEY
    tdir.mkdir(parents=True)
    plan = _HEAD + "".join(_step(i, f"AC-{i}") for i in range(1, n_steps + 1))
    (tdir / "impl-plan.md").write_text(plan)
    (tdir / "spec.md").write_text(_SPEC)
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    return tdir


def _f(title, ref="", sev="MEDIUM", body="b"):
    """The REAL stored shape (impl-plan-review-findings.json): `ref` is free
    text, `ac` is "" and there is never a `step` key."""
    return {"rule_name": "rule-x", "severity": sev, "file": "a.py", "line": 3,
            "title": title, "body": body, "fix": "f", "ref": ref, "ac": ""}


def test_step1_full_acs_later_steps_pointer(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    import task_brief
    b1 = task_brief.build_step_brief(_KEY, 1)
    assert "## Acceptance Criteria" in b1
    assert _AC_BLOCK in b1
    pointer = f"Goals and ACs: see .klc/tickets/{_KEY}/spec.md (sent with step 1)"
    for n in (2, 3):
        b = task_brief.build_step_brief(_KEY, n)
        assert pointer in b
        assert "AC-1: first criterion" not in b
        assert "## Acceptance Criteria" not in b


def test_one_step_plan_still_sends_full_block(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, n_steps=1)
    import task_brief
    b = task_brief.build_step_brief(_KEY, 1)
    assert _AC_BLOCK in b


def test_brief_lists_step_relevant_findings(tmp_path, monkeypatch):
    tdir = _seed(tmp_path, monkeypatch)
    (tdir / "spec-review-findings.json").write_text(json.dumps([
        _f("by-step-ref", ref="step-2 GREEN"),
        _f("other-step", ref="step-3"),
        _f("step-twenty", ref="step-20"),
        _f("by-title-step", ref="", body="see step-2, item"),
    ]))
    (tdir / "test-plan-review-findings.json").write_text(json.dumps(
        {"findings": [_f("by-ac-two", ref="AC-2", sev="HIGH"),
                      _f("by-ac-list", ref="AC-1, AC-2 / D-001"),
                      _f("by-ac-three", ref="AC-3"),
                      _f("ac-twelve", ref="AC-12"),
                      dict(_f("explicit-step", ref=""), step=2)]}))
    (tdir / "impl-plan-review-findings.json").write_text("{not json")
    import task_brief
    b = task_brief.build_step_brief(_KEY, 2)
    assert "## Review findings for this step" in b
    for want in ("by-step-ref", "by-title-step", "by-ac-list", "explicit-step"):
        assert want in b, want
    assert "[HIGH] rule-x — by-ac-two (a.py:3)" in b
    for nope in ("other-step", "step-twenty", "by-ac-three", "ac-twelve"):
        assert nope not in b, nope


def test_ac_twelve_does_not_match_ac_one(tmp_path, monkeypatch):
    tdir = _seed(tmp_path, monkeypatch)
    (tdir / "spec-review-findings.json").write_text(json.dumps(
        [_f("only-twelve", ref="AC-12"), _f("really-one", ref="AC-1")]))
    import task_brief
    got = [d["title"] for d in task_brief.step_findings(_KEY, 1)]
    assert got == ["really-one"]


def test_findings_section_none_when_missing_or_malformed(tmp_path, monkeypatch):
    tdir = _seed(tmp_path, monkeypatch)
    (tdir / "spec-review-findings.json").write_text("garbage")
    import task_brief
    b = task_brief.build_step_brief(_KEY, 2)
    sec = b.split("## Review findings for this step", 1)[1]
    assert "(none)" in sec


def test_impl_prompt_reads_last_log_entry_only():
    agent = (_FW_ROOT / "core" / "agents" / "impl.md").read_text(encoding="utf-8")
    assert "Read it first on every invocation" not in agent
    assert "Progress log" not in agent  # KLC-174: build-log.md is optional free notes
    inc = (_FW_ROOT / "core" / "agents" / "_includes" / "review-findings-assessment.md"
           ).read_text(encoding="utf-8")
    assert "listed in the brief" in inc
    assert "At the START of build" not in inc
    assert "HIGH" in inc  # stop-and-ask rule kept

    # klc-plugin/agents/impl.md byte-equality is enforced by tests/test_plugin_agents_in_sync.py
    deployed = (_FW_ROOT / "klc-plugin" / "agents" / "impl.md").read_text(encoding="utf-8")
    assert "Read it first on every invocation" not in deployed
    assert "listed in the brief" in deployed
