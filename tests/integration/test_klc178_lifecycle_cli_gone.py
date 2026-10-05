"""KLC-178 step-4 — AC-11: core/skills/lifecycle.py has no command-line interface."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
LIFECYCLE = FW / "core" / "skills" / "lifecycle.py"


def test_script_run_is_a_usage_error_and_functions_remain(tmp_path):
    td = tmp_path / ".klc" / "tickets" / "T-LC-1"
    td.mkdir(parents=True)
    mp = td / "meta.json"
    mp.write_text(json.dumps({"ticket": "T-LC-1", "phase": "build:work"}), encoding="utf-8")
    before = mp.read_text(encoding="utf-8")
    env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    for sub in ("show", "ack", "advance", "jump", "abort"):
        p = subprocess.run([sys.executable, str(LIFECYCLE), sub, "--ticket", "T-LC-1"],
                           capture_output=True, text=True, env=env)
        assert p.returncode == 2, (sub, p.stdout, p.stderr)
        assert p.stdout == ""
        assert len(p.stderr.strip().splitlines()) == 1
        assert "lifecycle.py has no CLI; use klc go/back/fix" in p.stderr
        assert mp.read_text(encoding="utf-8") == before

    sys.path.insert(0, str(FW / "core" / "skills"))
    import lifecycle
    assert not hasattr(lifecycle, "_main")
    for name in ("apply_ack", "advance_to_next", "jump", "abort", "current_state"):
        assert callable(getattr(lifecycle, name)), name
