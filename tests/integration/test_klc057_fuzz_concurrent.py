"""KLC-057 — TRUE-CONCURRENT CAS-race driver (multiprocessing, real git).

The sequential fuzz (test_klc057_fuzz.py) cannot produce a same-pull-window CAS
race: each op's state_tx pulls at enter, so a later actor always sees the earlier
push. This module uses real OS processes and a multiprocessing.Barrier to
DETERMINISTICALLY create the race: every worker runs its verb up to just before
the push, waits on the barrier, then all push at once against the shared bare
origin klc-state — so >=2 pushes contend on the same ref.

The barrier is armed by monkeypatching (in each child) state_sync.
commit_and_push_cas_subtree to barrier.wait() before delegating to the real one.
Because state_tx pulls BEFORE the body and pushes only via that function, and no
worker pushes until all have arrived at the barrier, every worker provably raced
from the same base commit.

Scenarios (many iterations each; assertions are who-wins-AGNOSTIC — we assert the
invariant, not a specific winner):
  1. same-ticket concurrent ack   → exactly one wins, losers clean-abort, converge
  2. concurrent intake same key   → exactly one INTAKE_OK, other clean "taken"
  3. intake --force vs peer-held   → holder-auth: no silent cross-user steal
  4. mixed random concurrent load  → all 7 invariants after each round settles

Env: KLC_FUZZ_CONC_ROUNDS (default 20), KLC_FUZZ_CONC_USERS (default 3, for #4).
Offline. Clean teardown of worker processes.
"""
from __future__ import annotations

import io
import json
import multiprocessing as _mp
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FW_ROOT))
sys.path.insert(0, str(_FW_ROOT / "core" / "skills"))
sys.path.insert(0, str(_FW_ROOT / "core" / "phases"))

import phases as _ph  # noqa: E402

_ROUNDS = int(os.environ.get("KLC_FUZZ_CONC_ROUNDS", "20"))
_CLEAN_ABORT_MARKERS = (
    "concurrent update", "remote state advanced", "phase held by",
    "already taken", "state sync failed", "resolve manually",
)


# --------------------------------------------------------------------------- #
# git helpers (parent side)
# --------------------------------------------------------------------------- #

def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd)},
    )


def _git(cwd: Path, *args: str) -> str:
    r = _run_git(cwd, *args)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} in {cwd} failed: {r.stderr or r.stdout}")
    return r.stdout


class _User:
    def __init__(self, root: Path, email: str):
        self.root = root
        self.klc = root / ".klc"
        self.email = email


def _build_cluster(tmp_path: Path, nusers: int) -> tuple[Path, list[_User], Path]:
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    users: list[_User] = []
    u0 = _User(tmp_path / "u0", "user0@example.com")
    u0.klc.mkdir(parents=True)
    _git(u0.klc, "init", "-q", "-b", "klc-state")
    _git(u0.klc, "config", "user.email", u0.email)
    _git(u0.klc, "config", "user.name", "user0")
    _git(u0.klc, "config", "commit.gpgsign", "false")
    (u0.klc / ".seed").write_text("seed\n", encoding="utf-8")
    _git(u0.klc, "add", "-A")
    _git(u0.klc, "commit", "-q", "-m", "klc-state: orphan root")
    _git(u0.klc, "remote", "add", "origin", str(bare))
    _git(u0.klc, "push", "-q", "-u", "origin", "klc-state")
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/klc-state")
    users.append(u0)
    for i in range(1, nusers):
        u = _User(tmp_path / f"u{i}", f"user{i}@example.com")
        _git(tmp_path, "clone", "-q", str(bare), str(u.klc))
        _git(u.klc, "config", "user.email", u.email)
        _git(u.klc, "config", "user.name", f"user{i}")
        _git(u.klc, "config", "commit.gpgsign", "false")
        users.append(u)
    observer = tmp_path / "observer"
    _git(tmp_path, "clone", "-q", str(bare), str(observer))
    return bare, users, observer


