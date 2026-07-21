#!/usr/bin/env python3
"""jira_sync.py — push klc phase transitions to Jira (one-way).

Called from lifecycle.set_state() after every phase write.
Never raises — all errors are caught and either queued or logged.

Transports
----------
rest  — direct HTTP to Jira REST API v3 (default)
mcp   — JSON-RPC over HTTP to a running mcp-atlassian instance

Configuration
-------------
config/jira.yml  (framework defaults)
.klc/config/jira.yml  (per-project override, merged on top)

sync.enabled must be explicitly set to true; default is false.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Any

# Add project root to sys.path for core.shared imports
_file_dir = Path(__file__).resolve().parent
_project_root = _file_dir.parent.parent  # current -> parent -> project root
sys.path.insert(0, str(_project_root))
from core.shared.paths import framework_root, project_root, klc_dir  # noqa: E402


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Merge framework jira.yml + per-project .klc/config/jira.yml."""
    try:
        import yaml
    except ImportError:
        return {}

    fw_cfg = framework_root() / "config" / "jira.yml"
    proj_cfg = klc_dir() / "config" / "jira.yml"

    cfg: dict = {}
    for path in (fw_cfg, proj_cfg):
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            _deep_merge(cfg, data)
    return cfg


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _sync_cfg(cfg: dict) -> dict:
    return cfg.get("sync") or {}


# ---------------------------------------------------------------------------
# Phase → Jira status resolution
# ---------------------------------------------------------------------------

def _resolve_status(phase: str, sync: dict) -> str | None:
    """Map a full phase string (e.g. 'build:work') to a Jira status name.

    Lookup order:
      1. Exact match on full phase string (e.g. 'build:work').
      2. Match on phase id only (e.g. 'build').
      3. Special terminal sentinels 'archived' / 'cancelled' (KLC-076).
    Returns None if no mapping found.
    """
    mapping: dict = sync.get("phase_to_status") or {}
    if not mapping:
        return None

    if phase in mapping:
        return mapping[phase]

    phase_id = phase.split(":")[0] if ":" in phase else phase
    if phase_id in mapping:
        return mapping[phase_id]

    # Terminal sentinels: a terminal phase owns no `<id>:<state>` form, so it is
    # looked up by its bare name. `cancelled` (KLC-076) sits parallel to
    # `archived` so a cancelled ticket is not left desynced in its old Jira
    # status; both require the operator to configure the key in phase_to_status.
    if phase in ("archived", "cancelled") and phase in mapping:
        return mapping[phase]

    return None


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

def _queue_path() -> Path:
    return klc_dir() / "jira-queue.jsonl"


def queue_size() -> int:
    p = _queue_path()
    if not p.exists():
        return 0
    try:
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        return len(lines)
    except OSError:
        return 0


def _enqueue(ticket: str, phase: str, status: str, source: str) -> None:
    p = _queue_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ticket": ticket,
        "phase":  phase,
        "status": status,
        "source": source,
        "at":     _now(),
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def flush_queue(*, timeout: float = 2.0, quiet: bool = False) -> dict:
    """Drain .klc/jira-queue.jsonl.

    Deduplicates: for each ticket keeps only the latest entry.
    Returns {"sent": N, "failed": N, "remaining": N}.
    """
    p = _queue_path()
    if not p.exists():
        return {"sent": 0, "failed": 0, "remaining": 0}

    try:
        raw = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"sent": 0, "failed": 0, "remaining": 0}

    entries = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # dedup: keep latest per ticket
    latest: dict[str, dict] = {}
    for e in entries:
        latest[e["ticket"]] = e

    cfg = _load_config()
    sync = _sync_cfg(cfg)
    if not sync.get("enabled"):
        return {"sent": 0, "failed": 0, "remaining": len(latest)}

    transport = _make_transport(sync, timeout)
    sent = 0
    failed_entries: list[dict] = []

    for ticket, entry in latest.items():
        try:
            transport.push(ticket, entry["status"])
            _update_last_sync(ticket, entry["status"], entry["phase"])
            sent += 1
            if not quiet:
                print(f"[jira-sync] flushed {ticket} → {entry['status']}")
        except Exception as exc:
            if not quiet:
                sys.stderr.write(f"[jira-sync] flush failed {ticket}: {exc}\n")
            failed_entries.append(entry)

    # rewrite queue with only failed entries
    try:
        if failed_entries:
            p.write_text(
                "\n".join(json.dumps(e) for e in failed_entries) + "\n",
                encoding="utf-8",
            )
        else:
            p.unlink(missing_ok=True)
    except OSError:
        pass

    return {"sent": sent, "failed": len(failed_entries), "remaining": len(failed_entries)}


