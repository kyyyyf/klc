"""tests/test_handback_take.py — KLC-127 step-3: `handback.py take` validates,
stores and counts every review hand-back (AC-5, AC-6, AC-7).

Hermetic: PROJECT_ROOT points at a tmp project for every test; `handback.
_run_planner` is stubbed (autouse) so no test here launches a subprocess or
runs git. AC-8 (the real planner invocation) is covered in
tests/integration/test_klc127_handback_planning.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

import handback  # noqa: E402
import metrics  # noqa: E402
import review_plan  # noqa: E402

TICKET = "KLC-990"


def _seed_ticket(tmp_path: Path, *, track: str = "M") -> tuple[Path, Path]:
    project_root = tmp_path / "proj"
    tdir = project_root / ".klc" / "tickets" / TICKET
    tdir.mkdir(parents=True)
    meta = {
        "ticket": TICKET, "kind": "tech", "kind_source": "user",
        "phase": "build:work", "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "spec.md").write_text("spec\n", encoding="utf-8")
    return project_root, tdir


@pytest.fixture(autouse=True)
def _project(tmp_path, monkeypatch):
    project_root, tdir = _seed_ticket(tmp_path)
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: False)
    return tdir


def _rule_name_for(kind: str) -> str:
    spec = handback.KINDS[kind]
    return spec.rule_names[0] if spec.rule_names else "readability"


def _finding(*, kind: str = "code-review", **overrides) -> dict:
    d = {"id": "F-1", "rule_name": _rule_name_for(kind), "severity": "HIGH", "file": "f.py",
         "line": 5, "title": "a title", "body": "a body", "fix": None}
    d.update(overrides)
    return d


def _verdict(findings=None, decisions=None) -> dict:
    return {"findings": [] if findings is None else findings,
           "decisions_to_confirm": [] if decisions is None else decisions}


def _write_verdict(path: Path, doc: dict) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _meta(tdir: Path) -> dict:
    return json.loads((tdir / "meta.json").read_text(encoding="utf-8"))


def _tagged_attempts(tdir: Path) -> list[dict]:
    meta = _meta(tdir)
    return [rec for _phase, rec in metrics.iter_attempts(meta, TICKET) if rec.get("reviewer")]


# --- hostile cases -------------------------------------------------------------

@pytest.mark.parametrize("kind,doc", [
    ("code-review", {"findings": [{"severity": "HIGH", "file": "f.py", "line": 5,
                                   "title": "t", "body": "an old in-client entry"}]}),
    ("spec", {"findings": [{"category": "infidelity", "severity": "high",
                           "detail": "old shape"}]}),
])
def test_take_writes_nothing_and_exits_1_on_any_schema_error(tmp_path, kind, doc):
    """AC-5, refined by step-12/F-2: any schema error refuses, writes
    nothing at the kind's own stored path, and exits 1 — AC-5's 'writes
    nothing' now means nothing at the kind's own findings path; the raw
    answer is deliberately kept at review/<kind>-rejected-<ts>.txt (below)
    so a retry after a schema fix has something to resubmit, never lost."""
    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    rc = handback.take(kind, TICKET, vfile)
    assert rc == 1
    spec = handback.KINDS[kind]
    if spec.stored:
        assert not (tdir / spec.stored).exists()


@pytest.mark.parametrize("case", ["missing", "permission", "bad-utf8"])
def test_take_fails_closed_on_an_unreadable_verdict_file(tmp_path, monkeypatch, case):
    """AC-5: an unreadable verdict file (missing, permission error, invalid
    UTF-8) refuses rather than raising."""
    vfile = tmp_path / "verdict.json"
    if case == "missing":
        pass
    elif case == "permission":
        vfile.write_text("{}", encoding="utf-8")
        orig = Path.read_bytes

        def _boom(self):
            if self == vfile:
                raise PermissionError("no access")
            return orig(self)
        monkeypatch.setattr(Path, "read_bytes", _boom)
    else:
        vfile.write_bytes(b"\xff\xfe\x00not-utf8")
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 1


def test_take_strips_a_utf8_bom_and_parses(tmp_path):
    """AC-5/D-107: a UTF-8 BOM before the verdict JSON is stripped, not fatal."""
    vfile = tmp_path / "verdict.json"
    vfile.write_bytes(b"\xef\xbb\xbf" + json.dumps(_verdict()).encode("utf-8"))
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 0


@pytest.mark.parametrize("text", [
    "just some prose, no JSON at all",
    '```json\n{"findings": [1, 2,]}\n```',
    '```json\n{"findings": ["unterminated\n```',
    '```json\n{"phase": "review", "signal": "done"}\n```',
])
def test_take_fails_closed_on_no_parseable_json_block(tmp_path, text):
    """AC-5: prose only, invalid JSON, or a completion-signal-only block all
    refuse — none is a parseable verdict."""
    vfile = tmp_path / "verdict.json"
    vfile.write_text(text, encoding="utf-8")
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 1


def test_take_tolerates_unexpected_extra_top_level_keys(tmp_path):
    """AC-5/D-107: an extra unrecognized top-level key is tolerated."""
    doc = _verdict()
    doc["some_extra_key"] = "whatever"
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 0


def test_take_handles_a_2mb_body_within_the_timeout(tmp_path):
    """AC-5: the schema has no length cap — a 2 MB body is accepted, fast."""
    big_body = "x" * (2 * 1024 * 1024)
    doc = _verdict(findings=[_finding(body=big_body)])
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    start = time.monotonic()
    rc = handback.take("code-review", TICKET, vfile)
    elapsed = time.monotonic() - start
    assert rc == 0
    assert elapsed < 10


def test_take_rejects_an_unknown_kind_with_exit_1(tmp_path):
    """AC-5: an unknown kind refuses with exit 1."""
    vfile = _write_verdict(tmp_path / "verdict.json", _verdict())
    rc = handback.take("not-a-kind", TICKET, vfile)
    assert rc == 1


def test_take_rejected_verdict_records_no_pass_and_runs_no_planner(tmp_path, monkeypatch):
    """AC-5/AC-7: a rejected verdict of a review kind records no pass and
    never touches the planner."""
    calls = []
    monkeypatch.setattr(handback, "_run_planner", lambda ticket: calls.append(ticket) or False)
    doc = {"findings": [{"id": "", "rule_name": "x", "severity": "HIGH"}]}  # old in-client shape
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    rc = handback.take("drift", TICKET, vfile)
    assert rc == 1
    assert calls == []
    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    assert not (tdir / "review-plan.json").exists()


# --- the storing path -----------------------------------------------------------

@pytest.mark.parametrize("kind", ["code-review", "external-review"])
def test_take_stores_findings_as_finding_dicts_with_reviewer_and_kind_stamped(tmp_path, kind):
    """AC-6: a valid code-review/external-review verdict is stored as Finding
    dicts at review/<kind>-findings.json, reviewer and kind stamped."""
    doc = _verdict(findings=[_finding(id="F-1"), _finding(id="F-2", line=9)])
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    rc = handback.take(kind, TICKET, vfile)
    assert rc == 0
    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    stored = json.loads((tdir / "review" / f"{kind}-findings.json").read_text(encoding="utf-8"))
    assert len(stored) == 2
    for rec in stored:
        assert rec["reviewer"] == kind
        assert rec["kind"] == kind
        assert rec["issue_id"]


@pytest.mark.parametrize("kind", ["spec", "test-plan", "impl-plan", "drift"])
def test_take_writes_no_file_at_all_for_the_four_independent_kinds(tmp_path, kind):
    """AC-6: a valid verdict of the four independent kinds writes no findings
    file at all."""
    doc = _verdict(findings=[_finding(kind=kind)])
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    rc = handback.take(kind, TICKET, vfile)
    assert rc == 0
    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    assert not (tdir / "review").exists()


def test_take_derives_the_target_path_from_kind_alone(tmp_path):
    """AC-6: the target path is derived from --kind alone."""
    doc = _verdict(findings=[_finding()])
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 0
    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    assert (tdir / "review" / "code-review-findings.json").is_file()


def test_take_overwrites_the_previous_intake_latest_wins(tmp_path):
    """AC-6: taking a second verdict overwrites the first — latest wins."""
    doc1 = _verdict(findings=[_finding(id="F-1", title="first")])
    vfile1 = _write_verdict(tmp_path / "v1.json", doc1)
    assert handback.take("code-review", TICKET, vfile1) == 0

    doc2 = _verdict(findings=[_finding(id="F-2", title="second")])
    vfile2 = _write_verdict(tmp_path / "v2.json", doc2)
    assert handback.take("code-review", TICKET, vfile2) == 0

    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    stored = json.loads((tdir / "review" / "code-review-findings.json").read_text(encoding="utf-8"))
    assert len(stored) == 1
    assert stored[0]["title"] == "second"


def test_take_stores_an_empty_findings_list_as_an_empty_json_list(tmp_path):
    """AC-6: an empty findings list is stored as an empty JSON list."""
    vfile = _write_verdict(tmp_path / "verdict.json", _verdict())
    rc = handback.take("code-review", TICKET, vfile)
    assert rc == 0
    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    stored = json.loads((tdir / "review" / "code-review-findings.json").read_text(encoding="utf-8"))
    assert stored == []


# --- counting the pass ----------------------------------------------------------

@pytest.mark.parametrize("kind,plan_reviewer", [
    ("code-review", "code-review"),
    ("external-review", "external"),
    ("drift", "drift"),
])
def test_take_records_exactly_one_reviewer_tagged_pass_through_record_pass(
        tmp_path, kind, plan_reviewer):
    """AC-7: a valid code-review/external-review/drift verdict records
    exactly one reviewer-tagged pass when the ticket's plan lists it."""
    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    plan = review_plan.build_plan(
        ticket=TICKET, track="M", path="job", diff_sha256="abc123", cap=None,
        override=False,
        passes=[review_plan.pass_entry(plan_reviewer, "manifest-always", "auto",
                                       None, None, "planned")])
    review_plan.write_plan(TICKET, plan)

    doc = _verdict(findings=[_finding(kind=kind)])
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    rc = handback.take(kind, TICKET, vfile)
    assert rc == 0

    stored_plan = json.loads((tdir / "review-plan.json").read_text(encoding="utf-8"))
    entry = next(p for p in stored_plan["passes"] if p["reviewer"] == plan_reviewer)
    assert entry["status"] == "executed"

    tagged = _tagged_attempts(tdir)
    assert len(tagged) == 1
    assert tagged[0]["reviewer"] == plan_reviewer


