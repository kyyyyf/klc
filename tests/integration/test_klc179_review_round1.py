"""KLC-179 step-6: the fixes of code-review round 1 (F-001 .. F-012, plus the branch guard).

Each test drives real `lifecycle` / `rules` / `go` calls on a tmp project (a real scratch git
repo where the merge check or the branch guard needs one). Nothing writes into the real .klc.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills"), str(_FW / "core" / "phases"), str(_FW / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import klc114_helpers as h  # noqa: E402
import lifecycle  # noqa: E402
import rules  # noqa: E402

KEY = "KLC-T9"
CLEAN = {"advisory": {"records": [], "threshold": "medium"}, "scope_expansion": False,
         "sentinels": False, "mutation": False, "budget_overrun": False,
         "verdict": "APPROVED", "route_confidence": "high"}

LIGHT_BUILT = {"track": "light", "spec_approved": True, "plan_reviewed": True, "steps_green": True}
FULL_ALL = {"track": "full", "spec_approved": True, "test_plan_approved": True,
            "design_approved": True, "plan_reviewed": True, "steps_green": True,
            "review_verdict": "APPROVED"}


def _flush():
    import core.skills.phases as a
    a._CACHE = None
    import phases as b
    b._CACHE = None


def _ticket(tmp_path, monkeypatch, phase, track="S", facts=None, **extra) -> Path:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    _flush()
    meta_extra = {"phase": phase, "phase_history": [], **extra}
    if facts is not None:
        meta_extra["facts"] = dict(facts)
    return h.make_ticket(tmp_path, KEY, track, "## step-1 — x\n", meta_extra=meta_extra)


def _meta(tdir: Path) -> dict:
    return json.loads((tdir / "meta.json").read_text("utf-8"))


def _git(cwd, *args) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _repo(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    for a in (("config", "user.email", "t@t"), ("config", "user.name", "t"),
              ("config", "commit.gpgsign", "false")):
        _git(root, *a)
    (root / "a.txt").write_text("a\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "init")


def _go(argv):
    import go
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = int(go.run(list(argv)))
    return rc, out.getvalue(), err.getvalue()


# --- PART A: the branch guard is scoped to the repo compare() reads ------------------

def test_branch_guard_uses_the_repo_compare_scans(tmp_path, monkeypatch):
    import scope_delta as sd
    import phase_completion as pc
    _repo(tmp_path)
    _git(tmp_path, "checkout", "-q", "-b", "scratch")
    seen = []
    real = pc._head_branch_mismatch
    monkeypatch.setattr(pc, "_head_branch_mismatch",
                        lambda ticket, repo=None: seen.append(repo) or real(ticket, repo))
    monkeypatch.setattr(sd, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sd, "_git_changed_files", lambda root: [])
    monkeypatch.setattr(sd._lc, "read_meta", lambda t: {"affected_modules": []})
    delta = sd.compare("KLC-179")
    assert seen == [tmp_path], "the guard must read HEAD of the repo the scan reads"
    assert "names" not in (delta.get("skipped") or "")      # a branch with no ticket is no mismatch


# --- F-001: approve over CHANGES_REQUESTED is an override, request-changes a rework ----

def _review_gate(tdir, verdict):
    (tdir / "review-report.md").write_text(f"# Review\n\n## Verdict: {verdict}\n", encoding="utf-8")
    import phase_completion
    ok, msg = phase_completion.can_complete(KEY, "review")
    assert ok, msg
    lifecycle.set_state(KEY, "review", "ack-needed", event="manual-completion")


def test_f001_approve_over_changes_requested_is_an_override(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "review:work", facts=LIGHT_BUILT)
    _review_gate(tdir, "CHANGES_REQUESTED")
    assert _meta(tdir)["facts"]["review_verdict"] == "CHANGES_REQUESTED"
    assert lifecycle.apply_ack(KEY, 1, "ship it anyway") == "integrate:work"
    meta = _meta(tdir)
    assert meta["facts"]["review_verdict"] == "APPROVED"
    override = meta["review_override"]
    assert override["note"] == "ship it anyway" and override["at"] and "by" in override


def test_f001_no_endless_build_loop_over_three_cycles(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "review:work", facts=LIGHT_BUILT)
    for _ in range(3):
        _review_gate(tdir, "CHANGES_REQUESTED")
        assert lifecycle.apply_ack(KEY, 2) == "build:work"           # request-changes: rework
        facts = _meta(tdir)["facts"]
        assert "steps_green" not in facts and "review_verdict" not in facts
        lifecycle.set_state(KEY, "review", "work", event="set_state")
        facts = _meta(tdir)["facts"]
        facts["steps_green"] = True                                # the build was redone
        lifecycle.write_meta(KEY, {**_meta(tdir), "facts": facts})
    _review_gate(tdir, "CHANGES_REQUESTED")
    assert lifecycle.apply_ack(KEY, 1) == "integrate:work"         # an override ends it
    assert _meta(tdir)["phase"] == "integrate:work"


def test_f001_a_rewritten_steps_green_clears_the_old_verdict(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "build:work",
                   facts={**LIGHT_BUILT, "review_verdict": "CHANGES_REQUESTED"})
    import phase_completion
    monkeypatch.setattr(phase_completion, "can_complete_build", lambda t, persist=True: (True, ""))
    ok, _ = phase_completion.can_complete(KEY, "build")
    assert ok
    lifecycle.set_state(KEY, "build", "ack-needed", event="manual-completion")
    assert "review_verdict" not in _meta(tdir)["facts"]
    assert lifecycle.apply_ack(KEY, 1) == "review:work"


# --- F-002: decision facts come only from the human pick -----------------------------

def test_f002_gate_does_not_write_the_spec_decision(tmp_path, monkeypatch):
    assert rules.gate_facts("discovery-lite") == {"plan_reviewed": True}
    assert rules.gate_facts("discovery") == {}
    assert rules.gate_facts("design") == {"plan_reviewed": True}
    tdir = _ticket(tmp_path, monkeypatch, "discovery-lite:work", facts={"track": "light"})
    import phase_completion
    monkeypatch.setattr(phase_completion, "can_complete_discovery_lite", lambda t, persist=True: (True, ""))
    assert phase_completion.can_complete(KEY, "discovery-lite")[0]
    lifecycle.set_state(KEY, "discovery-lite", "ack-needed", event="manual-completion")
    assert "spec_approved" not in _meta(tdir)["facts"]
    assert lifecycle.apply_ack(KEY, 1) == "build:work"
    assert _meta(tdir)["facts"]["spec_approved"] is True


def test_f002_switch_at_a_decision_keeps_the_pick(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "discovery-lite:ack-needed", facts={
        "track": "light", "plan_reviewed": True})
    assert lifecycle.switch_track(KEY, "full") == "discovery:work"
    assert "spec_approved" not in _meta(tdir)["facts"]


def test_f002_status_and_move_show_blocked_on_at_ack_needed(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "design:ack-needed", track="M", facts={
        "track": "full", "spec_approved": True, "test_plan_approved": True, "plan_reviewed": True})
    import status
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert status.run([KEY, "--json"]) == 0
    view = json.loads(out.getvalue())
    assert view["blocked_on"] == "design_approved"
    import next_move
    assert next_move.compute(KEY).blocked_on == "design_approved"
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        status.run([KEY])
    assert "blocked_on: design_approved" in text.getvalue()


def test_f002_next_work_phase_at_ack_needed_still_names_the_next_phase(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "discovery-lite:ack-needed", facts={
        "track": "light", "plan_reviewed": True})
    assert lifecycle.next_work_phase(_meta(tdir)) == "build"


# --- F-003: integrate checks the merge ------------------------------------------------

def _unmerged_ticket(tmp_path, monkeypatch, with_range=True):
    _repo(tmp_path)
    tdir = _ticket(tmp_path, monkeypatch, "integrate:work", facts={
        **LIGHT_BUILT, "review_verdict": "APPROVED"})
    import gate_policy
    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(CLEAN))
    _git(tmp_path, "checkout", "-q", "-b", "feature/klc-t9-x")
    (tmp_path / "b.txt").write_text("b\n")
    _git(tmp_path, "add", "b.txt")
    _git(tmp_path, "commit", "-q", "-m", "KLC-T9 work")
    head = _git(tmp_path, "rev-parse", "HEAD")
    base = _git(tmp_path, "rev-parse", "main")
    if with_range:
        meta = _meta(tdir)
        meta["pre_merge_range"] = {"base": base, "head": head, "recorded_at_phase": "review",
                                   "recorded_at": "2026-01-01T00:00:00Z"}
        lifecycle.write_meta(KEY, meta)
    return tdir


def test_f003_light_ticket_is_not_archived_by_one_go_when_unmerged(tmp_path, monkeypatch):
    tdir = _unmerged_ticket(tmp_path, monkeypatch)
    before = (tdir / "meta.json").read_bytes()
    rc, out, err = _go([KEY])
    assert rc == 2, (out, err)
    assert (tdir / "meta.json").read_bytes() == before
    assert "not merged into main" in (out + err)


def test_f003_merged_branch_archives_and_confirmation_is_recorded(tmp_path, monkeypatch):
    tdir = _unmerged_ticket(tmp_path, monkeypatch)
    _git(tmp_path, "checkout", "-q", "main")
    _git(tmp_path, "merge", "-q", "--ff-only", "feature/klc-t9-x")
    rc, out, err = _go([KEY])
    assert rc == 0, (out, err)
    meta = _meta(tdir)
    assert meta["phase"] == "archived" and meta["facts"]["merged"] is True


def test_f003_without_a_recorded_range_a_human_pick_is_required(tmp_path, monkeypatch):
    tdir = _unmerged_ticket(tmp_path, monkeypatch, with_range=False)
    rc, out, err = _go([KEY])
    assert rc == 2 and _meta(tdir)["phase"] == "integrate:work"
    rc, out, err = _go([KEY, "--pick", "1"])
    assert rc == 0, (out, err)
    meta = _meta(tdir)
    assert meta["phase"] == "archived"
    assert meta["integrate"]["confirmed_by_pick"] is True and meta["integrate"]["merge_verified"] is False


def test_f003_auto_ack_refuses_an_unmerged_ticket(tmp_path, monkeypatch):
    tdir = _unmerged_ticket(tmp_path, monkeypatch)
    lifecycle.set_state(KEY, "integrate", "ack-needed", event="manual-completion")
    import ack
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        rc = ack.run([KEY, "--auto"])
    assert rc == 2 and "not merged into main" in err.getvalue()
    assert _meta(tdir)["phase"] == "integrate:ack-needed"


# --- F-004: manual is a decision when it runs ----------------------------------------

def test_f004_manual_is_a_decision_and_needs_the_passed_pick(tmp_path, monkeypatch):
    move = rules.next_move(dict(FULL_ALL), "full", risk_tags=["security"])
    assert move.action == "manual" and move.stop is True and move.blocked_on == "manual_passed"
    assert rules.next_move(dict(FULL_ALL), "full", risk_tags=[]).action == "integrate"
    import phases
    manual = phases.load_phases().by_id("manual")
    assert [(p.label, p.gate) for p in manual.picks] == [("passed", "decision"), ("failed", "decision")]
    tdir = _ticket(tmp_path, monkeypatch, "manual:work", track="M", facts=FULL_ALL,
                   risk_tags=["security"])
    import gate_policy
    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(CLEAN))
    rc, out, err = _go([KEY])
    assert rc == 2 and _meta(tdir)["phase"] == "manual:work"
    assert "manual_passed" not in _meta(tdir)["facts"]
    rc, out, err = _go([KEY, "--pick", "1", "--note", "walked it"])
    assert rc == 0, err
    meta = _meta(tdir)
    assert meta["facts"]["manual_passed"] is True and meta["manual"]["verdict"] == "passed"


def test_f004_spec_sentence_names_manual():
    spec = (_FW / ".klc" / "tickets" / "KLC-179" / "spec.md")
    if not spec.exists():
        pytest.skip("no local .klc ticket state")
    assert "plus manual when risk tags demand it" in spec.read_text("utf-8")


# --- F-005: rollback reworks from the build ------------------------------------------

def test_f005_rollback_returns_to_build(tmp_path, monkeypatch):
    facts = {**FULL_ALL, "merged": True, "observed": True}
    tdir = _ticket(tmp_path, monkeypatch, "observe:ack-needed", track="M", facts=facts,
                   risk_tags=["data"])
    assert lifecycle.apply_ack(KEY, 3) == "build:work"
    got = _meta(tdir)["facts"]
    for gone in ("steps_green", "review_verdict", "merged", "observed"):
        assert gone not in got
    assert got["design_approved"] is True


# --- F-007: observe keeps its four tags ----------------------------------------------

@pytest.mark.parametrize("tag,observed", [("user-facing", True), ("data", True), ("security", True),
                                         ("migration", True), ("performance", False)])
def test_f007_observe_runs_for_the_four_tags_only(tag, observed):
    facts = {**FULL_ALL, "manual_passed": True, "merged": True}
    move = rules.next_move(facts, "full", risk_tags=[tag])
    assert (move.action == "observe") is observed
    assert ("observed" in rules.required_facts(facts, "full", risk_tags=[tag])) is observed
    # manual still runs for any tag
    assert "manual_passed" in rules.required_facts(facts, "full", risk_tags=[tag])


# --- F-008: switch_track is guarded first, intake keeps its ack ------------------------

def test_f008_blocked_entry_leaves_the_ticket_untouched(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "build:work", facts={
        "track": "light", "spec_approved": True, "plan_reviewed": True})
    def _blocked(ticket, phase):
        raise RuntimeError("blocked")

    monkeypatch.setattr(lifecycle, "enter_work_guard", _blocked)
    before = (tdir / "meta.json").read_bytes()
    with pytest.raises(RuntimeError):
        lifecycle.switch_track(KEY, "full")
    assert (tdir / "meta.json").read_bytes() == before


def test_f008_switch_at_intake_ack_needed_only_rewrites_the_lane(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "intake:ack-needed", facts={"track": "light"})
    assert lifecycle.switch_track(KEY, "full") == "intake:ack-needed"
    meta = _meta(tdir)
    assert meta["phase"] == "intake:ack-needed" and meta["facts"]["track"] == "full"
    assert meta["track"] == "M"


# --- F-009: phase_for is right at the ack-time acks -----------------------------------

@pytest.mark.parametrize("facts,tags,at", [
    ({**FULL_ALL}, ["data"], "manual:ack-needed"),
    ({**FULL_ALL, "manual_passed": True}, [], "integrate:ack-needed"),
    ({**FULL_ALL, "manual_passed": True, "merged": True}, ["data"], "observe:ack-needed"),
    ({**FULL_ALL, "manual_passed": True, "merged": True, "observed": True,
      "retro_required": True}, ["data"], "learn:ack-needed"),
])
def test_f009_phase_for_names_the_ack_time_phase(facts, tags, at):
    assert rules.phase_for(facts, at, risk_tags=tags) == at
    # the gate-fact acks are unchanged
    assert rules.phase_for(FULL_ALL, "ack-needed", risk_tags=[]) == "review:ack-needed"


def test_f009_a_hint_for_the_wrong_phase_falls_back():
    assert rules.phase_for(dict(FULL_ALL), "learn:ack-needed", risk_tags=[]) == "review:ack-needed"


# --- F-010: abort lands on a visited phase --------------------------------------------

def test_f010_abort_skips_phases_the_ticket_never_visited(tmp_path, monkeypatch):
    history = [{"phase": "integrate:work", "event": "advance"}]
    for pid in ("manual", "observe"):
        history.insert(0, {"phase": f"{pid}:work", "event": "skipped"})
    history.insert(0, {"phase": "review:ack", "event": "ack"})
    tdir = _ticket(tmp_path, monkeypatch, "integrate:work", track="M", facts=FULL_ALL,
                   phase_history=history)
    assert lifecycle.abort(KEY) == "review:ack"
    assert _meta(tdir)["phase"] == "review:ack"


def test_f010_abort_without_history_uses_applicable_phases(tmp_path, monkeypatch):
    _ticket(tmp_path, monkeypatch, "learn:work", track="M", facts=FULL_ALL, risk_tags=[])
    assert lifecycle.abort(KEY) == "integrate:ack"


# --- F-012: a light -> full switch without a design clears the build ------------------

def test_f012_upgrade_without_design_clears_build_and_verdict(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "review:work", facts={
        **LIGHT_BUILT, "review_verdict": "APPROVED"})
    assert lifecycle.switch_track(KEY, "full") == "acceptance-test-plan:work"
    facts = _meta(tdir)["facts"]
    assert "steps_green" not in facts and "review_verdict" not in facts
    assert facts["spec_approved"] is True


def test_f012_upgrade_keeps_the_build_when_the_design_exists(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "review:work", facts={
        **LIGHT_BUILT, "design_approved": True, "test_plan_approved": True})
    lifecycle.switch_track(KEY, "full")
    assert _meta(tdir)["facts"]["steps_green"] is True


# --- F-011: dead code gone -------------------------------------------------------------

def test_f011_unused_rework_clear_is_gone():
    assert not hasattr(rules, "rework_clear")


# --- round 2 ---------------------------------------------------------------------------

def test_r2_001_override_records_the_real_report_verdict(tmp_path, monkeypatch):
    """The gate did not stage the verdict (the report is written after); the override
    still names the verdict the report carried, not None."""
    tdir = _ticket(tmp_path, monkeypatch, "review:work", facts=LIGHT_BUILT)
    import gate_policy
    monkeypatch.setattr(gate_policy, "collect_signals", lambda t, p: dict(CLEAN))
    (tdir / "review-report.md").write_text("# Review\n\n## Verdict: CHANGES_REQUESTED\n",
                                           encoding="utf-8")
    lifecycle.set_state(KEY, "review", "ack-needed", event="manual-completion")
    assert "review_verdict" not in _meta(tdir)["facts"]
    lifecycle.apply_ack(KEY, 1, "ok")
    meta = _meta(tdir)
    assert meta["facts"]["review_verdict"] == "APPROVED"
    assert meta["review_override"]["report_verdict"] == "CHANGES_REQUESTED"


def _status(*argv):
    import status
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert status.run([KEY, *argv]) == 0
    return out.getvalue()


def test_r2_003_status_shows_the_review_override_and_pick_confirmed_merge(tmp_path, monkeypatch):
    tdir = _ticket(tmp_path, monkeypatch, "integrate:work", facts=LIGHT_BUILT,
                   review_override={"at": "2026-01-02T00:00:00Z", "by": "ek", "note": "",
                                    "report_verdict": "CHANGES_REQUESTED"},
                   integrate={"merge_verified": False, "confirmed_by_pick": True})
    text = _status()
    assert "review: approved by override over CHANGES_REQUESTED at 2026-01-02T00:00:00Z" in text
    assert "integrate: merge confirmed by pick (not verified against main)" in text
    view = json.loads(_status("--json"))
    assert view["review_override"]["report_verdict"] == "CHANGES_REQUESTED"
    assert view["integrate"]["confirmed_by_pick"] is True


def test_r2_003_status_is_quiet_without_overrides(tmp_path, monkeypatch):
    _ticket(tmp_path, monkeypatch, "integrate:work", facts=LIGHT_BUILT)
    text = _status()
    assert "by override" not in text and "confirmed by pick" not in text
    assert "review_override" not in json.loads(_status("--json"))
