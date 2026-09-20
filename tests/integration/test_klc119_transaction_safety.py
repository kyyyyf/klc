"""KLC-119 step-2 — AC-4/AC-5 (D-201, D-202, D-205): a telemetry write never
modifies a tracked file outside an open `state_tx`, and an attempt buffered
in the journal is drained by the next transaction for that ticket — on BOTH
of `state_tx`'s branches, inside its rollback protection, with a drain
failure restored and swallowed rather than propagated.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import identity  # noqa: E402
import state_feature  # noqa: E402
import state_sync  # noqa: E402
import state_tx as state_tx_mod  # noqa: E402
import token_journal  # noqa: E402
import budget_guard  # noqa: E402

ALICE = "alice@example.com"


# --------------------------------------------------------------------------- #
# helpers (mirrors tests/integration/test_klc057_hardening.py)
# --------------------------------------------------------------------------- #

def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr or r.stdout}")
    return r.stdout


def _meta(ticket: str, *, phase: str, track: str, holder=None) -> dict:
    m = {
        "ticket": ticket, "kind": "feature", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "budgets": {"mutation_fix_attempts": 0},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if holder is not None:
        m["holder"] = holder
    return m


def _init_repo(tmp_path: Path, tickets: dict | None = None) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   capture_output=True)
    klc = tmp_path / ".klc"
    klc.mkdir()
    _git(klc, "init", "-b", "klc-state")
    _git(klc, "config", "user.email", ALICE)
    _git(klc, "config", "user.name", "Alice")
    _git(klc, "config", "commit.gpgsign", "false")
    (klc / ".seed").write_text("seed\n", encoding="utf-8")
    for ticket, meta in (tickets or {}).items():
        td = klc / "tickets" / ticket
        td.mkdir(parents=True)
        (td / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                      encoding="utf-8")
    _git(klc, "add", "-A")
    _git(klc, "commit", "-m", "seed")
    _git(klc, "remote", "add", "origin", str(bare))
    _git(klc, "push", "-u", "origin", "klc-state")
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/klc-state")
    return klc


def _remote_meta(klc: Path, ticket: str) -> dict:
    _git(klc, "fetch", "origin")
    return json.loads(_git(klc, "show", f"origin/klc-state:tickets/{ticket}/meta.json"))


def _status(klc: Path) -> str:
    return _git(klc, "status", "--porcelain").strip()


def _commit_count(klc: Path) -> int:
    return int(_git(klc, "rev-list", "--count", "HEAD").strip())


@pytest.fixture(autouse=True)
def _alice(monkeypatch):
    monkeypatch.setattr(identity, "current", lambda: ALICE)


@pytest.fixture(autouse=True)
def _reset_token_journal_state(monkeypatch):
    """The journal module's `_OPEN`/`_IGNORE_ENSURED` are process-local
    globals; reset them per test so one test's fresh `.klc/` worktree isn't
    starved of the ignore-rule population another test already triggered."""
    monkeypatch.setattr(token_journal, "_IGNORE_ENSURED", False)
    monkeypatch.setattr(token_journal, "_OPEN", set())


# --------------------------------------------------------------------------- #
# AC-4
# --------------------------------------------------------------------------- #

def test_render_outside_open_state_tx_leaves_worktree_clean_and_lands_in_journal(
        tmp_path, monkeypatch):
    """D-205: a FRESH worktree whose very first operation is a no-transaction
    write must still leave `git status --porcelain` empty — the journal
    writer ensures its own ignore rule, it does not inherit one from a prior
    transaction."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-J001": _meta("KLC-J001", phase="build:work", track="M"),
    })
    assert state_feature.enabled() is True
    assert token_journal.tx_open("KLC-J001") is False

    budget_guard.write_token_metrics("KLC-J001", "build", 123, 45, 0,
                                     source="estimated", card_bytes=500)

    assert _status(klc) == "", \
        "a no-transaction telemetry write must leave the worktree clean (AC-4)"
    records = token_journal.read("KLC-J001")
    assert len(records) == 1
    assert records[0]["phase"] == "build"
    assert records[0]["in"] == 123


def test_journal_path_is_covered_by_state_sync_derived_ignores():
    """Q-001's working assumption, asserted directly: the journal's
    path/glob is present in `state_sync._DERIVED_IGNORES`."""
    assert any("telemetry.jsonl" in rule for rule in state_sync._DERIVED_IGNORES)


# --------------------------------------------------------------------------- #
# AC-5
# --------------------------------------------------------------------------- #

