"""KLC-176 step-6: review round 1 fixes (F-001 .. F-014)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_FW = Path(__file__).resolve().parents[2]
for _p in (str(_FW), str(_FW / "core" / "skills"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lifecycle  # noqa: E402
import metrics as _metrics  # noqa: E402
import retrieval_eval as _reval  # noqa: E402
import spec_selfreview  # noqa: E402
import state_sync  # noqa: E402
from core.skills import phase_completion as _pc  # noqa: E402
from test_klc176_approaches_gate import _PLAN, _S_SPEC, _TWO, _ticket  # noqa: E402


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "T"),
                 ("commit.gpgsign", "false")):
        _git(root, "config", k, v)
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    return root


def _klc(project: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PROJECT_ROOT=str(project))
    return subprocess.run([sys.executable, str(_FW / "scripts" / "klc"), *args],
                          cwd=str(project), env=env, capture_output=True, text=True)


def _read(rel: str) -> str:
    return (_FW / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------- F-001
def test_derived_untrack_never_matches_archived_ticket_files(tmp_path):
    repo = _repo(tmp_path / "state")
    names = ["tickets/KLC-1/retrieval_trace.json", "tickets/KLC-2/build/step-1-brief.md",
             "tickets/KLC-2/build/step-1-impl-report.md", "tickets/KLC-2/build/step-1-review.md",
             "tickets/KLC-2/build/step-1-findings.json", "tickets/KLC-2/build/step-1-fix-brief.md"]
    for n in names:
        f = repo / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    hit = _git(repo, "ls-files", "--", *state_sync.derived_untrack_pathspecs())
    for n in names:
        assert n not in hit.splitlines(), n
    ignores = " ".join(state_sync._DERIVED_IGNORES)
    assert "retrieval_trace" not in ignores and "step-*" not in ignores


# ---------------------------------------------------------------- F-002
def test_consume_stages_three_field_record(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    trace = {"status": "ok", "confidence": "high", "files_likely_to_edit": ["a.py"],
             "files_to_read_first": [], "tests_to_read_or_run": [],
             "affected_modules_hint": []}
    lifecycle._meta_patches.pop("KLC-950", None)
    _reval.consume("KLC-950", trace, set(), {"a.py"}, "M", persist=True)
    staged = lifecycle._meta_patches.pop("KLC-950")["metrics"]["retrieval"]
    assert set(staged) == {"score", "confidence", "at"}
    assert staged["confidence"] == "high" and staged["score"] == 1.0
    _reval.consume("KLC-951", trace, set(), {"a.py"}, "M", persist=False)
    assert "KLC-951" not in lifecycle._meta_patches


def test_rollup_reads_meta_first_then_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    compact = {"score": 0.4, "confidence": "medium", "at": "2026-10-05T00:00:00Z"}
    rec = _metrics._retrieval_record({"ticket": "KLC-952", "metrics": {"retrieval": compact}})
    assert rec["confidence"] == "medium"
    assert rec["files_likely_to_edit"]["precision"] == 0.4 and rec["status"] == "ok"
    # a compact record without a score reads as unavailable, never as a zero
    rec = _metrics._retrieval_record({"ticket": "KLC-953", "metrics": {"retrieval": {
        "score": None, "confidence": "low", "at": "x"}}})
    assert rec["status"] == "unavailable"
    # nothing in meta: fall back to the jsonl row
    _reval.append_log("KLC-954", "M", {"status": "ok", "confidence": "low"})
    assert _metrics._retrieval_record({"ticket": "KLC-954"})["confidence"] == "low"


def test_log_docstrings_state_the_current_truth():
    assert "not a source of truth" not in (_reval.read_log.__doc__ or "")
    assert "authoritative record is the per-ticket one" not in (_reval.append_log.__doc__ or "")


# ---------------------------------------------------------------- F-003
@pytest.mark.parametrize("root", ["core/agents", "klc-plugin/agents"])
def test_prompts_do_not_touch_dropped_meta_keys(root):
    assert "blast_radius" not in _read(f"{root}/discovery.md")
    triage = _read(f"{root}/intake-triage.md")
    intake = _read(f"{root}/intake.md")
    for key in ("route_signals", "mentions"):
        assert key not in triage, key
    for key in ("route_signals", "route_decision", "mentions"):
        assert key not in intake, key


def test_architecture_reviewer_does_not_name_the_retired_adr_agent():
    assert "adr --phase propose" not in _read("core/agents/review/architecture.md")


def test_discovery_reads_legacy_retro_headings():
    text = _read("core/agents/discovery.md")
    assert "What went wrong" in text and "Lessons (imperative)" in text


def test_discovery_lite_template_options_are_on_their_own_lines():
    for line in _read("core/agents/discovery-lite.md").splitlines():
        if "S only; XS skips" in line:
            assert "Option A" not in line, line


# ---------------------------------------------------------------- F-006
def test_integrate_records_branch_and_main_heads(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _repo(tmp_path)
    main_sha = _git(tmp_path, "rev-parse", "main")
    _git(tmp_path, "checkout", "-q", "-b", "feature/x")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "work")
    meta: dict = {}
    lifecycle._record_outcome(meta, "integrate", None, "")
    integ = meta["integrate"]
    assert set(integ) == {"branch_head", "main_head", "at"}
    assert integ["branch_head"] == _git(tmp_path, "rev-parse", "HEAD") != main_sha
    assert integ["main_head"] == main_sha


def test_integrate_main_head_is_null_without_main(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _repo(tmp_path)
    _git(tmp_path, "branch", "-m", "trunk")
    meta: dict = {}
    lifecycle._record_outcome(meta, "integrate", None, "")
    assert meta["integrate"]["main_head"] is None and meta["integrate"]["branch_head"]


def test_process_doc_does_not_promise_a_merge_commit():
    doc = _read("docs/process.md")
    assert "merge_sha" not in doc and "records the merge commit" not in doc
    assert "branch_head" in doc and "main_head" in doc


# ---------------------------------------------------------------- F-007
_BUG_BAD = "---\nticket: K\nkind: bug\n---\n\n## Goals\nfix\n\n## Acceptance Criteria\n- [ ] AC-1: ok\n"


def test_bug_shape_triggers_on_spec_frontmatter_kind():
    assert _pc._bug_shape_block({"kind": "unknown"}, _BUG_BAD)
    assert _pc._bug_shape_block({"kind": "bug"}, "## Goals\nx\n")
    assert not _pc._bug_shape_block({"kind": "unknown"}, "---\nkind: feature\n---\n## Goals\nx\n")
    assert not _pc._bug_shape_block({}, "## Goals\nx\n")


# ---------------------------------------------------------------- F-008
_SECT = ("## Reproduction\nr\n\n## Observed vs expected\no\n\n## Root cause\nc\n\n"
         "## Why existing tests missed it\nw\n\n## Acceptance Criteria\n")


def _bug_missing(ac: str) -> bool:
    vs = spec_selfreview.bug_shape_violations(_SECT + ac + "\n")
    return any("AC" in v["phrase"] for v in vs)


def test_regression_ac_detection():
    assert _bug_missing("- [ ] AC-1: no regression in the latest build")
    assert not _bug_missing("- [ ] AC-1: a regression test covers the crash")
    assert not _bug_missing("- [ ] AC-1: tests/test_x.py::test_crash_is_fixed fails before the fix")
    assert _bug_missing("- [ ] AC-1: test_crash_is_fixed reproduces the report")  # bare identifier (round 2)
    assert _bug_missing("- [ ] AC-1: the page renders")


def test_heading_only_bug_section_counts_as_empty():
    text = _SECT.replace("## Root cause\nc\n", "## Root cause\n### sub\n") + \
        "- [ ] AC-1: regression test\n"
    assert any("Root cause" in v["phrase"] for v in spec_selfreview.bug_shape_violations(text))


# ---------------------------------------------------------------- F-009
def test_abort_and_jump_do_not_claim_superseded_dir():
    for rel in ("core/phases/abort.py", "core/phases/jump.py"):
        text = _read(rel)
        assert "moved to _superseded/" not in text and "→ _superseded/<ts>/" not in text, rel
        assert "meta.superseded" in text, rel


# ---------------------------------------------------------------- F-012
def test_intake_writes_layout_marker(tmp_path):
    proj = _repo(tmp_path)
    r = _klc(proj, "intake", "--kind", "tech", "--no-index-refresh", "KLC-960", "fix a typo")
    assert r.returncode == 0, r.stderr
    meta = json.loads((proj / ".klc/tickets/KLC-960/meta.json").read_text("utf-8"))
    assert meta["layout"] == 2


def test_layout_marker_turns_off_legacy_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    legacy = "- Option A: a\n- Option B: b\nPicked: Option A — r\n"
    d = _ticket(tmp_path, "KLC-961", "S", _S_SPEC.format(ticket="KLC-961", approaches=""))
    (d / "options-lite.md").write_text(legacy, encoding="utf-8")
    ok, _ = _pc.can_complete_discovery_lite("KLC-961")
    assert ok                                   # pre-layout-2 ticket: fallback applies
    meta = json.loads((d / "meta.json").read_text("utf-8"))
    meta["layout"] = 2
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    ok, msg = _pc.can_complete_discovery_lite("KLC-961")
    assert not ok and "approaches" in msg.lower()


def test_layout_marker_turns_off_design_options_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = _ticket(tmp_path, "KLC-962", "M", _S_SPEC.format(ticket="KLC-962", approaches=_TWO))
    (d / "design").mkdir()
    (d / "design" / "options.md").write_text("old options\n", encoding="utf-8")
    (d / "impl-plan.md").write_text(_PLAN, encoding="utf-8")
    meta = json.loads((d / "meta.json").read_text("utf-8"))
    meta["phase"] = "design:work"
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    ok, _m = _pc.can_complete("KLC-962", "design", persist=False)
    assert ok, _m                               # legacy ticket keeps the fallback
    meta["layout"] = 2
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    ok, msg = _pc.can_complete("KLC-962", "design", persist=False)
    assert not ok and "design.md" in msg


# ---------------------------------------------------------------- F-014
def test_ack_note_lands_in_phase_history_for_any_phase(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = tmp_path / ".klc/tickets/KLC-970"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({
        "ticket": "KLC-970", "kind": "feature", "phase": "design:ack-needed", "track": "M",
        "phase_history": [{"phase": "design:ack-needed",
                           "started_at": "2026-10-01T00:00:00Z"}]}), encoding="utf-8")
    lifecycle.apply_ack("KLC-970", 1, "operator says go")
    meta = json.loads((d / "meta.json").read_text("utf-8"))
    ack = [e for e in meta["phase_history"] if e.get("event") == "ack"][-1]
    assert ack["note"] == "operator says go"


def test_regenerated_trace_is_labelled_replayed(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    d = tmp_path / ".klc/tickets/KLC-971"
    d.mkdir(parents=True)
    (d / "raw.md").write_text("raw\n", encoding="utf-8")

    class _PE:
        @staticmethod
        def rescore_trace(tdir, idx):
            return {"status": "ok", "confidence": "low"}

    monkeypatch.setattr(_reval, "load_planning_eval", lambda: _PE)
    assert _reval.read_trace("KLC-971")["source"] == "replayed"


def test_e2e_pipeline_no_longer_writes_dropped_files():
    text = _read("tests/e2e_pipeline.py")
    assert "integrate.md" not in text and "manual-checklist.md" not in text


# ---------------------------------------------------------------- round 2 (R2-001)
@pytest.mark.parametrize("root", ["core/agents", "klc-plugin/agents", "klc-plugin/skills"])
def test_no_prompt_names_adr_phase_handoff(root):
    for p in (_FW / root).rglob("*.md"):
        assert "adr --phase" not in p.read_text(encoding="utf-8"), str(p)
