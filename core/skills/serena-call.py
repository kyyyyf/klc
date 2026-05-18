#!/usr/bin/env python3
"""serena-call.py — policy and cache layer around Serena MCP queries.

Policy (enforced by `check`):
  1. Track-aware: XS forbids Serena in every phase; S only in `build`;
     M in design/impl/build/review; L in every phase. Defaults match
     `framework-changes.md` section 4.1. Overridable per project via
     `.klc/config/serena-policy.yml`.
  2. Denylist: `.klc/knowledge/serena-deny.yml` (falls back to the
     framework-shipped seed at `framework/config/serena-deny.yml`).
     Each entry has `pattern` (regex against "<operation> <subject>"
     joined by space) and `reason` (echoed on hit).

Cache (`lookup` / `save`):
  - Per-ticket at `.klc/tickets/<ticket>/serena-cache/`.
  - Key: SHA1 of "<op>|<symbol>|<file>|<line>" — deterministic, so
    identical queries within a ticket hit the same file.
  - Invalidates when the source file's git blob SHA changes; the cache
    never lies about which source state it describes.

Contract with the agent (documented in agent prompts):

    1. Before calling Serena, run
       `serena-call.py check --ticket T --op O --subject S [--file F --line L]`.
       Outputs one of:
         ALLOWED
         CACHED <absolute-cache-path>
         DENIED <reason>
       The agent MUST NOT call Serena when DENIED.
    2. After a live Serena call, run
       `serena-call.py save --ticket T --op O --subject S [--file F --line L]
                            --payload <path-to-answer-json>`.

Subcommands:
  check      — evaluate policy + cache, print the verdict
  save       — write a live Serena answer to cache
  lookup     — print cached answer (or exit 1 if none)
  status     — print summary per ticket (hits, misses, denies)

The skill is pure policy + I/O; it never calls Serena itself.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import (  # noqa: E402
    framework_root,
    klc_serena_deny_file,
    klc_ticket_dir,
    klc_ticket_meta_file,
    klc_ticket_serena_cache_dir,
    project_root,
)

# --- policy: track → phase whitelist ------------------------------------------
# Keys: track label (XS / S / M / L). Values: set of *semantic* phases
# (categories of work) in which Serena is allowed. Empty set =
# forbidden everywhere. These phase names are deliberately distinct
# from `lifecycle.PHASES` (which enumerates micro-states like
# `build-pending`, `review-pending-ack`, ...). Phase scripts pass the
# semantic label via `--phase`; if omitted, we map from the lifecycle
# state via _phase_to_semantic below.
DEFAULT_POLICY: dict[str, set[str]] = {
    "XS": set(),
    "S":  {"build"},
    "M":  {"design", "impl", "build", "review"},
    "L":  {"discovery", "design", "impl", "build", "review", "learn"},
}

# State-string → semantic-phase mapping. Called only when `--phase` is
# not passed explicitly. New-format states are `<phase-id>:<state>`; we
# map by phase-id (the state suffix doesn't matter for track-gate
# purposes). Legacy lifecycle states are kept here so old meta.json
# files still resolve to a sane semantic bucket until they're migrated.
SEMANTIC_BY_PHASE_ID: dict[str, str] = {
    "intake":              "intake",
    "discovery":           "discovery",
    "acceptance-test-plan": "test-plan",
    "detailed-test-plan":  "test-plan",
    "design":              "design",
    "build":               "build",
    "review":              "review",
    "manual":              "manual",
    "integrate":           "integrate",
    "observe":             "observe",
    "learn":               "learn",
    "archived":            "archived",
}

LEGACY_LIFECYCLE_TO_SEMANTIC: dict[str, str] = {
    "intake":                     "intake",
    "discovery-running":          "discovery",
    "discovery-pending-ack":      "discovery",
    "test-plan-pending":          "test-plan",
    "design-pending":             "design",
    "design-pending-ack":         "design",
    "detailed-test-plan-pending": "test-plan",
    "build-pending":              "build",
    "review-pending":             "review",
    "review-pending-ack":         "review",
    "manual-pending":             "manual",
    "manual-pending-ack":         "manual",
    "integrate-pre":              "integrate",
    "integrate-post":             "integrate",
    "observe":                    "observe",
    "learn":                      "learn",
    "archived":                   "archived",
}


def _phase_to_semantic(phase_value: str) -> str:
    """Map the meta.json:phase value (new or legacy format) to a
    semantic-phase string. Returns '' on unknown input."""
    if not phase_value:
        return ""
    if ":" in phase_value:
        pid = phase_value.split(":", 1)[0]
        return SEMANTIC_BY_PHASE_ID.get(pid, "")
    # legacy fallback
    return LEGACY_LIFECYCLE_TO_SEMANTIC.get(phase_value, "")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml_deny(path: Path) -> list[dict]:
    """Minimal YAML reader sufficient for the deny-list shape.

    Avoids the PyYAML hard dependency: the file is small, structurally
    simple (list of maps with string values), and pulling a fat parser
    for 10-line files adds a transitive dep to every skill.
    """
    if not path.exists():
        return []
    entries: list[dict] = []
    current: dict | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        if stripped.startswith("- "):
            if current:
                entries.append(current)
            current = {}
            stripped = stripped[2:].strip()
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                current[k.strip()] = v.strip().strip('"').strip("'")
        elif ":" in stripped and current is not None:
            k, _, v = stripped.partition(":")
            current[k.strip()] = v.strip().strip('"').strip("'")
    if current:
        entries.append(current)
    return [e for e in entries if e.get("pattern")]


def _load_denylist() -> list[dict]:
    """Project denylist overrides the framework seed; neither is required."""
    project = klc_serena_deny_file()
    if project.exists():
        return _load_yaml_deny(project)
    return _load_yaml_deny(framework_root() / "config" / "serena-deny.yml")


def _load_track_policy() -> dict[str, set[str]]:
    """Per-project override lives at `.klc/config/serena-policy.yml` with
    shape `{XS: [...], S: [build, ...], ...}`. Unspecified tracks keep
    their defaults. No override file → use DEFAULT_POLICY as-is."""
    override = project_root() / ".klc" / "config" / "serena-policy.yml"
    if not override.exists():
        return {k: set(v) for k, v in DEFAULT_POLICY.items()}
    merged = {k: set(v) for k, v in DEFAULT_POLICY.items()}
    current_track: str | None = None
    for raw in override.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            current_track = stripped[:-1].strip()
            merged[current_track] = set()
        elif stripped.startswith("- ") and current_track is not None:
            merged[current_track].add(stripped[2:].strip())
    return merged


def _read_ticket_meta(ticket: str) -> dict:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _cache_key(op: str, subject: str, file: str | None, line: int | None) -> str:
    raw = f"{op}|{subject}|{file or ''}|{line if line is not None else ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _git_blob_sha(repo: Path, file_rel: str) -> str | None:
    """Return the SHA of the file's current blob, or None if git can't
    see it (new / untracked / deleted). Invalidation logic compares
    this to the SHA recorded at cache-write time."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-s", "--", file_rel],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = r.stdout.strip()
    if not out:
        return None
    # Format: "<mode> <sha> <stage>\t<path>"
    parts = out.split()
    return parts[1] if len(parts) >= 2 else None


