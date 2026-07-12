"""KLC-052 step-5: clarify.yml + clarify_config.load_clarify_style.
step-8: wiring clarify.style into the clarify path (AC-12/C-006) —
the style switch drives batch-vs-serial in `intake-triage.md`'s
clarify section, and the headless/manual-CLI paths never read it.

Fail-closed, global-only (no per-track override), default "batch".
"""
from __future__ import annotations

import sys
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))

_INTAKE_TRIAGE = _FW_ROOT / "core" / "agents" / "intake-triage.md"


def test_batch_is_default_style(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import clarify_config

    assert clarify_config.load_clarify_style() == "batch"


def test_style_is_global_no_per_track_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    cfg_dir = tmp_path / ".klc" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "clarify.yml").write_text(
        "clarify:\n"
        "  style: serial\n"
        "  per_track:\n"
        "    XS: batch\n",
        encoding="utf-8",
    )
    import clarify_config

    assert clarify_config.load_clarify_style() == "serial"


def test_unknown_style_rejected_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    cfg_dir = tmp_path / ".klc" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "clarify.yml").write_text(
        "clarify:\n  style: chatty\n", encoding="utf-8",
    )
    import clarify_config

    try:
        clarify_config.load_clarify_style()
    except clarify_config.ClarifyConfigError:
        pass
    else:
        raise AssertionError("expected ClarifyConfigError for unknown style")


# ---------------------------------------------------------------------------
# step-8: wiring clarify.style into the clarify path (AC-8/AC-10/AC-11/AC-12)
# ---------------------------------------------------------------------------

def _clarify_section() -> str:
    text = _INTAKE_TRIAGE.read_text(encoding="utf-8")
    start = text.index("## Interactive clarify")
    end = text.index("## Hard rules")
    return text[start:end]


def test_batch_style_uses_ask_user_question():
    section = _clarify_section()
    batch_line = section[section.index("`batch`"):section.index("`serial`")]
    assert "AskUserQuestion" in batch_line
    assert "2-4" in batch_line or "2–4" in batch_line


def test_serial_style_asks_one_question_at_a_time():
    section = _clarify_section()
    serial_line = section[section.index("`serial`"):]
    assert "one question at a time" in serial_line or "one exchange per" in serial_line


def test_style_ignored_on_headless_runner_path():
    runner_src = (_FW_ROOT / "core" / "skills" / "runner.py").read_text(encoding="utf-8")
    assert "clarify_config" not in runner_src


def test_style_ignored_on_manual_cli_path():
    for name in ("intake.py", "ack.py", "next.py"):
        src = (_FW_ROOT / "core" / "phases" / name).read_text(encoding="utf-8")
        assert "clarify_config" not in src, f"{name} must not read clarify_config (C-006)"
