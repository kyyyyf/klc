"""KLC-115 step-1: core/skills/verify_runner.py — one bounded command executor
with a pass | fail | unverified vocabulary (AC-7, AC-12, AC-19).

Later steps append more cases to this same file: AC-5's read-only-probe twin
(step-3) and the arm-level degrade guard (step-7).
"""
from __future__ import annotations

import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS = FRAMEWORK_ROOT / "core" / "skills"
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import verify_runner as vr  # noqa: E402


def test_command_exceeding_budget_is_unverified_with_reason():
    v = vr.run([sys.executable, "-c", "import time; time.sleep(2)"], budget_s=1)
    assert v.state == vr.UNVERIFIED
    assert v.reason == vr.BUDGET_EXCEEDED
    assert v.state != vr.FAILED
    assert v.state != vr.PASSED
    assert "1s" in v.detail or "1.0s" in v.detail


def test_command_that_cannot_be_launched_is_unverified_not_failed():
    v = vr.run(["___this_executable_does_not_exist___"], budget_s=5)
    assert v.state == vr.UNVERIFIED
    assert v.reason == vr.LAUNCH_ERROR
    assert v.state != vr.FAILED
    assert v.state != vr.PASSED


def test_runner_treats_command_as_opaque_string_no_framework_assumption():
    v1 = vr.run("echo ok", budget_s=5)
    assert v1.state == vr.PASSED

    v2 = vr.run([sys.executable, "-c", "import sys; sys.exit(1)"], budget_s=5)
    assert v2.state == vr.FAILED

    # A command whose STDOUT happens to contain the word "failed" in prose
    # must still classify from exit status alone — never by scanning output
    # for a framework-specific pattern.
    v3 = vr.run([sys.executable, "-c",
                "import sys; print('0 failed, 3 passed'); sys.exit(0)"],
               budget_s=5)
    assert v3.state == vr.PASSED

    v4 = vr.run([sys.executable, "-c",
                "import sys; print('5 passed'); sys.exit(1)"], budget_s=5)
    assert v4.state == vr.FAILED


def test_large_output_command_is_bounded():
    v = vr.run([sys.executable, "-c",
               "import sys; sys.stdout.write('x' * 100000)"], budget_s=5)
    assert v.state == vr.PASSED
    assert len(v.output) <= vr.MAX_OUTPUT


def test_read_only_probe_spawns_zero_subprocesses(tmp_path, monkeypatch):
    """AC-5's fail-closed twin: the read-only probe path
    (`can_complete_build(ticket, persist=False)`, the same seam `gate_policy`
    calls on every prompt) must execute NOTHING — not one Evidence entry's
    command. `verify_runner.spawn` is monkeypatched to record every call and
    then raise, so any accidental invocation fails the test loudly."""
    import json

    FW_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(FW_ROOT))
    from core.skills.phase_completion import can_complete_build

    ticket = "KLC-RP01"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "spec.md").write_text(
        "---\nticket: {t}\nkind: feature\n---\n\n## Acceptance Criteria\n"
        "- [ ] AC-1: subject · acts · object · when a thing happens\n"
        .format(t=ticket), encoding="utf-8")
    (ticket_dir / "build-log.md").write_text(
        "---\nticket: {t}\nkind: build-log\n---\n\n# Build log — {t}\n\n"
        "## Evidence\n\n### AC-1 — proof\n\n```\n$ echo ok\nok\n```\n"
        .format(t=ticket), encoding="utf-8")

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    calls = []

    def fake_spawn(cmd, **kw):
        calls.append(cmd)
        raise AssertionError("verify_runner.spawn must not be called on the "
                             "read-only probe path")

    monkeypatch.setattr(vr, "spawn", fake_spawn)
    ok, msg = can_complete_build(ticket, persist=False)
    assert calls == [], f"the probe path spawned: {calls!r}"


def _make_degrade_ticket(tmp_path, ticket):
    import json
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "feature", "phase": "build:ack-needed",
        "track": "M",
        "estimate": {"complexity": 1, "uncertainty": 0, "risk": 0, "manual": 0, "total": 1},
        "affected_modules": ["core/skills"], "layer": "code",
    }
    (ticket_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (ticket_dir / "build-log.md").write_text(
        "---\nticket: {t}\nkind: build-log\n---\n\n# Build log — {t}\n\n"
        "## Evidence\n\n```\n$ echo ok\nok\n```\n".format(t=ticket), encoding="utf-8")
    return ticket_dir


def test_runner_launch_failure_degrades_to_surfaced_advisory_never_silent_pass(
        tmp_path, monkeypatch):
    """AC-16: with the Evidence arm's runner made unavailable (raises), the
    ack must succeed while carrying a non-empty advisory naming the reason —
    mirrors the existing 'ac-coverage: check did not run' degrade pattern."""
    FW_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(FW_ROOT))
    from core.skills.phase_completion import can_complete_build
    import advisories as _adv
    import evidence_gate as _evg

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-RP03"
    _make_degrade_ticket(tmp_path, ticket)

    def boom(*a, **kw):
        raise RuntimeError("runner unavailable")

    monkeypatch.setattr(_evg, "check_evidence", boom)
    ok, msg = can_complete_build(ticket)
    assert ok, f"a degraded verification arm must never block the ack, got {msg!r}"
    assert msg, "the ack message must be non-empty when an arm degraded"
    envelope = _adv.read(ticket, "build")
    assert envelope is not None
    assert any("unverified" in r["message"].lower() for r in envelope["records"]), (
        envelope["records"])


def test_gate_exception_never_silently_passes_with_no_advisory(tmp_path, monkeypatch):
    """AC-16's fail-closed twin, over the OTHER new arm: a raising
    step-verify gate must likewise leave a non-empty advisory naming the
    reason — an ack that swallowed the exception with zero advisory text
    fails this test."""
    FW_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(FW_ROOT))
    from core.skills.phase_completion import can_complete_build
    import advisories as _adv
    import step_verify as _sv

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-RP04"
    _make_degrade_ticket(tmp_path, ticket)

    def boom(*a, **kw):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(_sv, "check_steps", boom)
    ok, msg = can_complete_build(ticket)
    assert ok
    assert msg
    envelope = _adv.read(ticket, "build")
    assert envelope is not None
    assert any(r["message"].strip() for r in envelope["records"]), envelope["records"]
    assert any("unverified" in r["message"].lower() for r in envelope["records"]), (
        envelope["records"])
