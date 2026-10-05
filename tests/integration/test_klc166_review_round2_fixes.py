"""KLC-166 step-6 — review round 2 fixes (external code review, both LOW).

- F-1: `_validated_recorded_range`, extracted in step-5 as the leg shared by
  `_resolve_ground_truth` and `ticket_diff_range`, collapsed all three of
  its failure reasons onto the same `(None, reason)` shape. That silently
  reversed `_resolve_ground_truth`'s pre-step-5 precedence: the KLC-129
  branch-mismatch reason (`mismatch or why`) must win ONLY when NOTHING was
  recorded at all; a range that WAS recorded but is non-ancestral,
  unresolvable, or empty must report its OWN reason even while `HEAD` also
  sits on another ticket's branch. Before this fix, a branch mismatch hid a
  bad recorded range behind the mismatch's reason text.
- F-2: `_plan_outcome`'s unreadable-plan branch (`review.py` exits 0/2, a
  plan file exists, but it does not even parse as JSON) never called
  `_reject_plan`. The next `take` then saw `review-plan.json` as PRESENT
  (unreadable, not missing) and skipped the planner entirely, so an
  unreadable plan blocked every future `take` on that ticket forever —
  the same bug step-5's F-2 fixed for the sha-mismatch and bad-exit-code
  branches, missed on this third branch.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _git,
    _ground_truth,
    _rev_parse,
    _seed_ticket,
)

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
import handback  # noqa: E402

_MODULES = [{"name": "widgets", "path": "widgets/"}]


# --- F-1: a branch mismatch never hides a recorded-but-invalid range's own reason --

def test_branch_mismatch_plus_a_non_ancestral_recorded_range_reports_the_ancestry_reason(
    tmp_path, monkeypatch
):
    """KLC-952 has a recorded `pre_merge_range` whose `base` is a commit
    from an UNRELATED sibling branch — never an ancestor of its recorded
    `head` (the KLC-128 step-7 AC-8 scenario). `HEAD` is ALSO moved to a
    DIFFERENT ticket's real lowercase `feature/klc-953-add-a-gizmo` branch
    (the KLC-129 F-001 mismatch scenario), so BOTH failure legs fire at
    once. Before this fix, `_resolve_ground_truth` reported the mismatch's
    `"HEAD is on ..."` reason, silently hiding the ancestry failure. After
    the fix, the recorded range's own ancestry reason wins — the mismatch
    text must not even appear."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-952"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch=f"feature/{ticket.lower()}-add-a-widget")
    ticket_head = _rev_parse(clone, "HEAD")

    # An unrelated branch off the same main, sharing only the initial commit
    # as a common ancestor — never an ancestor of ticket_head.
    _git(clone, "checkout", "main")
    _git(clone, "checkout", "-b", "feature/other")
    (clone / "other.py").write_text("x = 1\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "unrelated commit")
    unrelated_head = _rev_parse(clone, "HEAD")

    # HEAD now moves to a DIFFERENT ticket's real branch — the mismatch leg.
    other_ticket = "KLC-953"
    _branch_with_commits(clone, other_ticket, [
        ("gizmos/other.py", "b = 2\n", f"{other_ticket} step-1: add b"),
    ], branch=f"feature/{other_ticket.lower()}-add-a-gizmo")

    _seed_ticket(clone, ticket, phase="build:work", track="M",
                affected_modules=["widgets"], modules=_MODULES,
                pre_merge_range={"base": unrelated_head, "head": ticket_head,
                                 "recorded_at_phase": "build",
                                 "recorded_at": "2026-01-01T00:00:00Z"})

    gt = _ground_truth(clone, ticket, monkeypatch=monkeypatch)
    assert gt["source"] == "none"
    assert "is not an ancestor of head" in gt["reason"]
    assert "HEAD is on" not in gt["reason"], (
        "the branch-mismatch reason must not hide the recorded range's "
        "own ancestry failure")


# --- F-2: an unreadable plan written in THIS call is moved aside so `take` re-plans --

def _plan_path(clone: Path, ticket: str) -> Path:
    return clone / ".klc" / "tickets" / ticket / "review" / "review-plan-r1.json"


def _review_dir(clone: Path, ticket: str) -> Path:
    return clone / ".klc" / "tickets" / ticket / "review"


def _seed_real_project(clone: Path, ticket: str, **kw) -> Path:
    tdir = _seed_ticket(clone, ticket, **kw)
    (clone / ".klc" / "config").mkdir(parents=True, exist_ok=True)
    (clone / ".klc" / "config" / "profile.yml").write_text(
        "profile: generic\n", encoding="utf-8")
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    return tdir


def _seed_with_live_range(tmp_path: Path, ticket: str) -> Path:
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ], branch=f"feature/{ticket.lower()}-add-a-widget")
    _seed_real_project(clone, ticket, phase="build:work", track="M",
                       affected_modules=["widgets"], modules=_MODULES)
    return clone