# ---------------------------------------------------------------------------
# Main entry point called from lifecycle.set_state()
# ---------------------------------------------------------------------------

def push_phase(ticket: str, phase: str, *, source: str = "set_state") -> None:
    """Push a phase transition to Jira.

    1. Load config; if sync.enabled=False → no-op.
    2. Resolve target Jira status from phase mapping.
    3. Skip if status matches last known sync for this ticket.
    4. Try transport.push with timeout.
       On success: update jira_last_sync in meta.json.
       On error: enqueue and emit a warning.
    """
    cfg = _load_config()
    sync = _sync_cfg(cfg)
    if not sync.get("enabled"):
        return

    status = _resolve_status(phase, sync)
    if status is None:
        return

    # skip if already at this status
    last = _read_last_sync(ticket)
    if last and last.get("status") == status:
        return

    timeout = float(sync.get("timeout_seconds", 2))
    transport = _make_transport(sync, timeout)

    try:
        transport.push(ticket, status)
        _update_last_sync(ticket, status, phase)
    except Exception as exc:
        sys.stderr.write(f"[jira-sync] warning: {ticket} queued ({exc})\n")
        _enqueue(ticket, phase, status, source)


# ---------------------------------------------------------------------------
# jira_last_sync helpers
# ---------------------------------------------------------------------------

def _meta_path(ticket: str) -> Path:
    from core.shared.paths import klc_ticket_meta_file  # noqa: F401
    return klc_ticket_meta_file(ticket)


def _read_last_sync(ticket: str) -> dict | None:
    try:
        p = _meta_path(ticket)
        if not p.exists():
            return None
        meta = json.loads(p.read_text(encoding="utf-8"))
        return meta.get("jira_last_sync")
    except Exception:
        return None


def _update_last_sync(ticket: str, status: str, phase: str) -> None:
    try:
        p = _meta_path(ticket)
        if not p.exists():
            return
        meta = json.loads(p.read_text(encoding="utf-8"))
        meta["jira_last_sync"] = {"status": status, "phase": phase, "at": _now()}
        p.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    except Exception:
        pass


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Transport factory
# ---------------------------------------------------------------------------

def _make_transport(sync: dict, timeout: float) -> "_Transport":
    kind = sync.get("transport", "rest")
    if kind == "mcp":
        return _McpTransport(sync.get("mcp") or {}, timeout)
    return _RestTransport(sync.get("rest") or {}, timeout)


class _Transport:
    def push(self, ticket: str, status: str) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# REST transport
# ---------------------------------------------------------------------------

