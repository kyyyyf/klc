"""KLC-174 step-6: code-review round 1 fixes.

F-002 ran_at bounded, F-003 verify tied to HEAD and a clean tree, F-004 per-step
review not repeated, F-005 executed passes counted from plan files, F-006 dangerous
flags refused, F-008 read-only derive and a NUL byte in a command, F-009 judge skips
a duplicate verify.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW / "core" / "phases"))
sys.path.insert(0, str(FW / "tests"))

import klc114_helpers as h  # noqa: E402
import step_state  # noqa: E402

KEY = "KLC-RF1"


@pytest.fixture()
def repo_env(tmp_path, monkeypatch):
    """A green step with a REAL recorded verify (`sh -c "echo 2 passed"`)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    plan = "# Implementation plan\n\n" + h.step_plan("step-1", affected="`src.py`")
    tdir = h.make_ticket(tmp_path, KEY, "M", plan)
    repo = h.make_repo(tmp_path)
    h.commit(repo, {"tests/test_x.py": "def test_a():\n    assert True\n"},
             f"{KEY} step-1: add failing tests")
    h.commit(repo, {"src.py": "x = 1\n"}, f"{KEY} step-1: do the thing")
    return tdir, repo


def _allow_sh(monkeypatch):
    monkeypatch.setattr(step_state.command_allowlist, "check", lambda c, e=(): (True, ""))


def _rec(repo):
    return step_state.derive(KEY, repo)[0]


def _edit_verify(tdir, **fields):
    f = tdir / "build" / "steps.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["steps"]["1"]["verify"].update(fields)
    f.write_text(json.dumps(data), encoding="utf-8")


# ------------------------------------------------------- F-003 head + dirty tree

