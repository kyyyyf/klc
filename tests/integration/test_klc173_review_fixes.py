"""KLC-173 step-6 — code-review round 1 fixes (F-001..F-007, F-013)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import advisories  # noqa: E402
import findings  # noqa: E402
import findings_store as fs  # noqa: E402
import gate_policy  # noqa: E402
import handback  # noqa: E402
import review_plan  # noqa: E402

TICKET = "KLC-991"
REC = {"source": "t", "severity": "high", "code": "t.c", "message": "m", "ref": ""}


def _rec(fid, title, kind, reviewer=None, rnd=1, rule="readability"):
    return {"id": fid, "rule_name": rule, "severity": "MEDIUM", "file": "a.py", "line": 3,
            "title": title, "body": "b", "fix": "f", "ref": "", "ac": "",
            "reviewer": reviewer or kind, "kind": kind, "round": rnd}


def _F(**kw):
    return findings.Finding.from_dict(_rec(**kw))


@pytest.fixture()
def tdir(tmp_path, monkeypatch):
    d = tmp_path / ".klc" / "tickets" / TICKET
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"ticket": TICKET, "kind": "tech", "phase": "build:ack-needed", "track": "M",
         "route_confidence": "high", "affected_modules": ["core/skills"], "layer": "code",
         "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 0, "total": 3},
         "phase_history": [{"phase": "build:work", "event": "set_state"},
                           {"phase": "build:ack-needed", "event": "manual-completion"}]}),
        "utf-8")
    (d / "spec.md").write_text("spec\n", "utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    return d


def _verdict(tmp_path, title, fid="F-1"):
    f = {"id": fid, "rule_name": "readability", "severity": "HIGH", "file": "f.py",
         "line": 5, "title": title, "body": "b", "fix": None}
    p = tmp_path / f"v-{title}.json"
    p.write_text(json.dumps({"findings": [f], "decisions_to_confirm": []}), "utf-8")
    return p


def _plan(sha):
    return review_plan.build_plan(
        ticket=TICKET, track="M", path="job", diff_sha256=sha, cap=None, override=False,
        passes=[review_plan.pass_entry("code-review", "manifest-always", "auto", None, None, "planned"),
                review_plan.pass_entry("external-review", "manifest-always", "auto", None, None, "planned")])


# ---- F-001 -----------------------------------------------------------------

def test_f001_failed_write_keeps_the_gate_dirty(tdir, monkeypatch):
    os.chmod(tdir, 0o555)
    try:
        if os.access(tdir, os.W_OK):
            pytest.skip("directory permissions are not enforced here")
        records, _s = advisories.finish(TICKET, "build", [("t", [REC])], persist=True)
    finally:
        os.chmod(tdir, 0o755)
    assert any(r["severity"] == "high" for r in records)
    assert advisories.write_failed(TICKET, "build") is True
    # the ack records the failure on its ack-needed history entry
    meta = json.loads((tdir / "meta.json").read_text("utf-8"))
    meta["phase_history"][-1]["advisories"] = "write-failed"
    (tdir / "meta.json").write_text(json.dumps(meta), "utf-8")
    sig = gate_policy.collect_signals(TICKET, "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is False


def test_f001_ack_stamps_the_failure_on_the_history_entry(tdir, monkeypatch):
    import lifecycle
    monkeypatch.setattr(advisories, "_store", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    advisories.finish(TICKET, "build", [("t", [REC])], persist=True)
    assert advisories.write_failed(TICKET, "build")
    extra = advisories.history_marker(TICKET, "build")
    assert extra == {"advisories": "write-failed"}
    lifecycle.set_state(TICKET, "build", "ack-needed", event="manual-completion", extra=extra)
    assert advisories.missing_key_is_clean(TICKET, "build") is False
    sig = gate_policy.collect_signals(TICKET, "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is False


def test_f001_a_later_successful_finish_clears_the_failure(tdir, monkeypatch):
    real = advisories._store
    monkeypatch.setattr(advisories, "_store", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    advisories.finish(TICKET, "build", [("t", [REC])], persist=True)
    monkeypatch.setattr(advisories, "_store", real)
    advisories.finish(TICKET, "build", [("t", [])], persist=True)
    assert advisories.write_failed(TICKET, "build") is False
    assert advisories.history_marker(TICKET, "build") is None


def test_f001_ack_run_passes_the_marker():
    src = (_FW_ROOT / "core" / "phases" / "ack.py").read_text("utf-8")
    assert "history_marker" in src


# ---- F-002 / F-005 ---------------------------------------------------------

def test_f002_take_and_headless_with_colliding_ids_all_load(tdir):
    fs.write_kind(tdir, "code-review", 1, [_F(fid="F-001", title="t", kind="code-review")],
                  replaces=lambda f: f.reviewer == "code-review")
    fs.write_kind(tdir, "code-review", 1,
                  [_F(fid="F-001", title="s", kind="code-review", reviewer="claude-sec"),
                   _F(fid="F-001", title="c", kind="code-review", reviewer="codex")],
                  replaces=lambda f: f.reviewer != "code-review")
    assert len(fs.read(tdir)[0]) == 3
    items, notes = handback.load_ticket_findings(tdir)
    assert notes == []
    assert len(items) == 3
    assert len({f.id for f in items}) == 3                    # re-keyed, none dropped


def test_f002_a_duplicate_inside_one_reviewer_still_fails_the_group(tdir):
    fs.write_kind(tdir, "code-review", 1,
                  [_F(fid="F-001", title="a", kind="code-review"),
                   _F(fid="F-001", title="b", kind="code-review")])
    items, notes = handback.load_ticket_findings(tdir)
    assert items == [] and notes and "duplicate" in notes[0]


def test_f005_pool_reads_only_the_latest_round_per_kind(tdir):
    fs.write_kind(tdir, "code-review", 1, [_F(fid="F-1", title="old", kind="code-review", rnd=1)])
    fs.write_kind(tdir, "code-review", 2, [_F(fid="F-1", title="new", kind="code-review", rnd=2)])
    fs.write_kind(tdir, "external-review", 1,
                  [_F(fid="F-1", title="ext", kind="external-review", rnd=1)])
    items, _n = handback.load_ticket_findings(tdir)
    assert sorted(f.title for f in items) == ["ext", "new"]
    every, _n = handback.load_ticket_findings(tdir, all_rounds=True)
    assert sorted(f.title for f in every) == ["ext", "new", "old"]
    assert handback.pool_main(["--ticket", TICKET]) == 0
    pool = json.loads((tdir / "review" / "findings-pool.json").read_text("utf-8"))
    assert pool["raw_count"] == 2


def test_f005_task_brief_step_findings_keeps_every_round(tdir):
    import task_brief
    fs.write_kind(tdir, "spec-review", 1, [_F(fid="F-1", title="s1", kind="spec-review")])
    got = fs.read(tdir, kind="spec-review")[0]
    assert len(got) == 1
    assert len(fs.read_dicts(tdir, kind="spec-review")[0]) == 1      # default stays all rounds
    assert hasattr(task_brief, "step_findings")


# ---- F-003 -----------------------------------------------------------------

def test_f003_empty_write_clears_the_group_when_it_is_the_only_one(tdir):
    fs.write_kind(tdir, "spec-review", 1, [_F(fid="F-1", title="x", kind="spec-review")])
    fs.write_kind(tdir, "spec-review", 1, [])
    assert fs.read(tdir)[0] == []


def test_f003_absent_store_stays_absent_on_an_empty_write(tmp_path):
    assert fs.write_kind(tmp_path, "spec-review", 1, []) is None
    assert not fs.path(tmp_path).exists()


def test_f003_empty_retake_clears_the_stale_round(tdir, tmp_path, monkeypatch):
    monkeypatch.setattr(handback, "_run_planner", lambda t: False)
    monkeypatch.setattr(handback, "_current_diff_sha", lambda t: "A" * 64)
    review_plan.write_plan(TICKET, _plan("A" * 64))
    assert handback.take("code-review", TICKET, _verdict(tmp_path, "x")) == 0
    assert len(fs.read(tdir)[0]) == 1
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"findings": [], "decisions_to_confirm": []}), "utf-8")
    assert handback.take("code-review", TICKET, empty) == 0
    assert fs.read(tdir)[0] == []


# ---- F-004 -----------------------------------------------------------------

def test_f004_one_round_per_diff_across_kinds(tdir, tmp_path, monkeypatch):
    sha = {"v": "A" * 64}
    monkeypatch.setattr(handback, "_current_diff_sha", lambda t: sha["v"])
    monkeypatch.setattr(handback, "_run_planner",
                        lambda t: (review_plan.write_plan(t, _plan(sha["v"])),
                                   handback.PlannerResult(True))[1])
    assert handback.take("code-review", TICKET, _verdict(tmp_path, "c1")) == 0
    sha["v"] = "B" * 64
    assert handback.take("external-review", TICKET, _verdict(tmp_path, "e2")) == 0
    assert handback.take("code-review", TICKET, _verdict(tmp_path, "c2")) == 0
    rounds = {(f.kind, f.title): f.round for f in fs.read(tdir)[0]}
    assert rounds[("external-review", "e2")] == rounds[("code-review", "c2")] == 2


def test_f004_planner_fails_then_succeeds_uses_the_plans_round(tdir, tmp_path, monkeypatch):
    monkeypatch.setattr(handback, "_current_diff_sha", lambda t: "A" * 64)
    ok = {"v": False}

    def planner(t):
        if ok["v"]:
            review_plan.write_plan(t, _plan("A" * 64))
            return handback.PlannerResult(True)
        return handback.PlannerResult(False, "x")

    monkeypatch.setattr(handback, "_run_planner", planner)
    assert handback.take("code-review", TICKET, _verdict(tmp_path, "c1")) == 0
    ok["v"] = True
    assert handback.take("code-review", TICKET, _verdict(tmp_path, "c1b")) == 0
    assert handback.take("code-review", TICKET, _verdict(tmp_path, "c1c")) == 0
    assert [(f.round, f.title) for f in fs.read(tdir)[0]] == [(1, "c1c")]


# ---- F-006 -----------------------------------------------------------------

def _git(cwd, *a):
    subprocess.run(["git", *a], cwd=str(cwd), check=True, capture_output=True)


def test_f006_review_py_plan_is_not_stale_for_take(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "a@b")
    _git(root, "config", "user.name", "n")
    (root / "a.py").write_text("a\n")
    _git(root, "add", "."); _git(root, "commit", "-qm", "a")
    _git(root, "checkout", "-qb", "feature/klc-991-x")
    (root / "b.py").write_text("b\n")
    _git(root, "add", "."); _git(root, "commit", "-qm", "b")
    _git(root, "checkout", "-q", "main")
    (root / "c.py").write_text("c\n")                       # main moved past the merge-base
    _git(root, "add", "."); _git(root, "commit", "-qm", "c")
    _git(root, "checkout", "-q", "feature/klc-991-x")
    d = root / ".klc" / "tickets" / TICKET
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"ticket": TICKET, "kind": "tech", "phase": "build:work", "phase_history": [],
         "track": "M"}), "utf-8")
    (d / "spec.md").write_text("spec\n", "utf-8")
    env = {**os.environ, "PROJECT_ROOT": str(root)}
    r = subprocess.run([sys.executable, str(_FW_ROOT / "scripts" / "review.py"), "--diff", "main",
                        "--spec", str(d / "spec.md"), "--plan-only"],
                       cwd=str(root), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    monkeypatch.setattr(handback, "_run_planner",
                        lambda t: pytest.fail("a fresh plan must not be re-planned"))
    assert handback.take("code-review", TICKET, _verdict(tmp_path, "c1")) == 0
    assert not (d / "review" / "review-plan-r2.json").exists()
    plan = json.loads((d / "review" / "review-plan-r1.json").read_text("utf-8"))
    assert [p["status"] for p in plan["passes"] if p["reviewer"] == "code-review"] == ["executed"]
    assert [f.round for f in fs.read(d, kind="code-review")[0]] == [1]   # KLC-175: layer0 rows share the store
    assert review_plan.diff_sha_for_ticket(TICKET) == plan["diff_sha256"]


# ---- F-007 -----------------------------------------------------------------

def test_f007_corrupt_store_is_moved_aside_and_gates_stay_dirty(tdir):
    (tdir / "advisories.json").write_text("{trunc", "utf-8")
    advisories.finish(TICKET, "design", [("t", [REC])], persist=True)
    aside = list(tdir.glob("advisories.corrupt-*.json"))
    assert len(aside) == 1 and aside[0].read_text("utf-8") == "{trunc"
    assert set(json.loads((tdir / "advisories.json").read_text("utf-8"))) == {"design"}
    assert advisories.store_corrupt(TICKET) is True
    sig = gate_policy.collect_signals(TICKET, "build")        # ack recorded, key absent
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is False
    sig = gate_policy.collect_signals(TICKET, "design")       # every phase is dirty
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is False


def test_f007_a_non_object_phase_entry_reads_dirty(tdir):
    (tdir / "advisories.json").write_text(json.dumps({"build": [1, 2]}), "utf-8")
    assert advisories.missing_key_is_clean(TICKET, "build") is False
    sig = gate_policy.collect_signals(TICKET, "build")
    assert gate_policy._CHECK["advisory"](sig["advisory"]) is False


# ---- F-013 -----------------------------------------------------------------

def test_f013_two_threads_appending_lose_nothing(tdir):
    def worker(name):
        for i in range(50):
            fs.write_kind(tdir, "code-review", 1,
                          [_F(fid=f"F-{i}", title=f"{name}{i}", kind="code-review", reviewer=name)],
                          replaces=lambda f, n=name, i=i: f.reviewer == n and f.id == f"F-{i}")
    ts = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(fs.read(tdir)[0]) == 100
    assert not list(tdir.glob("*.tmp"))


def test_f013_two_threads_on_advisories_lose_no_phase(tdir):
    def worker(name):
        for i in range(25):
            advisories.finish(TICKET, f"{name}{i}", [("t", [REC])], persist=True)
    ts = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(json.loads((tdir / "advisories.json").read_text("utf-8"))) == 50
    assert not list(tdir.glob("*.tmp"))


# ---- F-012 / F-010 ---------------------------------------------------------

def test_f012_legacy_paths_and_kind_stamp_live_in_the_store():
    hb = (_FW_ROOT / "core" / "skills" / "handback.py").read_text("utf-8")
    sr = (_FW_ROOT / "core" / "skills" / "spec_review.py").read_text("utf-8")
    assert "-review-findings.json" not in hb and "headless-findings.json" not in hb
    assert "STORE_KIND_BY_KEY[kind.name]" in sr
    assert fs.legacy_headless_rel() == "review/headless-findings.json"


def test_f012_record_pass_messages_name_the_review_plan_not_a_file(tdir):
    with pytest.raises(review_plan.RecordRefused) as e:
        review_plan.record_pass(TICKET, "code-review")
    assert "review-plan.json" not in str(e.value) and "review plan" in str(e.value)


def test_f010_schema_version_constant_is_gone():
    assert not hasattr(advisories, "SCHEMA_VERSION")
    process = (_FW_ROOT / "docs" / "process.md").read_text("utf-8")
    assert "schema version, ticket" not in process


# ---- review round 2 (R2-001..R2-003) ----

def test_r2_001_clean_newer_plan_round_hides_older_code_review_findings(tdir):
    fs.write_kind(tdir, "code-review", 1, [_F(fid="F-1", title="old", kind="code-review")])
    review_plan.write_plan(TICKET, _plan("A" * 64))
    review_plan.write_plan(TICKET, _plan("B" * 64))              # new diff -> plan round 2
    assert review_plan.round_of(review_plan.latest_plan_path(TICKET)) == 2
    fs.write_kind(tdir, "code-review", 2, [])                    # clean round 2: no rows
    items, _n = handback.load_ticket_findings(tdir)
    assert [f for f in items if f.kind == "code-review"] == []
    assert handback.pool_main(["--ticket", TICKET]) == 0
    pool = json.loads((tdir / "review" / "findings-pool.json").read_text("utf-8"))
    assert pool["raw_count"] == 0
    every, _n = handback.load_ticket_findings(tdir, all_rounds=True)
    assert [f.title for f in every] == ["old"]


def test_r2_001_without_a_plan_the_max_stored_round_is_the_cutoff(tdir):
    fs.write_kind(tdir, "code-review", 1, [_F(fid="F-1", title="old", kind="code-review")])
    fs.write_kind(tdir, "code-review", 2, [_F(fid="F-1", title="new", kind="code-review", rnd=2)])
    items, _n = handback.load_ticket_findings(tdir)
    assert [f.title for f in items] == ["new"]


def test_r2_002_corrupt_advisories_sibling_is_never_committed():
    import state_sync
    assert "advisories.corrupt-*.json" in state_sync._DERIVED_IGNORES
    assert ":(glob)**/advisories.corrupt-*.json" in state_sync._derived_match_pathspecs()
    assert ":(exclude,glob)**/advisories.corrupt-*.json" in state_sync.derived_add_exclude_pathspecs()


def test_r2_002_process_doc_says_how_to_clear_the_corrupt_flag():
    text = (_FW_ROOT / "docs" / "process.md").read_text("utf-8")
    assert "delete" in text.split("advisories.corrupt-<ts>.json", 1)[1][:900].lower()


def test_r2_003_stores_keep_the_default_file_mode(tmp_path):
    import store_lock
    old = os.umask(0o022)
    try:
        p = tmp_path / "findings.json"
        store_lock.atomic_write_text(p, "[]")
    finally:
        os.umask(old)
    mode = p.stat().st_mode & 0o777
    assert mode != 0o600 and mode == 0o644