class _RestTransport(_Transport):
    def __init__(self, rest_cfg: dict, timeout: float) -> None:
        self._base = (rest_cfg.get("base_url") or "").rstrip("/")
        self._timeout = timeout
        self._auth_env = rest_cfg.get("auth_env") or "JIRA_TOKEN"
        self._user_env = rest_cfg.get("auth_user_env") or ""
        self._cache: dict[str, dict[str, str]] = {}  # project_key → {status_name: transition_id}

    def _token(self) -> str:
        t = os.environ.get(self._auth_env, "")
        if not t:
            raise RuntimeError(f"env var {self._auth_env} not set")
        return t

    def _auth_header(self) -> str:
        user_env = self._user_env
        if user_env:
            user = os.environ.get(user_env, "")
            if user:
                import base64
                creds = base64.b64encode(f"{user}:{self._token()}".encode()).decode()
                return f"Basic {creds}"
        return f"Bearer {self._token()}"

    def _request(self, method: str, url: str,
                 body: dict | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace")[:300]
            raise RuntimeError(f"HTTP {exc.code}: {body_text}") from exc

    def _get_transition_id(self, ticket: str, target_status: str) -> str | None:
        """Return the Jira transition id that moves the issue to target_status.

        Results are cached in memory (per process) and in
        .klc/jira-transitions-cache.json (TTL 24h, per project key).
        """
        project_key = ticket.rsplit("-", 1)[0]

        # check in-memory cache first
        if project_key in self._cache:
            return self._cache[project_key].get(target_status)

        # check on-disk cache
        cache_file = klc_dir() / "jira-transitions-cache.json"
        disk: dict = {}
        if cache_file.exists():
            try:
                disk = json.loads(cache_file.read_text(encoding="utf-8"))
                entry = disk.get(project_key, {})
                cached_at = entry.get("_cached_at", "")
                if cached_at:
                    age = (_dt.datetime.now(_dt.timezone.utc) -
                           _dt.datetime.fromisoformat(cached_at.replace("Z", "+00:00")))
                    if age.total_seconds() < 86400:
                        self._cache[project_key] = entry
                        return entry.get(target_status)
            except Exception:
                pass

        # fetch from Jira
        url = f"{self._base}/rest/api/3/issue/{ticket}/transitions"
        data = self._request("GET", url)
        transitions = data.get("transitions") or []

        mapping: dict[str, str] = {"_cached_at": _now()}
        for t in transitions:
            name = (t.get("to") or {}).get("name") or t.get("name") or ""
            if name:
                mapping[name] = t["id"]

        self._cache[project_key] = mapping
        # persist to disk
        disk[project_key] = mapping
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(disk, indent=2), encoding="utf-8")
        except OSError:
            pass

        return mapping.get(target_status)

    def push(self, ticket: str, status: str) -> None:
        # idempotency check: get current status
        url = f"{self._base}/rest/api/3/issue/{ticket}?fields=status"
        data = self._request("GET", url)
        current = ((data.get("fields") or {}).get("status") or {}).get("name")
        if current == status:
            return

        transition_id = self._get_transition_id(ticket, status)
        if transition_id is None:
            raise RuntimeError(
                f"no transition to '{status}' found for {ticket}; "
                f"check phase_to_status mapping and Jira workflow"
            )

        url = f"{self._base}/rest/api/3/issue/{ticket}/transitions"
        self._request("POST", url, {"transition": {"id": transition_id}})


# ---------------------------------------------------------------------------
# MCP transport
# ---------------------------------------------------------------------------

class _McpTransport(_Transport):
    """Call mcp-atlassian running in HTTP mode."""

    def __init__(self, mcp_cfg: dict, timeout: float) -> None:
        self._url = (mcp_cfg.get("url") or "http://localhost:9000").rstrip("/")
        self._timeout = timeout
        self._auth_env = mcp_cfg.get("auth_env") or "JIRA_TOKEN"

    def _token(self) -> str:
        t = os.environ.get(self._auth_env, "")
        if not t:
            raise RuntimeError(f"env var {self._auth_env} not set")
        return t

    def push(self, ticket: str, status: str) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "tools/call",
            "params":  {
                "name": "jira_transition_issue",
                "arguments": {
                    "issue_key": ticket,
                    "status_name": status,
                },
            },
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._url}/",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                result = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode(errors="replace")[:300]
            raise RuntimeError(f"MCP HTTP {exc.code}: {body_text}") from exc

        if result.get("error"):
            raise RuntimeError(f"MCP error: {result['error']}")


# ---------------------------------------------------------------------------
# CLI (for flush from pre-commit hook and klc jira-sync)
# ---------------------------------------------------------------------------

