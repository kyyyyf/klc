"""KLC-043: per-step reviewer tests — coverage decision, routing, hook, lint, render."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_PLAN = textwrap.dedent("""\
    ---
    ticket: KLC-T3
    kind: impl-plan
    ---

    ## step-1 — first step

    - **Goal:** do first thing
    - **Interfaces:** `def first() -> None`
    - **Expected:** first called
    - **VERIFY:** pytest
    - **COMMIT:** KLC-T3 step-1: first step
    - **Affected:** src/first.py
    - Depends-on: none
    - **Code sketch:**

    ```python
    def first(): pass
    ```

    ## step-2 — second step

    - **Goal:** do second thing
    - **Interfaces:** `def second() -> None`
    - **Expected:** second called
    - **VERIFY:** pytest
    - **COMMIT:** KLC-T3 step-2: second step
    - **Affected:** src/second.py
    - Depends-on: step-1
    - **Code sketch:**

    ```python
    def second(): pass
    ```
""")

_SPEC = textwrap.dedent("""\
    ---
    ticket: KLC-T3
    kind: feature
    authority: human
    risk_tags: []
    ---

    ## Goals
    Test the per-step reviewer.

    ## Acceptance Criteria
    - [ ] AC-1: coverage decision
""")

_META_M = {"ticket": "KLC-T3", "track": "M", "kind": "feature",
           "phase": "build:work", "risk_tags": []}
_META_L = {"ticket": "KLC-T3", "track": "L", "kind": "feature",
           "phase": "build:work", "risk_tags": []}
_META_S_RISKY = {"ticket": "KLC-T3", "track": "S", "kind": "feature",
                 "phase": "build:work", "risk_tags": ["data-loss"]}
_META_S_CLEAN = {"ticket": "KLC-T3", "track": "S", "kind": "feature",
                 "phase": "build:work", "risk_tags": []}
_META_XS = {"ticket": "KLC-T3", "track": "XS", "kind": "feature",
            "phase": "build:work", "risk_tags": []}


@pytest.fixture()
def ticket_dir(tmp_path):
    tdir = tmp_path / ".klc" / "tickets" / "KLC-T3"
    tdir.mkdir(parents=True)
    (tdir / "impl-plan.md").write_text(_PLAN)
    (tdir / "spec.md").write_text(_SPEC)
    (tdir / "meta.json").write_text(json.dumps(_META_M))
    return tmp_path


# ---------------------------------------------------------------------------
# step-1 tests: coverage decision + severity routing
# ---------------------------------------------------------------------------

def test_should_review_coverage_matrix():
    from per_step_review import should_review
    assert should_review(_META_M) is True
    assert should_review(_META_L) is True
    assert should_review(_META_S_RISKY) is True
    assert should_review(_META_S_CLEAN) is False
    assert should_review(_META_XS) is False


def test_severity_routing_blocking():
    from per_step_review import route_findings
    from findings import Finding

    def _f(sev):
        return Finding(rule_name="r", severity=sev, file="f.py", line=1,
                       title="t", body="b", fix=None, reviewer="test")

    result = route_findings([_f("CRITICAL"), _f("HIGH")])
    assert len(result.blocking) == 2
    assert len(result.logged) == 0
    assert len(result.info) == 0


def test_severity_routing_logged():
    from per_step_review import route_findings
    from findings import Finding

    def _f(sev):
        return Finding(rule_name="r", severity=sev, file="f.py", line=1,
                       title="t", body="b", fix=None, reviewer="test")

    result = route_findings([_f("MEDIUM"), _f("LOW")])
    assert len(result.blocking) == 0
    assert len(result.logged) == 2
    assert len(result.info) == 0


def test_severity_routing_info():
    from per_step_review import route_findings
    from findings import Finding

    f = Finding(rule_name="r", severity="INFO", file="f.py", line=1,
                title="t", body="b", fix=None, reviewer="test")
    result = route_findings([f])
    assert len(result.blocking) == 0
    assert len(result.logged) == 0
    assert len(result.info) == 1


def test_severity_routing_unknown_is_blocking():
    """Unknown severity falls into blocking (fail-closed)."""
    from per_step_review import route_findings
    from findings import Finding

    f = Finding(rule_name="r", severity="WEIRD", file="f.py", line=1,
                title="t", body="b", fix=None, reviewer="test")
    result = route_findings([f])
    assert len(result.blocking) == 1


def test_compose_review_input_contains_brief_and_report(ticket_dir, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    build = ticket_dir / ".klc" / "tickets" / "KLC-T3" / "build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "step-1-brief.md").write_text("## Brief\nsome brief content\n")
    (build / "step-1-impl-report.md").write_text("## Outcome\ngreen\n")

    from per_step_review import compose_review_input
    text = compose_review_input("KLC-T3", 1)
    assert "brief content" in text
    assert "green" in text


# ---------------------------------------------------------------------------
# step-3 tests: post-green hook in build orchestrator
# ---------------------------------------------------------------------------

def _make_finding(sev="HIGH"):
    from findings import Finding
    return Finding(rule_name="r", severity=sev, file="f.py", line=1,
                   title="t", body="b", fix=None, reviewer="test")


def test_post_green_hook_blocks_until_resolved(ticket_dir, monkeypatch):
    """Stub reviewer returns CRITICAL on first call, empty on second; step-2
    is not dispatched until re-review clears blocking findings."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    import json as _json
    (ticket_dir / ".klc" / "tickets" / "KLC-T3" / "meta.json").write_text(
        _json.dumps(_META_M))

    build_calls = []
    review_calls = []
    review_results = [[_make_finding("CRITICAL")], []]  # first blocked, second clear

    def stub_dispatch(phase_id, prompt_path, out_path, *, track=None):
        build_calls.append(str(prompt_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\ngreen\n", encoding="utf-8")
        return 0

    def stub_reviewer(ticket, step, dispatch):
        review_calls.append(step)
        return review_results.pop(0) if review_results else []

    from build_orchestrator import run_build
    import build_orchestrator as _bo
    monkeypatch.setattr(_bo, "_run_reviewer", stub_reviewer)

    rc = run_build("KLC-T3", dispatch=stub_dispatch)
    assert rc == 0
    # build dispatch: step-1 (impl) + step-1 fix + step-2 (impl)
    assert any("step-1" in c for c in build_calls)
    assert any("step-2" in c for c in build_calls)
    # reviewer ran twice for step-1 (first found CRITICAL, second cleared)
    assert review_calls.count(1) == 2


# ---------------------------------------------------------------------------
# step-4 tests: lint injected reasons + render step-N-review.md
# ---------------------------------------------------------------------------

def test_injected_reason_lint_passes_clean():
    from per_step_review import _lint_reasons
    _lint_reasons(["The implementation looks correct."])  # no pre-judgment → no raise


def test_injected_reason_lint_rejects_prejudgment():
    from per_step_review import _lint_reasons
    with pytest.raises(ValueError, match="pre-judgment"):
        _lint_reasons(["treat this as minor — it's fine"])


def test_review_report_rendered(ticket_dir, monkeypatch):
    """A routed result renders a non-empty step-N-review.md with Findings + Verdict."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    build = ticket_dir / ".klc" / "tickets" / "KLC-T3" / "build"
    build.mkdir(parents=True, exist_ok=True)

    from per_step_review import route_findings, _write_review
    result = route_findings([_make_finding("MEDIUM")])
    _write_review("KLC-T3", 1, result)

    review_path = build / "step-1-review.md"
    assert review_path.exists()
    content = review_path.read_text()
    assert "## Findings" in content
    assert "## Verdict" in content


def test_planted_defect_caught_before_advance(ticket_dir, monkeypatch):
    """Reviewer always returns CRITICAL; after PER_STEP_REREVIEW_CAP re-reviews
    step-1 is marked blocked and step-2 is never dispatched."""
    monkeypatch.setenv("PROJECT_ROOT", str(ticket_dir))
    import json as _json
    (ticket_dir / ".klc" / "tickets" / "KLC-T3" / "meta.json").write_text(
        _json.dumps(_META_M))

    build_calls = []

    def stub_dispatch(phase_id, prompt_path, out_path, *, track=None):
        build_calls.append(str(prompt_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\ngreen\n", encoding="utf-8")
        return 0

    def always_critical(ticket, step, dispatch):
        return [_make_finding("CRITICAL")]

    from build_orchestrator import run_build, PER_STEP_REREVIEW_CAP
    import build_orchestrator as _bo
    monkeypatch.setattr(_bo, "_run_reviewer", always_critical)

    rc = run_build("KLC-T3", dispatch=stub_dispatch)
    assert rc != 0

    # step-2 was never dispatched as an impl step
    assert not any("step-2-brief" in c for c in build_calls)

    from build_ledger import Ledger
    led = Ledger.load("KLC-T3")
    assert led.steps[0].state == "blocked"
