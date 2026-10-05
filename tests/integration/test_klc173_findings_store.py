"""KLC-173 step-1: one findings.json per ticket, readers accept both layouts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

_KEY = "KLC-T9"
_TKEY = "KLC-991"
_PLAN = "".join(
    f"## step-{n} — s{n}\n\n- **Goal:** g\n- **Interfaces:** `def f() -> None`\n"
    f"- **Expected:** e\n- **VERIFY:** pytest\n- **COMMIT:** KLC-T9 step-{n}: s\n"
    f"- **Affected:** a.py\n- **Addresses:** AC-{n}\n- Depends-on: none\n\n"
    for n in (1, 2))
_SPEC = ("---\nticket: KLC-T9\nkind: feature\nauthority: human\nrisk_tags: []\n---\n\n"
         "## Goals\ng\n\n## Acceptance Criteria\n- [ ] AC-1: one\n- [ ] AC-2: two\n")


def _rec(fid, title, kind, ref="", rnd=None, rule="rule-x", reviewer=None):
    d = {"id": fid, "rule_name": rule, "severity": "MEDIUM", "file": "a.py", "line": 3,
         "title": title, "body": "b", "fix": "f", "ref": ref, "ac": "",
         "reviewer": reviewer or kind, "kind": kind}
    if rnd is not None:
        d["round"] = rnd
    return d


def _seed(tmp_path, monkeypatch):
    tdir = tmp_path / ".klc" / "tickets" / _KEY
    tdir.mkdir(parents=True)
    (tdir / "impl-plan.md").write_text("---\nticket: KLC-T9\nkind: impl-plan\n---\n\n" + _PLAN)
    (tdir / "spec.md").write_text(_SPEC)
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    return tdir


def _w(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_finding_round_defaults_to_one_and_stays_out_of_issue_id():
    import findings
    d = _rec("F-1", "t", "spec-review")
    a = findings.Finding.from_dict(d)
    b = findings.Finding.from_dict({**d, "round": 2})
    assert a.round == 1 and b.round == 2
    assert a.issue_id == b.issue_id
    assert a.to_dict()["round"] == 1


def test_store_read_filters_by_kind_and_round(tmp_path):
    import findings_store as fs
    _w(tmp_path / "findings.json", [
        _rec("F-1", "a", "code-review", rnd=1), _rec("F-1", "b", "code-review", rnd=2),
        _rec("F-1", "c", "spec-review")])
    allf, notes = fs.read(tmp_path)
    assert [f.title for f in allf] == ["a", "b", "c"] and notes == []
    assert [f.title for f in fs.read(tmp_path, kind="code-review", round=2)[0]] == ["b"]
    assert [f.title for f in fs.read(tmp_path, kind="spec-review")[0]] == ["c"]
    assert fs.latest_round(tmp_path, "code-review") == 2
    assert fs.latest_round(tmp_path, "drift-review") == 0


def test_store_write_kind_replaces_only_its_own_round_and_never_creates_empty(tmp_path):
    import findings
    import findings_store as fs
    assert fs.write_kind(tmp_path, "spec-review", 1, []) is None
    assert not fs.path(tmp_path).exists()
    mk = lambda t: findings.Finding.from_dict(_rec("F-1", t, "code-review"))  # noqa: E731
    fs.write_kind(tmp_path, "code-review", 1, [mk("r1")])
    fs.write_kind(tmp_path, "code-review", 2, [mk("r2")])
    fs.write_kind(tmp_path, "code-review", 2, [mk("r2b")])
    got = fs.read(tmp_path, kind="code-review")[0]
    assert [(f.round, f.title) for f in got] == [(1, "r1"), (2, "r2b")]
    assert all(f.kind == "code-review" for f in got)
    fs.write_kind(tmp_path, "code-review", 1, [])          # clears r1, keeps r2b
    assert [f.title for f in fs.read(tmp_path)[0]] == ["r2b"]


def test_store_malformed_findings_json_reads_empty_with_a_note(tmp_path):
    import findings_store as fs
    (tmp_path / "findings.json").write_text("{not json", encoding="utf-8")
    items, notes = fs.read(tmp_path)
    assert items == [] and len(notes) == 1 and "findings.json" in notes[0]


def test_readers_accept_old_and_new_layout(tmp_path, monkeypatch, capsys):
    import findings_store as fs
    import handback
    import task_brief
    tdir = _seed(tmp_path, monkeypatch)

    # ---- new layout: one findings.json, kinds mixed, same id in two kinds
    _w(tdir / "findings.json", [
        _rec("F-1", "new-spec", "spec-review", ref="step-2", rule="infidelity"),
        _rec("F-1", "new-tp", "test-plan-review", ref="AC-2", rule="uncovered-ac"),
        _rec("F-1", "new-impl", "impl-plan-review", ref="step-1", rule="missing-step"),
        _rec("F-1", "new-code", "code-review", ref="step-2", rnd=2),
    ])
    got = [d["title"] for d in task_brief.step_findings(_KEY, 2)]
    assert got == ["new-spec", "new-tp"]                   # code-review is not a brief kind
    items, notes = handback.load_ticket_findings(tdir)
    assert notes == [] and len(items) == 4
    assert handback.pool_main(["--ticket", _KEY]) == 0
    pool = json.loads((tdir / "review" / "findings-pool.json").read_text())
    assert pool["raw_count"] == 1                          # review kinds only: the code-review one

    # ---- old layout, findings.json absent: read-only fallback
    (tdir / "findings.json").unlink()
    (tdir / "review" / "findings-pool.json").unlink()
    _w(tdir / "spec-review-findings.json", [_rec("F-1", "old-spec", "spec", ref="step-2", rule="infidelity")])
    _w(tdir / "test-plan-review-findings.json",
       [_rec("F-1", "old-tp", "test-plan", ref="AC-2", rule="uncovered-ac")])
    _w(tdir / "review" / "code-review-findings.json", [_rec("F-1", "old-code", "code-review")])
    got = [d["title"] for d in task_brief.step_findings(_KEY, 2)]
    assert got == ["old-spec", "old-tp"]
    items, notes = handback.load_ticket_findings(tdir)
    assert {f.title for f in items} >= {"old-spec", "old-tp", "old-code"}
    assert [f.title for f in fs.read(tdir, kind="code-review")[0]] == ["old-code"]
    assert handback.pool_main(["--ticket", _KEY]) == 0
    assert not fs.path(tdir).exists()                      # legacy is never rewritten


def test_load_ticket_findings_validates_per_kind_round_group(tmp_path):
    """Same id in two kinds is not a duplicate; a bad record yields a note, not a crash."""
    import handback
    _w(tmp_path / "findings.json", [
        _rec("F-1", "a", "code-review", rnd=1), _rec("F-1", "a2", "code-review", rnd=2),
        _rec("F-1", "s", "spec-review", rule="not a slug")])
    items, notes = handback.load_ticket_findings(tmp_path, all_rounds=True)
    assert {f.title for f in items} == {"a", "a2"}
    assert len(notes) == 1 and "spec-review" in notes[0]


def test_rollup_pool_rate_still_read_for_legacy_ticket(tmp_path):
    import metrics
    pool = {"raw_count": 4, "pooled_count": 2, "duplicate_rate": 0.5}
    _w(tmp_path / "review" / "findings-pool.json", pool)
    assert metrics._pool_duplicate_rate(tmp_path) == (0.5, 4)


# ---------------------------------------------------------------------------
# step-2: every writer appends to findings.json (AC-1, AC-2, AC-3)
# ---------------------------------------------------------------------------

def _verdict_md(findings):
    doc = {"findings": findings, "decisions_to_confirm": []}
    return "narrative\n\n```json\n" + json.dumps(doc) + "\n```\n"


def _spec_finding(fid="F-1", title="t"):
    return {"id": fid, "rule_name": "infidelity", "severity": "HIGH", "file": "spec.md",
            "line": None, "title": title, "body": "b", "ref": "AC-1"}


_OLD_FILES = ("spec-review-findings.json", "test-plan-review-findings.json",
              "impl-plan-review-findings.json", "drift-review-findings.json")


def _all_files(root: Path):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_consume_appends_to_findings_json_and_writes_no_kind_file(tmp_path):
    import findings_store as fs
    import spec_review as sr
    import testplan_review as tp
    import implplan_review as ip
    import drift_review as dr
    kinds = [sr.SPEC_REVIEW, tp.TEST_PLAN_REVIEW, ip.IMPL_PLAN_REVIEW, dr.DRIFT_CHECK]
    # probe: nothing written
    (tmp_path / sr.SPEC_REVIEW.output_file).write_text(_verdict_md([_spec_finding()]), "utf-8")
    sr.consume(tmp_path, "M", persist=False)
    assert not fs.path(tmp_path).exists()
    # empty verdict: no file
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / sr.SPEC_REVIEW.output_file).write_text(_verdict_md([]), "utf-8")
    sr.consume(tmp_path / "empty", "M")
    assert not fs.path(tmp_path / "empty").exists()
    # each kind through the one seam
    for k in kinds:
        cat = k.finding_categories[0]
        f = {**_spec_finding(title=f"from-{k.name}"), "rule_name": cat}
        (tmp_path / k.output_file).write_text(_verdict_md([f]), "utf-8")
        sr.consume(tmp_path, "M", kind=k)
    rows = json.loads(fs.path(tmp_path).read_text("utf-8"))
    assert sorted(r["kind"] for r in rows) == ["drift-review", "impl-plan-review",
                                               "spec-review", "test-plan-review"]
    assert all(r["round"] == 1 for r in rows)
    assert not any((tmp_path / n).exists() for n in _OLD_FILES)
    # re-consume of one kind replaces only its own records
    (tmp_path / sr.SPEC_REVIEW.output_file).write_text(_verdict_md([_spec_finding(title="again")]), "utf-8")
    sr.consume(tmp_path, "M")
    got = fs.read(tmp_path)[0]
    assert len(got) == 4 and [f.title for f in got if f.kind == "spec-review"] == ["again"]
    # the store reads back through the handback loader
    import handback
    items, notes = handback.load_ticket_findings(tmp_path)
    assert notes == [] and len(items) == 4


def _plan(tdir, sha, rnd=None):
    d = {"diff_sha256": sha, "passes": []}
    if rnd is not None:
        d["round"] = rnd
    out = tdir / "review" / f"review-plan-r{rnd or 1}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d), "utf-8")


def _verdict_file(tmp_path, kind, title):
    rule = "readability"
    f = {"id": "F-1", "rule_name": rule, "severity": "HIGH", "file": "f.py", "line": 5,
         "title": title, "body": "b", "fix": None}
    p = tmp_path / f"v-{title}.json"
    p.write_text(json.dumps({"findings": [f], "decisions_to_confirm": []}), "utf-8")
    return p


def _take_ticket(tmp_path, monkeypatch):
    """take() only accepts a real intake key (digits), so use KLC-991 here."""
    tdir = tmp_path / ".klc" / "tickets" / "KLC-991"
    tdir.mkdir(parents=True)
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _meta(tdir)
    return tdir


def _meta(tdir):
    (tdir / "meta.json").write_text(json.dumps(
        {"ticket": tdir.name, "kind": "tech", "phase": "build:work", "phase_history": [],
         "track": "M"}), "utf-8")


def test_take_and_headless_write_only_findings_json(tmp_path, monkeypatch):
    import findings
    import findings_store as fs
    import handback
    tdir = _take_ticket(tmp_path, monkeypatch)
    monkeypatch.setattr(handback, "_run_planner", lambda t: False)
    monkeypatch.setattr(handback, "_current_diff_sha", lambda t: "A" * 64)
    _plan(tdir, "A" * 64, 1)                                 # review.py plans before it pools
    for kind in ("code-review", "external-review"):
        assert handback.take(kind, _TKEY, _verdict_file(tmp_path, kind, f"t-{kind}")) == 0
    hl = [findings.Finding.from_dict({**_rec("F-9", "hl", "code-review", reviewer="security",
                                             rule="ssrf")})]
    assert handback.write_headless_findings(_TKEY, hl) == fs.path(tdir)
    got = fs.read(tdir)[0]
    assert sorted((f.kind, f.reviewer, f.round) for f in got) == [
        ("code-review", "code-review", 1), ("code-review", "security", 1),
        ("external-review", "external-review", 1)]
    names = _all_files(tdir)
    assert not any(n.endswith("-findings.json") and n != "findings.json" for n in names), names
    assert "review/headless-findings.json" not in names
    # a headless rerun replaces only the headless records, never the take
    handback.write_headless_findings(_TKEY, [])
    assert sorted(f.reviewer for f in fs.read(tdir)[0]) == ["code-review", "external-review"]
    # an empty headless run on a fresh ticket creates no file
    t2 = tmp_path / ".klc" / "tickets" / "KLC-992"
    t2.mkdir()
    assert handback.write_headless_findings("KLC-992", []) is None
    assert not fs.path(t2).exists()


def test_second_round_take_preserves_round_one(tmp_path, monkeypatch):
    import findings_store as fs
    import handback
    tdir = _take_ticket(tmp_path, monkeypatch)
    monkeypatch.setattr(handback, "_run_planner", lambda t: False)
    sha = {"v": "A" * 64}
    monkeypatch.setattr(handback, "_current_diff_sha", lambda t: sha["v"])
    take = lambda title: handback.take("code-review", _TKEY,  # noqa: E731
                                       _verdict_file(tmp_path, "code-review", title))
    assert take("r1") == 0                                   # no plan yet: round 1
    _plan(tdir, "A" * 64, 1)
    sha["v"] = "B" * 64                                      # the diff changed
    assert take("r2") == 0
    assert [(f.round, f.title) for f in fs.read(tdir, kind="code-review")[0]] == [(1, "r1"), (2, "r2")]
    sha["v"] = "A" * 64                                      # retake on diff A: only round 1 is replaced
    assert take("r1b") == 0
    assert [(f.round, f.title) for f in fs.read(tdir, kind="code-review")[0]] == [(2, "r2"), (1, "r1b")]
    # no diff can be had at all: next round, never over an earlier one
    monkeypatch.setattr(handback, "_current_diff_sha", lambda t: None)
    assert take("r3") == 0
    assert sorted(f.round for f in fs.read(tdir, kind="code-review")[0]) == [1, 2, 3]


def test_take_refuses_when_the_store_is_unreadable_and_keeps_it(tmp_path, monkeypatch):
    import handback
    tdir = _take_ticket(tmp_path, monkeypatch)
    monkeypatch.setattr(handback, "_run_planner", lambda t: False)
    (tdir / "findings.json").write_text("{broken", "utf-8")
    assert handback.take("code-review", _TKEY, _verdict_file(tmp_path, "code-review", "x")) == 1
    assert (tdir / "findings.json").read_text("utf-8") == "{broken"
