#!/usr/bin/env python3
"""KLC-177 step-4 — dispatcher surface: help, hidden aliases, `internal` namespace.

AC-8: next/ack/ship/run/jump/abort stay callable and print exactly one
deprecation line on stderr; `klc work` is gone (unknown subcommand, exit 2).
AC-9: the help lists only intake/status/go/back/`step verify` plus one "Also:"
line, and every moved maintainer verb still runs as `klc internal <name>`.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

FW = Path(__file__).resolve().parents[2]
KLC = FW / "scripts" / "klc"

REMOVED_FROM_HELP = ("task-brief", "build-run", "jira-sync",
                     "steal", "reindex", "metrics", "migrate-notes", "skeleton",
                     "plugin-gen")
ALSO = ("board", "doctor", "jira", "publish")


def _klc(argv, root: Path):
    p = subprocess.run([sys.executable, str(KLC), *argv], capture_output=True,
                       text=True, env={**os.environ, "PROJECT_ROOT": str(root)})
    return p.returncode, p.stdout, p.stderr


def _module():
    loader = importlib.machinery.SourceFileLoader("klc_dispatcher_177", str(KLC))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _ticket(root: Path, key: str, phase: str, track: str = "S") -> Path:
    td = root / ".klc" / "tickets" / key
    td.mkdir(parents=True)
    (td / "meta.json").write_text(json.dumps({
        "ticket": key, "kind": "feature", "phase": phase, "track": track,
        "phase_history": [], "rework_count": {}, "affected_modules": [],
        "created": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    return td


def test_old_verbs_print_one_deprecation_line_and_work_is_gone(tmp_path):
    cases = {
        "next": ["next", "NOPE-1"], "ack": ["ack", "NOPE-1"], "ship": ["ship", "NOPE-1"],
        "run": ["run", "NOPE-1"], "jump": ["jump", "design", "NOPE-1"],
        "abort": ["abort", "NOPE-1"],
    }
    for verb, argv in cases.items():
        rc, out, err = _klc(argv, tmp_path)
        lines = [l for l in err.splitlines() if "deprecated" in l]
        assert len(lines) == 1, (verb, err)
        assert lines[0].startswith(f"klc {verb} is deprecated: use klc "), lines[0]
        target = "back" if verb in ("jump", "abort") else "go"
        assert f"use klc {target}" in lines[0], lines[0]
        assert "unknown subcommand" not in err, (verb, err)
    # the alias still does its old work: a terminal ticket is refused by `next`
    _ticket(tmp_path, "T-DEP", "cancelled")
    rc, out, err = _klc(["next", "T-DEP"], tmp_path)
    assert rc != 0 and "cancelled" in (out + err).lower()
    # `run` keeps dispatching through the old headless path (not `go --until`)
    assert "go <KEY> --until <phase>" in _klc(["run", "NOPE-1"], tmp_path)[2]

    rc, out, err = _klc(["work", "T-DEP"], tmp_path)
    assert rc == 2
    assert "unknown subcommand: work" in err
    assert not (FW / "core" / "phases" / "work.py").exists()
    # the new verbs print no deprecation line
    rc, out, err = _klc(["go", "T-DEP", "--dry-run"], tmp_path)
    assert "deprecated" not in err


def test_help_text_tuples_and_internal_namespace(tmp_path):
    rc, out, err = _klc(["--help"], tmp_path)
    assert rc == 0
    assert "seven" not in out
    for verb in ("intake", "status", "go", "back", "step verify"):
        assert verb in out, verb
    for gone in REMOVED_FROM_HELP:
        assert gone not in out, gone
    for old in ("next", "ack", "ship", "jump", "abort", "work"):
        assert f"\n    {old} " not in out, old
    also = [l for l in out.splitlines() if l.strip().startswith("Also:")]
    assert len(also) == 1, out
    for verb in ALSO:
        assert verb in also[0], verb

    mod = _module()
    assert tuple(mod.LIFECYCLE_CMDS) == ("intake", "status", "go", "back", "step", "fix")
    assert "work" not in mod.LIFECYCLE_CMDS and "work" not in mod.NO_DRAIN_CMDS
    for verb in REMOVED_FROM_HELP:
        assert verb not in mod.LIFECYCLE_CMDS and verb not in mod.OPERATIONAL_CMDS, verb
    assert set(mod.DEPRECATED) == {"next", "ack", "ship", "run", "jump", "abort", "retrack",
                                   "scope-fix"}
    assert set(REMOVED_FROM_HELP) | {"step-card"} <= set(mod.INTERNAL_CMDS)

    # klc internal <name> reaches every moved verb (no "unknown subcommand")
    _ticket(tmp_path, "T-INT", "build:work")
    for name, argv in (("task-brief", []), ("build-run", []), ("jira-sync", ["status"]),
                       ("reindex", []), ("metrics", []), ("migrate-notes", ["--help"]),
                       ("skeleton", []), ("plugin-gen", ["--help"]),
                       ("steal", ["T-INT"]), ("step-card", [])):
        rc, o, e = _klc(["internal", name, *argv], tmp_path)
        assert "unknown subcommand" not in e, (name, e)
        assert "not implemented" not in e, (name, e)
        assert "deprecated" not in e, (name, e)
    rc, o, e = _klc(["internal"], tmp_path)
    assert rc == 2 and "usage: klc internal" in e
    rc, o, e = _klc(["internal", "bogus"], tmp_path)
    assert rc == 2 and "usage: klc internal" in e
    # KLC-180: the retired hook verbs are no longer reachable at all
    for name in ("remind", "heartbeat"):
        rc, o, e = _klc(["internal", name], tmp_path)
        assert rc == 2 and "usage: klc internal" in e, name
