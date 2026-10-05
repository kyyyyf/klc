"""KLC-180 step-2 — hooks.json declares exactly two hooks and the old ones are gone."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
HOOKS = FW / "klc-plugin" / "hooks"


def _entries():
    data = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    return {ev: [h for g in groups for h in g["hooks"]] for ev, groups in data["hooks"].items()}


def test_hooks_json_has_exactly_two_entries():
    e = _entries()
    assert set(e) == {"PreToolUse", "UserPromptSubmit"}
    assert [len(v) for v in e.values()] == [1, 1]
    pre, = e["PreToolUse"]
    ups, = e["UserPromptSubmit"]
    assert "hooks/git_guard.py" in pre["command"] and pre["timeout"] == 5
    assert "hooks/klc.py" in ups["command"] and ups["timeout"] == 3
    assert ups["type"] == "command"
    for ent in (pre, ups):                                       # the same runpy wrapper shape
        assert "runpy.run_path" in ent["command"] and "os.path.exists" in ent["command"]


def test_launcher_exits_zero_when_klc_script_missing():
    ups, = _entries()["UserPromptSubmit"]
    cmd = ups["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(FW / "no-such-plugin"))
    import shlex
    p = subprocess.run(shlex.split(cmd), input="{}", capture_output=True, text=True)
    assert (p.returncode, p.stdout) == (0, "")


def test_retired_hook_files_and_verbs_are_gone():
    for name in ("gate.py", "remind.py", "heartbeat.py"):
        assert not (HOOKS / name).exists(), name
    assert (HOOKS / "klc.py").exists() and (HOOKS / "git_guard.py").exists()
    for rel in ("core/phases/remind.py", "core/phases/heartbeat.py",
                "tests/integration/test_remind.py", "tests/integration/test_heartbeat.py",
                "tests/integration/test_heartbeat_race.py"):
        assert not (FW / rel).exists(), rel
    text = (HOOKS / "hooks.json").read_text(encoding="utf-8")
    assert not re.search(r"gate\.py|remind\.py|heartbeat\.py", text)

    _retired_verbs_gone_but_steal_stays()


def _retired_verbs_gone_but_steal_stays():
    sys.path.insert(0, str(FW / "scripts"))
    from importlib.machinery import SourceFileLoader
    mod = SourceFileLoader("_klc_cli_180", str(FW / "scripts" / "klc")).load_module()
    for verb in ("remind", "heartbeat"):
        assert verb not in mod.INTERNAL_CMDS and verb not in mod._INTERNAL_PHASES
        assert verb not in mod.NO_DRAIN_CMDS
    assert "steal" in mod.INTERNAL_CMDS and "steal" in mod._INTERNAL_PHASES
    p = subprocess.run([sys.executable, str(FW / "scripts" / "klc"), "remind"],
                       capture_output=True, text=True)
    assert p.returncode != 0


def test_hook_scripts_are_stdlib_only_and_never_exit_two():
    src = (HOOKS / "klc.py").read_text(encoding="utf-8")
    assert "exit(2)" not in src and "return 2" not in src
    assert 'environ.get("KLC_GATE' not in src and 'environ.get("KLC_TICKET' not in src
