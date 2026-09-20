#!/usr/bin/env python3
"""token_journal.py — the derived, append-only per-ticket journal that
buffers token-telemetry attempts recorded while no `state_tx` transaction is
open (KLC-119, ADR-004 / design/options.md Option A).

Owns four small things:
  - the per-ticket append-only JSONL journal at
    `klc_card_root()/<KEY>/telemetry.jsonl`;
  - a process-local registry of which tickets currently have an open
    transaction (`scope`/`tx_open`);
  - the attempt-id generator (delegated to `budget_guard`, not duplicated
    here — this module does not import `budget_guard`);
  - a once-per-process call that makes sure the journal's directory is
    git-ignored in this worktree (D-205).

Imports neither `state_tx` nor `budget_guard`, so the dependency graph stays
a DAG: `state_tx -> token_journal <- budget_guard`, with
`token_journal -> state_sync` for the ignore rule (function-local, fires at
most once per process — the same direction `state_tx -> state_sync` already
has, so a card render's module-import graph is unchanged).
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from _paths import klc_card_root

# Process-local: which tickets currently have an open state_tx transaction.
# Fine for the single-process, sequential-verb-per-invocation model this
# codebase uses (confirmed at design time against scripts/klc's _run_phase).
_OPEN: set[str] = set()

_IGNORE_ENSURED = False


def _ensure_ignored() -> None:
    """D-205: the journal writer owns its own ignore rule, so the FIRST ever
    operation on a fresh worktree can be a no-transaction render and still
    leave `git status --porcelain` empty. Function-local import: a card
    render must not pull the git layer into its module graph at import time
    (design/options.md option C's rejection) — this runs at most once per
    process, on the journalling path only."""
    global _IGNORE_ENSURED
    if _IGNORE_ENSURED:
        return
    _IGNORE_ENSURED = True
    try:
        import state_sync
        from _paths import klc_dir
        state_sync.ensure_derived_ignored(klc_dir())  # public, idempotent
    except Exception:
        pass  # a missing git dir (or no .klc/ at all) is normal; never fatal


def journal_path(ticket) -> Path:
    """The one place any reader/warning learns where a ticket's journal
    lives — under the existing card root (`.klc/scratch/` by default,
    overridable with `KLC_CARD_ROOT`), so it is derived and machine-local by
    construction (D-001)."""
    return klc_card_root() / str(ticket) / "telemetry.jsonl"


@contextmanager
def scope(ticket):
    """`state_tx` registers the ticket's scope for the whole transaction —
    including the drain — so a `write_token_metrics` call made DURING the
    drain (or during the verb's own body) is routed straight into meta.json
    rather than looping back into the journal."""
    key = str(ticket)
    _OPEN.add(key)
    try:
        yield
    finally:
        _OPEN.discard(key)


def tx_open(ticket) -> bool:
    return str(ticket) in _OPEN


def append(ticket, record: dict) -> None:
    """Append one JSONL line. `O_APPEND` writes of a single short line are
    atomic on Linux (well under the practical atomicity window for regular
    files), so two klc processes appending to the same ticket's journal
    cannot interleave into a corrupt line."""
    _ensure_ignored()
    path = journal_path(ticket)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read(ticket) -> list[dict]:
    """Every record currently buffered for *ticket*. A torn/garbled line is
    dropped, never fatal — the journal is a derived sample, not a ledger."""
    path = journal_path(ticket)
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def consume(ticket, ids) -> None:
    """Drop exactly the drained *ids*; a concurrent append (from another
    process, between the drain's read and this call) survives because it is
    not in *ids*."""
    ids = set(ids or ())
    if not ids:
        return
    path = journal_path(ticket)
    if not path.exists():
        return
    keep = [r for r in read(ticket) if r.get("id") not in ids]
    if keep:
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep),
            encoding="utf-8")
    else:
        try:
            path.unlink()
        except OSError:
            pass
