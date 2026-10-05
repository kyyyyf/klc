"""KLC-111 step-4 — `klc scope-fix --migrate-vocabulary` reaches its own
entry point WITHOUT ever touching the ticket-existence check or the
module-list structural validation the three shipped modes need (AC-6,
test-plan N-2, impl-plan-review F-1/HIGH).

`scope_fix.run()`'s preamble assumes a real ticket and one of
`--modules`/`--add`/`--remove`; a ticket-less fourth mode crashes unless the
dispatch moves to the top of `run()`, ahead of both checks. This is the
highest-regression-risk edit in the ticket, so it gets its own fixture-driven
regression test over the three shipped modes' exit codes, feature-OFF (no
git, no lock — the dispatch restructuring itself is feature-independent).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import state_feature  # noqa: E402


def _meta(ticket: str, *, phase: str, affected) -> dict:
    return {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": "M",
        "route_hint": "M", "route_confidence": "high",
        "affected_modules": list(affected), "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }


def _write_ticket(tmp_path: Path, ticket: str, *, phase: str, affected) -> Path:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta_p = tdir / "meta.json"
    meta_p.write_text(json.dumps(_meta(ticket, phase=phase, affected=affected)),
                      encoding="utf-8")
    return meta_p


def test_migrate_vocabulary_runs_with_no_ticket_argument(monkeypatch, tmp_path, capsys):
    """AC-6: the batch mode returns 0 without ever reaching
    `klc_ticket_meta_file(None)` or `_parse_modules(None)` — both raise on a
    ticket-less invocation in the OLD dispatch order."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert state_feature.enabled() is False

    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary", "--json"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out)
    assert obj["mode"] == "migrate-vocabulary"
    assert obj["dry_run"] is False


def test_migrate_vocabulary_with_a_ticket_argument_is_rejected(monkeypatch, tmp_path):
    """AC-6 negative twin: a ticket positional together with
    `--migrate-vocabulary` is an argparse-style error, exit 2."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import scope_fix as sf
    with pytest.raises(SystemExit) as exc:
        sf.run(["KLC-1", "--migrate-vocabulary"])
    assert exc.value.code == 2


def test_three_existing_modes_keep_their_exit_codes_and_messages(monkeypatch, tmp_path, capsys):
    """AC-6 regression: `--modules`/`--add`/`--remove` on a fixture keep
    exit 2 for a missing ticket argument, 1 for an unknown ticket, 1 for a
    malformed comma list, 1 for a non-archived ticket and 0 for an applied
    edit — none of that behaviour may change because a fourth mode joined
    the verb."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import scope_fix as sf

    # 1. missing ticket argument entirely -> argparse error, exit 2.
    with pytest.raises(SystemExit) as exc:
        sf.run(["--modules", "a"])
    assert exc.value.code == 2

    # 2. unknown ticket -> 2 (KLC-178: the alias delegates to `klc fix`, which
    #    rejects bad input with exit 2).
    rc = sf.run(["KLC-DOES-NOT-EXIST", "--modules", "a", "--reason", "r"])
    assert rc == 2
    assert "unknown ticket" in capsys.readouterr().err

    # 3. malformed comma list on a REAL ticket -> argparse-style exit 2.
    _write_ticket(tmp_path, "KLC-2", phase="archived", affected=["a"])
    with pytest.raises(SystemExit) as exc:
        sf.run(["KLC-2", "--modules", "a,,b", "--reason", "r"])
    assert exc.value.code == 2
    assert "malformed module list" in capsys.readouterr().err

    # 4. non-archived ticket, well-formed list -> applied (KLC-178 dropped the
    #    archived-only gate: `klc fix` edits modules in any state).
    meta3 = _write_ticket(tmp_path, "KLC-3", phase="build:work", affected=["a"])
    rc = sf.run(["KLC-3", "--modules", "b", "--reason", "r"])
    assert rc == 0
    assert json.loads(meta3.read_text())["affected_modules"] == ["b"]

    # 5. archived ticket, applied edit -> 0.
    meta_p = _write_ticket(tmp_path, "KLC-4", phase="archived", affected=["a"])
    rc = sf.run(["KLC-4", "--modules", "b"])
    assert rc == 0
    assert json.loads(meta_p.read_text())["affected_modules"] == ["b"]


def test_feature_off_run_routes_the_batch_mode_through_the_same_early_branch(
        monkeypatch, tmp_path, capsys):
    """AC-6 fail-closed twin: feature-OFF, the batch mode still never falls
    through to the single-ticket fallback block at the bottom of `run()` —
    there is one dispatch branch, not two."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert state_feature.enabled() is False

    import scope_fix as sf
    rc = sf.run(["--migrate-vocabulary"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "migrate-vocabulary" in out
    assert not (tmp_path / ".klc" / ".git").exists()


def test_dry_run_flag_is_rejected_outside_migrate_vocabulary(monkeypatch, tmp_path, capsys):
    """AC-6 (review-fix LOW): `--dry-run` only makes sense with
    `--migrate-vocabulary` — combined with a ticket-scoped mode it is an
    argparse-style error, exit 2, naming the flag it is only valid with.
    Regression test only: the dispatch already enforces this (step-4's
    `if args.dry_run: ap.error(...)` guard, reached only once the batch
    branch and the missing-ticket branch are both ruled out); this locks
    the behaviour down with its own node rather than leaving it implicit."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    import scope_fix as sf
    with pytest.raises(SystemExit) as exc:
        sf.run(["KLC-X", "--modules", "a", "--dry-run"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--dry-run is only valid with --migrate-vocabulary" in err


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
