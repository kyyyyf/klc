"""KLC-180 step-3 — AC-6, AC-7: the plugin ships six commands, seven skills and
only the agents that something dispatches; check_sync flags leftovers; 0.2.0."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW))
import phases as _phases  # noqa: E402
import plugin_gen as pg  # noqa: E402

PLUGIN = FW / "klc-plugin"
SIX = {"intake", "status", "go", "back", "fix", "doctor"}


def test_plugin_surface_is_six_commands_plus_discuss_feature():
    cmds = {p.stem for p in (PLUGIN / "commands").glob("*.md")}
    assert cmds == SIX
    assert set(pg._LIFECYCLE_CMDS) == SIX
    assert pg.SKILL_VERBS == SIX
    skills = {p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir()}
    assert skills == SIX | {"discuss-feature"}
    assert pg.BESPOKE_SKILLS == {"discuss-feature"}


def test_agents_map_to_phases_or_dispatched_reviewers():
    assert pg.DISPATCHED_AGENTS == frozenset({
        "intake-triage", "spec-reviewer", "test-plan-reviewer",
        "impl-plan-reviewer", "drift-reviewer", "external-review",
    })
    prompts = [p.prompt for p in _phases.load_phases(force=True).ordered]
    wanted = pg.plugin_agent_names(prompts)
    assert wanted == {Path(p).stem for p in prompts if p} | set(pg.DISPATCHED_AGENTS)
    on_disk = {p.stem for p in (PLUGIN / "agents").glob("*.md")}
    assert on_disk == wanted
    for gone in ("consistency", "decompose", "task", "design-scout", "inventory",
                 "docgen", "test", "intake"):
        assert gone not in on_disk


def test_check_sync_flags_stale_agent_file():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "klc-plugin"
        import shutil
        shutil.copytree(PLUGIN, root)
        assert pg.check_sync(root) == []
        (root / "agents" / "docgen.md").write_text("old\n", encoding="utf-8")
        assert "STALE: agents/docgen.md" in pg.check_sync(root)


def test_manifest_version_bumped():
    data = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert data["version"] == "0.2.0"


# --- review round 1 ---------------------------------------------------------

def test_go_command_stub_carries_the_dispatch_loop():
    """F-002: /klc:go reaches the loop: Task is allowed, the stub holds the loop."""
    text = (FW / "klc-plugin" / "commands" / "go.md").read_text(encoding="utf-8")
    assert "allowed-tools: [Bash, Task, AskUserQuestion]" in text
    assert "klc go <KEY> --until integrate" in text
    assert "dispatch: agent=" in text and "model=<model>" in text
    assert "never omit `model=`" in text
