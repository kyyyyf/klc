#!/usr/bin/env python3
"""Phase 3 — Design.

Prepares the design bundle (spec, module context, related ADRs),
hands off to the design agent which writes `design/options.md`, then
optionally `design/adr.md` and `impl-plan.md`. `--continue` validates
the outputs and bumps phase to `design-pending-ack`.

XS: skipped entirely by the lifecycle (can_enter denies).
S:  hits this only when the user upgrades; otherwise test-plan jumps
    straight to build.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import (  # noqa: E402
    klc_ticket_dir,
    klc_ticket_meta_file,
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


def _bundle_path(ticket: str) -> Path:
    return klc_ticket_dir(ticket) / "design-context"


def _prepare(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    if meta["phase"] != "design-pending":
        sys.stderr.write(
            f"klc design: expected phase 'design-pending', got {meta['phase']!r}\n"
        )
        return 1

    lifecycle.advance(ticket, meta["phase"])  # idempotent noop
    bundle = _bundle_path(ticket)
    bundle.mkdir(parents=True, exist_ok=True)

    spec = klc_ticket_dir(ticket) / "spec.md"
    (bundle / "00-spec.md").write_text(spec.read_text(encoding="utf-8"),
                                        encoding="utf-8")

    tp = klc_ticket_dir(ticket) / "test-plan.md"
    if tp.exists():
        (bundle / "10-test-plan.md").write_text(tp.read_text(encoding="utf-8"),
                                                 encoding="utf-8")

    # Related ADRs in docs/adr/ touching affected modules.
    adr_dir = project_root() / "docs" / "adr"
    if adr_dir.exists():
        hits = []
        for m in meta.get("affected_modules", []):
            for adr in sorted(adr_dir.glob("ADR-*.md")):
                body = adr.read_text(encoding="utf-8", errors="ignore")
                if m in body:
                    hits.append(f"### {adr.name}\n{body}")
        if hits:
            (bundle / "20-related-adrs.md").write_text("\n\n".join(hits),
                                                        encoding="utf-8")

    design_dir = klc_ticket_dir(ticket) / "design"
    design_dir.mkdir(exist_ok=True)

    print(f"DESIGN_PENDING_LLM {ticket}")
    print(f"  bundle:   {bundle}")
    print(f"  prompt:   core/agents/design.md")
    print(f"  outputs:  {design_dir}/options.md")
    print(f"            {design_dir}/adr.md    (optional, if ADR_NEEDED=yes)")
    print(f"            {klc_ticket_dir(ticket)}/impl-plan.md")
    print()
    print(f"After the agent finished, run: klc design {ticket} --continue")
    return 0


def _continue(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    design_dir = klc_ticket_dir(ticket) / "design"
    opt = design_dir / "options.md"
    plan = klc_ticket_dir(ticket) / "impl-plan.md"

    if not opt.exists():
        sys.stderr.write("klc design --continue: options.md missing\n"); return 1
    if not plan.exists():
        sys.stderr.write("klc design --continue: impl-plan.md missing\n"); return 1

    # ADR is optional; if adr.md exists, meta.json:adr_triggered must be true
    adr = design_dir / "adr.md"
    meta.setdefault("metrics", {})["adr_triggered"] = adr.exists()
    klc_ticket_meta_file(ticket).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lifecycle.advance(ticket, "design-pending-ack",
                      note="options / impl-plan ready")
    print(f"DESIGN_READY {ticket}")
    print(f"  options:    {opt}")
    if adr.exists():
        print(f"  adr:        {adr}")
    print(f"  impl-plan:  {plan}")
    print()
    print(f"Ack with: klc ack {ticket} --for design")
    return 0


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc design")
    ap.add_argument("ticket")
    ap.add_argument("--continue", dest="cont", action="store_true")
    args = ap.parse_args(argv)
    return _continue(args) if args.cont else _prepare(args)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
