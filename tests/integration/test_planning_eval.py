"""KLC-067 — planning-eval harness: real-substrate fixture tests.

Offline: builds a synthetic git repo + ticket-archive in tmp_path (same pattern
as tests/test_tdd_order.py), runs planning-eval.py, and asserts the report's
numbers against hand-computed values. No network, no LLM.

Fixture module map (modules.json):
  intake        -> core/intake/          (dir module)
  routing       -> core/routing/         (dir module)
  review        -> core/agents/review     (file-stem module)
  core/agents   -> core/agents/          (dir module)
  files override: core/common/paths.py is shared (member_of intake+routing)

Fixture repo files (for coverage):
  core/intake/parser.py       -> intake
  core/intake/validation.py   -> intake
  core/routing/router.py      -> routing
  core/agents/review.py       -> review        (file-stem beats dir)
  core/agents/review-lite.py  -> core/agents   (boundary guard: NOT review)
  core/common/paths.py        -> shared (intake, routing)
  orphan.py                   -> orphan
  => total 7, assigned 6, orphan 1, shared 1

Fixture tickets (meta.affected_modules = ground truth; diff via git log):
  TCK-1  edits parser.py + router.py (+ a .klc/ lifecycle churn file, excluded)
         truth {intake,routing}       computed {intake,routing}   P=1   R=1
  TCK-2  edits validation.py + paths.py (shared)
         truth {intake}               computed {intake,routing}   P=0.5 R=1
  TCK-3  edits review-lite.py
         truth {core/agents}          computed {core/agents}      P=1   R=1
  TCK-11 edits review.py
         truth {review}               computed {review}           P=1   R=1
  TCK-EMPTY  truth []  -> skipped (no aggregate contribution)
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _FW_ROOT / "core" / "skills" / "planning-eval.py"


# --------------------------------------------------------------------------- #
# module loader (AC-2 unit-level assertions)
# --------------------------------------------------------------------------- #
def _load_skill():
    spec = importlib.util.spec_from_file_location("planning_eval", _SKILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# git fixture helpers
# --------------------------------------------------------------------------- #
def _run(args: list[str], cwd: Path) -> str:
    r = subprocess.run(args, capture_output=True, text=True, cwd=str(cwd))
    return r.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "t@t.com"], repo)
    _run(["git", "config", "user.name", "T"], repo)
    return repo


def _commit(repo: Path, files: dict[str, str], subject: str) -> None:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _run(["git", "add", "-f", rel], repo)
    _run(["git", "commit", "-m", subject], repo)


MODULES = {
    "modules": [
        {"name": "intake", "path": "core/intake/"},
        {"name": "routing", "path": "core/routing/"},
        {"name": "review", "path": "core/agents/review"},
        {"name": "core/agents", "path": "core/agents/"},
    ],
    "files": {
        "core/common/paths.py": {
            "primary_module": None,
            "member_of": ["intake", "routing"],
        }
    },
}


def _write_meta(tickets_root: Path, key: str, affected: list[str]) -> None:
    d = tickets_root / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({"ticket": key, "affected_modules": affected}))


def _build_corpus(tmp_path: Path, with_trace: bool = False) -> dict:
    repo = _make_repo(tmp_path)

    _commit(repo, {"core/intake/parser.py": "x=1\n",
                   "core/routing/router.py": "x=2\n"},
            "TCK-1 step-1: intake + routing")
    # lifecycle churn under .klc/ must be excluded from the computed module set:
    _commit(repo, {".klc/index/note.txt": "churn\n"}, "TCK-1 step-1: lifecycle churn")
    _commit(repo, {"core/intake/validation.py": "x=3\n",
                   "core/common/paths.py": "x=4\n"},
            "TCK-2 step-1: validation + shared helper")
    _commit(repo, {"core/agents/review-lite.py": "x=5\n"},
            "TCK-3 step-1: review-lite prompt")
    _commit(repo, {"core/agents/review.py": "x=6\n"},
            "TCK-11 step-1: review agent")
    # an orphan file present for coverage but touched by no ticket:
    _commit(repo, {"orphan.py": "x=0\n"}, "chore: add orphan file")

    idx = repo / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "modules.json").write_text(json.dumps(MODULES))

    tickets_root = repo / ".klc" / "tickets"
    _write_meta(tickets_root, "TCK-1", ["intake", "routing"])
    _write_meta(tickets_root, "TCK-2", ["intake"])
    _write_meta(tickets_root, "TCK-3", ["core/agents"])
    _write_meta(tickets_root, "TCK-11", ["review"])
    _write_meta(tickets_root, "TCK-EMPTY", [])
    # non-empty ground truth but its key is in NO commit subject (squash / PR
    # merge worded differently) -> no derivable diff -> must be SKIPPED, not 0/0.
    _write_meta(tickets_root, "TCK-NODIFF", ["intake"])

    if with_trace:
        (tickets_root / "TCK-1" / "retrieval_trace.json").write_text(json.dumps({
            "status": "ok",
            "files_to_read_first": [
                "core/intake/parser.py",
                "core/routing/router.py",
                "core/intake/schema.py",
            ],
            "files_likely_to_edit": ["core/intake/parser.py"],
        }))

    return {"repo": repo, "tickets_root": tickets_root,
            "modules": idx / "modules.json"}


def _run_harness(fx: dict, out: Path, extra: list[str] | None = None,
                 env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PROJECT_ROOT"] = str(fx["repo"])
    if env_extra:
        env.update(env_extra)
    args = [sys.executable, str(_SKILL),
            "--tickets", str(fx["tickets_root"]),
            "--repo", str(fx["repo"]),
            "--modules", str(fx["modules"]),
            "--out", str(out)]
    if extra:
        args += extra
    return subprocess.run(args, capture_output=True, text=True, env=env)


def _make_stored_patch_corpus(tmp_path: Path) -> dict:
    """A valid git repo whose tickets carry a stored diff (changed_files.txt /
    *.patch) instead of git-log-derivable commits — exercises stored_patch_files."""
    repo = _make_repo(tmp_path)
    # one committed file so the repo is a non-empty git checkout (repo_ok)
    _commit(repo, {"core/intake/parser.py": "x=1\n"}, "seed: initial file")

    idx = repo / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "modules.json").write_text(json.dumps(MODULES))

    tickets_root = repo / ".klc" / "tickets"

    # ticket via changed_files.txt (one line per path, incl. a shared file)
    d1 = tickets_root / "SP-1"
    d1.mkdir(parents=True, exist_ok=True)
    (d1 / "meta.json").write_text(json.dumps({"ticket": "SP-1", "affected_modules": ["intake"]}))
    (d1 / "changed_files.txt").write_text(
        "core/intake/parser.py\ncore/common/paths.py\n")

    # ticket via a real unified-diff *.patch: an add (+++ b/) and a delete
    # (--- a/ + +++ /dev/null). The deleted path must be captured from the a/ side.
    d2 = tickets_root / "SP-2"
    d2.mkdir(parents=True, exist_ok=True)
    (d2 / "meta.json").write_text(json.dumps({"ticket": "SP-2", "affected_modules": ["routing"]}))
    (d2 / "change.patch").write_text(
        "diff --git a/core/routing/router.py b/core/routing/router.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/core/routing/router.py\n"
        "@@ -0,0 +1 @@\n"
        "+x\n"
        "diff --git a/core/agents/review.py b/core/agents/review.py\n"
        "deleted file mode 100644\n"
        "--- a/core/agents/review.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-x\n"
    )
    return {"repo": repo, "tickets_root": tickets_root, "modules": idx / "modules.json"}


def _make_classification_corpus(tmp_path: Path) -> dict:
    """Distinguishes the two empty-diff causes:
      LC-EXCLUDED — commits EXIST but touch only excluded (.klc/**) paths ->
                    source PRESENT, footprint empty -> must be SCORED (recall 0).
      LC-NOMATCH  — no commit references the key -> source ABSENT -> derivation
                    gap -> must be SKIPPED with the derivation-gap reason.
    """
    repo = _make_repo(tmp_path)
    _commit(repo, {"core/intake/parser.py": "x=1\n"}, "seed: initial source file")
    # LC-EXCLUDED's commit exists and matches the key, but touches only .klc/**:
    _commit(repo, {".klc/index/lc.txt": "churn\n"}, "LC-EXCLUDED step-1: lifecycle only")

    idx = repo / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "modules.json").write_text(json.dumps(MODULES))

    tickets_root = repo / ".klc" / "tickets"
    _write_meta(tickets_root, "LC-EXCLUDED", ["intake"])   # source present, all excluded
    _write_meta(tickets_root, "LC-NOMATCH", ["intake"])    # no matching commit at all
    return {"repo": repo, "tickets_root": tickets_root, "modules": idx / "modules.json"}


def test_source_present_all_excluded_is_scored_recall_zero(tmp_path):
    """A ticket whose commits touch ONLY excluded paths is a REAL 0-recall
    evaluation (empty footprint vs non-empty truth) — it must be SCORED, not
    hidden in tickets_skipped."""
    fx = _make_classification_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    proc = _run_harness(fx, out)
    assert proc.returncode == 0, proc.stderr
    rep = json.loads(out.read_text())
    per = {t["ticket"]: t for t in rep["diff_affected_modules"]["per_ticket"]}
    skipped = {s["ticket"] for s in rep["corpus"]["tickets_skipped"]}
    assert "LC-EXCLUDED" in per, "all-excluded ticket must be scored, not skipped"
    assert "LC-EXCLUDED" not in skipped
    assert per["LC-EXCLUDED"]["computed"] == []
    assert per["LC-EXCLUDED"]["recall"] == pytest.approx(0.0)
    assert per["LC-EXCLUDED"]["missed"] == ["intake"]


def _make_merge_only_corpus(tmp_path: Path) -> dict:
    """The ticket key appears ONLY on a --no-ff MERGE commit; the feature commits
    do not repeat it. `git log --name-only` suppresses merge diffs, so a naive
    probe marks source_present but derives no files (wrong recall-0). The
    derivation must pull the merge's first-parent diff (the files it brought in)."""
    repo = _make_repo(tmp_path)
    _commit(repo, {"core/intake/parser.py": "x=1\n"}, "seed: base file")
    base = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    _run(["git", "checkout", "-b", "feature"], repo)
    _commit(repo, {"core/routing/router.py": "x=2\n"}, "feat: add router (no ticket key here)")
    _run(["git", "checkout", base], repo)
    _run(["git", "merge", "--no-ff", "-m", "MERGE-1 step-1: integrate router feature", "feature"], repo)

    idx = repo / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "modules.json").write_text(json.dumps(MODULES))
    tickets_root = repo / ".klc" / "tickets"
    _write_meta(tickets_root, "MERGE-1", ["routing"])
    return {"repo": repo, "tickets_root": tickets_root, "modules": idx / "modules.json"}


def test_merge_only_ticket_derives_merged_files(tmp_path):
    """FIX-A: a key present only on a merge commit is scored with the merge's
    real footprint (the files it integrated), not a spurious recall-0."""
    fx = _make_merge_only_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    proc = _run_harness(fx, out)
    assert proc.returncode == 0, proc.stderr
    rep = json.loads(out.read_text())
    per = {t["ticket"]: t for t in rep["diff_affected_modules"]["per_ticket"]}
    skipped = {s["ticket"] for s in rep["corpus"]["tickets_skipped"]}
    assert "MERGE-1" in per, "merge-only ticket must be scored"
    assert "MERGE-1" not in skipped
    assert per["MERGE-1"]["computed"] == ["routing"]   # router.py brought in by the merge
    assert per["MERGE-1"]["recall"] == pytest.approx(1.0)


def test_derivation_source_and_confidence_tagging(tmp_path):
    """FIX-B: each scored ticket carries its diff-derivation source + confidence,
    and the section summarises authoritative vs best-effort counts."""
    # stored-patch corpus -> authoritative
    sp_dir = tmp_path / "sp"; sp_dir.mkdir()
    sp = _make_stored_patch_corpus(sp_dir)
    out_sp = tmp_path / "sp.json"
    _run_harness(sp, out_sp)
    dam_sp = json.loads(out_sp.read_text())["diff_affected_modules"]
    per_sp = {t["ticket"]: t for t in dam_sp["per_ticket"]}
    assert per_sp["SP-1"]["derivation_source"] == "stored-patch"
    assert per_sp["SP-1"]["derivation_confidence"] == "authoritative"
    assert dam_sp["authoritative_tickets"] >= 1
    assert "note" in dam_sp

    # git-log corpus -> best-effort
    gl_dir = tmp_path / "gl"; gl_dir.mkdir()
    gl = _build_corpus(gl_dir)
    out_gl = tmp_path / "gl.json"
    _run_harness(gl, out_gl)
    dam_gl = json.loads(out_gl.read_text())["diff_affected_modules"]
    per_gl = {t["ticket"]: t for t in dam_gl["per_ticket"]}
    assert per_gl["TCK-1"]["derivation_source"] == "git-log-grep"
    assert per_gl["TCK-1"]["derivation_confidence"] == "best-effort"
    assert dam_gl["best_effort_tickets"] >= 1


def test_source_absent_is_skipped_derivation_gap(tmp_path):
    """A ticket with no matching commits and no stored patch is a derivation
    gap: skip with the source-absent reason, do not score 0/0."""
    fx = _make_classification_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    _run_harness(fx, out)
    rep = json.loads(out.read_text())
    per = {t["ticket"] for t in rep["diff_affected_modules"]["per_ticket"]}
    skipped = {s["ticket"]: s["reason"] for s in rep["corpus"]["tickets_skipped"]}
    assert "LC-NOMATCH" not in per
    assert "LC-NOMATCH" in skipped
    assert "no matching commits" in skipped["LC-NOMATCH"]


# --------------------------------------------------------------------------- #
# AC-1: report has the pre-retriever metrics
# --------------------------------------------------------------------------- #
def test_report_has_pre_retriever_metrics(tmp_path):
    fx = _build_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    proc = _run_harness(fx, out)
    assert proc.returncode == 0, proc.stderr
    rep = json.loads(out.read_text())
    assert "coverage" in rep and "diff_affected_modules" in rep
    assert "retrieval_metrics" in rep and "errors" in rep
    cov = rep["coverage"]
    assert cov["status"] == "ok"
    assert cov["files_total"] == 7
    assert cov["files_assigned"] == 6
    assert cov["files_orphan"] == 1
    assert cov["files_shared"] == 1
    assert cov["coverage_ratio"] == pytest.approx(6 / 7)
    assert cov["orphan_rate"] == pytest.approx(1 / 7)


# --------------------------------------------------------------------------- #
# AC-5: precision / recall numbers match the fixture
# --------------------------------------------------------------------------- #
def test_precision_recall_numbers_match_fixture(tmp_path):
    fx = _build_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    proc = _run_harness(fx, out)
    assert proc.returncode == 0, proc.stderr
    dam = json.loads(out.read_text())["diff_affected_modules"]
    assert dam["status"] == "ok"
    per = {t["ticket"]: t for t in dam["per_ticket"]}

    assert per["TCK-1"]["computed"] == ["intake", "routing"]
    assert per["TCK-1"]["precision"] == pytest.approx(1.0)
    assert per["TCK-1"]["recall"] == pytest.approx(1.0)

    assert per["TCK-2"]["computed"] == ["intake", "routing"]
    assert per["TCK-2"]["precision"] == pytest.approx(0.5)
    assert per["TCK-2"]["recall"] == pytest.approx(1.0)
    assert per["TCK-2"]["extra"] == ["routing"]

    assert per["TCK-3"]["computed"] == ["core/agents"]
    assert per["TCK-3"]["precision"] == pytest.approx(1.0)

    assert per["TCK-11"]["computed"] == ["review"]

    # aggregate over the 4 non-empty tickets
    assert dam["mean_precision"] == pytest.approx((1 + 0.5 + 1 + 1) / 4)
    assert dam["mean_recall"] == pytest.approx(1.0)
    assert dam["micro_precision"] == pytest.approx(5 / 6)
    assert dam["micro_recall"] == pytest.approx(1.0)


def test_empty_affected_modules_ticket_is_skipped(tmp_path):
    fx = _build_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    _run_harness(fx, out)
    rep = json.loads(out.read_text())
    per = {t["ticket"] for t in rep["diff_affected_modules"]["per_ticket"]}
    assert "TCK-EMPTY" not in per
    skipped = {s["ticket"] for s in rep["corpus"]["tickets_skipped"]}
    assert "TCK-EMPTY" in skipped


def test_grep_word_boundary_no_collision(tmp_path):
    """TCK-1 must NOT pick up TCK-11's commit (substring collision)."""
    fx = _build_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    _run_harness(fx, out)
    per = {t["ticket"]: t for t in json.loads(out.read_text())["diff_affected_modules"]["per_ticket"]}
    # if the boundary failed, 'review' (from TCK-11) would leak into TCK-1
    assert "review" not in per["TCK-1"]["computed"]


def test_lifecycle_churn_excluded(tmp_path):
    """A .klc/ file touched by TCK-1's commit must not add a module."""
    fx = _build_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    _run_harness(fx, out)
    per = {t["ticket"]: t for t in json.loads(out.read_text())["diff_affected_modules"]["per_ticket"]}
    assert per["TCK-1"]["computed"] == ["intake", "routing"]


# --------------------------------------------------------------------------- #
# AC-3: retrieval-metrics seam
# --------------------------------------------------------------------------- #
def test_retrieval_metrics_unavailable_without_trace(tmp_path):
    fx = _build_corpus(tmp_path, with_trace=False)
    out = tmp_path / "eval_report.json"
    proc = _run_harness(fx, out)
    assert proc.returncode == 0
    rm = json.loads(out.read_text())["retrieval_metrics"]
    assert rm["status"] == "unavailable"
    assert rm.get("reason")
    assert rm.get("recall_at_5") is None


def test_retrieval_metrics_computed_with_trace(tmp_path):
    fx = _build_corpus(tmp_path, with_trace=True)
    out = tmp_path / "eval_report.json"
    proc = _run_harness(fx, out)
    assert proc.returncode == 0, proc.stderr
    rm = json.loads(out.read_text())["retrieval_metrics"]
    assert rm["status"] == "ok"
    assert rm["recall_at_5"] == pytest.approx(1.0)
    assert rm["recall_at_10"] == pytest.approx(1.0)
    assert rm["precision_at_10"] == pytest.approx(2 / 3)
    assert rm["mean_files_before_first_edit"] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# AC-4: CLI contract
# --------------------------------------------------------------------------- #
def test_exit_2_on_bad_tickets_arg(tmp_path):
    fx = _build_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    proc = _run_harness({**fx, "tickets_root": tmp_path / "does-not-exist"}, out)
    assert proc.returncode == 2


def test_missing_modules_degrades_not_fails(tmp_path):
    fx = _build_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    proc = _run_harness({**fx, "modules": tmp_path / "no-modules.json"}, out)
    assert proc.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["coverage"]["status"] == "unavailable"
    assert rep["diff_affected_modules"]["status"] == "unavailable"
    assert any(rep["errors"])


def test_cli_writes_out_file(tmp_path):
    fx = _build_corpus(tmp_path)
    out = tmp_path / "sub" / "eval_report.json"
    proc = _run_harness(fx, out)
    assert proc.returncode == 0
    assert out.exists()


# --------------------------------------------------------------------------- #
# AC-2: single resolver reuse (unit level)
# --------------------------------------------------------------------------- #
def test_uses_module_membership_resolver():
    mod = _load_skill()
    # files-override shared file contributes every member_of module
    assert mod.resolve_modules_for_files(["core/common/paths.py"], MODULES) == ["intake", "routing"]
    # boundary guard: review-lite must NOT be swallowed by the 'review' stem module
    assert mod.resolve_modules_for_files(["core/agents/review-lite.py"], MODULES) == ["core/agents"]
    assert mod.resolve_modules_for_files(["core/agents/review.py"], MODULES) == ["review"]


def test_no_private_matcher_in_source():
    """AC-2: the skill must route through module_membership, not a private
    longest-prefix copy."""
    src = _SKILL.read_text()
    assert "module_membership" in src
    assert "file_to_module" in src


def test_precision_recall_helper():
    mod = _load_skill()
    prec, rec, missed, extra = mod.precision_recall(["a", "b"], ["a"])
    assert prec == pytest.approx(0.5)
    assert rec == pytest.approx(1.0)
    assert missed == []
    assert extra == ["b"]


# --------------------------------------------------------------------------- #
# FIX-1: bad data source must degrade, not report valid 0/0
# --------------------------------------------------------------------------- #
def test_bad_repo_degrades_not_ok_zeros(tmp_path):
    """--repo that is not a git checkout must degrade coverage + diff to
    'unavailable' + errors[], NOT report 'ok' with zero/0-precision numbers."""
    fx = _build_corpus(tmp_path)
    notgit = tmp_path / "notgit"
    notgit.mkdir()
    (notgit / "core").mkdir()
    (notgit / "core" / "x.py").write_text("x=1\n")
    out = tmp_path / "eval_report.json"
    proc = _run_harness({**fx, "repo": notgit}, out)
    assert proc.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["coverage"]["status"] == "unavailable"
    assert rep["diff_affected_modules"]["status"] == "unavailable"
    assert any(rep["errors"])
    # must NOT be an 'ok' section full of zeros
    assert rep["coverage"].get("coverage_ratio") in (None, )  # key absent when degraded


def test_ticket_with_no_derivable_diff_is_skipped(tmp_path):
    """A ground-truth ticket whose key is in no commit is a diff-derivation gap,
    not a 0/0 index miss: route to tickets_skipped, don't tank the aggregate."""
    fx = _build_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    _run_harness(fx, out)
    rep = json.loads(out.read_text())
    per = {t["ticket"] for t in rep["diff_affected_modules"]["per_ticket"]}
    assert "TCK-NODIFF" not in per
    skipped = {s["ticket"]: s["reason"] for s in rep["corpus"]["tickets_skipped"]}
    assert "TCK-NODIFF" in skipped
    assert "no matching commits" in skipped["TCK-NODIFF"]
    # aggregate is still over the 4 genuinely-diffable tickets, not tanked to include 0/0
    dam = rep["diff_affected_modules"]
    assert dam["mean_precision"] == pytest.approx((1 + 0.5 + 1 + 1) / 4)
    assert dam["mean_recall"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# FIX-2: stored-patch seam (changed_files.txt + unified diff, incl. deletion)
# --------------------------------------------------------------------------- #
def test_stored_patch_changed_files_seam(tmp_path):
    fx = _make_stored_patch_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    proc = _run_harness(fx, out)
    assert proc.returncode == 0, proc.stderr
    per = {t["ticket"]: t for t in json.loads(out.read_text())["diff_affected_modules"]["per_ticket"]}
    # parser -> intake ; paths.py (shared) -> intake+routing
    assert per["SP-1"]["computed"] == ["intake", "routing"]


def test_stored_patch_unified_diff_with_deletion(tmp_path):
    fx = _make_stored_patch_corpus(tmp_path)
    out = tmp_path / "eval_report.json"
    _run_harness(fx, out)
    per = {t["ticket"]: t for t in json.loads(out.read_text())["diff_affected_modules"]["per_ticket"]}
    # added router.py -> routing ; DELETED review.py (captured from --- a/) -> review
    assert per["SP-2"]["computed"] == ["review", "routing"]


def test_stored_patch_parser_captures_deletion_a_side():
    """Unit: a deletion hunk (+++ /dev/null) must contribute the a/ path."""
    mod = _load_skill()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "meta.json").write_text("{}")
        (d / "x.patch").write_text(
            "--- a/core/agents/review.py\n"
            "+++ /dev/null\n"
        )
        files = mod.stored_patch_files(d)
    assert files == ["core/agents/review.py"]


# --------------------------------------------------------------------------- #
# FIX-3: reproducible generated_at via SOURCE_DATE_EPOCH
# --------------------------------------------------------------------------- #
def test_generated_at_honors_source_date_epoch(tmp_path):
    fx = _build_corpus(tmp_path)
    out1 = tmp_path / "r1.json"
    out2 = tmp_path / "r2.json"
    env = {"SOURCE_DATE_EPOCH": "1000000000"}
    _run_harness(fx, out1, env_extra=env)
    _run_harness(fx, out2, env_extra=env)
    g1 = json.loads(out1.read_text())["generated_at"]
    g2 = json.loads(out2.read_text())["generated_at"]
    assert g1 == g2
    assert g1.startswith("2001-09-09")
