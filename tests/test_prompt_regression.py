from tests.prompt_harness import impl_plan_violations, has_min_approaches
from pathlib import Path
import pytest
import tests.prompt_harness as H

GOOD = (
    "## step-1 — x\n"
    "**Goal:** do the thing\n"
    "**VERIFY:** `pytest tests/ -q`\n"
    "**COMMIT:** `KLC-029 step-1: do the thing`\n"
    "**Affected:** tests/prompt_harness.py\n"
)
BAD = "## step-1 — x\n**Goal:** TODO\n"


def test_impl_plan_violations_flags_placeholders():
    assert impl_plan_violations(GOOD) == []
    assert impl_plan_violations(BAD)        # non-empty


def test_has_min_approaches_counts():
    assert has_min_approaches("- Option A: x\n- Option B: y", 2)
    assert not has_min_approaches("- Option A: x", 2)


def test_violations_missing_required_field():
    text = (
        "## step-1 — x\n"
        "**Goal:** do the thing\n"
        "**VERIFY:** `pytest`\n"
        # missing COMMIT and Affected
    )
    violations = impl_plan_violations(text)
    assert any("COMMIT" in v for v in violations)


def test_violations_placeholder_tbd():
    text = (
        "## step-1 — x\n"
        "**Goal:** TBD\n"
        "**VERIFY:** `pytest`\n"
        "**COMMIT:** `done`\n"
        "**Affected:** file.py\n"
    )
    violations = impl_plan_violations(text)
    assert violations


def test_violations_no_steps():
    text = "# just prose, no step headings\nsome text"
    violations = impl_plan_violations(text)
    assert any("no steps" in v for v in violations)


def test_has_min_approaches_not_prose():
    # Normal prose shouldn't be counted as approaches
    assert not has_min_approaches("We will implement this using clangd.", 2)


def test_judge_skips_without_key(monkeypatch):
    monkeypatch.delenv(H._judge_api_key_env(), raising=False)
    assert H.judge_available() is False


def test_judge_raises_without_key(monkeypatch):
    monkeypatch.delenv(H._judge_api_key_env(), raising=False)
    with pytest.raises(RuntimeError, match="Judge API key not set"):
        H.judge("output", "rubric")


def test_judge_returns_structured(monkeypatch):
    def _fake_run(**kw):
        Path(kw["out_path"]).write_text("PASS: ok")
        return 0
    monkeypatch.setattr(H, "run_agent", _fake_run, raising=False)
    monkeypatch.setattr(H, "judge_available", lambda: True)
    r = H.judge("out", "rubric")
    assert r["pass"] is True and isinstance(r["reason"], str)


@pytest.mark.xfail(
    reason="Socratic directives land in Phase 1 (KLC-1.1); sentinel flips to pass then.",
    strict=True,
)
def test_discovery_lite_lacks_socratic_sentinel():
    from tests.prompt_harness import _FW_ROOT
    txt = (_FW_ROOT / "core/agents/discovery-lite.md").read_text(encoding="utf-8")
    low = txt.lower()
    assert "one question at a time" in low
    assert ("2-3 approaches" in low) or ("2–3 approaches" in low)
