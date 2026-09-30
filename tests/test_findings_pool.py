"""tests/test_findings_pool.py — KLC-127 step-8: `findings.py pool` writes one
pool per ticket (AC-17).

`findings.build_pool` computes `raw_count`/`pooled_count`/`duplicate_rate`
over the REVIEW kinds only (code-review, external-review, drift) while
pooling every kind's findings; `handback.load_ticket_findings` reads every
stored findings file of a ticket directory (and, for an independent kind
without a derived JSON, its `.md` verdict read-only), stamping `reviewer`/
`kind` from context when a stored record lacks them.

Fail-closed/skip-with-note cases come first (impl-plan.md step-8's own RED
order). Hermetic: every test but the import-isolation one works on a plain
tmp_path directory, with no PROJECT_ROOT/CLI/subprocess/git involved.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = _FW_ROOT / "core" / "skills"
sys.path.insert(0, str(_SKILLS))

import findings  # noqa: E402
import handback  # noqa: E402
from findings import Finding  # noqa: E402


def _f(**overrides):
    kwargs = dict(rule_name="rule-x", severity="MEDIUM", file="f.py", line=1,
                  title="t", body="b", fix=None, reviewer="code-review",
                  id="", kind="code-review", ref="", ac="")
    kwargs.update(overrides)
    return Finding(kwargs["rule_name"], kwargs["severity"], kwargs["file"],
                   kwargs["line"], kwargs["title"], kwargs["body"], kwargs["fix"],
                   kwargs["reviewer"], kwargs["id"], kwargs["kind"], kwargs["ref"],
                   kwargs["ac"])


def _stored(**overrides):
    base = dict(id="F-1", rule_name="legacy-unclassified", severity="MEDIUM",
                file="f.py", line=10, title="t", body="b", fix=None,
                reviewer="code-review", kind="code-review", ref="", ac="")
    base.update(overrides)
    return base


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ----------------------------- fail-closed / skip-with-note first -----------

def test_pool_writes_raw_pooled_and_null_duplicate_rate_when_raw_count_is_zero():
    """AC-17: raw_count 0 -> duplicate_rate is JSON null, never the number 0."""
    pool = findings.build_pool([], ticket="KLC-991", min_similarity=0.15)
    assert pool["raw_count"] == 0
    assert pool["pooled_count"] == 0
    assert pool["duplicate_rate"] is None


def test_pool_skips_an_old_shape_stored_file_with_one_note_and_exit_0(tmp_path):
    """AC-17: an old-shape stored findings file is skipped with one note, not
    a crash — the pool keeps going for the ticket's other kinds."""
    tdir = tmp_path / "KLC-1"
    _write_json(tdir / "review" / "code-review-findings.json",
                [{"id": "F-1", "category": "old", "detail": "d",
                  "suggested_fix": "f", "severity": "high", "ref": "AC-1"}])
    items, notes = handback.load_ticket_findings(tdir)
    assert items == []
    assert len(notes) == 1
    assert "code-review" in notes[0]


def test_pool_skips_an_unreadable_json_file_with_one_note(tmp_path):
    """AC-17: a findings file that is not valid JSON is skipped with one
    note, not a crash."""
    tdir = tmp_path / "KLC-1"
    path = tdir / "review" / "code-review-findings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    items, notes = handback.load_ticket_findings(tdir)
    assert items == []
    assert len(notes) == 1


def test_pool_counts_review_kinds_only():
    """AC-17: raw_count/pooled_count/duplicate_rate sum only the review
    kinds (code-review, external-review, drift) — a spec/test-plan/impl-plan
    finding is pooled but never counted in the numeric summary."""
    items = [
        _f(kind="spec", reviewer="spec", file="spec.md", title="a spec finding",
          body="unrelated spec text entirely"),
        _f(kind="code-review", reviewer="code-review", file="x.py",
          title="a code finding", body="unrelated code text entirely"),
    ]
    pool = findings.build_pool(items, ticket="KLC-1", min_similarity=0.15)
    assert pool["raw_count"] == 1
    assert pool["pooled_count"] == 1
    # both still appear in the pooled findings list
    assert len(pool["findings"]) == 2