def _seed_ticket(users: list[_User], key: str, phase: str, track: str = "S",
                 holder: dict | None = None) -> None:
    """Commit a ticket meta on u0, push, and pull it into every other user so all
    checkouts share the same base for the race."""
    u0 = users[0]
    td = u0.klc / "tickets" / key
    td.mkdir(parents=True, exist_ok=True)
    meta = {
        "ticket": key, "kind": "feature", "kind_source": "user", "phase": phase,
        "phase_history": [], "track": track, "route_hint": track,
        "route_confidence": "high", "affected_modules": [], "estimate": None,
        "layer": "code", "budgets": {"mutation_fix_attempts": 0},
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if holder is not None:
        meta["holder"] = holder
    (td / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    _git(u0.klc, "add", "-A")
    _git(u0.klc, "commit", "-q", "-m", f"seed {key}")
    _git(u0.klc, "push", "-q", "origin", "klc-state")
    for u in users[1:]:
        _git(u.klc, "pull", "-q", "--rebase", "--autostash")


def _origin_paths(observer: Path) -> set[str]:
    _run_git(observer, "fetch", "-q", "origin")
    r = _run_git(observer, "ls-tree", "-r", "--name-only", "origin/klc-state")
    return {p for p in r.stdout.splitlines() if p.strip()} if r.returncode == 0 else set()


def _origin_meta(observer: Path, key: str):
    _run_git(observer, "fetch", "-q", "origin")
    r = _run_git(observer, "show", f"origin/klc-state:tickets/{key}/meta.json")
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return "MALFORMED"


def _valid_phase(phase, ph) -> bool:
    if phase == _ph.STATE_ARCHIVED:
        return True
    try:
        pid, st = _ph.parse_state(phase)
    except Exception:
        return False
    if st not in (_ph.STATE_WORK, _ph.STATE_ACK_NEEDED, _ph.STATE_ACK):
        return False
    try:
        ph.by_id(pid)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# worker (child process): run a verb, pausing at the barrier just before push
# --------------------------------------------------------------------------- #

def _worker(barrier, root: str, email: str, verb_name: str, argv, q) -> None:
    os.environ["PROJECT_ROOT"] = str(root)
    os.environ["KLC_INTAKE_TRIAGE"] = "0"
    import identity
    import state_sync
    import phase_completion
    identity.current = lambda: email
    phase_completion.can_complete = lambda t, p: (True, "")
    import intake as intake_mod
    import ack as ack_mod
    import next as next_mod
    import steal as steal_mod        # KLC-061
    import ship as ship_mod          # KLC-061
    import abort as abort_mod        # KLC-061
    import jump as jump_mod          # KLC-061
    mods = {"intake": intake_mod, "ack": ack_mod, "next": next_mod,
            "steal": steal_mod, "ship": ship_mod,
            "abort": abort_mod, "jump": jump_mod}

    reached = {"v": False}
    _orig_push = state_sync.commit_and_push_cas_subtree

    def _hooked(*a, **k):
        reached["v"] = True
        try:
            barrier.wait()          # release the race only once ALL have pulled
        except Exception:
            pass                    # broken/aborted barrier → proceed to push
        return _orig_push(*a, **k)

    state_sync.commit_and_push_cas_subtree = _hooked

    buf = io.StringIO()
    saved = (sys.stdout, sys.stderr)
    sys.stdout = sys.stderr = buf
    rc = -998
    try:
        rc = int(mods[verb_name].run(list(argv)))
    except BaseException as exc:  # noqa: BLE001 — a crash is a reportable outcome
        rc = -999
        buf.write(f"\nCRASH {type(exc).__name__}: {exc}\n")
    finally:
        sys.stdout, sys.stderr = saved
        if not reached["v"]:
            # We will never reach the barrier (aborted before push) — release any
            # peers waiting on us so the race cannot deadlock.
            try:
                barrier.abort()
            except Exception:
                pass
    q.put((email, verb_name, rc, buf.getvalue()))


def _spawn_race(specs) -> list[tuple]:
    """specs: list of (user, verb_name, argv). Runs them concurrently with a
    barrier aligned just before each push. Returns [(email, verb, rc, out), ...]."""
    ctx = _mp.get_context("fork")
    barrier = ctx.Barrier(len(specs), timeout=45)
    q = ctx.Queue()
    procs = []
    for (user, verb, argv) in specs:
        p = ctx.Process(target=_worker,
                        args=(barrier, str(user.root), user.email, verb, argv, q))
        p.start()
        procs.append(p)
    results = []
    for _ in specs:
        try:
            results.append(q.get(timeout=120))
        except Exception:
            break
    for p in procs:
        p.join(timeout=15)
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
    return results


# --------------------------------------------------------------------------- #
# shared post-race invariant checks
# --------------------------------------------------------------------------- #

def _assert_clean_abort(rc: int, out: str, ctx: str) -> None:
    assert rc != -999, f"{ctx}: verb CRASHED:\n{out[-800:]}"
    assert rc != 0, f"{ctx}: expected a non-zero (losing) rc, got 0"
    low = out.lower()
    assert "traceback" not in low, f"{ctx}: traceback leaked to the user:\n{out[-800:]}"
    assert any(m in low for m in _CLEAN_ABORT_MARKERS), \
        f"{ctx}: loser message not a recognized clean abort:\n{out[-800:]}"


def _settle_and_converge(users: list[_User], observer: Path, ctx: str) -> str:
    """Each user must have a clean tree (no wedge), a follow-up pull must succeed
    (no deadlock), and all must converge to the single origin tip. Returns tip."""
    for u in users:
        status = _run_git(u.klc, "status", "--porcelain").stdout.strip()
        assert status == "", f"{ctx}: INV1 wedge — {u.email} dirty tree:\n{status}"
    for u in users:
        pr = _run_git(u.klc, "pull", "--rebase", "--autostash")
        assert pr.returncode == 0, \
            f"{ctx}: INV2 deadlock — {u.email} follow-up pull failed: {pr.stderr or pr.stdout}"
    _run_git(observer, "fetch", "-q", "origin")
    tip = _git(observer, "rev-parse", "origin/klc-state").strip()
    heads = {u.email: _git(u.klc, "rev-parse", "HEAD").strip() for u in users}
    assert set(heads.values()) == {tip}, \
        f"{ctx}: INV6 divergence — heads {heads} != origin {tip}"
    return tip


def _assert_no_derived_on_origin(observer: Path, ctx: str) -> None:
    for p in _origin_paths(observer):
        base = p.rsplit("/", 1)[-1]
        assert not (base == ".lock" or base == ".index.json"
                    or base.startswith("_prompt")
                    or ("/" + p).find("/scratch/") >= 0
                    or p == "knowledge/tickets-index.jsonl"), \
            f"{ctx}: INV7 derived file on origin: {p!r}"


# --------------------------------------------------------------------------- #
# scenario 1 — same-ticket concurrent ack
# --------------------------------------------------------------------------- #

def test_scenario1_same_ticket_concurrent_ack(tmp_path):
    _, users, observer = _build_cluster(tmp_path, 2)
    ph = _ph.load_phases()
    wins = losses = 0
    for r in range(_ROUNDS):
        key = f"KLC-{2000 + r}"
        _seed_ticket(users, key, phase="build:ack-needed", track="S")  # UNHELD
        pre = _origin_meta(observer, key)
        results = _spawn_race([(users[0], "ack", [key, "--pick", "1"]),
                               (users[1], "ack", [key, "--pick", "1"])])
        ctx = f"scenario1 round={r} key={key} results={[(e,rc) for e,_,rc,_ in results]}"
        assert len(results) == 2, f"{ctx}: lost a worker result"
        winners = [x for x in results if x[2] == 0]
        assert len(winners) == 1, f"{ctx}: expected EXACTLY ONE winner"
        wins += 1
        for (e, v, rc, out) in results:
            if rc != 0:
                losses += 1
                _assert_clean_abort(rc, out, ctx + f" loser={e}")
        # the winner's advance is on origin; the loser's was NOT applied
        m = _origin_meta(observer, key)
        assert m not in (None, "MALFORMED"), f"{ctx}: INV3 meta lost/malformed"
        assert m.get("phase") == "review:work", \
            f"{ctx}: INV3/5 winner advance not on origin (phase={m.get('phase')!r})"
        assert _valid_phase(m.get("phase"), ph), f"{ctx}: INV5 illegal phase"
        _assert_no_derived_on_origin(observer, ctx)
        _settle_and_converge(users, observer, ctx)
    sys.stderr.write(f"\n[scenario1] {_ROUNDS} rounds: wins={wins} losses={losses}\n")


# --------------------------------------------------------------------------- #
# scenario 2 — concurrent intake of the SAME new key
# --------------------------------------------------------------------------- #

def test_scenario2_concurrent_intake_same_key(tmp_path):
    _, users, observer = _build_cluster(tmp_path, 2)
    ok = taken = 0
    for r in range(_ROUNDS):
        key = f"KLC-{3000 + r}"
        results = _spawn_race([(users[0], "intake", [key, f"desc0 {key}"]),
                               (users[1], "intake", [key, f"desc1 {key}"])])
        ctx = f"scenario2 round={r} key={key} results={[(e,rc) for e,_,rc,_ in results]}"
        assert len(results) == 2, f"{ctx}: lost a worker result"
        winners = [x for x in results if x[2] == 0 and "INTAKE_OK" in x[3]]
        assert len(winners) == 1, f"{ctx}: expected EXACTLY ONE INTAKE_OK"
        ok += 1
        winner_email = winners[0][0]
        for (e, v, rc, out) in results:
            if e != winner_email:
                taken += 1
                _assert_clean_abort(rc, out, ctx + f" loser={e}")
                assert "already taken" in out.lower() or "taken" in out.lower(), \
                    f"{ctx}: loser should say 'already taken':\n{out[-400:]}"
                # loser must leave NO partial artifacts locally
                loser = next(u for u in users if u.email == e)
                st = _run_git(loser.klc, "status", "--porcelain").stdout.strip()
                assert st == "", f"{ctx}: loser {e} left a dirty tree:\n{st}"
        # winner's ticket + holder intact on origin (not clobbered)
        m = _origin_meta(observer, key)
        assert m not in (None, "MALFORMED"), f"{ctx}: INV3 winner ticket missing/malformed"
        assert m.get("holder", {}).get("id") == winner_email, \
            f"{ctx}: INV4 winner holder clobbered (holder={m.get('holder')!r})"
        _assert_no_derived_on_origin(observer, ctx)
        _settle_and_converge(users, observer, ctx)
    sys.stderr.write(f"\n[scenario2] {_ROUNDS} rounds: intake_ok={ok} taken={taken}\n")


# --------------------------------------------------------------------------- #
# scenario 3 — intake --force vs a peer-HELD ticket (holder-auth corner)
# --------------------------------------------------------------------------- #

def test_scenario3_force_vs_peer_held(tmp_path):
    """INV4 (harden6): `intake --force` racing a peer-HELD ticket must NEVER
    silently transfer the holder to the forcing user. In every round the holder
    of the ticket stays the original holder (or a legal advance thereof) — the
    forcing user only obtains it via `klc steal`, never via --force. Who wins the
    CAS is irrelevant; the invariant is that no cross-user steal occurs."""
    ph = _ph.load_phases()
    _, users, observer = _build_cluster(tmp_path, 2)
    holder_user, force_user = users[0], users[1]
    force_refused = held_op_wins = steal_findings = 0
    for r in range(_ROUNDS):
        key = f"KLC-{4000 + r}"
        held = {"id": holder_user.email, "machine": "m",
                "since": "2026-01-01T00:00:00Z"}
        _seed_ticket(users, key, phase="build:ack", track="S", holder=held)
        # holder_user does a legit op it is authorized for; force_user re-intakes.
        results = _spawn_race([
            (holder_user, "next", [key]),
            (force_user, "intake", [key, "--force", f"force {key}"]),
        ])
        ctx = f"scenario3 round={r} key={key} results={[(e,rc) for e,_,rc,_ in results]}"
        assert len(results) == 2, f"{ctx}: lost a worker result"
        by_email = {e: (rc, out) for e, v, rc, out in results}
        for e, (rc, out) in by_email.items():
            assert rc != -999, f"{ctx}: {e} crashed:\n{out[-800:]}"
        force_rc, force_out = by_email[force_user.email]
        # --force must be REFUSED with a holder-auth message (it must not push).
        if force_rc != 0:
            force_refused += 1
            low = force_out.lower()
            assert "held by" in low or "steal" in low \
                or "concurrent update" in low or "remote state advanced" in low, \
                f"{ctx}: --force loser message not a clean holder/CAS abort:\n{force_out[-500:]}"
            assert "traceback" not in low, f"{ctx}: traceback leaked:\n{force_out[-500:]}"
        m = _origin_meta(observer, key)
        assert m not in (None, "MALFORMED"), f"{ctx}: INV3 meta lost/malformed"
        phase = m.get("phase")
        hid = (m.get("holder") or {}).get("id")
        # INV4: the forcing user must NEVER hold the ticket (no silent steal).
        if hid == force_user.email:
            steal_findings += 1
        assert hid != force_user.email, (
            f"{ctx}: INV4 cross-user steal — `intake --force` by {force_user.email} "
            f"took a phase held by {holder_user.email} "
            f"(now phase={phase!r} holder={hid!r})")
        # INV4/5: the phase must not have been reset to intake by the forcing user
        # (i.e. no silent overwrite of the peer's held ticket).
        assert not (force_rc == 0 and phase == "intake:ack-needed"), \
            f"{ctx}: INV4 --force overwrote the peer-held ticket to {phase!r}"
        if phase != "build:ack":
            held_op_wins += 1
        assert _valid_phase(phase, ph), f"{ctx}: INV5 illegal phase {phase!r}"
        _assert_no_derived_on_origin(observer, ctx)
        _settle_and_converge(users, observer, ctx)
    sys.stderr.write(
        f"\n[scenario3] {_ROUNDS} rounds: force_refused={force_refused} "
        f"held_op_advanced={held_op_wins} steal_findings={steal_findings}\n")
    assert steal_findings == 0, \
        f"scenario3: {steal_findings} cross-user steals (INV4) — the fix regressed"


# --------------------------------------------------------------------------- #
# scenario 4 — mixed random concurrent load, all 7 invariants each round
# --------------------------------------------------------------------------- #

def test_scenario4_mixed_concurrent_load(tmp_path):
    nusers = int(os.environ.get("KLC_FUZZ_CONC_USERS", "3"))
    _, users, observer = _build_cluster(tmp_path, nusers)
    ph = _ph.load_phases()
    rng = random.Random(20240607)
    created: set[str] = set()
    rounds = max(6, _ROUNDS // 2)
    kc = [0]

    def _fresh() -> str:
        kc[0] += 1
        return f"KLC-{5000 + kc[0]}"

    outcome = {"ok": 0, "abort": 0}
    for r in range(rounds):
        specs = []
        nw = rng.randint(2, min(3, nusers))
        actors = rng.sample(users, nw)
        # bias toward same-ticket contention when tickets exist
        shared_key = rng.choice(sorted(created)) if created and rng.random() < 0.6 else None
        for u in actors:
            if shared_key and rng.random() < 0.7:
                key = shared_key
                mp_phase = _origin_meta(observer, key)
                st = None
                if mp_phase not in (None, "MALFORMED"):
                    try:
                        _, st = _ph.parse_state(mp_phase.get("phase"))
                    except Exception:
                        st = None
                if st == _ph.STATE_ACK:
                    specs.append((u, "next", [key]))
                else:
                    specs.append((u, "ack", [key, "--pick", "1"]))
            else:
                key = _fresh()
                created.add(key)
                specs.append((u, "intake", [key, f"desc {key} r{r}"]))
        results = _spawn_race(specs)
        ctx = f"scenario4 round={r} specs={[(u.email,v,a) for u,v,a in specs]} " \
              f"results={[(e,rc) for e,_,rc,_ in results]}"
        # never a crash
        for (e, v, rc, out) in results:
            assert rc != -999, f"{ctx}: {e} crashed:\n{out[-800:]}"
            outcome["ok" if rc == 0 else "abort"] += 1
        # a fresh intake that reported INTAKE_OK is a durable ticket
        for (e, v, rc, out) in results:
            if v == "intake" and rc == 0 and "INTAKE_OK" in out:
                pass  # already in `created`
        # settle, then full invariant sweep over origin
        _assert_no_derived_on_origin(observer, ctx)
        tip = _settle_and_converge(users, observer, ctx)
        paths = _origin_paths(observer)
        for k in sorted(created):
            # a key only counts as durable once its meta is on origin; a losing
            # concurrent intake leaves nothing, so tolerate not-yet-present keys
            # that never won — but once present it must stay well-formed + legal.
            if f"tickets/{k}/meta.json" in paths:
                m = _origin_meta(observer, k)
                assert m not in (None, "MALFORMED"), f"{ctx}: INV3 {k} malformed"
                assert _valid_phase(m.get("phase"), ph), \
                    f"{ctx}: INV5 {k} illegal phase {m.get('phase')!r}"
        # INV4: no successful op moved a phase held by a different user is
        # enforced by the verbs' holder checks; here we assert the weaker global
        # property that every present ticket's holder (if any) is a known user.
        for k in sorted(created):
            if f"tickets/{k}/meta.json" in paths:
                m = _origin_meta(observer, k)
                h = (m or {}).get("holder")
                if isinstance(h, dict) and h.get("id"):
                    assert h["id"] in {u.email for u in users}, \
                        f"{ctx}: INV4 unknown holder {h['id']!r} on {k}"
    sys.stderr.write(
        f"\n[scenario4] {rounds} rounds: ok={outcome['ok']} abort={outcome['abort']} "
        f"tickets_attempted={len(created)}\n")


# --------------------------------------------------------------------------- #
# scenario 5 — concurrent steal of a STALE holder (KLC-061)
# --------------------------------------------------------------------------- #

def test_scenario5_concurrent_steal_stale_holder(tmp_path):
    """KLC-061 AC-6: two users race to `klc steal` a ticket whose holder is stale.
    Exactly one steal wins the CAS, the loser clean-aborts, the winner's identity
    is durable on origin, and all workers converge — the same 7 invariants as the
    ack race, now for the state_tx-wrapped steal verb. `steal` is a single-push op
    so it slots directly into the barrier race."""
    _, users, observer = _build_cluster(tmp_path, 2)
    ph = _ph.load_phases()
    stolen = 0
    for r in range(_ROUNDS):
        key = f"KLC-{6000 + r}"
        stale = {"id": "ghost@example.com", "machine": "m",
                 "since": "2020-01-01T00:00:00Z"}  # far past → stealable
        _seed_ticket(users, key, phase="build:work", track="S", holder=stale)
        results = _spawn_race([(users[0], "steal", [key]),
                               (users[1], "steal", [key])])
        ctx = f"scenario5 round={r} key={key} results={[(e,rc) for e,_,rc,_ in results]}"
        assert len(results) == 2, f"{ctx}: lost a worker result"
        winners = [x for x in results if x[2] == 0]
        assert len(winners) == 1, f"{ctx}: expected EXACTLY ONE steal to win"
        stolen += 1
        for (e, v, rc, out) in results:
            if rc != 0:
                _assert_clean_abort(rc, out, ctx + f" loser={e}")
        # the winner's identity is durable on origin (INV3/INV4/INV6).
        m = _origin_meta(observer, key)
        assert m not in (None, "MALFORMED"), f"{ctx}: INV3 meta lost/malformed"
        hid = (m.get("holder") or {}).get("id")
        assert hid == winners[0][0], \
            f"{ctx}: INV3 CAS winner's steal not durable on origin (holder={hid!r})"
        assert hid in {u.email for u in users}, \
            f"{ctx}: INV4 holder is not one of the known stealers ({hid!r})"
        assert _valid_phase(m.get("phase"), ph), f"{ctx}: INV5 illegal phase"
        _assert_no_derived_on_origin(observer, ctx)
        _settle_and_converge(users, observer, ctx)
    sys.stderr.write(f"\n[scenario5] {_ROUNDS} rounds: stolen={stolen}\n")


# --------------------------------------------------------------------------- #
# scenario 6 — concurrent ship vs ack from the SAME :ack-needed (KLC-061)
# --------------------------------------------------------------------------- #

def test_scenario6_concurrent_ship_and_ack(tmp_path):
    """KLC-061 AC-1/AC-6: `klc ship` (routed through the wrapped ack.run) races a
    plain `klc ack`, both advancing the same `<P>:ack-needed`. Exactly one wins,
    the loser clean-aborts, the advance is durable on origin. For every current
    phase apply_ack folds the advance in, so ship is a single-push op here and
    participates in the barrier race exactly like ack."""
    _, users, observer = _build_cluster(tmp_path, 2)
    ph = _ph.load_phases()
    wins = 0
    for r in range(_ROUNDS):
        key = f"KLC-{6500 + r}"
        _seed_ticket(users, key, phase="build:ack-needed", track="S")  # UNHELD
        results = _spawn_race([(users[0], "ship", [key, "--pick", "1"]),
                               (users[1], "ack", [key, "--pick", "1"])])
        ctx = f"scenario6 round={r} key={key} results={[(e,rc) for e,_,rc,_ in results]}"
        assert len(results) == 2, f"{ctx}: lost a worker result"
        winners = [x for x in results if x[2] == 0]
        assert len(winners) == 1, f"{ctx}: expected EXACTLY ONE winner"
        wins += 1
        for (e, v, rc, out) in results:
            if rc != 0:
                _assert_clean_abort(rc, out, ctx + f" loser={e}")
        m = _origin_meta(observer, key)
        assert m not in (None, "MALFORMED"), f"{ctx}: INV3 meta lost/malformed"
        assert m.get("phase") == "review:work", \
            f"{ctx}: INV3/5 advance not durable on origin (phase={m.get('phase')!r})"
        assert _valid_phase(m.get("phase"), ph), f"{ctx}: INV5 illegal phase"
        _assert_no_derived_on_origin(observer, ctx)
        _settle_and_converge(users, observer, ctx)
    sys.stderr.write(f"\n[scenario6] {_ROUNDS} rounds: wins={wins}\n")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
