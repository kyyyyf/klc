#!/usr/bin/env python3
"""Phase 0 — Intake.

Creates `.klc/tickets/<KEY>/`, writes meta.json + raw.md, appends to
the global index. Does NOT touch Jira, does NOT
create git branches. Leaves the ticket in `intake:ack-needed`.

Usage:
    klc intake <JIRA-KEY> [--kind feature|bug|tech] "<desc>"
    cat bug.txt | klc intake <JIRA-KEY> --stdin [--kind bug]

See docs/process.md for the full contract.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills"))
import identity  # noqa: E402
import holder  # noqa: E402
import state_sync  # noqa: E402
import state_tx  # noqa: E402
from artefacts import acquire_lock, LockedError  # noqa: E402
from _paths import (  # noqa: E402
    klc_config_dir,
    klc_global_tickets_index,
    klc_index_dir,
    klc_ticket_dir,
    klc_ticket_meta_file,
    klc_ticket_raw_file,
)


DEFAULT_KEY_RE = r"^[A-Z][A-Z0-9]+-\d+$"


class _KeyTakenError(Exception):
    """Raised inside the tx when `pull_rebase` reveals a peer already created this
    key on the shared state (HIGH-B) — abort WITHOUT overwriting their files."""


class _IdentityError(Exception):
    """Raised inside the tx when the holder write fails because the caller's
    identity is unusable (empty git user.email, …) — surfaced distinctly from a
    sync failure (LOW-3)."""


class _ForcePeerNewerError(Exception):
    """Raised inside the tx when a --force overwrite target was changed on the
    shared state by a peer since the local copy (P2) — refuse to clobber."""


def _load_key_pattern() -> re.Pattern:
    r"""Read the regex from .klc/config/ticket-id.yml.

    YAML semantics we honour (by hand — PyYAML isn't a hard dep of this
    skill): single-quoted strings are literal; double-quoted strings
    obey backslash escapes (so `"\\d"` means `\d`, as it would through
    a real parser).
    """
    cfg = klc_config_dir() / "ticket-id.yml"
    if not cfg.exists():
        return re.compile(DEFAULT_KEY_RE)
    for line in cfg.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("pattern:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value.startswith("'") and value.endswith("'"):
            raw = value[1:-1]        # single-quoted → literal
        elif value.startswith('"') and value.endswith('"'):
            raw = bytes(value[1:-1], "utf-8").decode("unicode_escape")
        else:
            raw = value              # bare scalar, no escapes in YAML
        return re.compile(raw)
    return re.compile(DEFAULT_KEY_RE)


def _load_jira_url(ticket: str) -> str | None:
    cfg = klc_config_dir() / "jira.yml"
    if not cfg.exists():
        return None
    for line in cfg.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("url_template:"):
            tmpl = line.split(":", 1)[1].strip().strip('"').strip("'")
            return tmpl.replace("{key}", ticket)
    return None


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _triage_available() -> bool:
    """Cheap intake triage is on by default. Disable to fall back to the
    deterministic-only "A" routing (low confidence → full discovery).

    Off switch: env KLC_INTAKE_TRIAGE in {0,false,no}.
    """
    return os.environ.get("KLC_INTAKE_TRIAGE", "").strip().lower() not in (
        "0", "false", "no")


def _classify_route(desc: str, kind: str) -> dict:
    """Deterministic routing via route_heuristic. Never raises.

    Returns a dict: hint, signals, confidence, mentions, decision.
    `decision` is the B+A routing action (trust|triage|full-discovery).
    """
    try:
        skills = Path(__file__).resolve().parent.parent / "skills"
        sys.path.insert(0, str(skills))
        import route_heuristic as _rh
        r = _rh.classify(desc, kind=kind)
        return {
            "hint":       r.hint,
            "signals":    r.signals,
            "confidence": r.confidence,
            "mentions":   [{"kind": "module", "value": m}
                           for m in r.modules_matched],
            "decision":   _rh.decide_route(r.hint, r.confidence,
                                           _triage_available()),
        }
    except Exception:
        return {"hint": "S", "signals": {}, "confidence": "medium",
                "mentions": [], "decision": "trust"}


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc intake", description=__doc__)
    ap.add_argument("--kind", choices=["feature", "bug", "tech", "unknown"],
                    default=None)
    ap.add_argument("--stdin", action="store_true",
                    help="read description from stdin")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing intake data")
    ap.add_argument("--jira-description",
                    choices=["klc", "jira", "both"], default=None,
                    dest="jira_description",
                    help="description source when Jira issue exists: "
                         "klc (default), jira, or both")
    ap.add_argument("ticket", help="Jira-style ticket key, e.g. PROJ-4502")
    ap.add_argument("description", nargs="*",
                    help="description words (any position; quote if it contains options)")
    # parse_intermixed_args lets the positional description follow --kind
    # without argparse dropping the tail as "unrecognized".
    args = ap.parse_intermixed_args(argv)
    if isinstance(args.description, list):
        args.description = " ".join(args.description) if args.description else None

    pat = _load_key_pattern()
    if not pat.match(args.ticket):
        sys.stderr.write(
            f"klc intake: invalid key {args.ticket!r}; expected {pat.pattern}\n"
        )
        return 2

    if args.stdin:
        desc = sys.stdin.read().strip()
    else:
        desc = (args.description or "").strip()
    if not desc:
        sys.stderr.write("klc intake: description required "
                         "(positional or --stdin)\n")
        return 2

    tdir = klc_ticket_dir(args.ticket)
    existing = klc_ticket_meta_file(args.ticket).exists()
    if existing and not args.force:
        meta = json.loads(klc_ticket_meta_file(args.ticket).read_text(encoding="utf-8"))
        if not (meta.get("phase") or "").startswith("intake"):
            sys.stderr.write(
                f"klc intake: ticket {args.ticket} already in phase "
                f"{meta.get('phase')!r}. Use `klc status` or `klc abort`.\n"
            )
            return 1
        sys.stderr.write(
            f"klc intake: {args.ticket} already at intake; use --force to overwrite.\n"
        )
        return 1

    t0 = _dt.datetime.now(_dt.timezone.utc)

    # Build raw.md + meta.json contents up front (pure computation — no fs writes
    # yet). The actual create happens INSIDE the state_tx body so it lands AFTER
    # `pull_rebase` on a clean tree (HIGH-1) and is captured by the rollback
    # snapshot (a rejected/failed push unwinds it).
    jira_url = _load_jira_url(args.ticket)
    raw_header = [
        "---",
        f"ticket: {args.ticket}",
    ]
    if jira_url:
        raw_header.append(f"jira_url: {jira_url}")
    raw_header += [
        f"kind_hint: {args.kind or 'unknown'}",
        f"created: {_now()}",
        "---",
        "",
    ]
    raw_body = "\n".join(raw_header) + desc + "\n"

    # Deterministic route classification (no LLM)
    route = _classify_route(desc, args.kind or "unknown")
    route_hint = route["hint"]

    meta = {
        "ticket":        args.ticket,
        "kind":          args.kind or "unknown",
        "kind_source":   "user" if args.kind else "heuristic",
        "phase":         "intake:ack-needed",
        "phase_history": [{"phase": "intake:ack-needed", "started_at": _now()}],
        "track":         route_hint,
        "estimate":      None,
        "layer":         None,
        "affected_modules": [],
        "created":       _now(),
        "owner":         identity.current(),
        "jira_url":      jira_url,
        "links":         [],
        "rework_count":  {},
        "route_hint":       route_hint,
        "route_signals":    route["signals"],
        "route_confidence": route["confidence"],
        "route_decision":   route["decision"],
        "mentions":         route["mentions"],
        "clarify_required": route["confidence"] == "low",
        "metrics":       {"intake_ms": int((_dt.datetime.now(_dt.timezone.utc) - t0).total_seconds() * 1000)},
    }
    meta_body = json.dumps(meta, indent=2, ensure_ascii=False) + "\n"

    # KLC-057: multi-user uniqueness + holder, INSIDE the same per-ticket lock
    # ack/next use (AC-9). The CAS push of this ticket's own files *is* the
    # uniqueness guarantee — a key a peer already created rejects as
    # StateConflictError. The first phase records the current holder in the SAME
    # push (AC-3). Feature-off (single-user), state_tx is a pure no-op and the
    # holder write is skipped, so behaviour is byte-for-byte identical (AC-8a).
    # P2: for a --force overwrite of an existing LOCAL ticket, remember its exact
    # bytes so that, if the pull reveals the shared state has since moved (a peer
    # took or advanced the key), we refuse rather than clobber their work.
    force_prev_meta = None
    if existing and args.force:
        try:
            force_prev_meta = klc_ticket_meta_file(args.ticket).read_bytes()
        except OSError:
            pass

    try:
        with acquire_lock(args.ticket):
            try:
                with state_tx.state_tx(
                    args.ticket, f"intake {args.ticket}"
                ) as tx:
                    # HIGH-B: state_tx has now pulled. A peer may have committed
                    # this key since our pre-tx check — writing would fast-forward
                    # over (silently clobber) their meta/holder. Re-check AFTER
                    # the pull and BEFORE writing; abort if the key appeared.
                    # (`existing` guards the legitimate --force overwrite of our
                    # OWN pre-existing local ticket.)
                    if not existing and klc_ticket_meta_file(args.ticket).exists():
                        raise _KeyTakenError()
                    # P2: --force may only overwrite if the pulled state is still
                    # the exact local record it intended to replace; if the pull
                    # changed it, a peer moved the shared state → refuse.
                    if existing and args.force and force_prev_meta is not None:
                        cur_bytes = (
                            klc_ticket_meta_file(args.ticket).read_bytes()
                            if klc_ticket_meta_file(args.ticket).exists() else None
                        )
                        if cur_bytes != force_prev_meta:
                            raise _ForcePeerNewerError()
                    tdir.mkdir(parents=True, exist_ok=True)
                    klc_ticket_raw_file(args.ticket).write_text(
                        raw_body, encoding="utf-8")
                    klc_ticket_meta_file(args.ticket).write_text(
                        meta_body, encoding="utf-8")
                    if tx is not None:
                        ident = {"id": identity.current(),
                                 "machine": socket.gethostname()}
                        try:
                            holder.acquire_holder(args.ticket, ident)
                        except ValueError as ie:
                            # LOW-3: a bad identity is NOT a sync failure.
                            raise _IdentityError(str(ie))
                    # step-6: fold the jira raw.md enrichment INTO the tx body so
                    # its merge is captured by the ticket-subtree push and never
                    # dirties the tracked tree post-push (which would wedge the
                    # next op's pull). Never raises (best-effort by contract).
                    _jira_intake_enrich(args.ticket, args.jira_description)
            except _KeyTakenError:
                # HIGH-B: the peer's tracked ticket was pulled into our worktree —
                # leave it intact (do NOT rmtree) and do not push.
                sys.stderr.write(
                    f"klc intake: key {args.ticket} already taken "
                    f"(exists on the shared state); nothing was written.\n"
                )
                return 1
            except _ForcePeerNewerError:
                # P2: the pulled state differs from the local record --force meant
                # to replace — a peer took/advanced the key. Their tracked files
                # are now in our worktree; leave them intact and refuse.
                sys.stderr.write(
                    f"klc intake: {args.ticket} was updated by another user since "
                    f"your local copy — refusing --force overwrite. Run "
                    f"`klc status {args.ticket}` and retry if still needed.\n"
                )
                return 1
            except _IdentityError as e:
                shutil.rmtree(tdir, ignore_errors=True)
                sys.stderr.write(
                    f"klc intake: cannot determine your identity ({e}); "
                    f"set your git user.email, then retry. Nothing was written.\n"
                )
                return 1
            except state_sync.StateConflictError:
                shutil.rmtree(tdir, ignore_errors=True)
                sys.stderr.write(
                    f"klc intake: key {args.ticket} already taken "
                    f"(created by another user); nothing was written.\n"
                )
                return 1
            except (state_sync.RetryExhaustedError,
                    state_sync.RebaseConflictError,
                    state_sync.ConfigError,
                    RuntimeError, ValueError):
                # Terminal, non-CAS sync failure (RRC set above, plus a plain
                # RuntimeError/ValueError/NothingToCommitError from pull/push).
                # Keep the shared state consistent by leaving no local-only
                # ticket, and surface a clean message (AC-7) — never a raw
                # traceback dumping git internals to the user.
                shutil.rmtree(tdir, ignore_errors=True)
                sys.stderr.write(
                    f"klc intake: state sync failed for {args.ticket}; "
                    f"nothing was written — retry.\n"
                )
                return 1

            # append to global index (append-only) — deferred until AFTER a clean
            # CAS push (D-005), so a rejected push leaves zero index pollution.
            idx = klc_global_tickets_index()
            idx.parent.mkdir(parents=True, exist_ok=True)
            with idx.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "key":        args.ticket,
                    "kind":       meta["kind"],
                    "phase":      "intake",
                    "created":    meta["created"],
                }, ensure_ascii=False) + "\n")

            print(f"INTAKE_OK {args.ticket}")
            print(f"  dir:    {tdir}")
            print(f"  kind:   {meta['kind']}")
            print(f"  route:  {route_hint}  confidence={route['confidence']}  (signals: {route['signals']})")
            print(f"  → intake:ack-needed")
            decision = route["decision"]
            if decision == "triage":
                print(f"  ⚠ {route['confidence']}-confidence routing — the hint may under-size the ticket.")
                print(f"     Recommended: run the cheap intake triage (core/agents/intake-triage.md)")
                print(f"     to disambiguate scope, or `klc ack {args.ticket} --pick 2` to force full discovery.")
            elif decision == "full-discovery":
                print(f"  ⚠ low-confidence routing, triage disabled.")
                print(f"     Recommended: `klc ack {args.ticket} --pick 2` (force-full-discovery).")
            print(f"  picks:  klc ack {args.ticket} --pick 1  [1=confirm-route, 2=force-full-discovery, 3=force-xs-skip]")
    except LockedError as e:
        sys.stderr.write(f"klc intake: {e}\n")
        return 1

    # jira raw.md enrichment already ran INSIDE the tx (step-6) so its merge rode
    # the ticket-subtree push; only the read-only stale-module warning is left.
    _warn_stale_modules()
    return 0


def _jira_intake_enrich(ticket: str, jira_desc_mode: str | None) -> None:
    """Optionally enrich intake from Jira: dup-check, description merge, raw.md link.

    Never raises — Jira errors are warnings, never block intake.
    """
    try:
        skills = Path(__file__).resolve().parent.parent / "skills"
        sys.path.insert(0, str(skills))
        from jira_config import load as _load_cfg, JiraConfigError
        cfg = _load_cfg()
        if not cfg.enabled:
            return
    except Exception:
        return

    try:
        from jira_client import make_client
        from jira_artifacts import upsert_artifact_links
        client = make_client(cfg)
    except Exception as exc:
        sys.stderr.write(f"[jira] client init failed: {exc}\n")
        return

    # Dup-check: does Jira issue exist?
    # Only 404 means "missing" — 403/timeout/other errors are warnings
    # and we stop to avoid silent data-loss (skipping link upsert).
    issue = None
    jira_exists = False
    try:
        issue = client.get_issue(ticket)
        jira_exists = True
    except RuntimeError as exc:
        err_str = str(exc)
        if "404" in err_str:
            jira_exists = False  # legitimately missing — proceed silently
        else:
            sys.stderr.write(
                f"[jira] could not check issue {ticket}: {exc}\n"
                f"       Skipping Jira enrichment (re-run after fixing connectivity).\n"
            )
            return  # don't attempt description merge or link upsert

    if jira_exists:
        jira_body = _extract_jira_description(issue)
        mode = jira_desc_mode  # may be None

        if mode is None:
            # Determine interactivity
            if sys.stdin.isatty():
                sys.stderr.write(
                    f"\n[jira] Issue {ticket} already exists in Jira.\n"
                    f"  Choose description source:\n"
                    f"  1) klc (keep local description)\n"
                    f"  2) jira (use Jira description)\n"
                    f"  3) both (keep local + append Jira section)\n"
                    f"  [1/2/3, default=1]: "
                )
                choice = input().strip()
                mode = {"1": "klc", "2": "jira", "3": "both"}.get(choice, "klc")
            else:
                sys.stderr.write(
                    f"[jira] Issue {ticket} exists in Jira. "
                    f"Using local description (--jira-description to change).\n"
                )
                mode = "klc"

        if mode in ("jira", "both") and jira_body:
            _merge_jira_description(ticket, jira_body, mode)

    # Always add raw.md link comment to Jira (whether issue existed or not,
    # if it exists now after the check above)
    if jira_exists:
        try:
            upsert_artifact_links(client, ticket, ticket, cfg)
        except RuntimeError as exc:
            sys.stderr.write(f"[jira] artefact link failed (non-fatal): {exc}\n")


def _extract_jira_description(issue: dict) -> str:
    """Extract plain-text description from Jira issue dict."""
    fields = issue.get("fields") or {}
    body = fields.get("description") or ""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        # ADF format — flatten to text
        return _flatten_adf(body)
    return ""


def _flatten_adf(adf: dict) -> str:
    """Flatten ADF to plain text — delegates to jira_artifacts.flatten_adf."""
    try:
        skills = Path(__file__).resolve().parent.parent / "skills"
        sys.path.insert(0, str(skills))
        from jira_artifacts import flatten_adf
        return flatten_adf(adf)
    except Exception:
        # Fallback if import fails
        parts = []
        if adf.get("type") == "text":
            parts.append(adf.get("text", ""))
        for child in adf.get("content") or []:
            if isinstance(child, dict):
                parts.append(_flatten_adf(child))
        return "".join(parts)


def _merge_jira_description(ticket: str, jira_body: str, mode: str) -> None:
    """Merge Jira description into raw.md using markers."""
    raw_path = klc_ticket_raw_file(ticket)
    marker_start = f"<!-- klc:jira-description {ticket} -->"
    marker_end = "<!-- /klc:jira-description -->"
    jira_section = f"\n{marker_start}\n{jira_body.strip()}\n{marker_end}\n"

    existing = raw_path.read_text(encoding="utf-8")
    if marker_start in existing:
        return  # already merged

    if mode == "jira":
        # Replace content after front-matter with Jira body
        lines = existing.splitlines(keepends=True)
        fm_end = None
        if lines and lines[0].strip() == "---":
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "---":
                    fm_end = i
                    break
        if fm_end is not None:
            frontmatter = "".join(lines[:fm_end + 1])
            raw_path.write_text(frontmatter + jira_section, encoding="utf-8")
        else:
            raw_path.write_text(existing + jira_section, encoding="utf-8")
    else:  # both
        raw_path.write_text(existing.rstrip() + jira_section, encoding="utf-8")


def _warn_stale_modules() -> None:
    """Print a warning if stale.json reports modules with outdated docs."""
    stale_file = klc_index_dir() / "stale.json"
    if not stale_file.exists():
        return
    try:
        data = json.loads(stale_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    modules = data.get("stale_modules") or []
    if not modules:
        return
    sys.stderr.write(
        f"\n  ⚠  {len(modules)} module doc(s) may be outdated: "
        f"{', '.join(modules[:5])}"
        + (" …" if len(modules) > 5 else "") + "\n"
        f"     Run `klc update --regen` to refresh CLAUDE.md files.\n\n"
    )


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