def _cli(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="jira_sync", description="Jira sync queue management")
    sub = ap.add_subparsers(dest="cmd")

    f = sub.add_parser("flush", help="drain the jira queue")
    f.add_argument("--timeout", type=float, default=2.0)
    f.add_argument("--quiet", action="store_true")
    f.add_argument("--dry-run", action="store_true",
                   help="show what would be sent without sending")

    sub.add_parser("status", help="show queue size and oldest entry")

    args = ap.parse_args(argv)

    if args.cmd == "status" or args.cmd is None:
        size = queue_size()
        p = _queue_path()
        print(f"queue: {size} pending")
        if size > 0 and p.exists():
            try:
                lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
                oldest = min(
                    (json.loads(l).get("at", "") for l in lines if l),
                    default="unknown",
                )
                print(f"oldest: {oldest}")
            except Exception:
                pass
        return 0

    if args.cmd == "flush":
        if args.dry_run:
            p = _queue_path()
            if not p.exists():
                print("queue empty")
                return 0
            lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
            latest: dict[str, dict] = {}
            for line in lines:
                try:
                    e = json.loads(line)
                    latest[e["ticket"]] = e
                except Exception:
                    pass
            for ticket, e in latest.items():
                print(f"would send: {ticket} → {e['status']}")
            return 0

        result = flush_queue(timeout=args.timeout, quiet=args.quiet)
        if not args.quiet:
            print(f"[jira-sync] sent={result['sent']} failed={result['failed']} remaining={result['remaining']}")
        return 0 if result["failed"] == 0 else 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))


# ---------------------------------------------------------------------------
# KLC-021: SyncPlan, build_plan(), push()
# These are the new explicit-sync API used by jira.py and lifecycle.py.
# The legacy push_phase() above remains for mirror-mode auto-push.
# ---------------------------------------------------------------------------

@dataclass
class SyncPlan:
    """Side-effect-free snapshot of klc/Jira divergence for one ticket."""
    ticket: str
    klc_phase: str               # full phase:state
    jira_status: str | None      # current Jira status (None = unreachable)
    last_jira_status: str | None # last known from meta.jira_sync
    target_status: str | None    # what klc wants Jira to be
    in_sync: bool
    transition_id: str | None    # available direct transition, if any
    conflicts: list[dict] = _field(default_factory=list)

    def has_conflict(self, conflict_type: str) -> bool:
        return any(c.get("type") == conflict_type for c in self.conflicts)


