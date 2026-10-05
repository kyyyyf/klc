#!/usr/bin/env python3
"""`klc go <ticket>` — one move forward from any non-terminal state.

  <X>:ack          -> the next phase's `:work` (one step into the next phase)
  <X>:ack-needed   -> ack; `go` picks by itself only when the gate is conditional
                      and clean, otherwise it wants `--pick N`
  <X>:work         -> ack in one move when the outputs are complete and the gate
                      is clean; with outputs missing it changes nothing, prints
                      the card path and exits 2

`--until PHASE [--cap N]` repeats single moves through clean conditional gates
(the autorunner loop with its cap and guardrails, never dispatching an agent)
until `PHASE:work` (exit 0) or the first human stop (exit 2, one line naming the
next action: a pick, a HIGH advisory, a build that is not green, the cap, the
integrate guardrail or an agent card).

One stop line carries exactly ONE reason, picked by priority: a guardrail
(integrate, cap, budget) > a pick > the clarify pass > a build that is not green
> an agent card. The target phase must be on the ticket's track and not behind
the current phase. `--pick` with `--until` is the pick of the first move and is
refused (exit 2, nothing written) when the first move needs no pick.

`--dry-run` prints the line `klc status` shows as its next action and writes
nothing; with `--until` it prints the first move only, never the loop.
`--reason` is recorded as the ack note when `--note` is absent.
Exit codes: 0 moved or done, 2 a human has to act or the arguments are refused
(unknown ticket or phase, forward target, a pick is needed), 1 an unexpected
error (unreadable meta, a refusal by the state machine).

This is a thin router over `next.run` and `ack.run`; the decision itself comes
from `next_move.compute`, so every lock, state_tx and holder rule stays where it was.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
PHASES = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(PHASES))
from _paths import klc_ticket_meta_file  # noqa: E402
import lifecycle as _lc  # noqa: E402
import phases as _ph  # noqa: E402
import next_move as _nm  # noqa: E402
import ack as _ack  # noqa: E402
import next as _next  # noqa: E402
import autorunner as _auto  # noqa: E402
import dispatch_spec as _dspec  # noqa: E402


def _state(ticket: str) -> str:
    return _lc.read_meta_ro(ticket).get("phase", "")


def _emit(args, rc: int, before: str, action: str, text: str, err: str = "") -> int:
    if args.json:
        stopped = rc != 0
        print(json.dumps({"ticket": args.ticket, "from": before,
                          "to": _state(args.ticket), "action": action,
                          "stopped": stopped}))
        if err:
            sys.stderr.write(err)
    else:
        sys.stdout.write(text)
        if err:
            sys.stderr.write(err)
    return rc


def _delegate(fn, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = int(fn(argv))
    return rc, out.getvalue(), err.getvalue()


_GUARDRAIL_PREFIXES = ("outward-facing", "budget-ceiling", "consecutive-auto-cap")


def _ensure_build_card(ticket: str, move) -> None:
    """build:work points at `_prompt_step_N.md`; render it when it is missing so the
    path `go` and `status` name always exists (the `internal step-card` function)."""
    if move.phase != "build" or not move.card or Path(move.card).exists():
        return
    import artefacts as _art
    meta = _lc.read_meta_ro(move.ticket)
    _art.render_card(move.ticket, "build", meta, step=meta.get("impl_step") or 1)


def _stop_line(ticket: str, res) -> str:
    """ONE reason per stop, by priority: guardrail > pick > clarify > build not
    green > agent card. The autorunner reason already names a guardrail, a build
    that is not green or an agent card with its card path; only a pick or clarify
    stop adds the next-move line, and a clarify stop replaces the gate reason."""
    reason = res.reason or ""
    head = f"klc go: stopped at {res.paused_at} — "
    if reason.startswith(_GUARDRAIL_PREFIXES):
        return head + reason
    try:
        move = _nm.compute(ticket)
    except Exception:
        return head + reason
    if move.action == "clarify":
        return head + _nm.render(move).replace("→ ", "", 1)
    if move.action == "pick":
        return head + reason + " " + _nm.render(move)
    return head + reason


def _dispatch_suffix(ticket: str, phase: str | None) -> str:
    """A second, machine-readable line for an agent stop: the orchestrator passes
    `model=` to `Task` from it (models.yml for the ticket's track)."""
    if not phase:
        return ""
    line = _dspec.dispatch_line(ticket, phase)
    return line + "\n" if line else ""


def _validate_until(args) -> int | None:
    """None when --until is usable, else the exit code (2) after a stderr line."""
    try:
        phases = _ph.load_phases()
        phases.by_id(args.until)
    except Exception:
        sys.stderr.write(f"klc go: unknown phase {args.until!r} for --until\n")
        return 2
    try:
        meta = _lc.read_meta_ro(args.ticket)
        cur = meta.get("phase") or "intake:ack-needed"
        if _ph.is_terminal(cur):
            return None
        pid, state = _ph.parse_state(cur)
        seq = [p.id for p in phases.track_phases(meta.get("track") or "M")]
    except Exception:
        return None
    if args.until not in seq:
        sys.stderr.write(f"klc go: phase {args.until!r} is not on this ticket's "
                         f"{meta.get('track')} track ({', '.join(seq)})\n")
        return 2
    if pid in seq:
        behind = seq.index(args.until) < seq.index(pid) or (
            args.until == pid and state != _ph.STATE_WORK)
        if behind:
            sys.stderr.write(f"klc go: --until {args.until} is behind the current phase "
                             f"{cur}; use `klc back {args.ticket} {args.until} "
                             f"--reason TEXT` to return\n")
            return 2
    return None


def _until(args) -> int:
    """`--until <phase>`: the autorunner loop with `no_dispatch=True` (one loop,
    reused). Stops with exit 0 at `<phase>:work` or a terminal state, exit 2 at
    the first human stop (one line, one reason), exit 1 on a state refusal."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        # the loop's own PAUSED notice and the moves' chatter are replaced by one line below
        res = _auto.run(args.ticket, until=args.until, no_dispatch=True, cap=args.cap)
    stopped = res.terminal is None and res.paused_at is not None
    refused = res.terminal is None and res.paused_at is None and res.reason is not None
    line = ""
    if stopped:
        line = " ".join(_stop_line(args.ticket, res).split())
        if "needs the agent" in line or "build is not green" in line:
            # --until keeps its one-line stop contract: the dispatch fields ride
            # on the same line (the single move prints them on a line of their own)
            line = (line + " " + _dispatch_suffix(args.ticket, res.paused_at)).strip()
        try:
            _ensure_build_card(args.ticket, _nm.compute(args.ticket))
        except Exception:
            pass
    elif refused:
        line = f"klc go: {res.reason}"
    elif res.terminal and res.terminal.startswith("until:"):
        line = f"{args.ticket}: reached {args.until}:work"
    else:
        line = f"{args.ticket}: {res.terminal or 'archived'} — nothing left to do"
    if args.json:
        print(json.dumps({"ticket": args.ticket, "transitions": res.transitions,
                          "paused_at": res.paused_at, "reason": res.reason,
                          "terminal": res.terminal, "next": line}))
    elif refused:
        sys.stderr.write(line + "\n")
    else:
        print(line)
    return 1 if refused else (2 if stopped else 0)


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc go", description=__doc__, allow_abbrev=False)
    ap.add_argument("ticket")
    ap.add_argument("--pick", type=int, default=None, help="numeric pick id")
    ap.add_argument("--reason", default="", help="recorded as the ack note when --note is absent")
    ap.add_argument("--note", default="", help="free text recorded with the ack")
    ap.add_argument("--dry-run", action="store_true", help="print the move, write nothing")
    ap.add_argument("--until", default=None, metavar="PHASE",
                    help="keep going through clean conditional gates until PHASE:work "
                         "(never dispatches an agent)")
    ap.add_argument("--cap", type=int, default=None,
                    help="with --until: max consecutive moves before stopping")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(
            f"klc go: unknown ticket {args.ticket!r}; run `klc intake {args.ticket}` "
            f"or `klc board` to list live tickets\n")
        return 2

    if args.until:
        bad = _validate_until(args)
        if bad:
            return bad
        if args.dry_run:
            try:
                move = _nm.compute(args.ticket)
            except (ValueError, KeyError):
                sys.stderr.write(f"klc go: meta.json:phase is unparseable for "
                                 f"{args.ticket!r}; run `klc status {args.ticket}`\n")
                return 1
            text = ("" if move.action == "done" else _nm.render(move))
            text = text or f"{args.ticket}: {move.state} — nothing to do."
            return _emit(args, 0, _state(args.ticket), move.action,
                         f"{text} (dry-run shows the first move only)\n")
        if args.pick is not None:
            try:
                first = _nm.compute(args.ticket)
            except (ValueError, KeyError):
                first = None
            if first is None or first.action not in ("pick", "clarify"):
                sys.stderr.write(
                    f"klc go: --pick {args.pick} with --until is ambiguous: the first "
                    f"move needs no pick; run `klc go {args.ticket} --pick N` at the "
                    f"stop that asks for it\n")
                return 2
            buf_o, buf_e = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
                rc = _single(args)
            if rc != 0:
                sys.stdout.write(buf_o.getvalue())
                sys.stderr.write(buf_e.getvalue())
                return rc
            args.pick = None
        return _until(args)
    return _single(args)


def _single(args) -> int:

    try:
        move = _nm.compute(args.ticket)
    except (ValueError, KeyError):
        sys.stderr.write(f"klc go: meta.json:phase is unparseable for {args.ticket!r}; "
                         f"run `klc status {args.ticket}`\n")
        return 1
    line = _nm.render(move)
    before = _state(args.ticket)

    if move.action == "done":
        return _emit(args, 0, before, "done", f"{args.ticket}: {move.state} — nothing to do.\n")
    if args.dry_run:
        return _emit(args, 0, before, move.action, line + "\n")
    if move.action == "agent":
        _ensure_build_card(args.ticket, move)
        return _emit(args, 2, before, "agent",
                     line + "\n" + _dispatch_suffix(args.ticket, move.phase))

    if move.action == "next":
        rc, out, err = _delegate(_next.run, [args.ticket])
        return _emit(args, rc, before, "next", out, err)

    if args.pick is None and move.action in ("pick", "clarify"):
        return _emit(args, 2, before, "pick", "", line.replace("→ ", "klc go: ", 1) + "\n")

    note = args.note or args.reason
    ack_argv = [args.ticket, "--pick", str(args.pick)] if args.pick is not None \
        else [args.ticket, "--auto"]
    if note:
        ack_argv += ["--note", note]
    rc, out, err = _delegate(_ack.run, ack_argv)
    if rc == 0 and _ph.parse_state(_state(args.ticket))[1] == _ph.STATE_ACK \
            and not _ph.is_terminal(_state(args.ticket)):
        rc2, out2, err2 = _delegate(_next.run, [args.ticket])
        out, err, rc = out + out2, err + err2, rc2
    return _emit(args, rc, before, "ack", out, err)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