def _cache_path(ticket: str, op: str, subject: str,
                file: str | None, line: int | None) -> Path:
    key = _cache_key(op, subject, file, line)
    return klc_ticket_serena_cache_dir(ticket) / f"{op}-{key}.json"


def _deny_hit(op: str, subject: str, file: str | None) -> dict | None:
    haystack = " ".join(p for p in (op, subject, file or "") if p)
    for entry in _load_denylist():
        pattern = entry.get("pattern")
        if not pattern:
            continue
        try:
            if re.search(pattern, haystack):
                return entry
        except re.error:
            sys.stderr.write(
                f"serena-call: bad regex in denylist: {pattern!r}\n"
            )
    return None


def cmd_check(args: argparse.Namespace) -> int:
    meta = _read_ticket_meta(args.ticket)
    track = (args.track or meta.get("track") or "M").upper()
    # --phase on the CLI is authoritative (phase scripts pass a
    # semantic label). If omitted, map from the lifecycle state in
    # meta.json via LIFECYCLE_TO_SEMANTIC. The pre-map value in meta
    # is NOT a valid Serena phase; using it directly would always
    # trip the whitelist.
    if args.phase:
        phase = args.phase.lower()
    else:
        phase = _phase_to_semantic((meta.get("phase") or "").lower())
        if not phase:
            # Unknown state — no safe mapping. Fall back to the most
            # restrictive interpretation: pretend we're in a category
            # absent from every track's whitelist, so the gate denies.
            # Caller should pass --phase explicitly.
            phase = "unknown"

    # 1. Track-aware gate.
    policy = _load_track_policy()
    allowed_phases = policy.get(track, set())
    if phase not in allowed_phases:
        reason = (
            f"track={track} does not allow Serena in phase={phase}; "
            f"allowed phases: {sorted(allowed_phases) or 'none'}"
        )
        print(f"DENIED {reason}")
        _append_log(args.ticket, "denied-track", args, reason)
        return 0

    # 2. Denylist.
    denied = _deny_hit(args.op, args.subject, args.file)
    if denied:
        reason = denied.get("reason") or "matches deny-list entry"
        print(f"DENIED {reason}")
        _append_log(args.ticket, "denied-pattern", args, reason)
        return 0

    # 3. Cache.
    cp = _cache_path(args.ticket, args.op, args.subject, args.file, args.line)
    if cp.exists():
        cached = json.loads(cp.read_text(encoding="utf-8"))
        stored_sha = cached.get("source_sha")
        if args.file:
            live_sha = _git_blob_sha(project_root(), args.file)
            if stored_sha and live_sha and stored_sha == live_sha:
                print(f"CACHED {cp}")
                _append_log(args.ticket, "cache-hit", args, str(cp))
                return 0
        else:
            # No file to compare against — trust the cache within the
            # ticket lifetime. Cheap to regenerate if wrong.
            print(f"CACHED {cp}")
            _append_log(args.ticket, "cache-hit", args, str(cp))
            return 0

    print("ALLOWED")
    _append_log(args.ticket, "allowed", args, "")
    return 0


