#!/usr/bin/env python3
"""index_fingerprint.py — per-file fingerprints and the full-rebuild fallback
decision (KLC-121).

Language-agnostic by construction (C-001, AC-9): no line below names a file
extension, a programming-language, or an external tool. Everything here
branches on nothing but a path string and the bytes at that path.

`build_map()`/`check_map()` (step-3) publish and validate the per-file
digest map `structural.json` carries. `REASONS`/`identity_of`/`decide`/
`format_line()` (step-4) turn a comparison against the previous artifact
into exactly one honest log line per run.

No producer consumes the fingerprint map to skip work on this ticket
(spec.md non-goals) — it is written and read back for the AC-6 fallback
comparison only. Consuming it to reprocess only changed files is KLC-125.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = 1
FINGERPRINT_ALGO = "sha256"
_CHUNK = 1 << 20


def build_map(root: Path, files_rel: list[str]) -> dict:
    """path -> {"sha256", "size"} for every member of *files_rel*. A path
    that cannot be read (removed between universe resolution and the
    digest pass, a broken symlink, ...) is simply omitted — `check_map()`
    then names it (C-005: degrade, never raise)."""
    out: dict[str, dict] = {}
    for rel in files_rel:
        h = hashlib.sha256()
        size = 0
        try:
            with (Path(root) / rel).open("rb") as fh:
                for chunk in iter(lambda: fh.read(_CHUNK), b""):
                    h.update(chunk)
                    size += len(chunk)
        except OSError:
            continue
        out[rel] = {"sha256": h.hexdigest(), "size": size}
    return out


def check_map(structural: dict) -> list[str]:
    """AC-1's negative twin: a fingerprint map that is short (or absent
    entirely, or a non-map JSON value) must be named, path by path, never
    silently accepted. Returns `[]` when the map is complete."""
    files = structural.get("files")
    if not isinstance(files, dict):
        return ["fingerprint map absent or not an object"]
    universe = set(structural.get("files_rel") or [])
    missing = [p for p in universe if p not in files]
    extra = [p for p in files if p not in universe]
    return (
        [f"fingerprint map missing: {p}" for p in sorted(missing)]
        + [f"fingerprint map has a non-universe path: {p}" for p in sorted(extra)]
    )


# ---------------------------------------------------------------------------
# step-4: the full-rebuild fallback decision, and the one honest log line.
# ---------------------------------------------------------------------------

REASON_FULL_FLAG   = "--full flag"
REASON_ABSENT      = "previous artifact absent"
REASON_UNPARSEABLE = "previous artifact unparseable"
REASON_SCHEMA      = "schema_version mismatch"
REASON_ALGO        = "fingerprint_algo mismatch"
REASON_UNIVERSE    = "files_rel_source mismatch"
REASON_PROFILE     = "profile identity mismatch"
REASONS = (REASON_FULL_FLAG, REASON_ABSENT, REASON_UNPARSEABLE, REASON_SCHEMA,
           REASON_ALGO, REASON_UNIVERSE, REASON_PROFILE)

# C-004: every branch here IS a full rebuild — no producer skips a file on
# this ticket. Naming it "not yet implemented" rather than anything that
# could read as a skip is the specific defect this constant exists to avoid.
NOT_YET = "full rebuild (incremental merge not yet implemented — KLC-125)"

UNPARSEABLE = "unparseable"


def read_previous_structural(path: Path) -> dict | str | None:
    """The previous run's `structural.json`, read BEFORE the scan
    overwrites it: a dict on success, the sentinel string "unparseable"
    (C-005: degrade, never raise) when the file exists but is not valid
    JSON, or `None` when it is absent entirely."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return UNPARSEABLE


def identity_of(structural: dict) -> dict:
    """The four fields a rebuild decision compares. `structural` here is
    always a genuine dict — the caller has already handled the
    absent/unparseable cases before this is called."""
    return {k: structural.get(k) for k in
            ("schema_version", "fingerprint_algo", "files_rel_source", "profile_identity")}


def decide(previous: dict | str | None, current: dict, *, forced_full: bool = False) -> str | None:
    """The FIRST matching condition, in the fixed precedence D-005 sets, or
    `None` when none fired — returning a single reason is what makes
    "exactly one line" true even when several conditions hold at once."""
    if forced_full:
        return REASON_FULL_FLAG
    if previous is None:
        return REASON_ABSENT
    if previous == UNPARSEABLE:
        return REASON_UNPARSEABLE
    prev, cur = identity_of(previous), identity_of(current)
    for key, reason in (("schema_version", REASON_SCHEMA),
                        ("fingerprint_algo", REASON_ALGO),
                        ("files_rel_source", REASON_UNIVERSE),
                        ("profile_identity", REASON_PROFILE)):
        if prev.get(key) != cur.get(key):
            return reason
    return None


def format_line(reason: str | None) -> str:
    """C-004: every branch here IS a full rebuild and says so. No wording
    on any branch may suggest that work was skipped."""
    return NOT_YET if reason is None else f"full rebuild (reason: {reason})"
