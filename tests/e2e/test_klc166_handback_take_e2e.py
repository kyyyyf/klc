"""KLC-166 step-2 — AC-7: a hermetic end-to-end run of `handback.py take`
for both in-client review kinds, with the REAL `_run_planner` and the REAL
`scripts/review.py` subprocess (C-004, "mock the real contract"). This is
the ticket's own reproduction, inverted: before this ticket `take` on a
ticket with no plan always ended with "pass not recorded"; after it, the
first `take` writes the plan and both passes count.

A stub `claude` executable is placed first on `PATH` (spec-review F-4) so
the external pass is planned deterministically regardless of whether a
real `claude` CLI happens to be installed on the machine running this
suite.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(FW_ROOT / "tests" / "integration"))

import handback  # noqa: E402
import metrics  # noqa: E402

from _klc128_fixtures import _bare_and_clone, _branch_with_commits  # noqa: E402

_MODULES = [{"name": "widgets", "path": "widgets/"}]
TICKET = "KLC-974"


def _stub_claude_on_path(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "claude"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{__import__('os').pathsep}{__import__('os').environ.get('PATH', '')}")


def _verdict() -> dict:
    return {"findings": [], "decisions_to_confirm": []}


def _tagged_attempts(tdir: Path) -> list:
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    return [rec for _phase, rec in metrics.iter_attempts(meta, TICKET) if rec.get("reviewer")]


def test_take_code_review_then_external_review_plans_and_records_both_passes_in_one_hermetic_repo(
    tmp_path, monkeypatch
):
    """AC-7: a temp git repo, a feature branch with one committed change, an
    M ticket with no `review-plan.json`. `take --kind code-review` then
    `take --kind external-review` each run the real planner and the real
    `review.py`. Afterwards the plan exists, both passes are `executed`,
    and `meta.json` carries exactly two reviewer-tagged attempts."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    _branch_with_commits(clone, TICKET, [
        ("widgets/thing.py", "a = 1\n", f"{TICKET} step-1: add a"),
    ], branch=f"feature/{TICKET.lower()}-add-a-widget")

    tdir = clone / ".klc" / "tickets" / TICKET
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": TICKET, "kind": "bug", "kind_source": "user",
        "phase": "build:work", "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": ["widgets"], "risk_tags": [],
        "estimate": {"complexity": 1, "uncertainty": 1, "risk": 1, "manual": 1, "total": 4},
        "layer": "code", "budgets": {},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
        "owner": "test@example.com",
    }
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (tdir / "spec.md").write_text("# spec\n", encoding="utf-8")
    index_dir = clone / ".klc" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "modules.json").write_text(
        json.dumps({"modules": _MODULES}, indent=2) + "\n", encoding="utf-8")
    (clone / ".klc" / "config").mkdir(parents=True, exist_ok=True)
    (clone / ".klc" / "config" / "profile.yml").write_text(
        "profile: generic\n", encoding="utf-8")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stub_claude_on_path(tmp_path, monkeypatch)

    assert not (tdir / "review-plan.json").exists()

    vfile1 = tmp_path / "code-review-verdict.json"
    vfile1.write_text(json.dumps(_verdict()), encoding="utf-8")
    rc1 = handback.take("code-review", TICKET, vfile1)
    assert rc1 == 0

    vfile2 = tmp_path / "external-review-verdict.json"
    vfile2.write_text(json.dumps(_verdict()), encoding="utf-8")
    rc2 = handback.take("external-review", TICKET, vfile2)
    assert rc2 == 0

    plan = json.loads((tdir / "review-plan.json").read_text(encoding="utf-8"))
    by_reviewer = {p["reviewer"]: p for p in plan["passes"]}
    assert by_reviewer["code-review"]["status"] == "executed"
    assert by_reviewer["external"]["status"] == "executed"
    assert len(_tagged_attempts(tdir)) == 2
