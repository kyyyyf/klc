"""KLC-114 step-6: the two settings knobs — `build.verify_steps` (default
true) and `build.per_step_review_on_verify` (default off) — and that the
hard-breach semantics of `can_complete_build` are unchanged in both toggle
positions (AC-11)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import settings  # noqa: E402


def test_verify_steps_defaults_true(tmp_path, monkeypatch):
    """AC-11: `build.verify_steps` defaults to true with no settings.yml at
    all — a default-on, report-producing pass cannot break an existing flow."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert settings.build_verify_steps() is True


def test_per_step_review_on_verify_defaults_off(tmp_path, monkeypatch):
    """AC-11: `build.per_step_review_on_verify` defaults to false — it costs
    a model call, so it opts in rather than opts out."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert settings.build_per_step_review_on_verify() is False


def test_verify_steps_false_skips_pass_entirely_builder_evidence_stands(tmp_path, monkeypatch):
    """AC-11: `build.verify_steps: false` skips the pass entirely on the
    `can_complete_build` call site — `step_ledger.verify_build_steps` must
    not even be invoked, and the builder's own build-log.md stands untouched."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    config_dir = tmp_path / ".klc" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.yml").write_text("build:\n  verify_steps: false\n", encoding="utf-8")
    assert settings.build_verify_steps() is False

    ticket = "KLC-SK01"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    (ticket_dir / "meta.json").write_text(
        json.dumps({"ticket": ticket, "track": "M"}), encoding="utf-8")
    original_log = "# Build log — KLC-SK01\n\n## Evidence\n\n```\n$ true\nok\n```\n"
    (ticket_dir / "build-log.md").write_text(original_log, encoding="utf-8")

    import step_ledger as sl

    def _boom(*a, **kw):
        raise AssertionError("verify_build_steps must not run when build.verify_steps is false")
    monkeypatch.setattr(sl, "verify_build_steps", _boom)

    from core.skills.phase_completion import can_complete_build
    ok, msg = can_complete_build(ticket)

    assert ok, msg
    assert (ticket_dir / "build-log.md").read_text(encoding="utf-8") == original_log
    assert not (ticket_dir / "build" / "progress.md").exists()


def test_hard_breach_semantics_unchanged_in_both_toggle_positions(tmp_path, monkeypatch):
    """AC-11: `can_complete_build`'s existing hard-breach set (here: a
    missing `## Evidence` section) is identical whether `build.verify_steps`
    is true (the default) or false."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-SK02"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    (ticket_dir / "meta.json").write_text(
        json.dumps({"ticket": ticket, "track": "M"}), encoding="utf-8")
    (ticket_dir / "build-log.md").write_text("# Build log\n\nno evidence section\n",
                                             encoding="utf-8")

    from core.skills.phase_completion import can_complete_build

    ok_default, msg_default = can_complete_build(ticket)
    assert not ok_default
    assert "Evidence" in msg_default

    config_dir = tmp_path / ".klc" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.yml").write_text("build:\n  verify_steps: false\n", encoding="utf-8")
    ok_off, msg_off = can_complete_build(ticket)
    assert not ok_off
    assert "Evidence" in msg_off