def build_plan(ticket: str, client: Any, cfg: Any) -> SyncPlan:
    """Build a SyncPlan by comparing klc phase vs Jira status.

    Pure read — no transitions, no comments, no meta writes.

    Args:
        ticket: ticket key
        client: JiraClient instance (real or fake)
        cfg:    JiraConfig instance
    """
    from core.shared.paths import klc_ticket_meta_file
    meta_path = klc_ticket_meta_file(ticket)
    if not meta_path.exists():
        return SyncPlan(
            ticket=ticket, klc_phase="", jira_status=None,
            last_jira_status=None, target_status=None,
            in_sync=False, transition_id=None,
            conflicts=[{"type": "issue-missing", "detail": f"meta.json not found for {ticket}"}],
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    klc_phase = meta.get("phase", "")
    phase_id = klc_phase.split(":")[0] if ":" in klc_phase else klc_phase
    target_status = (cfg.klc_to_jira or {}).get(phase_id)
    last_jira = (meta.get("jira_sync") or {}).get("last_jira_status")

    # Fetch current Jira status
    try:
        issue = client.get_issue(ticket)
        jira_status = ((issue.get("fields") or {}).get("status") or {}).get("name")
    except RuntimeError as exc:
        if "404" in str(exc):
            return SyncPlan(
                ticket=ticket, klc_phase=klc_phase, jira_status=None,
                last_jira_status=last_jira, target_status=target_status,
                in_sync=False, transition_id=None,
                conflicts=[{"type": "issue-missing",
                            "detail": f"Jira issue {ticket} not found"}],
            )
        return SyncPlan(
            ticket=ticket, klc_phase=klc_phase, jira_status=None,
            last_jira_status=last_jira, target_status=target_status,
            in_sync=False, transition_id=None,
            conflicts=[{"type": "jira-unreachable", "detail": str(exc)}],
        )

    conflicts: list[dict] = []

    # Detect PM moved Jira externally: current differs from last AND from target
    if (last_jira is not None and jira_status != last_jira
            and jira_status != target_status):
        conflicts.append({
            "type": "jira-moved-externally",
            "detail": (f"Jira changed from {last_jira!r} to {jira_status!r} "
                       f"outside klc (expected {target_status!r})"),
        })

    in_sync = (jira_status == target_status)

    # Find available direct transition
    transition_id = None
    if not in_sync and target_status:
        try:
            transitions = client.get_transitions(ticket)
            for t in transitions:
                name = (t.get("to") or {}).get("name") or t.get("name") or ""
                if name == target_status:
                    transition_id = t["id"]
                    break
        except RuntimeError:
            pass

    return SyncPlan(
        ticket=ticket,
        klc_phase=klc_phase,
        jira_status=jira_status,
        last_jira_status=last_jira,
        target_status=target_status,
        in_sync=in_sync,
        transition_id=transition_id,
        conflicts=conflicts,
    )


def push(ticket: str) -> dict:
    """Public entry point: push klc phase → Jira status for a ticket.

    Loads JiraConfig and creates the client internally.
    Returns {ok, action, detail}. Never raises.
    """
    try:
        from jira_config import load as _load_cfg
        from jira_client import make_client
        cfg = _load_cfg()
        if not cfg.enabled:
            return {"ok": False, "action": "disabled",
                    "detail": "Jira integration not enabled"}
        client = make_client(cfg)
        return push_to_jira(ticket, client, cfg)
    except Exception as exc:
        return {"ok": False, "action": "error", "detail": str(exc)}


def push_to_jira(ticket: str, client: Any, cfg: Any) -> dict:
    """Push klc phase → Jira status (single-hop), injectable client.

    Returns {ok, action, detail}.
    Adds "moved by klc" comment on success.
    Records transition-blocked conflict if no direct transition exists.
    Never raises.
    """
    plan = build_plan(ticket, client, cfg)

    if plan.in_sync:
        return {"ok": True, "action": "noop", "detail": "already in sync"}

    # Record issue-missing / unreachable in meta so klc doctor surfaces them.
    if plan.has_conflict("issue-missing"):
        _record_conflict_in_meta(ticket, {
            "type": "issue-missing",
            "detail": plan.conflicts[0]["detail"],
            "detected_at": _now(),
            "suggested": f"check Jira issue {ticket} exists",
        })
        return {"ok": False, "action": "error",
                "detail": plan.conflicts[0]["detail"]}

    if plan.has_conflict("jira-unreachable"):
        _record_conflict_in_meta(ticket, {
            "type": "jira-unreachable",
            "detail": plan.conflicts[0]["detail"],
            "detected_at": _now(),
            "suggested": "check Jira connectivity and JIRA_API_TOKEN",
        })
        return {"ok": False, "action": "error",
                "detail": plan.conflicts[0]["detail"]}

    if plan.target_status is None:
        return {"ok": False, "action": "no-mapping",
                "detail": f"no klc_to_jira mapping for phase {plan.klc_phase}"}

    if plan.transition_id is None:
        _record_conflict_in_meta(ticket, {
            "type": "transition-blocked",
            "detail": (f"No direct transition to {plan.target_status!r} "
                       f"from {plan.jira_status!r}"),
            "detected_at": _now(),
            "suggested": f"klc jira reconcile {ticket} push",
        })
        return {
            "ok": False, "action": "transition-blocked",
            "detail": (f"No direct transition to {plan.target_status!r} "
                       f"from {plan.jira_status!r}. "
                       f"Move Jira manually then run `klc jira sync {ticket} --apply`"),
        }

    try:
        client.transition_issue(ticket, plan.transition_id)
        client.add_comment(ticket, f"moved by klc — phase {plan.klc_phase}")
        # SUCCESS: update meta and clear resolved conflicts (HIGH-5 fix).
        _update_jira_sync_meta(ticket, plan.target_status, plan.klc_phase, "push",
                               clear_conflicts=True)
        return {"ok": True, "action": "pushed",
                "detail": f"Jira {ticket} → {plan.target_status!r}"}
    except RuntimeError as exc:
        return {"ok": False, "action": "error", "detail": str(exc)}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_conflict_in_meta(ticket: str, conflict: dict) -> None:
    """Append a conflict to meta.json:jira_sync.conflicts (non-fatal)."""
    try:
        from core.shared.paths import klc_ticket_meta_file
        meta_path = klc_ticket_meta_file(ticket)
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        sync = meta.setdefault("jira_sync", {})
        sync.setdefault("conflicts", []).append(conflict)
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    except Exception:
        pass


def _update_jira_sync_meta(ticket: str, jira_status: str,
                            klc_phase: str, action: str,
                            clear_conflicts: bool = False) -> None:
    """Write meta.json:jira_sync block after a sync operation.

    clear_conflicts=True: remove resolved conflicts on successful push/sync.
    """
    try:
        from core.shared.paths import klc_ticket_meta_file
        meta_path = klc_ticket_meta_file(ticket)
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        sync = meta.setdefault("jira_sync", {})
        sync.update({
            "enabled": True,
            "issue_key": ticket,
            "last_synced_at": _now(),
            "last_jira_status": jira_status,
            "last_klc_phase": klc_phase,
            "last_action": action,
        })
        if clear_conflicts:
            sync["conflicts"] = []
        else:
            sync.setdefault("conflicts", [])
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# KLC-022: pull() — jira→klc state movement
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dc, field as _field  # noqa: E402


@_dc
class PullResult:
    ok: bool
    action: str
    detail: str
    skipped_phases: list[str] = _field(default_factory=list)
    missing_artifacts: list[str] = _field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "action": self.action,
            "detail": self.detail,
            "skipped_phases": self.skipped_phases,
            "missing_artifacts": self.missing_artifacts,
        }


