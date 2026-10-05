#!/usr/bin/env python3
"""KLC-177 step-5 — AC-10: the plugin and docs match the go/back surface.

VERB_SPECS holds go and back but not next/ack/ship/jump/abort, the obsolete
command stubs and skill directories are gone, the go skill carries the
`klc go --until integrate` loop (the run skill is retired, KLC-180), and no prompt/skill/doc tells anyone to run a
removed verb as a command.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW / "core" / "skills"))

import plugin_gen as pg  # noqa: E402
import prompt_honesty as ph  # noqa: E402

PLUGIN = FW / "klc-plugin"
OLD = ("next", "ack", "ship", "jump", "abort")
RUN_SKILL = PLUGIN / "skills" / "go" / "SKILL.md"   # KLC-180: the loop moved into go
PROCESS = FW / "docs" / "process.md"
# A removed verb used as a command. Hyphen/word continuation is not a match.
OLD_CMD = re.compile(r"\bklc (?:ack|next|ship|jump|abort|work)(?![\w-])")


def test_plugin_regenerated_skill_short_and_process_doc_updated() -> None:
    assert {"go", "back"} <= set(pg.VERB_SPECS)
    assert not set(OLD) & set(pg.VERB_SPECS)
    lines = RUN_SKILL.read_text(encoding="utf-8").splitlines()
    assert len(lines) < 80, len(lines)
    assert "klc go <KEY> --until integrate" in "\n".join(lines)
    text = PROCESS.read_text(encoding="utf-8")
    assert "klc go" in text and "klc back" in text
    assert pg.check_sync() == []


def test_lifecycle_cmds_are_the_new_set() -> None:
    assert set(pg._LIFECYCLE_CMDS) == {
        "intake", "status", "go", "back", "fix", "doctor"}


def test_obsolete_stubs_and_skill_dirs_deleted_new_ones_present() -> None:
    for v in OLD:
        assert not (PLUGIN / "commands" / f"{v}.md").exists(), v
        assert not (PLUGIN / "skills" / v).exists(), v
    for v in ("go", "back"):
        assert (PLUGIN / "commands" / f"{v}.md").exists()
        assert (PLUGIN / "skills" / v / "SKILL.md").exists()
    assert (PLUGIN / "skills" / "discuss-feature" / "SKILL.md").exists()


def test_check_sync_flags_stub_for_verb_outside_verb_specs(tmp_path) -> None:
    copy = tmp_path / "klc-plugin"
    shutil.copytree(PLUGIN, copy)
    assert pg.check_sync(committed_root=copy) == []
    (copy / "commands" / "next.md").write_text(
        "---\ndescription: x\n---\n\nRun `klc next`.\n", encoding="utf-8")
    findings = pg.check_sync(committed_root=copy)
    assert any("commands/next.md" in f for f in findings), findings


def test_manifest_version_bumped() -> None:
    data = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert data["version"] == "0.2.0"   # KLC-180


def test_run_skill_loop_contract() -> None:
    t = " ".join(RUN_SKILL.read_text(encoding="utf-8").split())
    low = t.lower()
    assert "exit 2" in low and "Task" in t and "klc go" in t
    assert "never merge" in low and "never push" in low
    assert "fresh" in low
    assert not OLD_CMD.search(t)


def _scan(path: Path) -> list[str]:
    bad = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "deprecated" in line.lower():
            continue
        if OLD_CMD.search(line):
            bad.append(f"{path.relative_to(FW)}:{i}: {line.strip()[:100]}")
    return bad


def test_no_prompt_skill_or_doc_names_a_removed_verb_as_command() -> None:
    files = sorted((FW / "core" / "agents").rglob("*.md")) + [RUN_SKILL, PROCESS]
    bad = [b for f in files for b in _scan(f)]
    assert not bad, "\n".join(bad)


def test_process_doc_lists_public_verbs_and_deprecation_window() -> None:
    t = PROCESS.read_text(encoding="utf-8")
    verbs = t[t.index("## Verbs"):]
    for needle in ("klc intake", "klc status", "klc go", "klc back", "klc step verify",
                   "klc internal <name>", "removed after wave 3"):
        assert needle in verbs, needle


def test_honesty_scan_rejects_deprecated_verbs(tmp_path) -> None:
    verbs = ph.klc_verbs()
    assert not set(OLD) & verbs
    assert {"go", "back", "intake", "status", "reindex"} <= verbs
    f = tmp_path / "p.md"
    f.write_text("then run `klc ack KLC-1` now\n", encoding="utf-8")
    assert ph._bad_verbs(f, f.read_text(encoding="utf-8"), verbs)