@pytest.mark.parametrize("kind", ["spec", "test-plan", "impl-plan"])
def test_take_records_no_pass_for_spec_test_plan_and_impl_plan(tmp_path, kind):
    """AC-7: spec/test-plan/impl-plan verdicts never record a pass (they have
    no plan_reviewer) and never touch the planner."""
    doc = _verdict(findings=[_finding(kind=kind)])
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    rc = handback.take(kind, TICKET, vfile)
    assert rc == 0
    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    assert not (tdir / "review-plan.json").exists()
    assert _tagged_attempts(tdir) == []


def test_take_twice_with_the_same_verdict_records_one_attempt(tmp_path):
    """AC-7/D-120-10: taking the same verdict twice records one attempt, not
    two (the pass is already `executed` on the second call)."""
    tdir = tmp_path / "proj" / ".klc" / "tickets" / TICKET
    plan = review_plan.build_plan(
        ticket=TICKET, track="M", path="job", diff_sha256="abc123", cap=None,
        override=False,
        passes=[review_plan.pass_entry("code-review", "manifest-always", "auto",
                                       None, None, "planned")])
    review_plan.write_plan(TICKET, plan)

    doc = _verdict(findings=[_finding()])
    vfile = _write_verdict(tmp_path / "verdict.json", doc)
    assert handback.take("code-review", TICKET, vfile) == 0
    assert handback.take("code-review", TICKET, vfile) == 0

    assert len(_tagged_attempts(tdir)) == 1
