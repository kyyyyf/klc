"""KLC-114 step-7: one function backs every call site — `build_orchestrator.
run_build`, `phase_completion.can_complete_build` and (the future `/klc:run`
sub-step / CLI) a direct `step_ledger.verify_build_steps` call — so the same
ticket state yields byte-identical `progress.md` verdicts, and the pass
truly ran, through all of them (AC-1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import klc114_helpers as h  # noqa: E402


def _setup(tmp_path, monkeypatch, ticket):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "phase": "build:work", "track": "XS",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code", "risk_tags": [],
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        f"---\nticket: {ticket}\nkind: tech\n---\n\n## Acceptance Criteria\n\n## Estimate\n- total: 1\n",
        encoding="utf-8")
    (ticket_dir / "test-plan.md").write_text(
        f"---\nticket: {ticket}\nkind: test-plan\n---\n\n## Acceptance coverage\n\n## Edge cases\n- n/a\n",
        encoding="utf-8")
    (ticket_dir / "build-log.md").write_text(
        f"# Build log — {ticket}\n\n## Evidence\n\n"
        "```\n$ builder's own re-run\nbuilder output\n```\n",
        encoding="utf-8")
    plan = "# Implementation plan\n\n" + h.step_plan(
        "step-1", verify="`sh -c \"echo 2 passed\"`", expected="`2 passed`",
        affected="`core/skills/x.py`", addresses="AC-1")
    (ticket_dir / "impl-plan.md").write_text(plan, encoding="utf-8")

    repo = h.make_repo(tmp_path, f"repo-{ticket}")
    h.commit(repo, {"tests/test_x.py": "# test"}, f"{ticket} step-1: add test")
    h.commit(repo, {"core/skills/x.py": "# impl"}, f"{ticket} step-1: add impl")
    return ticket_dir, repo


def _verdicts(ticket: str) -> tuple:
    """(step_id, state, reason) per step — the VERDICT, stripped of the
    incidental `model`/`ts` fields that only a real agent dispatch (never a
    direct `verify_build_steps`/`can_complete_build` call) ever populates."""
    import build_ledger as bl
    led = bl.Ledger.load(ticket)
    return tuple((s.id, s.state, s.reason) for s in led.steps)


def test_three_call_sites_produce_byte_identical_progress(tmp_path, monkeypatch):
    """AC-1: the same ticket state yields byte-identical `progress.md`
    verdicts (ts fields stripped) and a genuinely-ran pass (the machine
    Evidence block appears in build-log.md) whether reached via a direct
    `step_ledger.verify_build_steps` call, via `build_orchestrator.run_build`,
    or via `phase_completion.can_complete_build`'s persisting path."""
    import step_ledger as sl
    import build_orchestrator as bo
    from core.skills.phase_completion import can_complete_build

    # call site 1: step_ledger.verify_build_steps directly (what a CLI /
    # `/klc:run` sub-step would call).
    t1, repo1 = _setup(tmp_path, monkeypatch, "KLC-LP01")
    sl.verify_build_steps("KLC-LP01", str(repo1), write=True)
    verdicts1 = _verdicts("KLC-LP01")
    log1 = (t1 / "build-log.md").read_text(encoding="utf-8")

    # call site 2: build_orchestrator.run_build (repo is threaded through the
    # process cwd, exactly as a real `klc build-run` invocation would have it).
    t2, repo2 = _setup(tmp_path, monkeypatch, "KLC-LP02")
    monkeypatch.chdir(repo2)

    def fake_dispatch(phase_id, prompt_path, out_path, *, track=None, inputs=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("## Outcome\ngreen\n", encoding="utf-8")
        return 0

    rc = bo.run_build("KLC-LP02", dispatch=fake_dispatch)
    assert rc == 0
    verdicts2 = _verdicts("KLC-LP02")
    log2 = (t2 / "build-log.md").read_text(encoding="utf-8")

    # call site 3: phase_completion.can_complete_build's persisting path.
    t3, repo3 = _setup(tmp_path, monkeypatch, "KLC-LP03")
    ok, msg = can_complete_build("KLC-LP03", repo3)
    assert ok, msg
    verdicts3 = _verdicts("KLC-LP03")
    log3 = (t3 / "build-log.md").read_text(encoding="utf-8")

    def _canon(verdicts, ticket):
        # Strip the ticket-scoped step_id prefix so only (state, reason) compare.
        return tuple((state, reason) for _sid, state, reason in verdicts)

    assert _canon(verdicts1, "KLC-LP01") == _canon(verdicts2, "KLC-LP02") == _canon(verdicts3, "KLC-LP03")
    assert _canon(verdicts1, "KLC-LP01") == (("green", None),)
    assert "step ledger pass" in log1
    assert "step ledger pass" in log2
    assert "step ledger pass" in log3
    assert "builder's own re-run" in log1  # builder's entry survives everywhere
    assert "builder's own re-run" in log2
    assert "builder's own re-run" in log3


def test_readonly_probe_path_does_not_run_pass(tmp_path, monkeypatch):
    """AC-1 boundary: `can_complete_build(ticket, repo, persist=False)` — the
    read-only probe `klc remind`/gate-policy advisories use on every prompt —
    must not invoke the pass at all."""
    from core.skills.phase_completion import can_complete_build
    ticket_dir, repo = _setup(tmp_path, monkeypatch, "KLC-LP04")

    import step_ledger as sl

    def _boom(*a, **kw):
        raise AssertionError("verify_build_steps must not run on the read-only probe path")
    monkeypatch.setattr(sl, "verify_build_steps", _boom)

    can_complete_build("KLC-LP04", repo, persist=False)

    assert not (ticket_dir / "build" / "progress.md").exists()
