#!/usr/bin/env python3
"""findings_store.py — the one `findings.json` of a ticket (KLC-173).

Every review finding of a ticket lives in a single bare JSON list at
`<ticket>/findings.json`. Each record carries its `kind` (spec-review,
test-plan-review, impl-plan-review, drift-review, code-review, external-review)
and its `round`; a writer replaces only its own (kind, round) records.

Archived tickets still hold the old per-kind files. The readers fall back to
them, read-only, only when `findings.json` is absent; nothing here ever
rewrites the old layout.

Leaf module: imports `findings` only, so handback, task_brief and metrics can
all depend on it without a cycle.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings  # noqa: E402
import store_lock  # noqa: E402

# kind -> the old per-kind file (archived tickets only).
_LEGACY = {"spec-review": "spec-review-findings.json",
           "test-plan-review": "test-plan-review-findings.json",
           "impl-plan-review": "impl-plan-review-findings.json",
           "drift-review": "drift-review-findings.json",
           "code-review": "review/code-review-findings.json",
           "external-review": "review/external-review-findings.json"}
# The ONE canonical set of kind names written to findings.json is the keys of
# _LEGACY (the `-review` names). The ReviewKind objects and `handback.KINDS`
# call the four independent kinds `spec`, `test-plan`, `impl-plan`, `drift`;
# this table is the only place that maps one to the other.
STORE_KIND_BY_KEY = {"spec": "spec-review", "test-plan": "test-plan-review",
                     "impl-plan": "impl-plan-review", "drift": "drift-review",
                     "code-review": "code-review", "external-review": "external-review"}
KEY_BY_STORE_KIND = {v: k for k, v in STORE_KIND_BY_KEY.items()}
# KLC-175: `layer0` (the deterministic checks of a review run) is a store kind
# with no ReviewKind, no hand-back and no old per-kind file; it keeps its own
# name as its key. It is deliberately NOT in STORE_KIND_BY_KEY (that table is
# the independent-review kinds' name mapping), only readable through
# KEY_BY_STORE_KIND.
STORE_ONLY_KINDS = ("layer0",)
KEY_BY_STORE_KIND.update({k: k for k in STORE_ONLY_KINDS})
_LEGACY_HEADLESS = "review/headless-findings.json"   # pooled as code-review (D-111)


def legacy_headless_rel() -> str:
    """The old pooled headless file (relative to the ticket dir), archived tickets only."""
    return _LEGACY_HEADLESS


def legacy_rel(key: str) -> str:
    """The old per-kind file (relative to the ticket dir) of a KINDS key, for
    the read-only archived-ticket fallback."""
    return _LEGACY[STORE_KIND_BY_KEY[key]]


def path(ticket_dir) -> Path:
    return Path(ticket_dir) / "findings.json"


def _load_list(p: Path, notes: list) -> list[dict]:
    """A bare list or a `{"findings": [...]}` object as dict rows; [] with one
    note when unreadable or not a list (fails closed, never raises)."""
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        notes.append(f"{p.name}: unreadable ({exc})")
        return []
    if isinstance(raw, dict):
        raw = raw.get("findings")
    if not isinstance(raw, list):
        notes.append(f"{p.name}: not a JSON list")
        return []
    return [d for d in raw if isinstance(d, dict)]


def _load_legacy(tdir: Path, kind, notes: list) -> list[dict]:
    rows: list[dict] = []
    for k, rel in _LEGACY.items():
        if kind is not None and k != kind:
            continue
        p = tdir / rel
        if p.is_file():
            rows.extend({**d, "kind": k} for d in _load_list(p, notes))   # old rows say "spec", not "spec-review"
    if kind in (None, "code-review"):
        p = tdir / _LEGACY_HEADLESS
        if p.is_file():
            rows.extend({**d, "kind": "code-review"} for d in _load_list(p, notes))
    return rows


def read_dicts(ticket_dir, kind=None, round=None) -> tuple[list[dict], list[str]]:
    """Raw rows (every key kept) filtered by kind and round, plus notes."""
    notes: list[str] = []
    p = path(ticket_dir)
    rows = _load_list(p, notes) if p.is_file() else _load_legacy(Path(ticket_dir), kind, notes)
    out = [d for d in rows
           if (kind is None or d.get("kind") == kind)
           and (round is None or _round_of(d) == round)]
    return out, notes


def _round_of(d: dict) -> int:
    try:
        return int(d.get("round") or 1)
    except (TypeError, ValueError):
        return 1


def read(ticket_dir, kind=None, round=None) -> tuple[list[findings.Finding], list[str]]:
    rows, notes = read_dicts(ticket_dir, kind, round)
    out = []
    for d in rows:
        try:
            out.append(findings.Finding.from_dict(d))
        except (KeyError, TypeError, ValueError) as exc:
            notes.append(f"{path(ticket_dir).name}: skipped a malformed record ({exc})")
    return out, notes


def latest_round(ticket_dir, kind) -> int:
    rows, _ = read_dicts(ticket_dir, kind)
    return max((_round_of(d) for d in rows), default=0)


def _stamp(f: findings.Finding, kind: str, round: int) -> findings.Finding:
    d = f.to_dict()
    d.update(kind=kind, round=round, reviewer=d.get("reviewer") or kind)
    return findings.Finding.from_dict(d)


def _atomic_write(p: Path, rows: list[dict]) -> None:
    store_lock.atomic_write_text(p, json.dumps(rows, indent=2, ensure_ascii=False) + "\n")


def write_kind(ticket_dir, kind, round, items, replaces=None):
    """Replace the (kind, round) records with *items*; other records stay.
    *replaces*, when given, is a predicate on an existing (kind, round) record:
    only the records it accepts are replaced (headless partials and a `take`
    share kind code-review and must not clobber each other).
    An EMPTY *items* still replaces the group (it clears stale records); the
    only thing it never does is create a findings.json that does not exist yet.
    An existing findings.json that cannot be read raises OSError, so a write
    never destroys records it could not parse. The read-modify-write runs under
    an advisory lock, so two writers cannot drop each other's records."""
    with store_lock.locked(path(ticket_dir)):
        existing, notes = read(ticket_dir)
        if notes and path(ticket_dir).is_file():
            raise OSError(f"{path(ticket_dir).name} is unreadable: {notes[0]}")
        keep = [f for f in existing if not (f.kind == kind and f.round == round
                                            and (replaces is None or replaces(f)))]
        new = [_stamp(f, kind, round) for f in items]
        if not (keep or new) and not path(ticket_dir).is_file():
            return None
        _atomic_write(path(ticket_dir), [f.to_dict() for f in keep + new])
        return path(ticket_dir)