def test_next_state_tx_drains_journal_into_meta_json_in_same_commit_and_empties_it(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-J003": _meta("KLC-J003", phase="review-lite:ack-needed", track="XS",
                         holder={"id": ALICE, "machine": "box",
                                 "since": "2026-01-01T00:00:00Z"}),
    })
    assert state_feature.enabled() is True

    token_journal.append("KLC-J003", {
        "id": "att-drain-1", "ts": "2026-01-01T00:00:00Z",
        "in": 10, "out": 2, "cache_hit": 0, "source": "estimated",
        "card_bytes": 40, "phase": "review-lite",
    })
    assert token_journal.read("KLC-J003"), "fixture must actually seed the journal"

    before = _commit_count(klc)
    import ack as ack_mod
    rc = ack_mod.run(["KLC-J003", "--pick", "1"])
    assert rc == 0, "ack must succeed"
    after = _commit_count(klc)
    assert after == before + 1, \
        "the drain must ride the SAME commit as the transition, not a second one"

    meta = _remote_meta(klc, "KLC-J003")
    attempts = meta["metrics"]["tokens"]["review-lite"]["attempts"]
    assert any(a["id"] == "att-drain-1" for a in attempts), \
        "the buffered attempt must be drained into the committed meta.json"
    # The journal is emptied of the DRAINED attempt; ack.py's own post-tx
    # render of the newly-entered "integrate" phase (F-013 — a journalling
    # site in its own right, AC-6) legitimately adds a fresh entry right
    # after, so the journal is not necessarily EMPTY, just no longer
    # carrying the drained id.
    assert not any(r.get("id") == "att-drain-1"
                  for r in token_journal.read("KLC-J003")), \
        "the drained attempt must no longer sit in the journal"


def test_crash_between_journal_write_and_drain_loses_nothing_journal_survives_and_drains_later(
        tmp_path, monkeypatch):
    """Simulates a process death between the journal append and the next
    transition's drain (the drain raises on the first transaction). The
    journal must still hold the attempt afterward, and a SUBSEQUENT normal
    transaction for the same ticket must drain it — 'no attempt is lost',
    not just 'not lost on the happy path'."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-J004": _meta("KLC-J004", phase="review:work", track="M"),
    })
    assert state_feature.enabled() is True

    token_journal.append("KLC-J004", {
        "id": "att-crash-1", "ts": "2026-01-01T00:00:00Z",
        "in": 7, "out": 1, "cache_hit": 0, "source": "estimated",
        "card_bytes": 30, "phase": "review",
    })

    real_drain = state_tx_mod._drain_journal

    def _boom(ticket):
        raise RuntimeError("simulated crash before the drain completes")

    def _touch(tag: str) -> None:
        p = klc / "tickets" / "KLC-J004" / "note.md"
        p.write_text(f"note {tag}\n", encoding="utf-8")

    monkeypatch.setattr(state_tx_mod, "_drain_journal", _boom)
    with state_tx_mod.state_tx("KLC-J004", "simulated op 1"):
        _touch("1")
    monkeypatch.setattr(state_tx_mod, "_drain_journal", real_drain)

    assert token_journal.read("KLC-J004"), \
        "the journal must still hold the attempt after the simulated crash"

    with state_tx_mod.state_tx("KLC-J004", "simulated op 2"):
        _touch("2")

    assert token_journal.read("KLC-J004") == [], \
        "a later normal transaction for the same ticket must drain it"
    meta = _remote_meta(klc, "KLC-J004")
    attempts = meta["metrics"]["tokens"]["review"]["attempts"]
    assert any(a["id"] == "att-crash-1" for a in attempts)


def test_feature_off_state_tx_drains_the_journal_into_meta_json(tmp_path, monkeypatch):
    """D-201: feature-OFF is the headless runner's ONLY mode — the drain
    must run on this branch too, or the autorunner's whole domain would
    never drain."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    tdir = tmp_path / ".klc" / "tickets" / "KLC-J005"
    tdir.mkdir(parents=True)
    meta = _meta("KLC-J005", phase="build:work", track="M")
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")

    monkeypatch.setattr(state_feature, "enabled", lambda: False)

    token_journal.append("KLC-J005", {
        "id": "att-off-1", "ts": "2026-01-01T00:00:00Z",
        "in": 8, "out": 3, "cache_hit": 0, "source": "estimated",
        "card_bytes": 32, "phase": "build",
    })

    with state_tx_mod.state_tx("KLC-J005", "feature-off no-op body"):
        pass

    stored = json.loads((tdir / "meta.json").read_text())
    attempts = stored["metrics"]["tokens"]["build"]["attempts"]
    assert any(a["id"] == "att-off-1" for a in attempts)
    assert token_journal.read("KLC-J005") == []


