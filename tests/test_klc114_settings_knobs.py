"""KLC-114 step-6 / KLC-174: the `build.per_step_review_on_verify` knob (default
off) stays; `build.verify_steps` was removed with the re-run pass (AC-11, AC-7)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills"), str(_FW_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import settings  # noqa: E402


def test_per_step_review_on_verify_defaults_off(tmp_path, monkeypatch):
    """AC-11: `build.per_step_review_on_verify` defaults to false — it costs
    a model call, so it opts in rather than opts out."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert settings.build_per_step_review_on_verify() is False


def test_removed_verify_steps_knob_is_inert(tmp_path, monkeypatch):
    """KLC-174: `build.verify_steps` is gone (the ack has no re-run pass to toggle).
    A leftover `build: verify_steps: false` in a project's settings.yml changes
    nothing: there is no accessor and the ack verdict is identical either way."""
    assert not hasattr(settings, "build_verify_steps")

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    ticket = "KLC-SK02"
    ticket_dir = tmp_path / ".klc" / "tickets" / ticket
    ticket_dir.mkdir(parents=True)
    (ticket_dir / "meta.json").write_text(
        json.dumps({"ticket": ticket, "track": "M"}), encoding="utf-8")
    (ticket_dir / "build-log.md").write_text("# Build log\n\nfree notes only\n",
                                             encoding="utf-8")

    from core.skills.phase_completion import can_complete_build

    ok_default, msg_default = can_complete_build(ticket)
    assert not ok_default
    assert "impl-plan.md has no steps" in msg_default

    config_dir = tmp_path / ".klc" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.yml").write_text("build:\n  verify_steps: false\n", encoding="utf-8")
    ok_off, msg_off = can_complete_build(ticket)
    assert (ok_off, msg_off) == (ok_default, msg_default)
