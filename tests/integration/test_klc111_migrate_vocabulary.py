"""KLC-111 steps 5/6 — `klc scope-fix --migrate-vocabulary`: the frozen
corpus fixture, the read-only `--dry-run` report (AC-11, AC-18), and the
write path (AC-6, AC-9, AC-10, AC-12, AC-13, AC-18).

The corpus is FROZEN under `tests/fixtures/klc111/` — a copy of a real
deterministic `modules.json` plus a legacy-name table reproducing the spec's
measured snapshot (79 distinct names, 544 entries, 391 in vocabulary =
71.9%, 153 entries over 45 out-of-vocabulary names: 35 mappable covering 128
entries, 8 unmappable covering 19 entries, 2 directory-prefix-ambiguous
names covering 6 entries). Tests never read the live `.klc/` tree (D-011).
"""
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import state_feature  # noqa: E402
import state_sync  # noqa: E402

FIXTURES = _FW_ROOT / "tests" / "fixtures" / "klc111"
ALICE = "alice@example.com"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)})
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _meta_for(ticket: str, *, phase: str, affected) -> dict:
    return {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": list(affected), "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }


def _seed_corpus(tmp_path: Path, *, extra_tickets: dict | None = None) -> Path:
    """Seed a tmp `.klc/{index,tickets}` tree from the frozen fixture pair
    (`modules.json` + `legacy_corpus.json`). `extra_tickets` (ticket ->
    {"phase":..., "affected_modules":...}) layers additional, scenario-
    specific tickets on top of the frozen corpus. Returns the `.klc` root."""
    klc = tmp_path / ".klc"
    idx = klc / "index"
    idx.mkdir(parents=True)
    (idx / "modules.json").write_text(
        (FIXTURES / "modules.json").read_text(encoding="utf-8"), encoding="utf-8")

    corpus = json.loads((FIXTURES / "legacy_corpus.json").read_text(encoding="utf-8"))
    tickets_dir = klc / "tickets"
    tickets_dir.mkdir(parents=True)
    for rec in corpus["tickets"]:
        tdir = tickets_dir / rec["ticket"]
        tdir.mkdir()
        meta = _meta_for(rec["ticket"], phase=rec["phase"], affected=rec["affected_modules"])
        (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    for ticket, spec in (extra_tickets or {}).items():
        tdir = tickets_dir / ticket
        tdir.mkdir()
        meta = _meta_for(ticket, phase=spec["phase"], affected=spec["affected_modules"])
        (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    return klc


def _seed_git_corpus(tmp_path: Path, **kw) -> tuple[Path, Path]:
    """`_seed_corpus` plus a real git-backed `klc-state` worktree bound to a
    bare `sm` remote — the CAS-push substrate `state_feature.enabled()`
    detects (mirrors `test_klc075_scope_fix.py`'s `_build_bound_state_repo`)."""
    klc = _seed_corpus(tmp_path, **kw)
    bound = tmp_path / "sm.git"
    subprocess.run(["git", "init", "--bare", "-b", "klc-state", str(bound)],
                   check=True, capture_output=True)
    _git(klc, "init", "-b", "klc-state")
    _git(klc, "config", "user.email", ALICE)
    _git(klc, "config", "user.name", "Alice")
    _git(klc, "config", "commit.gpgsign", "false")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")
    _git(klc, "remote", "add", "sm", str(bound))
    _git(klc, "push", "-u", "sm", "klc-state")
    return klc, bound


def _seed_two_ticket_corpus(tmp_path: Path) -> Path:
    """A lean, two-archived-ticket corpus (feature-OFF — `state_tx` is a
    pure pass-through either way, so no git is needed) for the review-fix
    tests that only need to prove per-ticket exception isolation, not the
    full frozen corpus. Both tickets carry the same mappable legacy name."""
    klc = tmp_path / ".klc"
    idx = klc / "index"
    idx.mkdir(parents=True)
    modules_data = {"modules": [
        {"name": "core/skills", "path": "core/skills/",
         "files": ["core/skills/phase_completion.py"]},
    ]}
    (idx / "modules.json").write_text(json.dumps(modules_data), encoding="utf-8")
    tickets_dir = klc / "tickets"
    tickets_dir.mkdir()
    for ticket in ("KLC-CONFLICT1", "KLC-CONFLICT2"):
        tdir = tickets_dir / ticket
        tdir.mkdir()
        meta = _meta_for(ticket, phase="archived", affected=["phase_completion"])
        (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return klc


# ============================================================ step-5: dry-run

def test_dry_run_prints_mapping_plus_unmappable_and_ambiguous_lists(monkeypatch, tmp_path, capsys):
    """AC-11: `--dry-run --json` prints the mapping table plus the
    unmappable and ambiguous lists, both non-empty on the frozen corpus."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_corpus(tmp_path)
    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary", "--dry-run", "--json"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out)
    assert obj["dry_run"] is True
    assert isinstance(obj["mapping"], list) and obj["mapping"]
    assert isinstance(obj["unmappable"], list) and obj["unmappable"]
    assert isinstance(obj["ambiguous"], list) and obj["ambiguous"]
    assert "knowledge" in {e["name"] for e in obj["unmappable"]}
    assert "klc-plugin/skills" in {e["name"] for e in obj["ambiguous"]}


def test_dry_run_enters_no_state_tx_writes_no_meta_json_issues_no_git_command(
        monkeypatch, tmp_path):
    """AC-11: `--dry-run` never enters `state_tx`, writes no `meta.json` and
    issues no git command — proven against a REAL git-backed klc-state
    substrate (a fresh commit + CAS-push bound remote): HEAD, the bound
    remote's tip, the working tree and every `meta.json` mtime are all
    byte-for-byte unchanged after the run."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound = _seed_git_corpus(tmp_path)
    assert state_feature.enabled() is True

    before_head = _git(klc, "rev-parse", "HEAD").strip()
    before_bound = _git(bound, "rev-parse", "klc-state").strip()
    mtimes = {p: p.stat().st_mtime_ns for p in (klc / "tickets").rglob("meta.json")}

    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary", "--dry-run"])
    assert rc == 0

    assert _git(klc, "rev-parse", "HEAD").strip() == before_head
    assert _git(bound, "rev-parse", "klc-state").strip() == before_bound
    assert _git(klc, "status", "--porcelain").strip() == ""
    after_mtimes = {p: p.stat().st_mtime_ns for p in (klc / "tickets").rglob("meta.json")}
    assert after_mtimes == mtimes


def test_report_states_before_after_in_vocabulary_share_before_71_9_after_at_least_95_percent(
        monkeypatch, tmp_path, capsys):
    """AC-18: the dry-run report states the in-vocabulary share of
    `affected_modules` entries before and after the migration — 71.9% before
    (the frozen corpus's measured value) and at least 95% after."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_corpus(tmp_path)
    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary", "--dry-run", "--json"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out)
    share = obj["in_vocabulary_share"]
    before = share["before"]["share"]
    after = share["after"]["share"]
    assert round(before * 1000) == 719, share["before"]
    assert after >= 0.95, share["after"]


# ============================================================= step-6: write

def test_real_run_maps_at_least_35_of_45_distinct_legacy_names(monkeypatch, tmp_path, capsys):
    """AC-6: a real (non-dry-run) migration over the frozen corpus maps at
    least 35 of the 45 distinct out-of-vocabulary legacy names."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_corpus(tmp_path)
    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary", "--json"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out)
    assert len(obj["mapping"]) >= 35, obj["mapping"]


def test_real_run_maps_at_least_128_of_153_out_of_vocabulary_entries(monkeypatch, tmp_path, capsys):
    """AC-6: the same real run maps at least 128 of the 153 out-of-vocabulary
    `affected_modules` entries — measured as the growth in in-vocabulary
    entries between the before and after share (both computed against the
    ORIGINAL, pre-write corpus so the arithmetic is entry-count-preserving)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_corpus(tmp_path)
    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary", "--json"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out)
    share = obj["in_vocabulary_share"]
    grown = share["after"]["in_vocabulary"] - share["before"]["in_vocabulary"]
    assert grown >= 128, share


def test_audit_entry_appended_with_distinct_event_from_modules_to_modules_bare_ts(
        monkeypatch, tmp_path):
    """AC-9: exactly one `vocabulary-migration` audit entry is appended to a
    rewritten ticket's `phase_history`, carrying `from_modules`, `to_modules`
    and a BARE `ts` key — never `started_at`/`finished_at` (C-003), and the
    event name is distinct from `scope-fix`'s own `"scope-fix"` event."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _seed_corpus(tmp_path)
    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary"])
    assert rc == 0

    meta = json.loads((klc / "tickets" / "KLC-3000" / "meta.json").read_text())
    entries = [e for e in meta["phase_history"] if e.get("event") == "vocabulary-migration"]
    assert len(entries) == 1, meta["phase_history"]
    e = entries[0]
    assert e["event"] != "scope-fix"
    assert "from_modules" in e and "to_modules" in e
    assert "ts" in e and "started_at" not in e and "finished_at" not in e


def test_no_audit_entry_appended_when_ticket_already_in_vocabulary(monkeypatch, tmp_path):
    """AC-9 negative twin: an archived ticket whose `affected_modules` are
    ALL already in the vocabulary gets zero new `phase_history` entries."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _seed_corpus(tmp_path, extra_tickets={
        "KLC-9001": {"phase": "archived", "affected_modules": ["core/skills"]},
    })
    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary"])
    assert rc == 0
    meta = json.loads((klc / "tickets" / "KLC-9001" / "meta.json").read_text())
    assert meta["phase_history"] == []
    assert meta["affected_modules"] == ["core/skills"]


def test_migration_write_rides_acquire_lock_then_state_tx_per_ticket(monkeypatch, tmp_path):
    """AC-10: each migration write rides `acquire_lock` -> `state_tx` for
    that ONE ticket, so the klc-state commit and CAS push cover the
    rewritten ticket's own subtree — proven against a real git-backed
    substrate, mirroring `test_klc075_scope_fix.py`'s CAS-push proof."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc, bound = _seed_git_corpus(tmp_path)
    assert state_feature.enabled() is True

    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary"])
    assert rc == 0

    _git(klc, "fetch", "sm")
    remote_meta = json.loads(
        _git(klc, "show", "sm/klc-state:tickets/KLC-3000/meta.json"))
    assert any(e.get("event") == "vocabulary-migration"
               for e in remote_meta.get("phase_history", [])), (
        "the rewrite must be CAS-pushed to the bound remote")


def test_second_run_over_migrated_corpus_reports_zero_rewrites_and_exits_zero(
        monkeypatch, tmp_path, capsys):
    """AC-12: a second `--migrate-vocabulary` run over an already-migrated
    corpus reports zero rewritten tickets and exits success — the audit
    entry marks a ticket as already done."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_corpus(tmp_path)
    import scope_fix as sf
    rc1 = sf.run(["--migrate-vocabulary", "--json"])
    assert rc1 == 0
    first = json.loads(capsys.readouterr().out)
    assert first["rewritten"] > 0, first

    rc2 = sf.run(["--migrate-vocabulary", "--json"])
    assert rc2 == 0
    second = json.loads(capsys.readouterr().out)
    assert second["rewritten"] == 0, second


def test_live_non_archived_ticket_is_refused_and_left_untouched(monkeypatch, tmp_path, capsys):
    """AC-13 negative/fail-closed twin: a live (non-archived) ticket carrying
    an out-of-vocabulary name is refused, not silently corrected — its
    `affected_modules` is left byte-identical."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _seed_corpus(tmp_path, extra_tickets={
        "KLC-9002": {"phase": "discovery:work", "affected_modules": ["phase_completion"]},
    })
    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary", "--json"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out)
    row = next(r for r in obj["tickets"] if r["ticket"] == "KLC-9002")
    assert row["status"] == "refused", row
    meta = json.loads((klc / "tickets" / "KLC-9002" / "meta.json").read_text())
    assert meta["affected_modules"] == ["phase_completion"]
    assert meta["phase_history"] == []


def test_per_ticket_precision_recall_is_computable_over_migrated_corpus_no_null(
        monkeypatch, tmp_path):
    """AC-18: once `affected_modules` speaks the live vocabulary, the
    diff-to-`affected_modules` precision/recall KLC-110 wants is a plain
    set computation over two same-vocabulary name sets — never a null
    result from an incompatible universe. This ticket does not implement
    that scorer (Non-goals); it proves the computation is well-defined
    over the migrated corpus."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _seed_corpus(tmp_path)
    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary"])
    assert rc == 0

    modules_data = json.loads((klc / "index" / "modules.json").read_text())
    import module_vocabulary as mv
    vocab = mv.vocabulary(modules_data)

    checked = 0
    for tdir in sorted((klc / "tickets").iterdir()):
        meta = json.loads((tdir / "meta.json").read_text())
        planned = set(meta.get("affected_modules") or [])
        if not planned or not planned <= vocab:
            continue
        # A synthetic diff-derived "actual" set sharing the SAME vocabulary,
        # exactly what scope_delta.compare's `actual` key already produces.
        actual = planned | {sorted(vocab)[0]}
        precision = len(planned & actual) / len(actual)
        recall = len(planned & actual) / len(planned)
        assert precision is not None and recall is not None
        checked += 1
    assert checked > 0, "at least one migrated ticket must be checkable"


# ================================================== step-9: per-ticket isolation

def _patch_state_tx_to_fail_one_ticket(monkeypatch, sf, failing_ticket: str, exc: Exception):
    """Wrap the REAL `state_tx.state_tx` so it raises `exc` on entry for
    exactly `failing_ticket`, delegating to the real envelope for every
    other ticket — so the isolation proof exercises the genuine write path
    for the ticket that must still succeed."""
    real_state_tx = sf.state_tx.state_tx

    @contextlib.contextmanager
    def fake_state_tx(ticket, msg):
        if ticket == failing_ticket:
            raise exc
        with real_state_tx(ticket, msg) as v:
            yield v

    monkeypatch.setattr(sf.state_tx, "state_tx", fake_state_tx)


def test_migration_write_skips_a_ticket_on_state_conflict_and_continues(
        monkeypatch, tmp_path, capsys):
    """AC-9/AC-10: a `state_sync.StateConflictError` raised inside one
    ticket's `state_tx` is caught and turned into a `skipped` row — the walk
    continues over the remaining corpus and the report still prints (spec
    Assumptions: "a lock held by another writer... skips that ticket...
    leaves every other ticket's result intact"; ADR point 5). Before this
    fix `_migrate_one` only caught `NothingToCommitError`/`StaleStateError`/
    `_Refuse`/`_NoChange`/`LockedError`, so this exception propagated
    uncaught out of the whole batch run."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_two_ticket_corpus(tmp_path)
    import scope_fix as sf
    _patch_state_tx_to_fail_one_ticket(
        monkeypatch, sf, "KLC-CONFLICT1",
        state_sync.StateConflictError("simulated concurrent update"))

    rc = sf.run(["--migrate-vocabulary", "--json"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out)
    row1 = next(r for r in obj["tickets"] if r["ticket"] == "KLC-CONFLICT1")
    row2 = next(r for r in obj["tickets"] if r["ticket"] == "KLC-CONFLICT2")
    assert row1["status"] == "skipped", row1
    assert "concurrent" in row1["reason"].lower(), row1
    assert row2["status"] == "rewritten", row2


def test_migration_write_skips_a_ticket_on_generic_exception_and_continues(
        monkeypatch, tmp_path, capsys):
    """AC-9/AC-10 twin: a bare, unnamed exception from `state_tx`'s exit
    (mirroring `run()`'s own terminal `except Exception` for the bare
    `ValueError` `commit_and_push_cas_subtree` can raise) is ALSO caught
    and turned into a `skipped` row — one bad ticket must never abort the
    walk over the rest of the corpus."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    _seed_two_ticket_corpus(tmp_path)
    import scope_fix as sf
    _patch_state_tx_to_fail_one_ticket(
        monkeypatch, sf, "KLC-CONFLICT1",
        ValueError("git add -A refused the subtree"))

    rc = sf.run(["--migrate-vocabulary", "--json"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out)
    row1 = next(r for r in obj["tickets"] if r["ticket"] == "KLC-CONFLICT1")
    row2 = next(r for r in obj["tickets"] if r["ticket"] == "KLC-CONFLICT2")
    assert row1["status"] == "skipped", row1
    assert row2["status"] == "rewritten", row2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
