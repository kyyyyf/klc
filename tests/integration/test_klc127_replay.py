#!/usr/bin/env python3
"""tests/integration/test_klc127_replay.py — KLC-127 step-8, AC-21: a replay
of `findings.py pool` over the three redacted, real-corpus replay fixtures
(`tests/fixtures/klc127-replay/`, step-6) gives 12 merged pairs, 0 false
merges and the pooled counts 4, 6 and 7 — the exact P-3/P-4 pairing (step-6's
README) reproduced through the real `findings.group`/`dedupe`.

Hermetic: reads only the committed replay fixtures; the CLI test copies a
ticket dir into tmp_path first, so nothing under the committed
tests/fixtures tree is ever written to (KLC-136/KLC-152).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import findings  # noqa: E402
import handback  # noqa: E402
from findings import Finding  # noqa: E402

REPLAY = FW_ROOT / "tests" / "fixtures" / "klc127-replay"
TICKETS = ("KLC-133", "KLC-137", "KLC-139")


def _load_pairs(ticket: str) -> dict:
    return json.loads((REPLAY / f"{ticket}-pairs.json").read_text(encoding="utf-8"))


def _load_items(ticket: str) -> list[Finding]:
    items = []
    for kind in ("code-review", "external-review"):
        path = REPLAY / f"{ticket}-{kind}-findings.json"
        for d in json.loads(path.read_text(encoding="utf-8")):
            items.append(Finding.from_dict(d))
    return items


def _key(f: Finding) -> str:
    return f"{f.reviewer}:{f.id}"


@pytest.mark.parametrize("ticket", TICKETS)
def test_replay_per_ticket_merges_only_true_pairs(ticket):
    """AC-21 (pin — already holds on step-7's `findings.group`/
    `min_similarity` alone): every merged group is exactly one of
    pairs.json's true pairs, and the pooled count matches."""
    pairs = _load_pairs(ticket)
    true_pairs = {frozenset(p) for p in pairs["true_pairs"]}
    items = _load_items(ticket)
    groups = findings.group(items, findings.min_similarity())
    assert len(groups) == pairs["pooled_count"]
    for g in groups:
        if len(g) > 1:
            assert len(g) == 2, "a group of more than 2 is not a named pair"
            assert frozenset(_key(f) for f in g) in true_pairs


def test_replay_over_the_three_tickets_yields_twelve_merges_and_zero_false():
    """AC-21 (pin — already holds on step-7's `findings.group` alone): 12
    merged pairs across the three tickets, 0 false merges."""
    total_merges = 0
    total_raw = 0
    total_pooled = 0
    for ticket in TICKETS:
        items = _load_items(ticket)
        pairs = _load_pairs(ticket)
        groups = findings.group(items, findings.min_similarity())
        merges = sum(len(g) - 1 for g in groups if len(g) > 1)
        false_merges = sum(
            1 for g in groups if len(g) > 1
            and frozenset(_key(f) for f in g) not in {frozenset(p) for p in pairs["true_pairs"]}
        )
        assert false_merges == 0
        total_merges += merges
        total_raw += len(items)
        total_pooled += len(groups)
    assert total_merges == 12
    assert total_raw == 29
    assert total_pooled == 17


def test_replay_runs_through_the_cli_on_a_copied_ticket_dir(tmp_path, monkeypatch):
    """AC-21: the replay also holds through the real `findings.py pool` CLI
    path — a fixture ticket dir is copied into tmp_path first, so nothing
    under the committed tests/fixtures tree is ever written to."""
    ticket = "KLC-133"
    project = tmp_path / "proj"
    tdir = project / ".klc" / "tickets" / ticket
    (tdir / "review").mkdir(parents=True)
    for kind in ("code-review", "external-review"):
        shutil.copy(REPLAY / f"{ticket}-{kind}-findings.json",
                   tdir / "review" / f"{kind}-findings.json")
    monkeypatch.setenv("PROJECT_ROOT", str(project))

    rc = handback.pool_main(["--ticket", ticket])
    assert rc == 0

    pool_path = tdir / "review" / "findings-pool.json"
    assert pool_path.is_file()
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    pairs = _load_pairs(ticket)
    assert pool["pooled_count"] == pairs["pooled_count"]
    assert pool["raw_count"] == 8

    # nothing under the committed fixtures tree was touched
    assert not (REPLAY / f"{ticket}-findings-pool.json").exists()
    assert not (REPLAY / ticket).exists()