def test_pool_reads_every_stored_findings_file_and_the_underived_md_for_independent_kinds(tmp_path):
    """AC-17: a stored code-review/external-review file plus a drift-review.md
    whose derived JSON does not exist yet — the pool reads the drift findings
    from the .md read-only, and never writes drift-review-findings.json."""
    tdir = tmp_path / "KLC-1"
    _write_json(tdir / "review" / "code-review-findings.json",
               [_stored(id="F-1", reviewer="code-review", kind="code-review")])
    _write_json(tdir / "review" / "external-review-findings.json",
               [_stored(id="F-1", reviewer="external-review", kind="external-review")])
    drift_md = tdir / "drift-review.md"
    drift_md.parent.mkdir(parents=True, exist_ok=True)
    drift_md.write_text(
        "Some narrative.\n\n```json\n"
        '{"findings": [{"id": "F-1", "rule_name": "spec-drift", '
        '"severity": "HIGH", "file": "spec.md", "line": 5, '
        '"title": "a drift finding", "body": "drifts from the decision", '
        '"fix": null, "ref": "AC-1"}], "decisions_to_confirm": []}'
        "\n```\n", encoding="utf-8")
    items, notes = handback.load_ticket_findings(tdir)
    kinds_seen = {f.kind for f in items}
    assert "drift" in kinds_seen
    drift_items = [f for f in items if f.kind == "drift"]
    assert len(drift_items) == 1
    assert drift_items[0].reviewer == "drift"
    assert not (tdir / "drift-review-findings.json").exists()


def test_pool_includes_review_headless_findings(tmp_path):
    """AC-17/D-111/D-118: review/headless-findings.json's stamped, validated
    findings (reviewer values such as 'architecture', kind 'code-review')
    are included and pass validate_findings('code-review', ...)."""
    tdir = tmp_path / "KLC-1"
    entry = _stored(id="F-1", reviewer="architecture", kind="code-review",
                    rule_name="legacy-unclassified")
    _write_json(tdir / "review" / "headless-findings.json", [entry])
    assert handback.validate_findings("code-review", [entry]) == []
    items, notes = handback.load_ticket_findings(tdir)
    headless = [f for f in items if f.reviewer == "architecture"]
    assert len(headless) == 1
    assert headless[0].kind == "code-review"


def test_load_ticket_findings_stamps_reviewer_and_kind_from_the_path_when_absent(tmp_path):
    """AC-17/D-110: a stored record that lacks reviewer/kind (older data) is
    stamped from the file's own kind, not left blank."""
    tdir = tmp_path / "KLC-1"
    record = {"id": "F-1", "rule_name": "legacy-unclassified", "severity": "MEDIUM",
             "file": "f.py", "line": 10, "title": "t", "body": "b", "fix": None}
    _write_json(tdir / "review" / "code-review-findings.json", [record])
    items, notes = handback.load_ticket_findings(tdir)
    assert len(items) == 1
    assert items[0].reviewer == "code-review"
    assert items[0].kind == "code-review"


def test_pooled_entry_lists_every_contributor_title_and_body():
    """AC-17: each pooled (merged) entry carries every contributor's own
    title/body/reviewer/severity/file/line in `contributors[]`."""
    shared = "modelusage cumulative tokens accounting basis session drift"
    a = _f(file="runner.py", line=88, title="A title", body=shared,
          reviewer="code-review")
    b = _f(file="runner.py", line=90, title="B title", body=shared,
          reviewer="external-review", kind="external-review")
    pool = findings.build_pool([a, b], ticket="KLC-1", min_similarity=0.15)
    assert len(pool["findings"]) == 1
    contributors = pool["findings"][0]["contributors"]
    assert len(contributors) == 2
    titles = {c["title"] for c in contributors}
    assert titles == {"A title", "B title"}
    reviewers = {c["reviewer"] for c in contributors}
    assert reviewers == {"code-review", "external-review"}


def test_pool_prints_the_raw_to_pooled_line(tmp_path, monkeypatch, capsys):
    """AC-17: `findings.py pool` prints the "N raw -> M pooled" line."""
    project = tmp_path / "proj"
    tdir = project / ".klc" / "tickets" / "KLC-991"
    _write_json(tdir / "review" / "code-review-findings.json",
               [_stored(id="F-1"), _stored(id="F-2", title="t2", body="different text")])
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    rc = handback.pool_main(["--ticket", "KLC-991"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 raw -> 2 pooled" in out


def test_pool_import_does_not_load_handback_at_module_import():
    """AC-17 (pin — already true on main today, findings.py imports nothing
    from handback yet; the ADR requires it to STAY true once `pool` exists):
    importing findings.py alone never loads handback —
    the only findings -> handback edge is the lazy import inside the `pool`
    CLI branch. Checked in a fresh subprocess so an earlier test's import of
    handback in this same process can't hide a real violation."""
    code = ("import sys; sys.path.insert(0, %r); import findings; "
            "print('handback' in sys.modules)" % str(_SKILLS))
    proc = subprocess.run([sys.executable, "-B", "-c", code],
                         capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"
