"""KLC-174 step-4: per-step review marker in steps.json and stale-verify re-run.

* a blocked per-step review keeps the step non-green until a NEW commit lands;
* a step that is non-green only because its verify is older than the latest
  commit gets `record_verify` again, not a whole new step agent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW / "tests"))

import klc114_helpers as h  # noqa: E402
import step_state  # noqa: E402

KEY = "KLC-OS1"


@pytest.fixture()
def green_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    plan = "# Implementation plan\n\n" + h.step_plan("step-1", affected="`src.py`")
    tdir = h.make_ticket(tmp_path, KEY, "M", plan)
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "def test_a():\n    assert True\n"},
             f"{KEY} step-1: add failing tests")
    h.commit(repo, {"src.py": "x = 1\n"}, f"{KEY} step-1: do the thing")
    h.seed_steps(tdir, repo)
    return tdir, repo


def _state(repo):
    return step_state.derive(KEY, repo)[0]


def _steps_file(tdir):
    return json.loads((tdir / "build" / "steps.json").read_text(encoding="utf-8"))


def test_blocked_review_marker_blocks_until_a_new_commit(green_repo):
    tdir, repo = green_repo
    assert _state(repo)["state"] == "green"
    step_state.mark_review(KEY, 1, "blocked", round=3, repo=repo)
    rec = _steps_file(tdir)["steps"]["1"]
    assert rec["review"]["state"] == "blocked" and rec["review"]["round"] == 3
    assert rec["review"]["at"] and rec["verify"]["exit_code"] == 0   # verify kept
    blocked = _state(repo)
    assert blocked["state"] == "blocked" and "review" in blocked["reason"]
    assert step_state.check_build(KEY, repo)[0] is False
    # a re-read without any new commit changes nothing
    assert _state(repo)["state"] == "blocked"
    # a NEW commit on the step makes the marker stale: green again, marker cleared
    h.commit(repo, {"src.py": "x = 2\n"}, f"{KEY} step-1: address review")
    assert _state(repo)["state"] == "blocked"      # the verify predates the new commit
    assert "review" not in _steps_file(tdir)["steps"]["1"]   # stale marker cleared
    h.seed_steps(tdir, repo)                       # ... re-verified at the new HEAD
    assert _state(repo)["state"] == "green"
    assert "review" not in _steps_file(tdir)["steps"]["1"]


def test_passed_marker_does_not_block(green_repo):
    tdir, repo = green_repo
    step_state.mark_review(KEY, 1, "passed", round=1, repo=repo)
    assert _state(repo)["state"] == "green"
    assert _steps_file(tdir)["steps"]["1"]["review"]["state"] == "passed"


def test_record_verify_keeps_review_marker(green_repo):
    tdir, repo = green_repo
    step_state.mark_review(KEY, 1, "blocked", round=1, repo=repo)
    step_state.record_verify(KEY, 1, repo=repo)
    assert _steps_file(tdir)["steps"]["1"]["review"]["state"] == "blocked"


def test_stale_only_verify_is_flagged_and_other_reasons_are_not(green_repo):
    tdir, repo = green_repo
    assert _state(repo)["verify_stale"] is False
    # verify older than the green commit
    data = _steps_file(tdir)
    data["steps"]["1"]["verify"]["ran_at"] = "2000-01-01T00:00:00Z"
    (tdir / "build" / "steps.json").write_text(json.dumps(data), encoding="utf-8")
    rec = _state(repo)
    assert rec["state"] == "blocked" and rec["verify_stale"] is True
    # a failed verify is not "stale only"
    data["steps"]["1"]["verify"].update(ran_at="2999-01-01T00:00:00Z", exit_code=1)
    (tdir / "build" / "steps.json").write_text(json.dumps(data), encoding="utf-8")
    rec = _state(repo)
    assert rec["state"] == "blocked" and rec["verify_stale"] is False
    # blocked review wins over stale verify
    data["steps"]["1"]["verify"].update(ran_at="2000-01-01T00:00:00Z", exit_code=0)
    (tdir / "build" / "steps.json").write_text(json.dumps(data), encoding="utf-8")
    step_state.mark_review(KEY, 1, "blocked", round=1, repo=repo)
    assert _state(repo)["verify_stale"] is False


# --------------------------------------------------------- orchestrator wiring

class _Stale(h.FakeStepState):
    """step-1 starts blocked on a stale verify; record_verify makes it green."""

    def derive(self, ticket, repo=None):
        recs = super().derive(ticket, repo)
        for r in recs:
            if r["step"] not in self.green:
                r.update(state="blocked", reason="recorded verify is older than the green commit",
                         verify_stale=True)
        return recs


def _meta(tmp_path, track):
    tdir = h.make_ticket(tmp_path, "KLC-OS2", track,
                         "# Implementation plan\n\n" + h.step_plan("step-1"))
    (tdir / "spec.md").write_text(
        "---\nticket: KLC-OS2\nkind: feature\nauthority: human\nrisk_tags: []\n---\n\n"
        "## Goals\nx\n\n## Acceptance Criteria\n- [ ] AC-1: x\n", encoding="utf-8")


def test_stale_verify_reruns_record_verify_without_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _meta(tmp_path, "XS")
    fake = _Stale([1])
    import build_orchestrator as bo
    monkeypatch.setattr(bo.step_state, "derive", fake.derive)
    monkeypatch.setattr(bo.step_state, "record_verify", fake.record_verify)
    calls = []

    def dispatch(*a, **k):
        calls.append(a)
        return 0
    assert bo.run_build("KLC-OS2", dispatch=dispatch) == 0
    assert calls == [] and fake.recorded == [1]


def test_stale_verify_that_still_fails_halts_without_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _meta(tmp_path, "XS")
    fake = _Stale([1])
    fake.fail = {1}
    import build_orchestrator as bo
    monkeypatch.setattr(bo.step_state, "derive", fake.derive)
    monkeypatch.setattr(bo.step_state, "record_verify", fake.record_verify)
    calls = []
    assert bo.run_build("KLC-OS2", dispatch=lambda *a, **k: calls.append(a) or 0) == 1
    assert calls == []


def test_blocked_per_step_review_is_marked_and_passed_is_marked(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _meta(tmp_path, "M")
    import build_orchestrator as bo
    fake = h.pin_step_state(monkeypatch, [1])
    marks = []
    monkeypatch.setattr(bo.step_state, "mark_review",
                        lambda t, n, state, **kw: marks.append((n, state)), raising=False)
    monkeypatch.setattr(bo, "should_review", lambda meta: True)
    monkeypatch.setattr(bo, "_per_step_gate", lambda *a, **k: False)

    def ok(phase_id, prompt_path, out_path, *, inputs=None, track=None):
        return 0
    assert bo.run_build("KLC-OS2", dispatch=ok) == 1
    assert marks == [(1, "blocked")]

    marks.clear()
    fake.green.clear()
    monkeypatch.setattr(bo, "_per_step_gate", lambda *a, **k: True)
    assert bo.run_build("KLC-OS2", dispatch=ok) == 0
    assert marks == [(1, "passed")]
