#!/usr/bin/env python3
"""token_backfill.py — KLC-119 AC-12: record `estimated` attempts for every
prompt card still on disk for a ticket, reproducing the BEFORE baseline
without inventing a single number.

Records through the SAME single writer (`budget_guard.write_token_metrics`)
as every other call site. No transaction is open while the backfill runs,
so its attempts land in each ticket's derived, machine-local journal
(D-005) — the rollup's `iter_attempts` union (metrics.py) is what makes
them visible without 92 CAS pushes against the shared klc-state branch.

Operator entry point (dry-run by default):

    python3 core/skills/token_backfill.py [--apply] [TICKET ...]

With no TICKET arguments, every live ticket directory is scanned.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

from _paths import klc_card_root, klc_ticket_dir, klc_tickets_dir  # noqa: E402

_CARD_GLOBS = ("_prompt.md", "_prompt_step_*.md")
_STEP_RE = re.compile(r"_prompt_step_(\d+)\.md$")


def stored_cards(ticket: str):
    """Q-006: every `_prompt*.md` file for *ticket*, under BOTH the
    (pre-KLC-118) ticket directory and the (KLC-118+) derived card root,
    excluding `_superseded/`. Read here; swept by nobody in this ticket."""
    roots = [klc_ticket_dir(ticket), klc_card_root() / ticket]
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in _CARD_GLOBS:
            for card in root.rglob(pattern):
                if "_superseded" in card.parts:
                    continue
                resolved = card.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield card


def _phase_of(card: Path) -> str:
    """The card's phase id is its parent directory's name — the same
    convention `artefacts.py`'s `_card_dir`/`write_prompt_card` use."""
    return card.parent.name


def _step_of(card: Path) -> int | None:
    m = _STEP_RE.search(card.name)
    return int(m.group(1)) if m else None


def _deterministic_id(ticket: str, card: Path, size: int) -> str:
    """D-004: a deterministic digest of (ticket, card path, card bytes), so
    re-running the backfill is idempotent — the same card always yields the
    same attempt id, unlike a live render's random uuid4 id."""
    digest = hashlib.sha256(
        f"{ticket}:{card}:{size}".encode("utf-8")
    ).hexdigest()
    return f"bf{digest[:10]}"


def backfill_ticket(ticket: str, apply: bool = False) -> int:
    """Record one `estimated` attempt per stored card for *ticket*. Returns
    the number of cards found (recorded only when apply=True — the CLI's
    dry-run default just counts)."""
    import budget_guard
    n = 0
    for card in stored_cards(ticket):
        try:
            text = card.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        size = len(text.encode("utf-8"))
        rec_id = _deterministic_id(ticket, card, size)
        if apply:
            budget_guard.write_token_metrics(
                ticket, _phase_of(card), budget_guard.estimate_tokens(text),
                0, 0, source="estimated", card_bytes=size,
                step=_step_of(card), attempt_id=rec_id)
        n += 1
    return n


def _live_tickets() -> list[str]:
    tickets_dir = klc_tickets_dir()
    if not tickets_dir.exists():
        return []
    return sorted(p.name for p in tickets_dir.iterdir()
                 if p.is_dir() and p.name != "archive")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="KLC-119 AC-12: backfill estimated token attempts from "
                    "stored prompt cards")
    ap.add_argument("tickets", nargs="*",
                    help="ticket keys to backfill; default: every live ticket")
    ap.add_argument("--apply", action="store_true",
                    help="actually record attempts (default: dry-run count only)")
    args = ap.parse_args(argv)

    tickets = args.tickets or _live_tickets()
    total_cards = 0
    for ticket in tickets:
        n = backfill_ticket(ticket, apply=args.apply)
        if n:
            print(f"{ticket}: {n} card(s){' recorded' if args.apply else ' found (dry-run)'}")
        total_cards += n
    print(f"{'recorded' if args.apply else 'would record'} {total_cards} "
         f"attempt(s) across {len(tickets)} ticket(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
