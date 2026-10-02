"""tests/integration/test_klc154_property.py — KLC-154 step-3, AC-12: a
seeded property test over the frozen redacted corpus. For at least 50
seeded ticket orderings, with injected lock and JSON failures on up to two
tickets: every migrated list/block passes the AC-8 check, a second run
(failures lifted) changes only the tickets that failed in the first run, a
third run changes nothing, every finding count and every non-empty old id
survive, and `findings.py pool` never holds fewer pooled findings than the
largest single reviewer's list. The harness itself must bite when the
mapping is patched to drop a finding.
"""
from __future__ import annotations

import contextlib
import random
import sys
from pathlib import Path

import pytest

FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW_ROOT / "core" / "skills"))

import _klc154_support as support  # noqa: E402
import findings_migrate  # noqa: E402

_JSON_RELS = tuple(r for r in support._CANDIDATE_RELS if r.endswith(".json"))


@contextlib.contextmanager
def _inject_failures(tickets: Path, victims: list, rng: random.Random):
    """Each victim either has its lock held, or has one of its JSON
    findings files truncated (restored by the returned callable) — a
    truncation victim is drawn only from tickets that own a findings JSON
    file; any other victim gets the lock failure (impl-plan-review F-4).
    Manual save/restore of `findings_migrate.acquire_lock` (not
    `monkeypatch`) because this runs inside a 50-iteration loop in one test
    function."""
    real_acquire_lock = findings_migrate.acquire_lock
    locked: set = set()
    truncated: dict = {}

    for v in victims:
        tdir = tickets / v
        candidates = [r for r in _JSON_RELS if (tdir / r).is_file()]
        if candidates and rng.random() < 0.5:
            rel = rng.choice(candidates)
            path = tdir / rel
            original = path.read_bytes()
            truncated[path] = original
            path.write_bytes(original[: max(0, len(original) // 2)])
        else:
            locked.add(v)

    def fake_acquire_lock(ticket):
        if ticket in locked:
            raise findings_migrate.LockedError(f"ticket {ticket!r} is locked")
        return real_acquire_lock(ticket)

    findings_migrate.acquire_lock = fake_acquire_lock

    def restore():
        for path, original in truncated.items():
            path.write_bytes(original)

    try:
        yield restore
    finally:
        findings_migrate.acquire_lock = real_acquire_lock


def _assert_invariants(tickets, before, first, second, third, victims):
    failed = {r["ticket"] for r in first["tickets"] if r["status"] in ("failed", "skipped")}
    assert failed == victims, (failed, victims)
    rewritten_second = {r["ticket"] for r in second["tickets"] if r["status"] == "rewritten"}
    assert rewritten_second == victims, (rewritten_second, victims)
    assert third["files_changed"] == 0, third

    after = support.snapshot_findings(tickets)
    for key, files in before.items():
        for rel, (count, ids) in files.items():
            assert after[key][rel][0] == count, (key, rel, after[key][rel][0], count)
            assert ids <= after[key][rel][1], (key, rel, ids, after[key][rel][1])
            assert support.passes_stored_check(tickets / key / rel), (key, rel)
        assert support.pool_floor_holds(tickets, key), key


def test_property_idempotent_lossless_and_pool_floor(tmp_path, monkeypatch):
    """AC-12: 50 seeded orderings with injected lock and JSON failures."""
    for seed in range(50):
        rng = random.Random(seed)
        tickets = support.make_project(tmp_path / f"s{seed}", monkeypatch)
        keys = support.materialize_corpus(tickets)
        before = support.snapshot_findings(tickets)
        victims = rng.sample(keys, k=rng.randint(0, 2))

        with _inject_failures(tickets, victims, rng) as restore:
            first = findings_migrate.migrate(tickets, order_seed=seed)
        restore()
        second = findings_migrate.migrate(tickets, order_seed=seed)
        third = findings_migrate.migrate(tickets, order_seed=seed)
        _assert_invariants(tickets, before, first, second, third, set(victims))


def test_property_harness_bites_on_a_lossy_mapping(tmp_path, monkeypatch):
    """AC-12: the invariant check itself must raise when the mapping is
    patched to drop the last record of every non-empty list — proves the
    harness is not vacuously true."""
    tickets = support.make_project(tmp_path, monkeypatch)
    support.materialize_corpus(tickets)
    before = support.snapshot_findings(tickets)

    real_map_findings = findings_migrate.map_findings

    def lossy(items, kind, *, stamp=False):
        mapped = real_map_findings(items, kind, stamp=stamp)
        return mapped[:-1] if mapped else mapped

    monkeypatch.setattr(findings_migrate, "map_findings", lossy)

    rng = random.Random(0)
    first = findings_migrate.migrate(tickets, order_seed=0)
    second = findings_migrate.migrate(tickets, order_seed=0)
    third = findings_migrate.migrate(tickets, order_seed=0)

    with pytest.raises(AssertionError):
        _assert_invariants(tickets, before, first, second, third, set())
