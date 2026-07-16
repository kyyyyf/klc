"""KLC-057 — multi-user concurrency FUZZ / property harness (convergence gate).

A single local bare repo is the shared ``origin`` klc-state remote. M virtual
users each own a real ``.klc/`` worktree bound to ``klc-state`` (feature-ON),
each with a distinct git identity. A seeded RNG drives N steps of random legal-ish
ops through the REAL verb entry points (intake / ack / next / intake --force),
including deliberately-concurrent same-ticket ops. Everything is offline.

A non-zero rc with a clean abort (already-taken / phase held by / remote advanced
/ concurrent update / cannot complete / scope / unknown-pick / archived) is an
EXPECTED outcome — only INVARIANT violations fail the test:

  1. no wedge        — actor `.klc` `git status --porcelain` empty after the op
  2. no deadlock     — a follow-up `git pull --rebase` by the actor succeeds
  3. no data loss    — every ticket that ever succeeded still has a well-formed
                       meta.json on origin/klc-state
  4. holder auth     — no successful op moved a phase held by a DIFFERENT user
  5. legal state     — every remote phase is a valid phases.yml state
  6. convergence     — after everyone pulls, all see the identical origin tip
  7. derived private — origin never carries .lock/_prompt*/.index.json/scratch/
                       /knowledge/tickets-index.jsonl

Overridable via env: KLC_FUZZ_SEEDS="1337,2024,7", KLC_FUZZ_STEPS=60,
KLC_FUZZ_USERS=3.
"""
from __future__ import annotations

import collections
import json
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

import identity  # noqa: E402
import phases as _ph  # noqa: E402
import phase_completion  # noqa: E402


