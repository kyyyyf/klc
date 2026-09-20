#!/usr/bin/env python3
"""profile_cache.py — the ONE accessor every builder reads a profile field
through (KLC-121, ADR-005 D-101/D-102).

A klc index run resolves the active profile exactly once, at its entry
point (`scripts/init.py` or `scripts/update.py`), via `run_scope()`, and
hands the result to every child and grandchild process through the
`KLC_PROFILE_PAYLOAD` environment variable. Every builder that used to
shell out to `core/skills/profile-resolve.py` on its own now calls
`field()` here instead: `field()` reads the handed-down payload when the
current process was launched inside such a run, and spawns
`profile-resolve.py --field <name>` for itself — exactly as it does
today — when no run handed one down (C-007: the handoff is an
optimisation, never a precondition; every builder stays independently
runnable from a shell).

This module imports no YAML, directly or transitively (D-001):
`tdd_order.verify_step` is a hard ack-gate import of `test_conventions`,
and `test_conventions._read_profile_conventions` becomes a caller of
this module, so a yaml import here would silently re-introduce the
dependency KLC-109's design removed. All manifest parsing stays inside
the `profile-resolve.py` subprocess, where it already lives.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

_file_dir = Path(__file__).resolve().parent
if str(_file_dir) not in sys.path:
    sys.path.insert(0, str(_file_dir))
from _paths import project_root as _project_root  # noqa: E402  (the one PROJECT_ROOT reader)

ENV_PAYLOAD = "KLC_PROFILE_PAYLOAD"
_RESOLVER = _file_dir / "profile-resolve.py"


def resolve_profile_once() -> dict:
    """Spawn `profile-resolve.py --all-fields` exactly once and wrap its
    output with the root it was resolved for and the identity digest
    (D-009). Returns ``{"root", "identity", "fields"}`` where every value
    in ``fields`` is the exact string ``--field <key>`` would have
    printed (D-003) — `field()` is then a dict lookup with no formatting
    logic of its own, so a handed-down builder and a standalone one parse
    the same string either way.

    Degrades to an empty field map on any spawn failure (C-005): a
    profile hiccup must never propagate into a builder that would
    otherwise complete."""
    try:
        r = subprocess.run([sys.executable, str(_RESOLVER), "--all-fields"],
                           capture_output=True, text=True, timeout=15)
        fields = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        fields = {}
    canon = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return {
        "root": str(_project_root()),
        "identity": {
            "name": fields.get("name") or "generic",
            "fields_sha256": hashlib.sha256(canon.encode("utf-8")).hexdigest(),
        },
        "fields": fields,
    }


def handed_down() -> dict | None:
    """The run's payload, or ``None`` when absent, unparseable, or
    resolved for a DIFFERENT root (D-004) — the same guard
    `file_universe.resolve` already applies to `structural.json`: a
    builder run against a temp fixture must not silently inherit the
    ambient project's profile from an environment variable a parent
    shell still holds."""
    raw = os.environ.get(ENV_PAYLOAD)
    if not raw:
        return None
    try:
        p = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(p, dict):
        return None
    try:
        same_root = Path(str(p.get("root", ""))).resolve() == _project_root().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if not same_root:
        return None
    return p


def field(name: str) -> str:
    """What `profile-resolve.py --field <name>` would print, stripped.
    Degrades to "" exactly as every caller does today (C-007): a builder
    never REQUIRES a handed-down payload, and a spawn failure never
    raises out of here."""
    p = handed_down()
    if p is not None:
        return str((p.get("fields") or {}).get(name, "")).strip()
    try:
        r = subprocess.run([sys.executable, str(_RESOLVER), "--field", name],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip()


def identity() -> dict:
    """{"name", "fields_sha256"} for the profile this run resolved
    (D-203): the handed-down payload's identity when one is present and
    valid for THIS root, a fresh `resolve_profile_once()` otherwise — the
    same handed-down/fall-through shape as `field()`, so a standalone
    `file_scanner` writes the same `profile_identity` a run-launched one
    does (AC-4)."""
    p = handed_down()
    return p["identity"] if p is not None else resolve_profile_once()["identity"]


@contextmanager
def run_scope(payload: dict | None = None):
    """The ONE resolution point per run (D-101, AC-3). Sets *payload* (a
    fresh `resolve_profile_once()` when none is given) into the process
    environment for the duration of the `with` block and restores whatever
    was there before on exit — so an in-process test caller leaks nothing
    into the next test, and a nested `run_scope()` (an in-process caller
    already inside one) still round-trips correctly.

    `scripts/init.py` and `scripts/update.py` open this once, around
    everything they do. Neither script passes `env=` to any of its
    subprocess.run calls, so every child and grandchild builder simply
    inherits `KLC_PROFILE_PAYLOAD` — the handoff needs zero changes at any
    spawn site."""
    payload = payload if payload is not None else resolve_profile_once()
    before = os.environ.get(ENV_PAYLOAD)
    os.environ[ENV_PAYLOAD] = json.dumps(payload, ensure_ascii=False)
    try:
        yield payload
    finally:
        if before is None:
            os.environ.pop(ENV_PAYLOAD, None)
        else:
            os.environ[ENV_PAYLOAD] = before
