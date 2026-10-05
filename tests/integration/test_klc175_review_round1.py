"""KLC-175 step-6: tests for the round-1 code-review fixes.

F-001 unevaluable signals plan their specialists (fail closed)
F-002 `review.py --report` renders the TICKET's review-report.md
F-003 code-review.md covers correctness and baseline security
F-004 `--diff recorded` is validated, with a live fallback; digests are bytes
F-005 the card addendum reaches a headless reviewer
F-006 narrower public-API and hot-path signals; fired signals are reported
F-007 the duplicate rate is this run's; headless bytes count adr_context
F-008 an unreadable manifest is named in the plan
F-009 review_map rules
F-010 track_thresholds and the "cheap" log are gone; depth from executed passes
F-011 stale text, cheap.md, the scratch wildcard
F-012 layer 0 after the cap check; SystemExit survives; empty range end named

Real temp repos and the real planner; only the three subprocess-backed inputs
of the cascade are replaced where a failure has to be forced."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT))
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings as findings_mod  # noqa: E402
import findings_store  # noqa: E402
import models as models_mod  # noqa: E402
import publish_github as pg  # noqa: E402
import review as rv  # noqa: E402
import review_cascade as rc  # noqa: E402
import review_layer0  # noqa: E402
import review_map  # noqa: E402
import review_plan  # noqa: E402
import review_report  # noqa: E402
import review_signals as rs  # noqa: E402
from test_klc120_review_plan import (  # noqa: E402
    _HARMLESS_DIFF, _seed_project, _stub_claude_on_path, _write_diff,
)
from test_klc175_diff_range import _review, _setup  # noqa: E402
from _klc128_fixtures import _git, _rev_parse  # noqa: E402

SPECIALISTS = ["security", "architecture", "performance", "deep-impact"]


def _diff(path: str, added: str) -> str:
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1 +1 @@\n-old\n+{added}\n")


def _env(tmp_path, monkeypatch, track="L"):
    project_root, spec = _seed_project(tmp_path, track=track)
    monkeypatch.setenv("PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)
    models_mod._reset_cache()
    return project_root, spec


def _plan(project_root: Path, n: int = 1) -> dict:
    return json.loads((project_root / ".klc" / "tickets" / "KLC-990" / "review"
                       / f"review-plan-r{n}.json").read_text(encoding="utf-8"))


def _planned(plan: dict) -> list[str]:
    return [p["reviewer"] for p in plan["passes"]
            if p["status"] in ("planned", "executed") and p["reviewer"] not in ("drift", "external")]


def _plan_only(spec, diff, *extra):
    return rv.main(["--diff", str(diff), "--spec", str(spec), "--plan-only", "--no-external", *extra])


# --- F-001 -------------------------------------------------------------------

def test_signals_are_tri_state_and_none_plans_the_specialist():
    sig = rs.signals(_diff("docs/a.md", "x"), None, {}, None, sentinel_hits=None)
    assert sig["sentinel_hit"] is None and sig["critical_tier"] is None
    assert rs.unevaluable(sig) == ["sentinel_hit", "critical_tier"]
    assert rc.specialists_for(sig) == ["security"]
    ok = rs.signals(_diff("docs/a.md", "x"), None, {}, {}, sentinel_hits=0)
    assert ok["sentinel_hit"] is False and ok["critical_tier"] is False
    assert rc.specialists_for(ok) == []


def test_failed_scanners_return_none_not_zero(tmp_path):
    diff = tmp_path / "d.patch"
    diff.write_text(_diff("src/auth/login.py", "x = 1"), encoding="utf-8")
    with patch.object(rc, "_run_skill", return_value=None):
        assert rc._get_sentinel_hits(diff) is None
        assert rc._get_file_tiers(diff) is None


def test_classifier_crash_plans_security_in_decide(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    diff = tmp_path / "d.patch"
    diff.write_text(_diff("src/auth/login.py", "x = 1"), encoding="utf-8")
    no_drift = {"planned": [], "actual": [], "drift": [], "expansion": [],
                "shared_touched": [], "unknown_files": []}
    with patch.object(rc, "_get_sentinel_hits", return_value=0), \
         patch.object(rc, "_get_file_tiers", return_value=None), \
         patch.object(rc, "_load_cascade_config", return_value={"enabled": True}), \
         patch("scope_delta.compare", return_value=no_drift):
        d = rc.decide("KLC-T9", diff)
    assert d.signals["critical_tier"] is None
    assert "security" in d.layers["layer2"]


def test_review_plans_security_when_the_classifier_fails(tmp_path, monkeypatch, capsys):
    project_root, spec = _env(tmp_path, monkeypatch)
    diff = _write_diff(tmp_path, "d.patch", _HARMLESS_DIFF)
    with patch.object(rc, "_get_file_tiers", return_value=None):
        assert _plan_only(spec, diff, "--over-cap") == 0
    plan = _plan(project_root)
    assert "security" in _planned(plan)
    sec = next(p for p in plan["passes"] if p["reviewer"] == "security")
    assert sec["planned_reason"] == "signal unevaluable"
    assert "critical_tier" in plan["signals"]["unevaluable"]
    assert any("signals unevaluable" in n and "critical_tier" in n for n in plan["notes"])
    out = capsys.readouterr().out
    assert "UNEVALUABLE" in out and "critical_tier" in out


def test_signals_raising_plans_all_specialists(tmp_path, monkeypatch, capsys):
    project_root, spec = _env(tmp_path, monkeypatch)
    diff = _write_diff(tmp_path, "d.patch", _HARMLESS_DIFF)
    with patch.object(rc, "decide", side_effect=RuntimeError("cascade down")), \
         patch.object(rs, "signals", side_effect=RuntimeError("signals down")):
        assert _plan_only(spec, diff, "--over-cap") == 0
    plan = _plan(project_root)
    assert _planned(plan) == ["code-review", *SPECIALISTS]
    assert all(p["planned_reason"] == "signal unevaluable"
               for p in plan["passes"] if p["reviewer"] in SPECIALISTS)
    assert any("ALL specialists planned" in n for n in plan["notes"])
    assert "ALL specialists planned" in capsys.readouterr().out


# --- F-002 -------------------------------------------------------------------

def _finding(fid, sev, title, kind="code-review", reviewer=None, file="src/a.py"):
    return findings_mod.Finding(rule_name="logic-error", severity=sev, file=file, line=3,
                                title=title, body="b", fix=None,
                                reviewer=reviewer or kind, id=fid, kind=kind, round=1)


def _ticket_with_findings(tmp_path, monkeypatch):
    project_root, spec = _env(tmp_path, monkeypatch, track="M")
    diff = _write_diff(tmp_path, "d.patch", _diff("db/migrations/0001.sql", "select 1;"))
    assert _plan_only(spec, diff) == 0
    tdir = project_root / ".klc" / "tickets" / "KLC-990"
    findings_store.write_kind(tdir, "code-review", 1, [
        _finding("F-001", "HIGH", "wrong condition in loop"),
        _finding("F-002", "LOW", "naming nit")])
    findings_store.write_kind(tdir, "layer0", 1, [
        _finding("L0-001", "HIGH", "layer zero says so", kind="layer0")])
    return project_root, spec, diff, tdir


def test_report_writes_the_ticket_report_with_where_to_look_and_cost_lines(
        tmp_path, monkeypatch, capsys):
    project_root, spec, diff, tdir = _ticket_with_findings(tmp_path, monkeypatch)
    rc_ = rv.main(["--report", "--spec", str(spec), "--diff", str(diff)])
    out = capsys.readouterr().out
    report = tdir / "review-report.md"
    assert report.is_file() and f"REPORT {report}" in out
    text = report.read_text(encoding="utf-8")
    assert "## Where to look" in text and "### Critical" in text
    assert "`db/migrations/0001.sql` — migration" in text
    assert re.search(r"^planned_passes: \d+$", text, re.M)
    assert re.search(r"^inlined_bytes_in_client: \d+$", text, re.M)   # plan-only recorded it
    assert re.search(r"^inlined_bytes_headless: \d+$", text, re.M)
    assert "review_duplicate_rate:" in text
    assert "wrong condition in loop" in text and "naming nit" in text
    blocking = text.split("## Blocking Issues")[1].split("## Non-blocking")[0]
    assert "wrong condition in loop" in blocking and "layer zero says so" not in blocking
    assert text.rstrip().endswith("## Verdict: CHANGES REQUESTED") and rc_ == 1
    # what publish copies is in the report
    assert "## Where to look" in pg.extract_summary(text)


def test_report_verdict_defaults_and_assessments(tmp_path, monkeypatch, capsys):
    project_root, spec, diff, tdir = _ticket_with_findings(tmp_path, monkeypatch)
    base = ["--report", "--spec", str(spec), "--diff", str(diff)]
    assert rv.main(base) == 1                                   # open HIGH: CHANGES_REQUESTED
    assess = tmp_path / "assess.json"
    assess.write_text(json.dumps([{"id": "F-001", "kind": "code-review",
                                   "disposition": "fixed"}]), encoding="utf-8")
    assert rv.main([*base, "--assessments", str(assess)]) == 0  # fixed: nothing blocks
    assert (tdir / "review-report.md").read_text(encoding="utf-8").rstrip().endswith(
        "## Verdict: APPROVED")
    assert rv.main([*base, "--verdict", "CHANGES_REQUESTED"]) == 1
    assert (tdir / "review-report.md").read_text(encoding="utf-8").rstrip().endswith(
        "## Verdict: CHANGES REQUESTED")


def test_report_depth_follows_executed_passes_and_duplicate_rate_is_this_runs(tmp_path):
    tdir = tmp_path / "KLC-X"
    tdir.mkdir()
    rows = [_finding("F-1", "MEDIUM", "same defect in the loop body").to_dict(),
            _finding("F-1", "MEDIUM", "same defect in the loop body", kind="external-review",
                     reviewer="external-review").to_dict()]
    plan = {"passes": [
        {"reviewer": "code-review", "status": "executed"},
        {"reviewer": "security", "status": "planned"}]}
    text, verdict = review_report.render(ticket="KLC-X", spec_path="s", tdir=tdir, plan=plan,
                                         rows=rows, assessments=[], where="## Where to look",
                                         verdict=None)
    assert "review_depth: L1\n" in text                         # security planned, never executed
    assert "review_duplicate_rate: 0.50" in text and verdict == "APPROVED"
    plan["passes"][1]["status"] = "executed"
    text2, _ = review_report.render(ticket="KLC-X", spec_path="s", tdir=tdir, plan=plan,
                                    rows=rows, assessments=[], where="", verdict=None)
    assert "review_depth: L1+L2" in text2


# --- F-003 -------------------------------------------------------------------

def test_code_review_prompt_covers_correctness_and_baseline_security():
    text = (FW_ROOT / "core" / "agents" / "review" / "code-review.md").read_text(encoding="utf-8")
    assert "### Correctness" in text and "### Baseline security" in text
    for word in ("injection", "path traversal", "deserialization", "shell=True", "secret",
                 "off-by-one", "data loss"):
        assert word in text, word
    assert "Do not review security here" not in text
    assert "`security-smell`" in text and "`logic-error`" in text
    assert len(text.encode("utf-8")) < 9 * 1024


# --- F-004 -------------------------------------------------------------------

def _plan_of(tdir: Path) -> dict:
    return json.loads((tdir / "review" / "review-plan-r1.json").read_text(encoding="utf-8"))


def test_recorded_range_with_a_later_fix_commit_uses_the_live_range_and_handbacks_digest(
        tmp_path, monkeypatch):
    clone, tdir, base, head = _setup(tmp_path, "KLC-971")
    (clone / "widgets" / "thing.py").write_text("a = 2\n", encoding="utf-8")
    _git(clone, "add", "widgets/thing.py")
    _git(clone, "commit", "-q", "-m", "KLC-971 fix after review")
    assert _rev_parse(clone, "HEAD") != head
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    r = _review(clone, tdir, "recorded", monkeypatch)
    assert r.returncode == 0, r.stderr
    assert "recorded range not used" in r.stdout
    assert _plan_of(tdir)["diff_sha256"] == review_plan.diff_sha_for_ticket("KLC-971")
    live = subprocess.run(["git", "diff", base, "HEAD"], cwd=str(clone), capture_output=True).stdout
    assert _plan_of(tdir)["diff_sha256"] == hashlib.sha256(live).hexdigest()


def test_crlf_and_non_utf8_diff_does_not_crash_and_digest_is_bytes(tmp_path, monkeypatch):
    clone, tdir, base, head = _setup(tmp_path, "KLC-972")
    (clone / "widgets" / "thing.py").write_bytes(b"s = 'caf\xe9'\r\nt = 1\r\n")
    _git(clone, "add", "widgets/thing.py")
    _git(clone, "commit", "-q", "-m", "KLC-972 latin-1 and CRLF")
    head2 = _rev_parse(clone, "HEAD")
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    r = _review(clone, tdir, f"{base}..{head2}", monkeypatch)
    assert r.returncode == 0, r.stderr
    raw = subprocess.run(["git", "diff", base, head2], cwd=str(clone), capture_output=True).stdout
    assert b"\r\n" in raw or b"\xe9" in raw
    assert _plan_of(tdir)["diff_sha256"] == hashlib.sha256(raw).hexdigest()


# --- F-005 -------------------------------------------------------------------

def _load_runner():
    spec = importlib.util.spec_from_file_location("klc175_r1_runner",
                                                  FW_ROOT / "scripts" / "review-runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_headless_prompt_carries_the_card_addendum(tmp_path):
    import runner
    ctx = tmp_path / "context.md"
    ctx.write_text("CTX-BODY", encoding="utf-8")
    allow = tmp_path / "allow.yml"
    allow.write_text("entries: []\n", encoding="utf-8")
    card = tmp_path / "job-architecture.md"
    rv._write_job_card(card, reviewer="architecture", prompt="core/agents/review/architecture.md",
                       context=ctx, addendum=rv._addendum("architecture", r"\.py$"),
                       partial=tmp_path / "architecture.partial.md", diff=tmp_path / "d.patch",
                       spec=tmp_path / "spec.md", allowlist=allow, adr_context=None,
                       callgraph_slice=None)
    rr = _load_runner()
    inputs = rr._build_inputs(rr._parse_job_card(card))
    assert list(inputs)[:2] == ["context", "addendum"]          # addendum follows context
    composed = runner._compose_prompt(FW_ROOT / "core/agents/review/architecture.md", inputs)
    assert r"Look only at files matching `\.py$`" in composed
    assert len(inputs["addendum"].encode("utf-8")) <= 1024


# --- F-006 -------------------------------------------------------------------

def _layer2(diff_text):
    return rc.specialists_for(rs.signals(diff_text, None, {}, {}, sentinel_hits=0))


@pytest.mark.parametrize("diff_text", [
    _diff("src/a.py", "def _private():"),
    _diff("src/a.py", "    def method(self):"),                 # nested, not top-level
    _diff("tests/test_a.py", "def test_helper():"),
    _diff("docs/notes.md", "def documented():"),
    _diff("docs/notes.md", "mark a hot line with `x  # perf:hot`"),
    _diff("src/a.py", "# perf:hot"),                            # comment-only line
    _diff("conf/app.json", "x = 1  # perf:hot"),                # not a code file
])
def test_prose_private_and_test_lines_plan_no_specialist(diff_text):
    assert _layer2(diff_text) == []


def test_public_def_and_trailing_hot_marker_still_plan_their_specialist():
    assert _layer2(_diff("src/a.py", "def helper():")) == ["architecture", "deep-impact"]
    assert _layer2(_diff("src/a.py", "class Thing:")) == ["architecture", "deep-impact"]
    assert _layer2(_diff("src/a.py", "x = 1  # perf:hot")) == ["performance"]
    assert _layer2(_diff("src/a.js", "y = 2  // perf:hot")) == ["performance"]


def test_plan_says_which_signals_fired(tmp_path, monkeypatch, capsys):
    project_root, spec = _env(tmp_path, monkeypatch)
    diff = _write_diff(tmp_path, "d.patch", _diff("src/a.py", "def helper():"))
    assert _plan_only(spec, diff, "--over-cap") == 0
    plan = _plan(project_root)
    assert "changed_public_api" in plan["signals"]["fired"]
    assert plan["signals"]["unevaluable"] == []
    assert "signals fired: " in capsys.readouterr().out


# --- F-007 -------------------------------------------------------------------

def test_duplicate_rate_is_computed_from_this_runs_lists_not_a_stale_pool(tmp_path, monkeypatch):
    project_root, _spec = _env(tmp_path, monkeypatch)
    pool = project_root / ".klc" / "tickets" / "KLC-990" / "review"
    pool.mkdir(parents=True, exist_ok=True)
    (pool / "findings-pool.json").write_text(json.dumps({"duplicate_rate": 0.9}), encoding="utf-8")
    raw = [_finding("F-1", "HIGH", "null deref in parser loop", reviewer="security"),
           _finding("F-1", "HIGH", "null deref in parser loop", reviewer="architecture"),
           _finding("F-2", "LOW", "unrelated naming remark here", reviewer="architecture",
                    file="src/b.py")]
    assert rv._run_duplicate_rate("KLC-990", raw) == "0.33"
    assert rv._run_duplicate_rate("KLC-990", raw[:1]) == "n/a"      # one reviewer: not measured
    assert rv._run_duplicate_rate("KLC-990", []) == "n/a"


def test_headless_bytes_count_adr_context_per_card(tmp_path):
    ctx = tmp_path / "context.md"
    ctx.write_bytes(b"c" * 100)
    adr = tmp_path / "adr.md"
    adr.write_bytes(b"a" * 40)
    with_adr = "Addendum: x\n- adr_context:       adr.md\n"
    without = "Addendum: y\n"
    plan: dict = {}
    rv._record_inlined_bytes(None, plan, [with_adr, without], ctx, adr)
    n = lambda t: len(t.encode())  # noqa: E731
    assert plan["inlined_bytes_headless"] == n(with_adr) + n(without) + 2 * 100 + 40
    assert plan["inlined_bytes_in_client"] == n(with_adr) + n(without) + 100 + 40


# --- F-008 -------------------------------------------------------------------

def test_unreadable_manifest_is_named_in_the_plan_and_the_output(tmp_path, monkeypatch, capsys):
    project_root, spec = _env(tmp_path, monkeypatch, track="M")
    diff = _write_diff(tmp_path, "d.patch", _HARMLESS_DIFF)
    with patch.object(rv, "_resolve_profile_field", lambda field: ""):
        assert _plan_only(spec, diff) == 0
    plan = _plan(project_root)
    assert _planned(plan) == ["code-review"]
    assert any(n.startswith("manifest unreadable:") and "specialists not planned" in n
               for n in plan["notes"])
    assert "manifest unreadable:" in capsys.readouterr().out


# --- F-009 -------------------------------------------------------------------

def _fdiff(path, added):
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(added)} @@\n" + "".join(f"+{a}\n" for a in added))


def _tdir(tmp_path):
    t = tmp_path / "KLC-995"
    t.mkdir()
    return t


def test_wontfix_rule_needs_assessments_and_uses_them(tmp_path):
    t = _tdir(tmp_path)
    (t / "review").mkdir()
    (t / "review" / "assessments.json").write_text(json.dumps([
        {"file": "src/med.py", "line": 7, "severity": "MEDIUM", "disposition": "wont-fix"}]),
        encoding="utf-8")
    d = _fdiff("src/med.py", ["m = 1"])
    cfg = {"repo_root": str(tmp_path)}
    assert review_map.build(d, t, cfg, {})["important"] == []          # the dead file is not read
    got = review_map.build(d, t, cfg, {}, assessments=[
        {"file": "src/med.py", "line": 7, "severity": "MEDIUM", "disposition": "wont-fix"}])
    assert [e["file"] for e in got["important"]] == ["src/med.py:7"]


def test_gate_rule_lists_only_files_a_layer0_finding_named(tmp_path):
    t = _tdir(tmp_path)
    findings_store.write_kind(t, "layer0", 1, [
        _finding("L0-001", "MEDIUM", "t", kind="layer0", file="tests/test_named.py")])
    d = _fdiff("tests/test_named.py", ["a = 1"]) + _fdiff("tests/test_other.py", ["b = 1"])
    tiers = review_map.build(d, t, {"repo_root": str(tmp_path)}, {})
    listed = {e["file"]: e["reason"] for e in tiers["optional"]}
    assert listed == {"tests/test_named.py": "gate"}


def test_decision_matches_whole_paths_only(tmp_path):
    t = _tdir(tmp_path)
    (t / "spec.md").write_text(
        "---\nticket: KLC-995\n---\n\n> [!DECISION D-001] owner=ek refs=src/data.py\n> why\n",
        encoding="utf-8")
    d = _fdiff("a.py", ["x = 1"]) + _fdiff("src/data.py", ["y = 1"])
    crit = {e["file"].split(":")[0] for e in
            review_map.build(d, t, {"repo_root": str(tmp_path)}, {})["critical"]}
    assert crit == {"src/data.py"}


def test_generated_files_are_never_critical_even_when_risk_tagged(tmp_path):
    t = _tdir(tmp_path)
    (t / "spec.md").write_text("---\nrisk_tags: [user-facing]\n---\n", encoding="utf-8")
    (t / "impl-plan.md").write_text(
        "## step-1 — x\n**Addresses:** AC-1\n**Affected files:** `klc-plugin/agents/x.md`\n",
        encoding="utf-8")
    tiers = review_map.build(_fdiff("klc-plugin/agents/x.md", ["g"]), t,
                             {"repo_root": str(tmp_path)}, {"klc-plugin/agents/x.md": "critical"})
    assert tiers["critical"] == [] and tiers["optional"][0]["reason"] == "generated"


def test_churn_git_log_is_limited_to_the_diffs_files(tmp_path):
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="src/a.py\n", stderr="")

    with patch.object(review_map.subprocess, "run", fake_run):
        counts = review_map._churn(str(tmp_path), ["src/a.py", "src/b.py"])
    assert counts == {"src/a.py": 1}
    assert seen[0][-3:] == ["--", "src/a.py", "src/b.py"]
    assert review_map._churn(str(tmp_path), []) == {}


# --- F-010 -------------------------------------------------------------------

def test_track_thresholds_and_the_cheap_depth_log_are_gone(tmp_path, monkeypatch, capsys):
    assert "track_thresholds" not in (FW_ROOT / "config" / "reviewers.yml").read_text(encoding="utf-8")
    assert not hasattr(rc, "_track_of")
    project_root, spec = _env(tmp_path, monkeypatch, track="M")
    diff = _write_diff(tmp_path, "d.patch", _HARMLESS_DIFF)
    assert _plan_only(spec, diff) == 0
    assert "cheap depth" not in capsys.readouterr().out


# --- F-011 -------------------------------------------------------------------

def test_stale_text_is_fixed_and_cheap_is_retired():
    assert not (FW_ROOT / "core" / "agents" / "review" / "cheap.md").exists()
    review_md = (FW_ROOT / "core" / "agents" / "review.md").read_text(encoding="utf-8")
    assert "default-on for S+" not in review_md and "default-on for L" in review_md
    script = (FW_ROOT / "scripts" / "review.py").read_text(encoding="utf-8")
    assert "default-on for S+" not in script
    arch = (FW_ROOT / "core" / "agents" / "review" / "architecture.md").read_text(encoding="utf-8")
    assert "`test_plan`" not in arch
    for name in ("architecture", "security", "performance"):
        text = (FW_ROOT / "core" / "agents" / "review" / f"{name}.md").read_text(encoding="utf-8")
        assert "`severity_rubric` input" not in text, name
        assert "config/severity-rubric.md" in text, name


def test_honesty_allowlist_has_no_scratch_wildcard():
    import prompt_honesty
    patterns = [e.pattern for e in prompt_honesty.ALLOWLIST]
    assert ".klc/scratch/*" not in patterns
    assert ".klc/scratch/<KEY>/review/context.md" in patterns
    assert prompt_honesty.scan() == []


# --- F-012 -------------------------------------------------------------------

def test_over_cap_refusal_leaves_findings_json_untouched(tmp_path, monkeypatch):
    project_root, spec = _env(tmp_path, monkeypatch, track="S")
    diff = _write_diff(tmp_path, "d.patch", _HARMLESS_DIFF)
    with patch.object(rc, "decide", side_effect=RuntimeError("down")), \
         patch.object(rs, "signals", side_effect=RuntimeError("down")):
        assert rv.main(["--diff", str(diff), "--spec", str(spec), "--plan-only",
                        "--no-external"]) == 2                # all specialists: over the S cap
    assert not (project_root / ".klc" / "tickets" / "KLC-990" / "findings.json").exists()


def test_layer0_survives_a_check_that_calls_sys_exit(tmp_path, monkeypatch):
    import scan_sentinels
    monkeypatch.setattr(scan_sentinels, "load_sentinels_config",
                        lambda *a, **k: sys.exit(1))
    diff = tmp_path / "d.patch"
    diff.write_text(_HARMLESS_DIFF, encoding="utf-8")
    out = review_layer0._check_sentinels  # the adapter itself raises SystemExit...
    with pytest.raises(SystemExit):
        out("KLC-1", diff)
    items = review_layer0.collect("KLC-1", diff)                # ...collect degrades it
    sent = [f for f in items if f.rule_name == review_layer0.UNAVAILABLE
            and "sentinels" in f.title]
    assert len(sent) == 1 and sent[0].severity == "INFO"


@pytest.mark.parametrize("arg,side", [("HEAD..", "right"), ("..HEAD", "left"),
                                      ("HEAD...", "right")])
def test_empty_range_end_is_named(tmp_path, monkeypatch, arg, side):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert rv._resolve_diff(arg, tmp_path / "out.patch") is False
    assert "range needs both ends" in rv._diff_error and f"{side} end is empty" in rv._diff_error