def pull(ticket: str, target_phase: str,
         force: bool = False, reason: str | None = None) -> dict:
    """Public entry point: jira→klc state movement. Never raises."""
    try:
        from jira_config import load as _load_cfg
        from jira_client import make_client
        cfg = _load_cfg()
        if not cfg.enabled:
            return PullResult(False, "disabled",
                              "Jira integration not enabled").as_dict()
        client = make_client(cfg)
        return _pull_impl(ticket, target_phase, force, reason, client, cfg)
    except Exception as exc:
        return PullResult(False, "error", str(exc)).as_dict()


def _pull_impl(ticket: str, target_phase: str,
               force: bool, reason: str | None,
               client: Any, cfg: Any) -> dict:
    """Internal pull implementation with injectable client."""
    from core.shared.paths import klc_ticket_meta_file, klc_ticket_dir
    import phases as _ph
    import lifecycle as _lc

    meta_path = klc_ticket_meta_file(ticket)
    if not meta_path.exists():
        return PullResult(False, "error",
                          f"ticket {ticket!r} not found").as_dict()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    track = meta.get("track") or "M"

    # Read current Jira status
    try:
        issue = client.get_issue(ticket)
        jira_status = ((issue.get("fields") or {}).get("status") or {}).get("name")
    except RuntimeError as exc:
        return PullResult(False, "error",
                          f"Jira unreachable: {exc}").as_dict()

    # Validate target ∈ jira_to_klc[jira_status]
    candidates: list[str] = (cfg.jira_to_klc or {}).get(jira_status) or []
    if target_phase not in candidates:
        return PullResult(
            False, "invalid-target",
            f"{target_phase!r} is not a valid target for Jira status "
            f"{jira_status!r}. Valid candidates: {candidates}"
        ).as_dict()

    # Validate target applies to track
    ph = _ph.load_phases()
    track_ids = [p.id for p in ph.track_phases(track)]
    if target_phase not in track_ids:
        return PullResult(
            False, "invalid-target",
            f"{target_phase!r} does not apply to track {track!r}"
        ).as_dict()

    # Detect direction by phase index
    current_full = meta.get("phase", "")
    current_id = current_full.split(":")[0] if ":" in current_full else current_full
    try:
        cur_idx = track_ids.index(current_id)
        tgt_idx = track_ids.index(target_phase)
    except ValueError:
        return PullResult(False, "error",
                          "Could not determine phase index").as_dict()

    if cur_idx == tgt_idx:
        return PullResult(True, "noop", "Already at target phase").as_dict()

    if tgt_idx > cur_idx:
        return _forward_pull(ticket, target_phase, tgt_idx, cur_idx,
                             track_ids, jira_status, force, reason, meta, ph, cfg)
    else:
        return _backward_pull(ticket, target_phase, cur_idx, tgt_idx,
                              track_ids, jira_status, reason, meta)


