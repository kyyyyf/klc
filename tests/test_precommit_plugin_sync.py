#!/usr/bin/env python3
"""KLC-102 — the pre-commit plugin-sync gate (AC-7, AC-8).

The bash pre-commit hook is a thin shell over a UNIT-TESTABLE python seam
(test-plan D-1): ``plugin_gen.check_sync()`` regenerates agents+skills+manifest
into a temp dir and compares against a committed tree, returning drift findings;
``plugin_gen.plugin_sources_staged()`` is the scope predicate (AC-8). Both are
injectable so a mutated committed tree / an arbitrary staged-path list is
testable without touching the real repo state.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

FW = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FW / "core" / "skills"))
sys.path.insert(0, str(FW))

import plugin_gen as pg  # noqa: E402


def _copy_committed(dst: Path) -> Path:
    shutil.copytree(FW / "klc-plugin", dst)
    return dst


def test_sync_clean_when_in_sync() -> None:
    """AC-7: with the committed plugin already regenerated, check_sync finds no
    drift (default committed_root == the real, in-sync tree)."""
    assert pg.check_sync() == []


def test_sync_fails_on_agent_drift(tmp_path) -> None:
    """AC-7: a staged ``core/agents/*`` change not regenerated into the plugin —
    simulated by a stale committed agent copy — is reported as drift."""
    committed = _copy_committed(tmp_path / "klc-plugin")
    victim = sorted(committed.glob("agents/*.md"))[0]
    victim.write_text("stale agent body — not what plugin_gen emits\n", encoding="utf-8")
    findings = pg.check_sync(committed_root=committed)
    assert any(f"DRIFT: agents/{victim.name}" in f for f in findings), findings


def test_sync_fails_on_verb_dict_drift(tmp_path, monkeypatch) -> None:
    """AC-7: a VERB_SPECS change not regenerated into skills is reported as
    drift (the committed skill is now stale relative to the verb-dictionary)."""
    committed = _copy_committed(tmp_path / "klc-plugin")
    monkeypatch.setitem(pg.VERB_SPECS["go"], "short", "CHANGED short description")
    findings = pg.check_sync(committed_root=committed)
    assert any("DRIFT: skills/go/SKILL.md" in f for f in findings), findings


def test_plugin_sources_staged_true_for_agents_and_plugin_gen() -> None:
    """AC-8: staged ``core/agents/*`` or ``core/skills/plugin_gen.py`` → True."""
    assert pg.plugin_sources_staged(["core/agents/discovery.md"]) is True
    assert pg.plugin_sources_staged(["core/skills/plugin_gen.py"]) is True
    assert pg.plugin_sources_staged(["README.md", "core/agents/review.md"]) is True


def test_plugin_sources_staged_false_otherwise() -> None:
    """AC-8 (scoped skip, review F-2): staged paths outside the two plugin-source
    locations → False, so the gate never fires spuriously."""
    assert pg.plugin_sources_staged([]) is False
    assert pg.plugin_sources_staged(["core/skills/consistency_check.py", "docs/x.md"]) is False
    assert pg.plugin_sources_staged(["klc-plugin/skills/ack/SKILL.md"]) is False


def test_check_never_restages(tmp_path) -> None:
    """AC-8: check_sync is a read-only compare — it modifies/restages no file in
    the committed tree (it regenerates into a throwaway temp dir)."""
    committed = _copy_committed(tmp_path / "klc-plugin")
    snap = lambda: {
        p.relative_to(committed).as_posix(): p.read_bytes()
        for p in committed.rglob("*") if p.is_file()
    }
    before = snap()
    pg.check_sync(committed_root=committed)
    assert snap() == before


# ---------------------------------------------------------------------------
# review LOW-2 — check_sync also catches command-description drift so the
# commit-time gate (not only the offline drift-guard test) flags it.
# ---------------------------------------------------------------------------

def test_sync_clean_has_no_command_desc_drift(tmp_path) -> None:
    """review LOW-2: a fresh committed copy has every shared command stub's
    ``description:`` equal to ``VERB_SPECS[verb]["short"]`` — no CMD-DESC-DRIFT."""
    committed = _copy_committed(tmp_path / "klc-plugin")
    findings = pg.check_sync(committed_root=committed)
    assert not any(f.startswith("CMD-DESC-DRIFT") for f in findings), findings


def test_sync_fails_on_command_desc_drift(tmp_path) -> None:
    """review LOW-2: a committed ``commands/<verb>.md`` whose frontmatter
    description no longer matches ``VERB_SPECS[verb]["short"]`` is reported as
    ``CMD-DESC-DRIFT`` by check_sync (the commit-time gate now catches it)."""
    committed = _copy_committed(tmp_path / "klc-plugin")
    go_cmd = committed / "commands" / "go.md"
    text = go_cmd.read_text(encoding="utf-8")
    mutated = text.replace(
        f"description: {pg.VERB_SPECS['go']['short']}",
        "description: totally different — stale hand edit",
    )
    assert mutated != text, "fixture must actually mutate the description line"
    go_cmd.write_text(mutated, encoding="utf-8")
    findings = pg.check_sync(committed_root=committed)
    assert any("CMD-DESC-DRIFT: commands/go.md" in f for f in findings), findings


# ---------------------------------------------------------------------------
# review LOW-1 — --check-if-staged is the REAL hook gate: it computes staged
# paths, applies the plugin_sources_staged scope predicate, and only then runs
# check_sync. The staged-paths source is an injectable seam (`_staged_paths`).
# ---------------------------------------------------------------------------

def test_check_if_staged_skips_when_out_of_scope(monkeypatch) -> None:
    """review LOW-1: out-of-scope staged paths → the mode SKIPS (exit 0) and
    never runs check_sync (proven by making check_sync explode if called)."""
    monkeypatch.setattr(pg, "_staged_paths", lambda: ["docs/x.md", "README.md"])

    def _boom(*a, **k):
        raise AssertionError("check_sync must not run when out of scope")

    monkeypatch.setattr(pg, "check_sync", _boom)
    assert pg.main(["--check-if-staged"]) == 0


def test_check_if_staged_passes_when_in_scope_and_in_sync(monkeypatch) -> None:
    """review LOW-1: in-scope staged path + no drift → exit 0."""
    monkeypatch.setattr(pg, "_staged_paths", lambda: ["core/agents/review.md"])
    monkeypatch.setattr(pg, "check_sync", lambda *a, **k: [])
    assert pg.main(["--check-if-staged"]) == 0


def test_check_if_staged_fails_on_injected_drift(monkeypatch) -> None:
    """review LOW-1: in-scope staged path + injected drift findings → exit 1."""
    monkeypatch.setattr(pg, "_staged_paths", lambda: ["core/skills/plugin_gen.py"])
    monkeypatch.setattr(pg, "check_sync", lambda *a, **k: ["DRIFT: agents/review.md"])
    assert pg.main(["--check-if-staged"]) == 1


def test_sync_fails_on_command_tools_drift(tmp_path) -> None:
    """F-008: a stub whose allowed-tools line differs from VERB_SPECS is CMD-TOOLS-DRIFT."""
    committed = _copy_committed(tmp_path / "klc-plugin")
    assert not any(f.startswith("CMD-TOOLS-DRIFT") for f in pg.check_sync(committed_root=committed))
    go_cmd = committed / "commands" / "go.md"
    text = go_cmd.read_text(encoding="utf-8")
    mutated = text.replace("allowed-tools: [Bash, Task, AskUserQuestion]", "allowed-tools: [Bash]")
    assert mutated != text
    go_cmd.write_text(mutated, encoding="utf-8")
    findings = pg.check_sync(committed_root=committed)
    assert any("CMD-TOOLS-DRIFT: commands/go.md" in f for f in findings), findings