def test_drain_failure_restores_meta_json_leaves_journal_intact_and_worktree_clean(
        tmp_path, monkeypatch):
    """D-202: a drain that fails mid-write is restored and swallowed — never
    propagated. meta.json ends up byte-identical to its pre-drain snapshot
    (no partial write survives), the journal keeps the undrained attempt,
    the worktree is clean, and the verb's own transition still went through
    with exit code 0."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-J006": _meta("KLC-J006", phase="review-lite:ack-needed", track="XS",
                         holder={"id": ALICE, "machine": "box",
                                 "since": "2026-01-01T00:00:00Z"}),
    })
    assert state_feature.enabled() is True

    token_journal.append("KLC-J006", {
        "id": "att-fail-1", "ts": "2026-01-01T00:00:00Z",
        "in": 5, "out": 1, "cache_hit": 0, "source": "estimated",
        "card_bytes": 20, "phase": "review-lite",
    })

    def _boom(ticket):
        # A partial write BEFORE failing — proves the restore actually
        # reverts a half-completed drain, not just a no-op.
        budget_guard.write_token_metrics(
            ticket, "review-lite", 999, 999, 0, source="estimated",
            card_bytes=1, attempt_id="partial-write")
        raise RuntimeError("simulated drain failure mid-write")

    monkeypatch.setattr(state_tx_mod, "_drain_journal", _boom)

    import ack as ack_mod
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        rc = ack_mod.run(["KLC-J006", "--pick", "1"])

    assert rc == 0, "a drain failure must never take the verb down (D-202/C-003)"
    stderr_text = buf.getvalue()
    assert "telemetry: drain failed" in stderr_text
    assert str(token_journal.journal_path("KLC-J006")) in stderr_text

    meta = _remote_meta(klc, "KLC-J006")
    attempts = meta.get("metrics", {}).get("tokens", {}) \
                   .get("review-lite", {}).get("attempts", [])
    assert not any(a.get("id") == "partial-write" for a in attempts), \
        "the partial drain write must be rolled back"
    assert meta["phase"] != "review-lite:ack-needed", \
        "the verb's own transition must still go through despite the drain failure"
    assert token_journal.read("KLC-J006"), \
        "the journal must still hold the undrained attempt"
    assert _status(klc) == "", "the worktree must be clean after a drain failure"


# --------------------------------------------------------------------------- #
# AC-5 — review-fix round 1, LOW finding: drain succeeded, THEN the CAS push
# itself is rejected (distinct from the drain call itself raising, already
# covered above).
# --------------------------------------------------------------------------- #

def test_drain_succeeds_then_cas_push_is_rejected_leaves_journal_intact_and_meta_unpromoted(
        tmp_path, monkeypatch):
    """AC-5: `_drain_journal` completes cleanly (the attempt lands in the
    in-memory `meta.json` about to be committed) and THEN
    `state_sync.commit_and_push_cas_subtree` itself raises — a real
    CAS-rejection class of failure, unrelated to the drain. The whole `try`
    that wraps `yield` and the CAS push also wraps the (already-succeeded)
    drain, so the `except Exception:` handler must restore the pre-drain
    subtree snapshot and never reach the post-try `token_journal.consume`
    line: the journal keeps the id exactly as if the drain had never run,
    and no attempt is promoted into the ticket's committed `meta.json`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    klc = _init_repo(tmp_path, {
        "KLC-J007": _meta("KLC-J007", phase="review:work", track="M"),
    })
    assert state_feature.enabled() is True

    token_journal.append("KLC-J007", {
        "id": "att-cas-rejected-1", "ts": "2026-01-01T00:00:00Z",
        "in": 9, "out": 4, "cache_hit": 0, "source": "estimated",
        "card_bytes": 36, "phase": "review",
    })
    assert token_journal.read("KLC-J007"), "fixture must actually seed the journal"

    before_commits = _commit_count(klc)
    before_meta = _remote_meta(klc, "KLC-J007")

    def _boom_commit(ticket, msg, kdir):
        raise state_sync.StaleStateError(
            "simulated CAS rejection — remote advanced under this push")

    monkeypatch.setattr(state_sync, "commit_and_push_cas_subtree", _boom_commit)

    with pytest.raises(state_sync.StaleStateError):
        with state_tx_mod.state_tx("KLC-J007", "op rejected by a stale CAS push"):
            pass  # the body itself never gets a chance to matter here

    # The drain ran (it is not monkeypatched in this test) and would have
    # produced a durable write had the push succeeded; since it did not, the
    # rollback must have reverted that write along with everything else.
    assert _remote_meta(klc, "KLC-J007") == before_meta, \
        "a rejected CAS push after a successful drain must leave the " \
        "ticket's committed meta.json exactly as it was — no partial promotion"
    assert _commit_count(klc) == before_commits, \
        "no commit should have landed on a rejected CAS push"
    remaining = token_journal.read("KLC-J007")
    assert any(r.get("id") == "att-cas-rejected-1" for r in remaining), \
        "the journal must still hold the attempt — it was drained but never " \
        "confirmed-pushed, so token_journal.consume must never have run for it"
    assert _status(klc) == "", \
        "the rollback must leave the worktree clean despite the successful " \
        "drain that preceded the rejected push"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