def _forward_pull(ticket: str, target_phase: str,
                  tgt_idx: int, cur_idx: int,
                  track_ids: list[str], jira_status: str,
                  force: bool, reason: str | None,
                  meta: dict, ph: Any, cfg: Any) -> dict:
    """Walk forward from current toward target, respecting conditional skips."""
    from core.shared.paths import klc_ticket_dir
    import lifecycle as _lc

    ticket_dir = klc_ticket_dir(ticket)
    skipped: list[str] = []
    missing: list[str] = []

    # Walk phases between current (exclusive) and target (inclusive)
    for phase_id in track_ids[cur_idx + 1: tgt_idx + 1]:
        try:
            phase = ph.by_id(phase_id)
        except KeyError:
            continue

        # Conditional skip — record structured event in phase_history (AC-3)
        if not phase.should_run(meta):
            skipped.append(phase_id)
            _lc._record_skipped(ticket, phase_id,
                                phase.condition or "condition not met")
            continue

        # Check required inputs
        absent = [inp for inp in (phase.inputs or [])
                  if not (ticket_dir / inp).exists()]
        if absent:
            missing.extend(absent)

    if missing and not force:
        return PullResult(
            False, "stopped",
            f"Cannot pull to {target_phase!r}: missing artefacts block the path. "
            f"Use force-pull to skip.",
            skipped_phases=skipped,
            missing_artifacts=missing,
        ).as_dict()

    _lc.jira_pull(ticket, target_phase,
                  jira_status=jira_status,
                  force=force,
                  reason=reason,
                  missing_artifacts=missing,
                  skipped_phases=skipped)
    return PullResult(
        True, "pulled",
        f"klc moved to {target_phase}:work",
        skipped_phases=skipped,
        missing_artifacts=missing,
    ).as_dict()


def _backward_pull(ticket: str, target_phase: str,
                   cur_idx: int, tgt_idx: int,
                   track_ids: list[str], jira_status: str,
                   reason: str | None, meta: dict) -> dict:
    """Supersede downstream artefacts and move klc backward."""
    import lifecycle as _lc

    # Phases AFTER target through current are superseded.
    # The target phase itself is not superseded — it's where klc lands.
    phases_to_supersede = track_ids[tgt_idx + 1: cur_idx + 1]
    _lc.supersede_phases(ticket, phases_to_supersede)
    _lc.jira_pull(ticket, target_phase,
                  jira_status=jira_status,
                  force=False,
                  reason=reason,
                  skipped_phases=[])
    return PullResult(
        True, "pulled",
        f"klc moved back to {target_phase}:work "
        f"(superseded: {phases_to_supersede})",
        skipped_phases=[],
    ).as_dict()
