#!/usr/bin/env python3
"""KLC-072 — CLI + VS Code dispatch bug fixes.

Covers four pre-existing dispatch bugs surfaced during KLC-070 drift review:

1. `klc metrics` / `klc reindex` were shadowed by the generic `_run_phase`
   route (both names sat in OPERATIONAL_CMDS ahead of their explicit handlers),
   so they printed "command not implemented".
2. `klc jira-sync` routed via `_run_phase` looked for `core/phases/jira_sync.py`,
   but the wrapper is `jira_sync_cmd.py`, so it failed the same way.
3. (VS Code, verified here by shim-parity) `resolveFrameworkRoot` parsed
   `KLC_FRAMEWORK_ROOT` / `$FW`, but `klc install` writes `KLC_FW`.
4. At `build:work`, `status.py` looked for a flat `build/_prompt.md` and omitted
   the required single pick; the per-step card is `build/_prompt_step_<N>.md` and
   build's ack requires `--pick 1`.

The Python surface (bugs 1, 2, 4) is asserted directly. The VS Code `.ts` fixes
(bug 3 and the reader/tree half of bug 4) have no extension test harness, so we
assert the shims `klc install` actually writes are parseable by the regexes the
fixed reader uses (shim-parity), which is the load-bearing property.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = FW_ROOT / "scripts"
KLC = SCRIPTS / "klc"
PHASES_DIR = FW_ROOT / "core" / "phases"
SKILLS_DIR = FW_ROOT / "core" / "skills"

for _p in (str(SKILLS_DIR), str(PHASES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _run_klc(argv, project_root: Path) -> tuple[int, str]:
    """Run `scripts/klc <argv>` as a subprocess in a clean PROJECT_ROOT.

    Returns (rc, combined-stdout+stderr).
    """
    proc = subprocess.run(
        [sys.executable, str(KLC), *argv],
        env={**os.environ, "PROJECT_ROOT": str(project_root)},
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


NOT_IMPL = "command not implemented"


# --- AC-1: metrics / reindex reach their real handlers ----------------------- #

def test_reindex_no_arg_reaches_handler(tmp_path):
    """`klc reindex` with no ticket prints its usage, not 'not implemented'."""
    rc, out = _run_klc(["reindex"], tmp_path)
    assert NOT_IMPL not in out, out
    assert "usage: klc reindex" in out, out
    assert rc == 2, out


def test_metrics_no_arg_reaches_handler(tmp_path):
    """`klc metrics` with no args prints its usage, not 'not implemented'."""
    rc, out = _run_klc(["metrics"], tmp_path)
    assert NOT_IMPL not in out, out
    assert "usage: klc metrics" in out, out
    assert rc == 2, out


def test_metrics_rollup_reaches_handler(tmp_path):
    """`klc metrics --rollup` reaches the metrics skill (no 'not implemented')."""
    rc, out = _run_klc(["metrics", "--rollup"], tmp_path)
    assert NOT_IMPL not in out, out


# --- AC-2: jira-sync dispatches to jira_sync_cmd ----------------------------- #

def test_jira_sync_reaches_wrapper(tmp_path):
    """`klc jira-sync status` reaches jira_sync_cmd.run (no 'not implemented')."""
    rc, out = _run_klc(["jira-sync", "status"], tmp_path)
    assert NOT_IMPL not in out, out
    assert rc == 0, out


def test_jira_sync_bare_flush_reaches_wrapper(tmp_path):
    """The bare `klc jira-sync` (flush) route also reaches jira_sync_cmd, not the
    generic _run_phase that would look for the nonexistent jira_sync.py."""
    rc, out = _run_klc(["jira-sync"], tmp_path)
    assert NOT_IMPL not in out, out
    assert "jira_sync" not in out or "No module named" not in out, out


def test_jira_still_reaches_phase_after_dead_handler_removed(tmp_path):
    """`klc jira` must still route via core/phases/jira.py (OPERATIONAL_CMDS)
    after the unreachable explicit `jira` handler was deleted (KLC-072)."""
    rc, out = _run_klc(["jira"], tmp_path)
    assert NOT_IMPL not in out, out
    assert "unknown subcommand: jira" not in out, out


# --- status.py helpers ------------------------------------------------------- #

def _load_status():
    path = PHASES_DIR / "status.py"
    spec = importlib.util.spec_from_file_location("klc_phase_status_072", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(tmp_path: Path, ticket: str, *, phase: str, **extra) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "bug", "phase": phase, "track": "M",
        "affected_modules": [], "created": "2026-01-01T00:00:00Z",
    }
    meta.update(extra)
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _status_out(ticket: str, monkeypatch, tmp_path) -> str:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    status = _load_status()
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        status.run([ticket])
    return buf.getvalue()


# --- AC-4: build:work next-action names the step card + required pick --------- #

def test_status_build_work_names_step_card(monkeypatch, tmp_path):
    """At build:work with impl_step=2 and the step-2 card present, the hint names
    the per-step card, not a flat _prompt.md."""
    _seed(tmp_path, "KLC-900", phase="build:work", impl_step=2)
    bdir = tmp_path / ".klc" / "tickets" / "KLC-900" / "build"
    bdir.mkdir(parents=True)
    (bdir / "_prompt_step_2.md").write_text("step 2 card\n", encoding="utf-8")

    out = _status_out("KLC-900", monkeypatch, tmp_path)
    assert "_prompt_step_2.md" in out, out
    assert "_prompt.md`" not in out.replace("_prompt_step_2.md", ""), out


def test_status_build_work_defaults_step_1(monkeypatch, tmp_path):
    """A build:work ticket with no impl_step defaults to step 1."""
    _seed(tmp_path, "KLC-901", phase="build:work")
    bdir = tmp_path / ".klc" / "tickets" / "KLC-901" / "build"
    bdir.mkdir(parents=True)
    (bdir / "_prompt_step_1.md").write_text("step 1 card\n", encoding="utf-8")

    out = _status_out("KLC-901", monkeypatch, tmp_path)
    assert "_prompt_step_1.md" in out, out


def test_status_build_work_names_required_pick(monkeypatch, tmp_path):
    """The build:work 'when done' hint names the required single pick (--pick 1)."""
    _seed(tmp_path, "KLC-902", phase="build:work", impl_step=1)
    out = _status_out("KLC-902", monkeypatch, tmp_path)
    assert "--pick 1" in out, out


def test_status_nonbuild_work_flat_card(monkeypatch, tmp_path):
    """A non-build :work phase still points at flat <phase>/_prompt.md."""
    _seed(tmp_path, "KLC-903", phase="design:work")
    ddir = tmp_path / ".klc" / "tickets" / "KLC-903" / "design"
    ddir.mkdir(parents=True)
    (ddir / "_prompt.md").write_text("design card\n", encoding="utf-8")

    out = _status_out("KLC-903", monkeypatch, tmp_path)
    assert "design/_prompt.md" in out, out
    assert "_prompt_step_" not in out, out


def test_status_multipick_phase_uses_placeholder(monkeypatch, tmp_path):
    """A phase with MULTIPLE required picks (review-lite: 3) must emit the
    `--pick N` placeholder, never a concrete id — only a single-required-pick
    phase (build) names the id. Guards the multi-pick branch of _ack_command."""
    _seed(tmp_path, "KLC-904", phase="review-lite:work")
    out = _status_out("KLC-904", monkeypatch, tmp_path)
    assert "--pick N" in out, out
    assert "--pick 1" not in out, out
    assert "--pick 2" not in out and "--pick 3" not in out, out


# --- AC-3 + AC-4(ts): shim-parity — the regexes the fixed reader uses must
#     parse the shims `klc install` actually writes. ------------------------- #

def _load_install():
    path = PHASES_DIR / "install.py"
    spec = importlib.util.spec_from_file_location("klc_phase_install_072", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolve_fw(text: str) -> str | None:
    """Python mirror of klcReader.ts resolveFrameworkRoot's KLC_FW parsing.

    Kept in lockstep with the four ordered matchers in the reader so shim-parity
    (and the apostrophe-path handling from KLC-072's re-review) is actually
    asserted rather than approximated by a single lenient regex.
    """
    m = re.search(r'KLC_FW\s*=\s*"([^"\n]*)"', text)  # bash double-quoted
    if m:
        return m.group(1).strip()
    m = re.search(r"KLC_FW\s*=\s*'((?:[^'\n]|'')*)'", text)  # ps1 single-quoted
    if m:
        return m.group(1).replace("''", "'").strip()
    m = re.search(r'KLC_FW=([^"\n]*)"', text)  # cmd: set "KLC_FW=…"
    if m:
        return m.group(1).strip()
    m = re.search(r"KLC_FW\s*=\s*([^\"'\n]+)", text)  # bare/unquoted fallback
    if m:
        return m.group(1).strip()
    return None


def test_klc_fw_regex_parses_bash_shim(tmp_path):
    inst = _load_install()
    fw = Path("/opt/klc-framework")
    body = inst._shim_source(fw, tmp_path)
    assert _resolve_fw(body) == str(fw), body


def test_klc_fw_regex_parses_cmd_shim(tmp_path):
    inst = _load_install()
    fw = Path("/opt/klc-framework")
    body = inst._shim_source_cmd(fw, tmp_path)
    assert _resolve_fw(body) == str(fw).replace("/", "\\"), body


def test_klc_fw_regex_parses_ps1_shim(tmp_path):
    inst = _load_install()
    fw = Path("/opt/klc-framework")
    body = inst._shim_source_ps1(fw, tmp_path)
    assert _resolve_fw(body) == str(fw).replace("/", "\\"), body


# --- KLC-072 re-review: a framework path containing an apostrophe must resolve
#     for each shim quoting style (the old `[^"'\n]+` class truncated at `'`). - #

def test_klc_fw_bash_shim_with_apostrophe():
    body = 'KLC_FW="/Users/o\'brien/klc"\nexec "$KLC_FW/scripts/klc" "$@"\n'
    assert _resolve_fw(body) == "/Users/o'brien/klc", body


def test_klc_fw_cmd_shim_with_apostrophe():
    body = 'set "KLC_FW=C:\\Users\\o\'brien\\klc"\r\npython "%KLC_FW%\\scripts\\klc" %*\r\n'
    assert _resolve_fw(body) == "C:\\Users\\o'brien\\klc", body


def test_klc_fw_ps1_shim_with_escaped_apostrophe():
    # PowerShell escapes a single quote inside a single-quoted string by doubling.
    body = "$env:KLC_FW = 'C:\\Users\\O''Brien\\klc'\n& python \"$env:KLC_FW\\scripts\\klc\" @args\n"
    assert _resolve_fw(body) == "C:\\Users\\O'Brien\\klc", body


def test_reader_source_matches_klc_fw():
    """The shipped klcReader.ts must contain the actual load-bearing KLC_FW
    matcher literal — not merely mention KLC_FW in a comment. A revert to
    KLC_FRAMEWORK_ROOT/$FW-only would drop this substring."""
    reader = (FW_ROOT / "vscode-extension" / "src" / "klcReader.ts").read_text(
        encoding="utf-8")
    assert r'KLC_FW\s*=\s*"([^"\n]*)"' in reader, \
        "klcReader.ts has no load-bearing KLC_FW regex (only a comment/legacy?)"


def test_reader_source_resolves_build_step_card():
    """buildTicketState must pass the build step into promptCardPath (so the
    per-step card resolves, not just flat _prompt.md), and mirror status.py's
    `or 1` fallback with `|| 1` (KLC-072 re-review parity)."""
    reader = (FW_ROOT / "vscode-extension" / "src" / "klcReader.ts").read_text(
        encoding="utf-8")
    assert "promptCardPath(workspaceRoot, ticketKey, phaseId, buildStep)" in reader, \
        "buildTicketState does not wire buildStep into promptCardPath"
    assert "_prompt_step_" in reader, "reader never resolves a per-step card"
    assert "meta.impl_step || 1" in reader, \
        "reader uses `?? 1` (0 -> step 0) instead of `|| 1` parity with status.py"


def test_tree_source_includes_required_single_pick():
    """buildAckCommand must emit --pick <id> for a single required pick."""
    tree = (FW_ROOT / "vscode-extension" / "src" / "treeProvider.ts").read_text(
        encoding="utf-8")
    # a single-required-pick branch must exist (picks.length === 1 -> --pick id)
    assert re.search(r"picks\.length\s*===\s*1", tree), \
        "treeProvider buildAckCommand has no single-required-pick branch"