def _write_verdict(tmp_path: Path) -> Path:
    vfile = tmp_path / "verdict.json"
    vfile.write_text(json.dumps({"findings": [], "decisions_to_confirm": []}),
                     encoding="utf-8")
    return vfile


def test_an_unreadable_plan_from_this_call_is_moved_aside_and_the_next_take_re_plans(
    tmp_path, monkeypatch, capsys
):
    """F-2: a passthrough swaps the real `review.py` for a fake script that
    writes INVALID JSON to `review-plan.json` and exits 0 — exactly the
    `_plan_outcome` unreadable-plan branch (`json.loads` raises
    `JSONDecodeError`, a `ValueError` subclass). Before the fix the
    unreadable plan is left at `review-plan.json`, so a second `take` sees
    a plan file present, skips `_run_planner` entirely (`_record` only
    re-plans when the file is MISSING), and keeps failing on the same
    unreadable plan forever. After the fix the plan is moved aside to
    `review/review-plan.rejected-<ts>.json`; the second `take` (with the
    real, unmodified `review.py` restored) must re-run the planner from
    scratch, write a FRESH valid plan, and record against it."""
    ticket = "KLC-954"
    clone = _seed_with_live_range(tmp_path, ticket)
    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plan_file = _plan_path(clone, ticket)
    review_dir = _review_dir(clone, ticket)

    fake_script = tmp_path / "fake_review.py"
    fake_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "spec_path = Path(sys.argv[sys.argv.index('--spec') + 1])\n"
        "plan_path = spec_path.parent / 'review' / 'review-plan-r1.json'\n"
        "plan_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "plan_path.write_text('{not valid json', encoding='utf-8')\n"
        "sys.exit(0)\n",
        encoding="utf-8")

    real_run = subprocess.run

    def _swap_review_py_for_the_fake_script(argv, *a, **kw):
        if isinstance(argv, list) and argv and argv[0] == sys.executable:
            argv = list(argv)
            argv[1] = str(fake_script)
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _swap_review_py_for_the_fake_script)

    vfile = _write_verdict(tmp_path)
    rc1 = handback.take("code-review", ticket, vfile)
    assert rc1 == 0
    out1 = capsys.readouterr().out
    assert "pass not recorded" in out1
    assert not plan_file.is_file(), (
        "an unreadable plan written in THIS call must be moved aside, "
        "not left at review-plan.json")
    rejected = sorted(review_dir.glob("review-plan.rejected-*.json"))
    assert len(rejected) == 1
    assert rejected[0].read_text(encoding="utf-8") == "{not valid json"

    monkeypatch.setattr(subprocess, "run", real_run)  # second take: real review.py
    rc2 = handback.take("code-review", ticket, vfile)
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "accepted" in out2
    assert "pass not recorded" not in out2
    assert plan_file.is_file()
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    code_review_pass = next(p for p in plan["passes"] if p["reviewer"] == "code-review")
    assert code_review_pass["status"] == "executed"
    assert len(sorted(review_dir.glob("review-plan.rejected-*.json"))) == 1, (
        "the second take's fresh plan must not itself be rejected again")