def cmd_save(args: argparse.Namespace) -> int:
    payload_path = Path(args.payload)
    if not payload_path.exists():
        sys.stderr.write(f"serena-call: payload not found: {payload_path}\n")
        return 1
    try:
        response = json.loads(payload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"serena-call: payload not JSON: {exc}\n")
        return 1

    cp = _cache_path(args.ticket, args.op, args.subject, args.file, args.line)
    cp.parent.mkdir(parents=True, exist_ok=True)
    source_sha = _git_blob_sha(project_root(), args.file) if args.file else None
    record = {
        "operation":    args.op,
        "subject":      args.subject,
        "file":         args.file,
        "line":         args.line,
        "queried_at":   _now_iso(),
        "source_sha":   source_sha,
        "response":     response,
    }
    cp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"SAVED {cp}")
    _append_log(args.ticket, "saved", args, str(cp))
    return 0


def cmd_lookup(args: argparse.Namespace) -> int:
    cp = _cache_path(args.ticket, args.op, args.subject, args.file, args.line)
    if not cp.exists():
        return 1
    sys.stdout.write(cp.read_text(encoding="utf-8"))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cache_dir = klc_ticket_serena_cache_dir(args.ticket)
    log_path = klc_ticket_dir(args.ticket) / "serena-calls.log"
    counts = {"hits": 0, "misses": 0, "denied-track": 0, "denied-pattern": 0, "saved": 0}
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = rec.get("event")
            if ev == "cache-hit":
                counts["hits"] += 1
            elif ev == "allowed":
                counts["misses"] += 1
            elif ev == "denied-track":
                counts["denied-track"] += 1
            elif ev == "denied-pattern":
                counts["denied-pattern"] += 1
            elif ev == "saved":
                counts["saved"] += 1
    cache_files = 0
    if cache_dir.exists():
        cache_files = sum(1 for _ in cache_dir.glob("*.json"))
    print(json.dumps({"ticket": args.ticket, "cache_files": cache_files, **counts}))
    return 0


def _append_log(ticket: str, event: str, args: argparse.Namespace, detail: str) -> None:
    log_path = klc_ticket_dir(ticket) / "serena-calls.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "t":        _now_iso(),
        "event":    event,
        "op":       args.op,
        "subject":  args.subject,
        "file":     getattr(args, "file", None),
        "line":     getattr(args, "line", None),
        "detail":   detail,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _add_query_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ticket", required=True)
    p.add_argument("--op", required=True,
                   help="Serena operation: find_symbol, find_references, "
                        "get_hover_info, get_document_symbols, ...")
    p.add_argument("--subject", required=True,
                   help="symbol name / path / whatever identifies the query")
    p.add_argument("--file", default=None,
                   help="source file (path relative to project root). "
                        "Required for cache invalidation by blob SHA.")
    p.add_argument("--line", type=int, default=None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="policy gate + cache lookup")
    _add_query_args(p_check)
    p_check.add_argument("--track", default=None,
                         help="XS|S|M|L; falls back to meta.json")
    p_check.add_argument("--phase", default=None,
                         help="discovery|design|impl|build|review|learn; "
                              "falls back to meta.json")
    p_check.set_defaults(func=cmd_check)

    p_save = sub.add_parser("save", help="store a Serena answer in cache")
    _add_query_args(p_save)
    p_save.add_argument("--payload", required=True,
                        help="path to a JSON file with the Serena response")
    p_save.set_defaults(func=cmd_save)

    p_lookup = sub.add_parser("lookup", help="emit cached record (or exit 1)")
    _add_query_args(p_lookup)
    p_lookup.set_defaults(func=cmd_lookup)

    p_status = sub.add_parser("status", help="print hit/miss/denied counts")
    p_status.add_argument("--ticket", required=True)
    p_status.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
