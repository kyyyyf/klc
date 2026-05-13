#!/usr/bin/env python3
"""Phase 2 / Phase 4 — Test planning (split).

Two entry modes, same phase script:

  klc test-plan <key>            # acceptance mode — phase 2
  klc test-plan <key> --detailed # detailed mode   — phase 4 (M / L)

Both produce / extend `test-plan.md`. Acceptance mode writes the
`## Acceptance coverage` section + manual checklist block; detailed
mode appends `## Detailed coverage` after Design without touching the
acceptance section or the manual block.

Acceptance mode (phase 2):
  - XS: writes a stub and bumps straight to `build-pending`.
  - S:  prompts the planner, then bumps to `build-pending` (no Design).
  - M/L: prompts the planner, then bumps to `design-pending`.

Detailed mode (phase 4, M / L only):
  - expects phase `detailed-test-plan-pending` (set by the Design ack).
  - requires existing test-plan.md with acceptance section and
    impl-plan.md from Design.
  - `--continue` validates coverage and bumps to `build-pending`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import (  # noqa: E402
    klc_ticket_dir,
    klc_ticket_meta_file,
)
import lifecycle  # noqa: E402


def _read_meta(ticket: str) -> dict:
    return json.loads(klc_ticket_meta_file(ticket).read_text(encoding="utf-8"))


# --- Acceptance mode (phase 2) ----------------------------------------------

def _prepare_acceptance(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    if meta["phase"] != "test-plan-pending":
        sys.stderr.write(
            f"klc test-plan: expected phase 'test-plan-pending', "
            f"got {meta['phase']!r}\n"
        )
        return 1

    spec = klc_ticket_dir(ticket) / "spec.md"
    if not spec.exists():
        sys.stderr.write("klc test-plan: spec.md missing\n")
        return 1

    # XS auto-finalises with a stub; no LLM call. XS has no Design and
    # no detailed phase — tests emerge inline during Build.
    if meta.get("track") == "XS":
        stub = (
            "---\n"
            f"ticket: {ticket}\n"
            "track: XS\n"
            "authority: generated\n"
            "---\n\n"
            "# Test plan (short)\n\n"
            "XS-track: tests will be written inline during Build.\n"
            "See the test file(s) produced by test-writer.py once the\n"
            "agent runs.\n"
        )
        (klc_ticket_dir(ticket) / "test-plan.md").write_text(stub, encoding="utf-8")
        lifecycle.advance(ticket, "build-pending",
                          note="XS track — test plan stubbed, skipping design")
        print(f"TEST_PLAN_OK {ticket} (stub, XS)")
        print(f"  next: klc build {ticket}")
        return 0

    print(f"TEST_PLAN_PENDING_LLM {ticket}  (acceptance mode)")
    print(f"  prompt:  core/agents/test-planner.md (acceptance section)")
    print(f"  input:   {spec}")
    print(f"  output:  {klc_ticket_dir(ticket)}/test-plan.md")
    print(f"           (# Acceptance coverage + # Manual checklist;")
    print(f"            leave # Detailed coverage empty / TBD)")
    print()
    print(f"After the agent writes test-plan.md run:")
    print(f"  klc test-plan {ticket} --continue")
    return 0


def _continue_acceptance(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    tp = klc_ticket_dir(ticket) / "test-plan.md"
    if not tp.exists():
        sys.stderr.write("klc test-plan --continue: test-plan.md missing\n")
        return 1
    text = tp.read_text(encoding="utf-8")
    if "## Acceptance coverage" not in text and "| AC |" not in text:
        sys.stderr.write(
            "klc test-plan --continue: test-plan.md has no acceptance "
            "coverage table; agent must emit one before continuing.\n"
        )
        return 1

    # S tracks jump straight to Build; M / L head to Design first.
    target = "design-pending"
    if meta.get("track") == "S":
        target = "build-pending"
    lifecycle.advance(ticket, target, note="acceptance test plan ready")
    print(f"TEST_PLAN_OK {ticket} (acceptance)")
    print(f"  next:    klc " + ("design" if target == "design-pending" else "build")
          + f" {ticket}")
    return 0


# --- Detailed mode (phase 4) ------------------------------------------------

def _prepare_detailed(args: argparse.Namespace) -> int:
    ticket = args.ticket
    meta = _read_meta(ticket)
    if meta["phase"] != "detailed-test-plan-pending":
        sys.stderr.write(
            f"klc test-plan --detailed: expected phase "
            f"'detailed-test-plan-pending', got {meta['phase']!r}\n"
        )
        return 1
    if meta.get("track") not in ("M", "L"):
        sys.stderr.write(
            "klc test-plan --detailed: only M / L tracks need a detailed "
            f"pass; track is {meta.get('track')!r}\n"
        )
        return 1

    tp = klc_ticket_dir(ticket) / "test-plan.md"
    options = klc_ticket_dir(ticket) / "design" / "options.md"
    impl = klc_ticket_dir(ticket) / "impl-plan.md"
    for req in (tp, options, impl):
        if not req.exists():
            sys.stderr.write(
                f"klc test-plan --detailed: missing {req}; run Design first\n"
            )
            return 1

    print(f"TEST_PLAN_PENDING_LLM {ticket}  (detailed mode)")
    print(f"  prompt:  core/agents/test-planner.md (detailed section)")
    print(f"  inputs:  {tp}  (keep # Acceptance coverage + manual block verbatim)")
    print(f"           {options}")
    print(f"           {impl}")
    print()
    print(f"Agent appends ## Detailed coverage (step-N → unit/integration")
    print(f"tests) to the existing test-plan.md.")
    print()
    print(f"After the agent writes the section, run:")
    print(f"  klc test-plan {ticket} --detailed --continue")
    return 0


def _continue_detailed(args: argparse.Namespace) -> int:
    ticket = args.ticket
    tp = klc_ticket_dir(ticket) / "test-plan.md"
    if not tp.exists():
        sys.stderr.write("klc test-plan --detailed --continue: test-plan.md missing\n")
        return 1
    text = tp.read_text(encoding="utf-8")
    if "## Detailed coverage" not in text:
        sys.stderr.write(
            "klc test-plan --detailed --continue: test-plan.md lacks "
            "'## Detailed coverage' section; agent must add one.\n"
        )
        return 1

    lifecycle.advance(ticket, "build-pending",
                      note="detailed test plan ready")
    print(f"TEST_PLAN_OK {ticket} (detailed)")
    print(f"  next: klc build {ticket}")
    return 0


# --- dispatch ---------------------------------------------------------------

def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc test-plan")
    ap.add_argument("ticket")
    ap.add_argument("--continue", dest="cont", action="store_true")
    ap.add_argument("--detailed", action="store_true",
                    help="detailed mode — phase 4, M / L only")
    args = ap.parse_args(argv)

    if args.detailed:
        return _continue_detailed(args) if args.cont else _prepare_detailed(args)
    return _continue_acceptance(args) if args.cont else _prepare_acceptance(args)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
