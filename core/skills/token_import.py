#!/usr/bin/env python3
"""token_import.py — KLC-172 AC-1: import REAL token usage from Claude Code
subagent transcripts into the per-ticket telemetry (`source: transcript`).

Why: the old path recorded `estimated` attempts derived from prompt-card
sizes, which are fiction. Claude Code already writes the true usage of every
subagent run to `~/.claude/projects/<slug>/<session>/subagents/agent-<id>.jsonl`
(plus `agent-<id>.meta.json` with the agent type); this module sums it.

Writes through the single writer `budget_guard.write_token_metrics`. The
attempt id is deterministic (`tr` + sha1 of the agent id), so re-running the
import never double-counts a run.

    python3 core/skills/token_import.py [--project-dir DIR] [--ticket KEY] [--include-live]

The ticket of a run is the key named in the subagent's first user message
(the first key-shaped token that has a ticket on disk); `--ticket` is only
the fallback for runs that name none. A transcript touched in the last
10 minutes may still be running, so it is skipped unless `--include-live`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

import _paths  # noqa: E402
import budget_guard  # noqa: E402
import metrics  # noqa: E402
import ticket_id  # noqa: E402

LIVE_WINDOW_S = 600   # a transcript younger than this may still be in progress


def default_project_dir(cwd: Path | None = None) -> Path:
    """Claude Code's per-project transcript dir: the project root (PROJECT_ROOT
    when set, else the cwd) with every non-alphanumeric character -> '-'."""
    root = Path(cwd) if cwd is not None else (
        _paths.project_root() if os.environ.get("PROJECT_ROOT") else Path.cwd())
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root))


def _text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def _scan(path: Path) -> dict:
    """Sum one transcript: usage per message id (last seen wins), model,
    first timestamp and the first user message text."""
    usage: dict[str, dict] = {}
    model = ts = first_user = None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raw = ""
    for line in raw.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        if ts is None and isinstance(obj.get("timestamp"), str):
            ts = obj["timestamp"]
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        if obj.get("type") == "user" and first_user is None:
            first_user = _text_of(msg)
        elif obj.get("type") == "assistant":
            if not model and msg.get("model"):
                model = msg["model"]
            u = msg.get("usage")
            if isinstance(u, dict):
                usage[msg.get("id") or f"_line{len(usage)}"] = u

    def total(key: str) -> int:
        return sum(v for v in (u.get(key) for u in usage.values())
                   if type(v) is int)
    return {"in": total("input_tokens"), "out": total("output_tokens"),
            "cache_hit": total("cache_read_input_tokens"),
            "cache_write": total("cache_creation_input_tokens"),
            "model": model, "ts": ts, "first_user": first_user or ""}


def _phase_for(agent_type: str | None) -> str:
    t = agent_type or ""
    if t.startswith("klc-"):
        import phases
        prompt = f"core/agents/{t.removeprefix('klc-')}.md"
        for p in phases.load_phases().ordered:
            if p.prompt == prompt:
                return p.id
    if "review" in t:
        return "review"
    return "other"


def _infer_key(text: str) -> str | None:
    """The first key-shaped token of *text* that names a ticket on disk —
    `AC-2` / `UTF-8` come first in many briefs but have no meta.json."""
    for cand in ticket_id.find_keys(text):
        if _paths.klc_ticket_meta_file(cand).exists():
            return cand
    return None


def import_transcripts(project_dir: Path, *, ticket: str | None = None,
                       include_live: bool = False) -> list[dict]:
    """Import every not-yet-recorded subagent transcript under *project_dir*.
    The key in the run's first message wins; *ticket* is the fallback.
    Returns the attempt records written (as stored)."""
    existing: dict[str, set] = {}
    bad_meta: set[str] = set()
    written: list[dict] = []
    now = time.time()
    for path in sorted(Path(project_dir).glob("*/subagents/agent-*.jsonl")):
        try:
            if not include_live and now - path.stat().st_mtime < LIVE_WINDOW_S:
                continue
        except OSError:
            continue
        agent_id = path.stem.removeprefix("agent-")
        scan = _scan(path)
        key = _infer_key(scan["first_user"]) or ticket
        if not key or key in bad_meta or not _paths.klc_ticket_meta_file(key).exists():
            continue
        if key not in existing:
            try:
                meta = json.loads(_paths.klc_ticket_meta_file(key).read_text(encoding="utf-8"))
                existing[key] = {r.get("id") for _, r in metrics.iter_attempts(meta, key)}
            except (OSError, ValueError) as exc:
                bad_meta.add(key)
                sys.stderr.write(f"token_import: {key}: unreadable meta.json "
                                 f"({exc}); its agents are skipped\n")
                continue
        attempt_id = "tr" + hashlib.sha1(agent_id.encode()).hexdigest()[:10]
        if attempt_id in existing[key]:
            continue
        info: dict = {}
        try:
            info = json.loads(path.with_name(f"agent-{agent_id}.meta.json")
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        agent_type = info.get("agentType") if isinstance(info, dict) else None
        phase = _phase_for(agent_type)
        budget_guard.write_token_metrics(
            key, phase, scan["in"], scan["out"], scan["cache_hit"],
            source="transcript", card_bytes=None, attempt_id=attempt_id,
            ts=scan["ts"], cache_write=scan["cache_write"],
            model=scan["model"], agent_id=agent_id, agent_type=agent_type)
        rec = budget_guard.attempt_record(
            scan["in"], scan["out"], scan["cache_hit"], "transcript", None,
            attempt_id=attempt_id, ts=scan["ts"], cache_write=scan["cache_write"],
            model=scan["model"], agent_id=agent_id, agent_type=agent_type)
        existing[key].add(attempt_id)
        written.append(rec)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project-dir", type=Path, default=None)
    ap.add_argument("--ticket", default=None,
                    help="fallback ticket for runs whose first message names none")
    ap.add_argument("--include-live", action="store_true",
                    help="also import transcripts touched in the last 10 minutes")
    args = ap.parse_args(argv)
    pdir = args.project_dir or default_project_dir()
    recs = import_transcripts(pdir, ticket=args.ticket, include_live=args.include_live)
    print(f"imported {len(recs)} attempt(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