def test_record_verify_stores_head_and_dirty(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    v = step_state.record_verify(KEY, 1, repo=repo)
    assert v["head"] == h._run(["git", "rev-parse", "HEAD"], repo)
    assert v["dirty"] is False
    assert _rec(repo)["state"] == "green"


def test_dirty_tree_verify_is_not_green(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    (repo / "src.py").write_text("x = 999  # uncommitted\n")
    v = step_state.record_verify(KEY, 1, repo=repo)
    assert v["dirty"] is True
    rec = _rec(repo)
    assert rec["state"] == "blocked" and "dirty" in rec["reason"]


def test_untracked_klc_dir_does_not_make_the_tree_dirty(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    assert step_state.record_verify(KEY, 1, repo=repo)["dirty"] is False


def test_verify_on_an_older_head_than_the_green_commit_is_not_green(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    step_state.record_verify(KEY, 1, repo=repo)
    assert _rec(repo)["state"] == "green"
    h.commit(repo, {"src.py": "x = 2\n"}, f"{KEY} step-1: fix after verify")
    rec = _rec(repo)
    assert rec["state"] == "blocked" and rec["verify_stale"] is True


def test_forged_head_that_is_not_a_descendant_is_not_green(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    step_state.record_verify(KEY, 1, repo=repo)
    first = h._run(["git", "rev-list", "--max-parents=0", "HEAD"], repo)
    _edit_verify(tdir, head=first)
    assert _rec(repo)["state"] == "blocked"


def test_verify_without_head_is_not_green(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    step_state.record_verify(KEY, 1, repo=repo)
    _edit_verify(tdir, head=None)
    assert _rec(repo)["state"] == "blocked"


def test_a_later_unrelated_commit_keeps_the_verify_valid(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    step_state.record_verify(KEY, 1, repo=repo)
    h.commit(repo, {"other.txt": "x\n"}, "unrelated later commit")
    assert _rec(repo)["state"] == "green"


# --------------------------------------------------------------- F-002 ran_at

def test_future_ran_at_is_unverified(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    step_state.record_verify(KEY, 1, repo=repo)
    _edit_verify(tdir, ran_at="2999-01-01T00:00:00Z")
    rec = _rec(repo)
    assert rec["state"] == "blocked"
    assert "unverified: ran_at in the future" in rec["reason"]


@pytest.mark.parametrize("ahead,state", [(60, "green"), (300, "blocked")])
def test_commit_time_check_tolerates_clock_skew(repo_env, monkeypatch, ahead, state):
    import time
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    step_state.record_verify(KEY, 1, repo=repo)
    monkeypatch.setattr(step_state, "_commit_epoch", lambda sha, r: int(time.time()) + ahead)
    assert _rec(repo)["state"] == state


# ---------------------------------------------------------------- F-008 derive

def test_derive_persist_false_never_writes(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    step_state.record_verify(KEY, 1, repo=repo)
    step_state.mark_review(KEY, 1, "blocked", repo=repo)
    h.commit(repo, {"src.py": "x = 3\n"}, f"{KEY} step-1: fix")      # marker is now stale
    f = tdir / "build" / "steps.json"
    before = f.read_bytes()
    step_state.derive(KEY, repo, persist=False)
    assert step_state.check_build(KEY, repo, persist=False)[0] in (True, False)
    assert f.read_bytes() == before
    step_state.derive(KEY, repo)                                    # default clears it
    assert "review" not in json.loads(f.read_text())["steps"]["1"]


def test_can_complete_build_probe_does_not_write(repo_env, monkeypatch):
    import phase_completion
    tdir, repo = repo_env
    _allow_sh(monkeypatch)
    step_state.record_verify(KEY, 1, repo=repo)
    step_state.mark_review(KEY, 1, "blocked", repo=repo)
    h.commit(repo, {"src.py": "x = 3\n"}, f"{KEY} step-1: fix")
    f = tdir / "build" / "steps.json"
    before = f.read_bytes()
    phase_completion.can_complete_build(KEY, repo, persist=False)
    assert f.read_bytes() == before


def test_nul_byte_command_is_recorded_unverified_not_a_traceback(repo_env, monkeypatch, capsys):
    tdir, repo = repo_env
    monkeypatch.setattr(step_state, "_plan_command", lambda step: "pytest -q\x00 x")
    v = step_state.record_verify(KEY, 1, repo=repo)
    assert v["exit_code"] is None
    assert v["summary_line"] == "unverified: command-not-runnable"
    import step
    monkeypatch.setattr(step_state, "_plan_command", lambda s: "pytest -q\x00 x")
    assert step.run(["verify", KEY, "1"]) == 1


def test_oserror_from_the_runner_is_command_not_runnable(repo_env, monkeypatch):
    tdir, repo = repo_env
    _allow_sh(monkeypatch)

    def boom(*a, **k):
        raise OSError("no shell")
    monkeypatch.setattr(step_state.verify_runner, "run", boom)
    v = step_state.record_verify(KEY, 1, repo=repo)
    assert v["exit_code"] is None and v["summary_line"] == "unverified: command-not-runnable"


# ------------------------------------------------------------------ F-006 flags

@pytest.mark.parametrize("cmd", ["pytest -p x", "python3 -m pytest --basetemp=.klc -q"])
def test_dangerous_flags_refused_with_a_reason(cmd):
    import command_allowlist
    ok, why = command_allowlist.check(cmd)
    assert ok is False and why.startswith("command-not-allowed: flag")


@pytest.mark.parametrize("cmd", ["pytest --junit-xml=/tmp/j.xml", "pytest --junit-xml /tmp/j.xml",
                                 "pytest -o addopts=x", "python3 -m pytest --override-ini addopts=x"])
def test_more_denied_pytest_flags(cmd):
    import command_allowlist
    ok, why = command_allowlist.check(cmd)
    assert ok is False and why.startswith("command-not-allowed: flag")


def test_q_and_k_still_allowed():
    import command_allowlist
    assert command_allowlist.check("pytest -q -k 'a or b' tests/x.py") == (True, "")


def test_ordinary_flags_still_allowed():
    import command_allowlist
    assert command_allowlist.check("python3 -m pytest tests/x.py -q -x -k 'a and b'") == (True, "")


# ----------------------------------------------------------- F-004 orchestrator

class _Gate(h.FakeStepState):
    """A step whose gate makes a fix commit: `green_commit` moves, so the stored
    verify goes stale and the review marker records the commit it was written for."""

    def __init__(self, **kw):
        super().__init__([1], **kw)
        self.commit_no = 1
        self.verified_at = None
        self.marker = None
        self.marker_commit = "marker"       # overridden by the well-behaved fake

    def green_commit(self):
        return f"c{self.commit_no}"

    def derive(self, ticket, repo=None):
        ok = self.verified_at == self.commit_no
        stale = self.verified_at is not None and not ok
        return [{"step": 1, "state": "green" if ok else "blocked",
                 "reason": "" if ok else ("recorded verify is older than the green commit"
                                          if stale else "no recorded verify"),
                 "verify_stale": stale, "verify": None, "green_commit": self.green_commit(),
                 "red_commit": None, "addresses": []}]

    def record_verify(self, ticket, step, *, runner="agent", repo=None):
        self.recorded.append(step)
        self.verified_at = self.commit_no
        return {"exit_code": 0}

    def mark_review(self, ticket, step, state, *, round=1, repo=None):
        self.reviews.append((step, state))
        self.marker = {"state": state, "commit": self.marker_commit or self.green_commit()}
        return self.marker

    def read(self, ticket):
        return {1: {"review": self.marker}} if self.marker else {}


def _gate_env(tmp_path, monkeypatch, *, well_behaved):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = h.make_ticket(tmp_path, "KLC-OS3", "M", "# Implementation plan\n\n" + h.step_plan("step-1"))
    (tdir / "spec.md").write_text(
        "---\nticket: KLC-OS3\nkind: feature\nauthority: human\nrisk_tags: []\n---\n\n"
        "## Goals\nx\n\n## Acceptance Criteria\n- [ ] AC-1: x\n", encoding="utf-8")
    import build_orchestrator as bo
    fake = _Gate()
    if well_behaved:
        fake.marker_commit = None
    for name in ("derive", "record_verify", "mark_review", "read"):
        monkeypatch.setattr(bo.step_state, name, getattr(fake, name))
    monkeypatch.setattr(bo, "should_review", lambda meta: True)
    return bo, fake


def test_gate_fix_commit_does_not_trigger_a_second_gate(tmp_path, monkeypatch):
    bo, fake = _gate_env(tmp_path, monkeypatch, well_behaved=True)
    gates = []

    def gate(ticket, n, meta, dispatch, **kw):
        gates.append(n)
        fake.commit_no += 1               # the fix subagent commits inside the gate
        return True
    monkeypatch.setattr(bo, "_per_step_gate", gate)
    assert bo.run_build("KLC-OS3", dispatch=lambda *a, **k: 0) == 0
    assert gates == [1]
    assert fake.reviews == [(1, "passed")]
    assert fake.recorded == [1, 1]        # first verify, then the stale re-verify


def test_review_cap_per_step_blocks_with_a_reason(tmp_path, monkeypatch, capsys):
    bo, fake = _gate_env(tmp_path, monkeypatch, well_behaved=False)   # marker never matches
    gates = []

    def gate(ticket, n, meta, dispatch, **kw):
        gates.append(n)
        fake.commit_no += 1
        return True
    monkeypatch.setattr(bo, "_per_step_gate", gate)
    assert bo.run_build("KLC-OS3", dispatch=lambda *a, **k: 0) == 1
    assert len(gates) == 3                                # build.max_reviews_per_step default
    assert fake.reviews[-1] == (1, "blocked")
    assert "max_reviews_per_step" in capsys.readouterr().err


def test_max_reviews_per_step_setting_default(monkeypatch):
    import settings
    assert settings.build_max_reviews_per_step() == 3


# ------------------------------------------------- F-009 judge skips a repeat

def test_judge_step_skips_record_verify_when_already_green(monkeypatch):
    import build_orchestrator as bo
    calls = []
    monkeypatch.setattr(bo.step_state, "derive", lambda t, repo=None, **k: [
        {"step": 1, "state": "green", "reason": "", "green_commit": "c1"}])
    monkeypatch.setattr(bo.step_state, "record_verify",
                        lambda *a, **k: calls.append(a))
    assert bo._judge_step("KLC-X", 1)["state"] == "green"
    assert calls == []


def test_judge_step_records_when_not_green(monkeypatch):
    import build_orchestrator as bo
    calls = []
    monkeypatch.setattr(bo.step_state, "derive", lambda t, repo=None, **k: [
        {"step": 1, "state": "blocked", "reason": "no recorded verify", "green_commit": "c1"}])
    monkeypatch.setattr(bo.step_state, "record_verify", lambda *a, **k: calls.append(a))
    bo._judge_step("KLC-X", 1)
    assert len(calls) == 1


# ------------------------------------------------------------- F-005 metrics

def _seed_ticket(tmp_path, ticket, *, plans=(), attempts=None):
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {"ticket": ticket, "kind": "tech", "kind_source": "user", "phase": "build:ack",
            "phase_history": [], "track": "M", "route_hint": "M", "route_confidence": "high",
            "affected_modules": [], "estimate": None, "layer": "code", "jira_url": None,
            "created": "2026-01-01T00:00:00Z"}
    if attempts:
        meta["metrics"] = {"tokens": {"review": {"attempts": attempts}}}
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    for rel, plan in plans:
        p = tdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(plan), encoding="utf-8")
    return tdir


def _plan(gen, passes):
    return {"generated_at": gen, "diff_sha256": "d" * 8,
            "passes": [{"reviewer": r, "status": s} for r, s in passes]}


def _rollup(tmp_path):
    import metrics
    metrics.cmd_rollup(None)
    out = tmp_path / ".klc" / "knowledge" / "process-metrics.json"
    return json.loads(out.read_text(encoding="utf-8"))["per_track"]["M"]


def test_executed_handback_pass_without_an_attempt_is_counted(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_ticket(tmp_path, "KLC-P1", plans=[
        ("review/review-plan-r1.json",
         _plan("t1", [("code-review", "executed"), ("security", "planned"),
                      ("drift", "skipped")]))])
    t = _rollup(tmp_path)
    assert t["review_llm_passes_per_ticket"] == 1
    assert t["review_llm_passes_measured_tickets"] == 1


def test_all_rounds_and_the_legacy_root_plan_are_counted(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_ticket(tmp_path, "KLC-P2", plans=[
        ("review/review-plan-r1.json", _plan("t1", [("code-review", "executed")])),
        ("review/review-plan-r2.json", _plan("t2", [("code-review", "executed"),
                                                    ("security", "executed")])),
        ("review-plan.json", _plan("t0", [("code-review", "executed")]))])
    assert _rollup(tmp_path)["review_llm_passes_per_ticket"] == 4


def test_plan_pass_and_its_attempt_are_not_double_counted(tmp_path, monkeypatch):
    import review_plan
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    plan = _plan("t1", [("code-review", "executed")])
    aid = review_plan._plan_attempt_id("KLC-P3", plan, "code-review")
    _seed_ticket(tmp_path, "KLC-P3",
                 plans=[("review/review-plan-r1.json", plan)],
                 attempts=[{"id": aid, "in": 1, "out": 1, "cache_hit": 0,
                            "source": "provider", "reviewer": "code-review"},
                           {"id": "other", "in": 1, "out": 1, "cache_hit": 0,
                            "source": "provider", "reviewer": "external"}])
    assert _rollup(tmp_path)["review_llm_passes_per_ticket"] == 2


def test_provider_attempt_and_its_executed_plan_pass_count_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_ticket(tmp_path, "KLC-P4",
                 plans=[("review/review-plan-r1.json", _plan("t1", [("code-review", "executed")]))],
                 attempts=[{"id": "a1b2c3d4e5f6", "in": 1, "out": 1, "cache_hit": 0,
                            "source": "provider", "reviewer": "code-review"}])
    assert _rollup(tmp_path)["review_llm_passes_per_ticket"] == 1


def test_same_reviewer_in_two_rounds_counts_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_ticket(tmp_path, "KLC-P5",
                 plans=[("review/review-plan-r1.json", _plan("t1", [("code-review", "executed")])),
                        ("review/review-plan-r2.json", _plan("t2", [("code-review", "executed")]))],
                 attempts=[{"id": "aaaaaaaaaaaa", "in": 1, "out": 1, "cache_hit": 0,
                            "source": "provider", "reviewer": "code-review"},
                           {"id": "bbbbbbbbbbbb", "in": 1, "out": 1, "cache_hit": 0,
                            "source": "provider", "reviewer": "code-review"}])
    assert _rollup(tmp_path)["review_llm_passes_per_ticket"] == 2
