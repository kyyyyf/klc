#!/usr/bin/env python3
"""`klc publish <ticket>` — publish the review verdict to the ticket's GitHub PR.

After the `review` phase writes `review-report.md` + a verdict, this verb reads
that report, resolves the ticket's GitHub PR (via the `gh` CLI), and publishes:

  - verdict APPROVED          → PR label `review:approved`                (AC-1)
  - verdict CHANGES REQUESTED → label `review:changes-requested` +
                                a failing `klc/review` commit status      (AC-2)
  - always                    → the review summary posted as a PR comment (AC-3)

This verb is strictly READ-ONLY with respect to the lifecycle (like `klc work`):
it never advances phases, never writes `meta.json`, and never drains the Jira
queue (registered in `scripts/klc`'s `NO_DRAIN_CMDS`).

Degrade-not-fail is the whole theme (AC-4): no open PR, `gh` not installed / not
authenticated, or a non-GitHub context is a CLEAN no-op — one log line, return 0,
the local `review-report.md` stays authoritative, the lifecycle is never broken.
This mirrors the KLC-076 Jira-sentinel precedent.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS))
from _paths import klc_ticket_dir, klc_ticket_meta_file  # noqa: E402
import publish_github as _pg  # noqa: E402


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="klc publish", description=__doc__)
    ap.add_argument("ticket")
    ap.add_argument("--branch",
                    help="override the PR head branch to resolve "
                         "(default: derived from the ticket's feature branch)")
    args = ap.parse_args(argv)

    # Read-only existence guard first, mirroring work.py / status.py: a missing
    # ticket never creates or touches meta.
    if not klc_ticket_meta_file(args.ticket).exists():
        sys.stderr.write(
            f"klc publish: unknown ticket {args.ticket!r}; "
            f"run `klc intake {args.ticket}` or `klc board`\n"
        )
        return 1

    report = klc_ticket_dir(args.ticket) / "review-report.md"
    try:
        report_text = report.read_text(encoding="utf-8")
    except OSError:
        # No review-report yet → clean no-op (AC-4). Nothing to publish.
        print(f"klc publish: no review-report.md for {args.ticket} — "
              f"nothing to publish (run the review phase first).")
        return 0

    # Everything below degrades to a no-op; publish() never raises for a
    # forge/context problem. The broad guard is belt-and-suspenders so a bug in
    # the adapter can never break the lifecycle.
    try:
        result = _pg.publish(args.ticket, report_text, _pg.default_run_gh,
                             branch=args.branch)
    except Exception as exc:  # pragma: no cover - defensive, never break caller
        print(f"klc publish: adapter error, treated as no-op ({exc}); "
              f"local report stays authoritative.")
        return 0

    if result.published:
        print(f"klc publish: {result.message} "
              f"[{', '.join(result.actions)}]")
    else:
        print(f"klc publish: {result.message}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