# --------------------------------------------------------------------------- #
# git helpers
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
    """Create the bare origin, `nusers` user worktrees, and a read-only observer
    clone — all bound to the same klc-state branch."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    users: list[_User] = []
    # user0 initialises the orphan root and publishes klc-state.
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

    # remaining users clone the bare (clone sets origin + tracking upstream).
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


# --------------------------------------------------------------------------- #
# observer reads (authoritative origin/klc-state view)
# --------------------------------------------------------------------------- #

def _observer_refresh(observer: Path) -> None:
    _run_git(observer, "fetch", "-q", "origin")


def _origin_paths(observer: Path) -> set[str]:
    r = _run_git(observer, "ls-tree", "-r", "--name-only", "origin/klc-state")
    return {p for p in r.stdout.splitlines() if p.strip()} if r.returncode == 0 else set()


def _origin_meta(observer: Path, key: str):
    r = _run_git(observer, "show", f"origin/klc-state:tickets/{key}/meta.json")
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return "MALFORMED"


def _local_phase(user: _User, key: str):
    mp = user.klc / "tickets" / key / "meta.json"
    if not mp.exists():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8")).get("phase")
    except (json.JSONDecodeError, OSError):
        return None


# --------------------------------------------------------------------------- #
# the fuzz driver
# --------------------------------------------------------------------------- #

class _Violation(AssertionError):
    pass


def _categorize(rc: int, out: str) -> str:
    """Classify an op outcome so a run can prove it exercised the conflict/abort
    paths (not just happy-path intakes)."""
    if rc == 0:
        return "ok"
    low = out.lower()
    for needle, label in (
        ("already taken", "abort:taken"),
        ("held by", "abort:held-by"),
        ("remote state advanced", "abort:stale"),
        ("concurrent update", "abort:concurrent"),
        ("cannot complete", "abort:cannot-complete"),
        ("scope", "abort:scope"),
        ("pick", "abort:pick"),
        ("archived", "abort:archived"),
        ("unknown ticket", "abort:unknown-ticket"),
        ("state sync failed", "abort:sync-failed"),
    ):
        if needle in low:
            return label
    return "abort:other"


def _valid_phase(phase: str, ph) -> bool:
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


def _run_one_seed(seed: int, steps: int, nusers: int, tmp_path: Path,
                  monkeypatch, capsys) -> None:
    bare, users, observer = _build_cluster(tmp_path, nusers)
    ph = _ph.load_phases()

    # Acting identity is switched per op via this mutable holder.
    actor = {"email": users[0].email}
    monkeypatch.setattr(identity, "current", lambda: actor["email"])
    # Drive progress past :work without real artifacts (we test sync, not
    # artifact gating).
    monkeypatch.setattr(phase_completion, "can_complete", lambda t, p: (True, ""))
    monkeypatch.setenv("KLC_INTAKE_TRIAGE", "0")

    import intake as intake_mod
    import ack as ack_mod
    import next as next_mod

    rng = random.Random(seed)
    oplog: list[str] = []
    created: set[str] = set()   # keys that ever returned INTAKE_OK
    stats: collections.Counter = collections.Counter()
    key_counter = [0]

    def _fresh_key() -> str:
        key_counter[0] += 1
        return f"KLC-{1000 + key_counter[0]}"

    def _run_verb(user: _User, mod, argv: list[str]) -> tuple[int, str]:
        actor["email"] = user.email
        os.environ["PROJECT_ROOT"] = str(user.root)
        capsys.readouterr()  # clear
        try:
            rc = mod.run(argv)
        except BaseException as exc:  # a verb must never crash — that's a bug
            cap = capsys.readouterr()
            raise _Violation(
                f"[seed={seed}] verb CRASHED (uncaught {type(exc).__name__}: {exc})\n"
                f"  op: {user.email} {mod.__name__} {argv}\n"
                f"  stderr: {cap.err[-500:]}\n"
                f"  oplog tail:\n    " + "\n    ".join(oplog[-15:])
            ) from exc
        cap = capsys.readouterr()
        return int(rc), (cap.out + cap.err)

    def _check_invariants(user: _User, target: str | None,
                          pre_meta, rc: int, op_desc: str) -> None:
        # 1. no wedge
        status = _run_git(user.klc, "status", "--porcelain").stdout.strip()
        if status:
            raise _Violation(
                f"[seed={seed}] INV1 wedge — {user.email} tree dirty after `{op_desc}`:\n"
                f"  git status:\n{status}\n"
                f"  oplog tail:\n    " + "\n    ".join(oplog[-15:]))
        # 2. no deadlock — a trivial follow-up pull must succeed
        pr = _run_git(user.klc, "pull", "--rebase", "--autostash")
        if pr.returncode != 0:
            raise _Violation(
                f"[seed={seed}] INV2 deadlock — {user.email} follow-up pull failed "
                f"after `{op_desc}`:\n  {pr.stderr.strip() or pr.stdout.strip()}\n"
                f"  oplog tail:\n    " + "\n    ".join(oplog[-15:]))

        _observer_refresh(observer)
        paths = _origin_paths(observer)

        # 7. derived files never shared
        for p in paths:
            base = p.rsplit("/", 1)[-1]
            if (base == ".lock" or base == ".index.json"
                    or base.startswith("_prompt")
                    or "/scratch/" in ("/" + p)
                    or p == "knowledge/tickets-index.jsonl"):
                raise _Violation(
                    f"[seed={seed}] INV7 derived file on origin: {p!r} after `{op_desc}`\n"
                    f"  oplog tail:\n    " + "\n    ".join(oplog[-15:]))

        # 3. no data loss — every ever-succeeded ticket still present + well-formed
        for k in sorted(created):
            if f"tickets/{k}/meta.json" not in paths:
                raise _Violation(
                    f"[seed={seed}] INV3 data loss — ticket {k} vanished from origin "
                    f"after `{op_desc}`\n  oplog tail:\n    " + "\n    ".join(oplog[-15:]))
        # well-formedness + legal state of the targeted ticket
        if target is not None:
            m = _origin_meta(observer, target)
            if m == "MALFORMED":
                raise _Violation(
                    f"[seed={seed}] INV3 malformed meta.json for {target} after `{op_desc}`\n"
                    f"  oplog tail:\n    " + "\n    ".join(oplog[-15:]))
            if m is not None:
                phase = m.get("phase")
                # 5. legal state
                if not _valid_phase(phase, ph):
                    raise _Violation(
                        f"[seed={seed}] INV5 illegal phase {phase!r} on {target} "
                        f"after `{op_desc}`\n  oplog tail:\n    " + "\n    ".join(oplog[-15:]))
                # 4. holder authorization — a SUCCESSFUL phase change must have
                # acted on a phase that was unheld or held by THIS user.
                if rc == 0 and pre_meta not in (None, "MALFORMED"):
                    pre_phase = pre_meta.get("phase")
                    if phase != pre_phase:
                        h = pre_meta.get("holder")
                        hid = h.get("id") if isinstance(h, dict) else None
                        if hid is not None and hid != user.email:
                            raise _Violation(
                                f"[seed={seed}] INV4 cross-user phase move — {user.email} "
                                f"moved {target} {pre_phase!r}→{phase!r} while held by "
                                f"{hid!r} after `{op_desc}`\n"
                                f"  oplog tail:\n    " + "\n    ".join(oplog[-15:]))

    def _do_op(step: int) -> None:
        user = rng.choice(users)
        roll = rng.random()

        # ---- intake a NEW key ------------------------------------------------
        if roll < 0.30 or not created:
            key = _fresh_key()
            op_desc = f"{user.email} intake {key}"
            _observer_refresh(observer)
            pre = _origin_meta(observer, key)
            rc, out = _run_verb(user, intake_mod, [key, f"fuzz ticket {key} step {step}"])
            oplog.append(f"{step}: {op_desc} -> rc={rc}")
            stats[_categorize(rc, out)] += 1
            if rc == 0 and "INTAKE_OK" in out:
                created.add(key)
            _check_invariants(user, key, pre, rc, op_desc)
            return

        # ---- act on an EXISTING ticket --------------------------------------
        key = rng.choice(sorted(created))
        local_phase = _local_phase(user, key)
        _observer_refresh(observer)
        pre = _origin_meta(observer, key)

        # occasional --force re-intake
        if roll < 0.36:
            op_desc = f"{user.email} intake --force {key}"
            rc, out = _run_verb(user, intake_mod,
                                [key, "--force", f"re-intake {key} step {step}"])
            oplog.append(f"{step}: {op_desc} -> rc={rc}")
            stats[_categorize(rc, out)] += 1
            _check_invariants(user, key, pre, rc, op_desc)
            return

        # choose ack/next based on the user's (possibly stale) local view
        pid = None
        if local_phase and local_phase != _ph.STATE_ARCHIVED:
            try:
                pid, st = _ph.parse_state(local_phase)
            except Exception:
                st = None
        else:
            st = None

        if st == _ph.STATE_ACK:
            op_desc = f"{user.email} next {key}"
            rc, out = _run_verb(user, next_mod, [key])
        elif st == _ph.STATE_ACK_NEEDED and pid is not None:
            try:
                picks = [pk.id for pk in ph.by_id(pid).picks] or [1]
            except Exception:
                picks = [1]
            pick = rng.choice(picks)
            op_desc = f"{user.email} ack {key} --pick {pick}"
            rc, out = _run_verb(user, ack_mod, [key, "--pick", str(pick)])
        else:
            # :work (manual-completion), archived, or unknown-local → try ack.
            # A required pick is supplied opportunistically.
            argv = [key, "--pick", "1"]
            op_desc = f"{user.email} ack {key} --pick 1"
            rc, out = _run_verb(user, ack_mod, argv)

        oplog.append(f"{step}: {op_desc} -> rc={rc}")
        stats[_categorize(rc, out)] += 1
        _check_invariants(user, key, pre, rc, op_desc)

    for step in range(steps):
        _do_op(step)

    # ---- final convergence (INV6): everyone pulls → identical origin tip -----
    tips = set()
    for u in users:
        pr = _run_git(u.klc, "pull", "--rebase", "--autostash")
        assert pr.returncode == 0, (
            f"[seed={seed}] INV6/2 final pull failed for {u.email}: "
            f"{pr.stderr.strip() or pr.stdout.strip()}")
        head = _git(u.klc, "rev-parse", "HEAD").strip()
        tips.add(head)
    _observer_refresh(observer)
    origin_tip = _git(observer, "rev-parse", "origin/klc-state").strip()
    assert tips == {origin_tip}, (
        f"[seed={seed}] INV6 divergence — user tips {tips} != origin {origin_tip}")

    # final full data-loss + legality sweep over origin
    paths = _origin_paths(observer)
    for k in sorted(created):
        assert f"tickets/{k}/meta.json" in paths, \
            f"[seed={seed}] INV3 final: ticket {k} missing from origin"
        m = _origin_meta(observer, k)
        assert m not in (None, "MALFORMED"), \
            f"[seed={seed}] INV3 final: {k} meta.json missing/malformed"
        assert _valid_phase(m.get("phase"), ph), \
            f"[seed={seed}] INV5 final: {k} illegal phase {m.get('phase')!r}"

    # report progress + outcome mix for the record (not an assertion) — proves
    # the run exercised the conflict/abort paths, not just happy-path intakes.
    mix = ", ".join(f"{k}={v}" for k, v in sorted(stats.items()))
    sys.stderr.write(
        f"\n[seed={seed}] fuzz OK: {steps} steps, {len(created)} tickets created, "
        f"origin tip {origin_tip[:10]}\n  outcomes: {mix}\n")


def _seeds() -> list[int]:
    env = os.environ.get("KLC_FUZZ_SEEDS")
    if env:
        return [int(s) for s in env.split(",") if s.strip()]
    return [1337, 2024, 7]


@pytest.mark.parametrize("seed", _seeds())
def test_multiuser_convergence_fuzz(seed, tmp_path, monkeypatch, capsys):
    steps = int(os.environ.get("KLC_FUZZ_STEPS", "60"))
    nusers = int(os.environ.get("KLC_FUZZ_USERS", "3"))
    _run_one_seed(seed, steps, nusers, tmp_path, monkeypatch, capsys)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
