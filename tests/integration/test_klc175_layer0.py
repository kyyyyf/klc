"""KLC-175 step-2 (AC-2): layer 0 turns the five deterministic checks into
`layer0` findings in the ticket's one `findings.json` (KLC-173 store). A check
that raises becomes ONE degraded `layer0-unavailable` INFO finding that names
it; a layer-0 finding is pooled and shown but never counted as a review pass.

The underlying checks are replaced by stand-ins that return their REAL shapes
(ac_test_coverage.Report, tdd_order.step_commits/verify_step tuples, the
drift_check / scope_delta report dicts, scan_sentinels.scan_diff's dict)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

KEY = "KLC-T9"
_PLAN = ("---\nticket: KLC-T9\nkind: impl-plan\n---\n\n"
         "## step-1 — s1\n\n- **Goal:** g\n- **Interfaces:** `def f() -> None`\n"
         "- **Expected:** e\n- **VERIFY:** pytest\n- **COMMIT:** KLC-T9 step-1: s\n"
         "- **Affected:** a.py\n- **Addresses:** AC-1\n- Depends-on: none\n\n")


@pytest.fixture
def tdir(tmp_path, monkeypatch):
    d = tmp_path / ".klc" / "tickets" / KEY
    d.mkdir(parents=True)
    (d / "impl-plan.md").write_text(_PLAN, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"ticket": KEY, "track": "M"}), encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    (tmp_path / "x.diff").write_text("", encoding="utf-8")
    return d


def _stub_checks(monkeypatch, *, ok=False):
    import ac_test_coverage, drift_check, scan_sentinels, scope_delta, tdd_order
    rep = ac_test_coverage.Report(track="M", findings=[] if ok else [
        ac_test_coverage.Finding("AC-1", "miss", ac_test_coverage.BLOCK, "AC-1 has no implemented test"),
        ac_test_coverage.Finding("AC-2", "weak", ac_test_coverage.SURFACE, "AC-2 test is weak")])
    monkeypatch.setattr(ac_test_coverage, "check", lambda *a, **k: rep)
    monkeypatch.setattr(tdd_order, "step_commits",
                        lambda t, n, repo=None: [{"sha": "a" * 40, "subject": f"{t} step-{n}: x"}])
    monkeypatch.setattr(tdd_order, "verify_step",
                        lambda t, n, repo=None: (True, "") if ok else
                        (False, f"{t} step-{n}: implementation commit (aaaa) precedes test commit"))
    drift = {"ticket": KEY,
             "scope_drift": {"drifted_modules": [] if ok else ["widgets"],
                             "orphan_files": [] if ok else ["z/other.py"], "skipped": None},
             "step_without_commit": {"flagged": [] if ok else ["step-3"], "exempt": [], "skipped": None}}
    monkeypatch.setattr(drift_check, "compare", lambda *a, **k: drift)
    monkeypatch.setattr(scope_delta, "compare", lambda *a, **k: {
        "planned": ["a"], "actual": ["a"] if ok else ["a", "b"], "drift": [] if ok else ["b"],
        "expansion": [] if ok else ["b"], "shared_touched": [], "unknown_files": []})
    monkeypatch.setattr(scan_sentinels, "scan_diff", lambda *a, **k: {
        "matches": [] if ok else [{"sentinel_id": "S-1", "file": "auth.py", "line": 4,
                                   "matched_text": "password=", "severity_override": "CRITICAL"}],
        "summary": {"total": 0 if ok else 1}})


def test_failing_checks_become_layer0_findings(tdir, monkeypatch, tmp_path):
    import findings_store, review_layer0
    _stub_checks(monkeypatch)
    out = review_layer0.run(KEY, tmp_path / "x.diff", round=1)
    assert out and all(f.kind == "layer0" and f.reviewer == "layer0" for f in out)
    by_rule = {}
    for f in out:
        by_rule.setdefault(f.rule_name, []).append(f)
    assert {f.severity for f in by_rule["ac-test-coverage"]} == {"HIGH", "LOW"} \
        or {f.severity for f in by_rule["ac-test-coverage"]} == {"HIGH", "MEDIUM"}
    assert any(f.severity == "HIGH" for f in by_rule["tdd-order"])
    assert by_rule["drift-check"] and by_rule["scope-delta"] and by_rule["sentinel-hit"]
    assert any(f.severity == "HIGH" for f in by_rule["scope-delta"])      # an expansion blocks at ack
    assert "layer0-unavailable" not in by_rule
    stored, notes = findings_store.read(tdir, kind="layer0", round=1)
    assert notes == [] and len(stored) == len(out)
    assert len({f.id for f in stored}) == len(stored)                      # ids are unique


def test_clean_checks_write_nothing_and_clear_the_group(tdir, monkeypatch, tmp_path):
    import findings_store, review_layer0
    _stub_checks(monkeypatch)
    review_layer0.run(KEY, tmp_path / "x.diff", round=1)
    _stub_checks(monkeypatch, ok=True)
    assert review_layer0.run(KEY, tmp_path / "x.diff", round=1) == []
    assert findings_store.read(tdir, kind="layer0", round=1)[0] == []      # replaced, not appended


def test_unavailable_check_is_degraded_finding(tdir, monkeypatch, tmp_path):
    import ac_test_coverage, review_layer0
    _stub_checks(monkeypatch, ok=True)

    def boom(*a, **k):
        raise RuntimeError("spec exploded")
    monkeypatch.setattr(ac_test_coverage, "check", boom)
    out = review_layer0.run(KEY, tmp_path / "x.diff", round=1)
    assert len(out) == 1
    f = out[0]
    assert (f.rule_name, f.severity, f.kind) == ("layer0-unavailable", "INFO", "layer0")
    assert "ac_test_coverage" in f.title and "spec exploded" in f.body


def test_rerun_replaces_only_its_round_and_keeps_other_kinds(tdir, monkeypatch, tmp_path):
    import findings_store, review_layer0
    (tdir / "findings.json").write_text(json.dumps([
        {"id": "F-1", "rule_name": "rule-x", "severity": "LOW", "file": "a.py", "line": 1,
         "title": "t", "body": "b", "fix": None, "reviewer": "code-review",
         "kind": "code-review", "round": 1}]), encoding="utf-8")
    _stub_checks(monkeypatch)
    review_layer0.run(KEY, tmp_path / "x.diff", round=1)
    n1 = len(findings_store.read(tdir, kind="layer0", round=1)[0])
    review_layer0.run(KEY, tmp_path / "x.diff", round=1)
    review_layer0.run(KEY, tmp_path / "x.diff", round=2)
    assert len(findings_store.read(tdir, kind="layer0", round=1)[0]) == n1
    assert len(findings_store.read(tdir, kind="layer0", round=2)[0]) == n1
    assert len(findings_store.read(tdir, kind="code-review")[0]) == 1


def test_layer0_is_pooled_but_never_counted(tdir, monkeypatch, tmp_path):
    import handback, review_layer0, task_brief
    _stub_checks(monkeypatch)
    out = review_layer0.run(KEY, tmp_path / "x.diff", round=1)
    items, notes = handback.load_ticket_findings(tdir)
    assert notes == []
    assert {f.kind for f in items} == {"layer0"} and len(items) == len(out)
    assert handback.validate_findings("layer0", [f.to_dict() for f in items]) == []
    assert handback.pool_main(["--ticket", KEY]) == 0
    pool = json.loads((tdir / "review" / "findings-pool.json").read_text())
    assert pool["raw_count"] == 0 and pool["findings"]                    # shown, not a review pass
    titles = [d["title"] for d in task_brief.step_findings(KEY, 1)]
    assert any("step-1" in t for t in titles)                             # the tdd-order finding names it


def test_review_plan_only_runs_layer0_and_lists_the_count(tmp_path):
    from _klc128_fixtures import _bare_and_clone, _branch_with_commits, _git, _rev_parse, _seed_ticket
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    key = "KLC-991"
    base = _rev_parse(clone, "main")
    _branch_with_commits(clone, key, [("widgets/a.py", "token = 'x'\n", f"{key} step-1: a")],
                         branch="feature/klc-991-w")
    head = _rev_parse(clone, "HEAD")
    tdir = _seed_ticket(clone, key, phase="build:work", track="M", affected_modules=["widgets"],
                        modules=[{"name": "widgets", "path": "widgets/"}],
                        pre_merge_range={"base": base, "head": head,
                                         "recorded_at_phase": "build", "recorded_at": "2026-01-01T00:00:00Z"})
    (clone / ".klc" / "config").mkdir(parents=True, exist_ok=True)
    (clone / ".klc" / "config" / "profile.yml").write_text("profile: generic\n", encoding="utf-8")
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    env = {**os.environ, "PROJECT_ROOT": str(clone)}
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        env.pop(k, None)
    r = subprocess.run([sys.executable, str(FW_ROOT / "scripts" / "review.py"), "--plan-only",
                        "--diff", "recorded", "--spec", str(tdir / "spec.md")],
                       cwd=str(clone), capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "layer 0" in (r.stdout + r.stderr).lower()
    rows = json.loads((tdir / "findings.json").read_text())
    assert rows and {d["kind"] for d in rows} == {"layer0"}
    plan = json.loads((tdir / "review" / "review-plan-r1.json").read_text())
    assert all(p.get("name") != "layer0" for p in plan["passes"])         # never a counted pass
