"""KLC-129 step-2 — `gate_policy._sentinel_hits` refuses to read the git diff
at all when `HEAD` sits on a DIFFERENT ticket's branch (AC-3), so an
unattended `klc ack --auto` run never scans another ticket's diff for
sentinels under this ticket's key.

White-box on `subprocess.run`: `_sentinel_hits`'s OBSERVABLE return value
cannot demonstrate this guard on its own — two pre-existing, unrelated bugs
(F-008: `load_sentinels_config()` passes a `Path` to a text-only yaml parser;
F-009: `bool(hits)` checks a dict that is always truthy) mean it returns
`True` regardless of branch today. Both tests here stub
`load_sentinels_config` to return the REAL parsed `config/sentinels.yml`
(never a fictional shape) so that pre-existing bug can't mask whether the
git-diff subprocess call itself was reached.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc128_fixtures import (  # noqa: E402
    _bare_and_clone,
    _branch_with_commits,
    _seed_ticket,
)


def _real_sentinels_config() -> dict:
    """The REAL parsed `config/sentinels.yml` — bypassing F-008's `Path`-to-
    text-parser bug so it can't mask this guard's behaviour."""
    from core.shared.paths import framework_root
    from core.shared.yaml import parse as _load_yaml
    path = framework_root() / "config" / "sentinels.yml"
    return _load_yaml(path.read_text(encoding="utf-8"))


def _count_subprocess_run(monkeypatch):
    """A counting PASSTHROUGH around `subprocess.run` — every call is logged,
    then delegated to the REAL function (mock-the-real-contract rule)."""
    real = subprocess.run
    calls: list = []

    def _wrapped(*args, **kwargs):
        calls.append(args[0] if args else kwargs.get("args"))
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _wrapped)
    return calls


def test_sentinel_scan_is_skipped_without_reading_the_diff_when_head_is_another_tickets_branch(
    tmp_path, monkeypatch
):
    """AC-3 negative: HEAD sits on a DIFFERENT ticket's branch
    (feature/KLC-949) while `_sentinel_hits` is asked about KLC-948. The
    diff subprocess must never be invoked — the result is the existing
    fail-closed `True` (dirty), reached without reading any diff."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket_a = "KLC-948"
    _seed_ticket(clone, ticket_a, phase="build:work", track="M")

    ticket_b = "KLC-949"
    _branch_with_commits(clone, ticket_b, [
        ("gizmos/other.py", "b = 2\n", f"{ticket_b} step-1: add b"),
    ])

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import gate_policy as _gp
    import scan_sentinels as _ss
    monkeypatch.setattr(_ss, "load_sentinels_config", _real_sentinels_config)
    calls = _count_subprocess_run(monkeypatch)

    assert _gp._sentinel_hits(ticket_a) is True
    diff_calls = [c for c in calls if len(c) > 1 and c[1] == "diff"]
    assert diff_calls == [], "the diff subprocess must never be invoked on a branch mismatch"


def test_sentinel_scan_still_reads_the_diff_on_the_tickets_own_branch(tmp_path, monkeypatch):
    """Regression: HEAD on the ticket's OWN branch still reaches the diff
    subprocess exactly as today — the branch-mismatch guard must never fire
    on a false positive."""
    _bare_and_clone(tmp_path)
    clone = tmp_path / "clone"
    ticket = "KLC-950"
    _branch_with_commits(clone, ticket, [
        ("widgets/thing.py", "a = 1\n", f"{ticket} step-1: add a"),
    ])
    _seed_ticket(clone, ticket, phase="build:work", track="M")

    monkeypatch.setenv("PROJECT_ROOT", str(clone))
    import gate_policy as _gp
    import scan_sentinels as _ss
    monkeypatch.setattr(_ss, "load_sentinels_config", _real_sentinels_config)
    calls = _count_subprocess_run(monkeypatch)

    _gp._sentinel_hits(ticket)
    diff_calls = [c for c in calls if len(c) > 1 and c[1] == "diff"]
    assert len(diff_calls) >= 1, "the diff subprocess must still be invoked on the ticket's own branch"
    assert diff_calls[0][:2] == ["git", "diff"]
