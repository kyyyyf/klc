#!/usr/bin/env python3
"""Phase 1 — Discovery.

Gathers context (raw description, CLAUDE.md of candidate modules,
symbols_by_module slice, related tickets, optional external docs),
writes a prompt bundle at `.klc/tickets/<key>/discovery-context/`,
and prints a handoff message pointing the LLM agent at
`core/agents/discovery.md`.

After the agent has produced `spec.md` + meta updates, the user runs
`klc discover <key> --continue` which advances the phase to
`discovery-pending-ack` and prints the ack instruction.

Design intent — see process-phases.md §4 and the prompt contract in
`core/agents/discovery.md`. This script never calls Serena.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import (  # noqa: E402
    klc_config_dir,
    klc_global_tickets_index,
    klc_index_dir,
    klc_ticket_dir,
    klc_ticket_meta_file,
    klc_ticket_raw_file,
    project_root,
)
import lifecycle  # noqa: E402


def _read_meta(ticket: str) -> dict:
    p = klc_ticket_meta_file(ticket)
    if not p.exists():
        import sys as _sys
        _sys.stderr.write(
            f"klc: unknown ticket {ticket!r}; run `klc intake {ticket}` "
            f"or `klc board` to list live tickets
"
        )
        raise SystemExit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def _write_meta(ticket: str, meta: dict) -> None:
    klc_ticket_meta_file(ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _load_modules() -> list[dict]:
    p = klc_index_dir() / "modules.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("modules", [])


def _load_sbm() -> dict:
    p = klc_index_dir() / "symbols_by_module.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("modules", {})


def _related_tickets(meta: dict, limit: int = 10) -> list[dict]:
    idx = klc_global_tickets_index()
    if not idx.exists():
        return []
    rows: list[dict] = []
    own_kind = meta.get("kind")
    own_key = meta.get("ticket")
    for line in reversed(idx.read_text(encoding="utf-8").splitlines()):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("key") == own_key:
            continue
        score = 0
        if rec.get("kind") == own_kind and own_kind:
            score += 1
        if score:
            rec["_score"] = score
            rows.append(rec)
        if len(rows) >= limit:
            break
    return rows


def _candidate_modules(raw_text: str, modules: list[dict]) -> list[str]:
    """Very dumb heuristic: module name appears in the raw description."""
    cands: list[str] = []
    for m in modules:
        name = m.get("name", "")
        if name and name in raw_text:
            cands.append(name)
    return cands[:5]


def _bundle_path(ticket: str) -> Path:
    return klc_ticket_dir(ticket) / "discovery-context"


def _prepare(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta_path = klc_ticket_meta_file(ticket)
    if not meta_path.exists():
        sys.stderr.write(f"klc discover: ticket {ticket!r} not intake-d yet\n")
        return 1
    meta = _read_meta(ticket)

    if not lifecycle.can_enter(meta["phase"], "discovery-running"):
        sys.stderr.write(
            f"klc discover: cannot enter discovery from phase {meta['phase']!r}\n"
        )
        return 1

    t0 = _dt.datetime.now(_dt.timezone.utc)
    lifecycle.advance(ticket, "discovery-running", note="context preparation")

    bundle = _bundle_path(ticket)
    bundle.mkdir(parents=True, exist_ok=True)

    # 1. raw description
    raw_path = klc_ticket_raw_file(ticket)
    (bundle / "00-raw.md").write_text(raw_path.read_text(encoding="utf-8"),
                                       encoding="utf-8")

    # 2. root CLAUDE.md if present
    root_claude = project_root() / "CLAUDE.md"
    if root_claude.exists():
        (bundle / "10-root-CLAUDE.md").write_text(
            root_claude.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # 3. module candidates
    modules = _load_modules()
    candidates = args.focus.split(",") if args.focus else _candidate_modules(
        raw_path.read_text(encoding="utf-8"), modules
    )
    candidates = [c.strip() for c in candidates if c.strip()]

    module_docs: list[str] = []
    module_symbol_lines: list[str] = []
    sbm = _load_sbm()
    for m in modules:
        if m["name"] not in candidates:
            continue
        path = project_root() / m.get("path", "")
        doc = path / (m.get("doc_filename") or "CLAUDE.md")
        if doc.exists():
            module_docs.append(f"<!-- module {m['name']} -->\n" +
                               doc.read_text(encoding="utf-8"))
        entries = sbm.get(m["name"], [])
        if entries:
            module_symbol_lines.append(f"### {m['name']}")
            for e in entries[:30]:
                module_symbol_lines.append(
                    f"- `{e.get('name')}` ({e.get('kind')})  "
                    f"{e.get('file')}:{e.get('line')}"
                )
    if module_docs:
        (bundle / "20-module-docs.md").write_text("\n\n".join(module_docs),
                                                   encoding="utf-8")
    if module_symbol_lines:
        (bundle / "30-module-symbols.md").write_text(
            "\n".join(module_symbol_lines), encoding="utf-8"
        )

    # 4. related tickets
    related = [] if args.skip_related else _related_tickets(meta)
    related_lines = [f"- {r['key']} (kind={r.get('kind')}, phase={r.get('phase')})"
                     for r in related]
    if related_lines:
        (bundle / "40-related.md").write_text(
            "# Related tickets\n\n" + "\n".join(related_lines) + "\n",
            encoding="utf-8"
        )

    # 5. external docs listed in .klc/config/discovery.yml — we only
    #    leave a pointer note; actual fetch is the agent's job (WebFetch).
    docs_cfg = klc_config_dir() / "discovery.yml"
    if docs_cfg.exists():
        (bundle / "50-external-docs.md").write_text(
            "# External docs the agent may read\n\n"
            "(see discovery.yml for the full list; fetch via WebFetch)\n\n" +
            docs_cfg.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Metrics so far
    dur = int((_dt.datetime.now(_dt.timezone.utc) - t0).total_seconds() * 1000)
    meta = _read_meta(ticket)
    meta.setdefault("metrics", {})["discovery_prep_ms"] = dur
    meta["affected_modules_candidates"] = candidates
    _write_meta(ticket, meta)

    print(f"DISCOVERY_PENDING_LLM {ticket}")
    print(f"  bundle:  {bundle}")
    print(f"  prompt:  core/agents/discovery.md")
    print(f"  output:  {klc_ticket_dir(ticket)}/spec.md")
    print(f"  meta:    set track / estimate / affected_modules / layer")
    print()
    print(f"When the agent finished writing spec.md and updating meta.json,")
    print(f"run: klc discover {ticket} --continue")
    return 0


def _continue(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta_path = klc_ticket_meta_file(ticket)
    if not meta_path.exists():
        sys.stderr.write(f"klc discover --continue: unknown ticket {ticket!r}\n")
        return 1
    meta = _read_meta(ticket)

    # Must have phase=discovery-running
    if meta["phase"] != "discovery-running":
        sys.stderr.write(
            f"klc discover --continue: expected phase 'discovery-running', "
            f"got {meta['phase']!r}\n"
        )
        return 1

    spec = klc_ticket_dir(ticket) / "spec.md"
    if not spec.exists():
        sys.stderr.write(
            f"klc discover --continue: spec.md not found at {spec}. "
            "Have the discovery agent write it before continuing.\n"
        )
        return 1

    # Validation the script can do without an LLM:
    if meta.get("track") not in ("XS", "S", "M", "L"):
        sys.stderr.write(
            "klc discover --continue: meta.json:track missing or invalid. "
            "The discovery agent must set one of XS/S/M/L.\n"
        )
        return 1
    est = meta.get("estimate") or {}
    for axis in ("complexity", "uncertainty", "risk", "manual"):
        if axis not in est:
            sys.stderr.write(
                f"klc discover --continue: meta.json:estimate.{axis} missing.\n"
            )
            return 1

    lifecycle.advance(ticket, "discovery-pending-ack",
                      note="spec.md written; awaiting human ack")

    # Global index: patch the last record for this ticket
    idx = klc_global_tickets_index()
    if idx.exists():
        with idx.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "key":    ticket,
                "phase":  "discovery-pending-ack",
                "track":  meta["track"],
                "updated": _dt.datetime.now(_dt.timezone.utc)
                           .strftime("%Y-%m-%dT%H:%M:%SZ"),
            }, ensure_ascii=False) + "\n")

    print(f"DISCOVERY_READY {ticket}")
    print(f"  spec:     {spec}")
    print(f"  track:    {meta['track']} (estimate total={est.get('total', '?')})")
    print(f"  modules:  {', '.join(meta.get('affected_modules', []) or [])}")
    print()
    print(f"Ack with: klc ack {ticket} --for discovery")
    return 0


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc discover")
    ap.add_argument("ticket")
    ap.add_argument("--continue", dest="cont", action="store_true",
                    help="finalise after the agent wrote spec.md")
    ap.add_argument("--focus", default=None,
                    help="comma-separated module names the agent should focus on")
    ap.add_argument("--skip-related", action="store_true",
                    help="skip the related-tickets lookup (cheap)")
    args = ap.parse_args(argv)
    return _continue(args) if args.cont else _prepare(args)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
