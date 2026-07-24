#!/usr/bin/env python3
"""tests/integration/test_board_epic.py — KLC-078.

`klc board --epic <ROOT>` is an epic-scoped, READ-ONLY view over the same
meta.json scan the default board uses: computed epic state, per-member
dependency status, the ready set, and cycle/dangling validation warnings.

Subprocess harness mirrors tests/integration/test_board_holder.py. Fixtures seed
meta.epic + meta.blocked_by directly (KLC-078 only reads these fields — it does
not need KLC-077's writer).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parent.parent.parent
KLC = FW_ROOT / "scripts" / "klc"


def _env(root: Path) -> dict[str, str]:
    e = {**os.environ, "PROJECT_ROOT": str(root)}
    e.pop("KLC_TICKETS_DIR", None)
    return e


def _bootstrap(klc_dir: Path, ticket: str, *, phase: str, track: str,
               epic=None, blocked_by=None, holder=None) -> Path:
    tdir = klc_dir / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "affected_modules": [], "estimate": None,
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    if epic is not None:
        meta["epic"] = epic
    if blocked_by is not None:
        meta["blocked_by"] = blocked_by
    if holder is not None:
        meta["holder"] = holder
    (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return tdir / "meta.json"


def _run(args, root: Path):
    return subprocess.run([sys.executable, str(KLC), *args],
                          capture_output=True, text=True, env=_env(root))


def _seed_linear(kd: Path):
    """KLC-077 (root, design:work) <- KLC-078 gated at build by design-accepted."""
    _bootstrap(kd, "KLC-077", phase="design:work", track="M", epic="KLC-077")
    _bootstrap(kd, "KLC-078", phase="design:ack", track="M", epic="KLC-077",
               blocked_by=[{"on": "KLC-077", "phase": "build",
                            "point": "design-accepted"}])


def test_epic_state_and_ready_set_text():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _seed_linear(kd)
        r = _run(["board", "--epic", "KLC-077"], root)
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        out = r.stdout
        assert "epic KLC-077" in out
        assert "in-progress" in out           # KLC-077 past intake
        assert "ready set:" in out
        # KLC-077 ready, KLC-078 blocked by the design-accepted edge
        assert "KLC-077" in out
        assert "blocked by KLC-077 @ design-accepted" in out, out


def test_epic_json_shape():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _seed_linear(kd)
        r = _run(["board", "--epic", "KLC-077", "--json"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        data = json.loads(r.stdout)
        assert data["root"] == "KLC-077"
        assert data["state"] == "in-progress"
        assert data["ready"] == ["KLC-077"]
        assert data["blocked"] == ["KLC-078"]


def test_epic_ready_after_point_reached():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "KLC-077", phase="design:ack", track="M", epic="KLC-077")
        _bootstrap(kd, "KLC-078", phase="design:ack", track="M", epic="KLC-077",
                   blocked_by=[{"on": "KLC-077", "phase": "build",
                                "point": "design-accepted"}])
        r = _run(["board", "--epic", "KLC-077", "--json"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        data = json.loads(r.stdout)
        assert set(data["ready"]) == {"KLC-077", "KLC-078"}
        assert data["blocked"] == []


def test_epic_cycle_warning():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "KLC-A", phase="intake:ack-needed", track="M", epic="KLC-A",
                   blocked_by=[{"on": "KLC-B", "phase": "build", "point": "integrated"}])
        _bootstrap(kd, "KLC-B", phase="intake:ack-needed", track="M", epic="KLC-A",
                   blocked_by=[{"on": "KLC-A", "phase": "build", "point": "integrated"}])
        r = _run(["board", "--epic", "KLC-A"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "validation warnings" in r.stdout
        assert "cycle" in r.stdout, r.stdout


def test_epic_dangling_warning():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "KLC-077", phase="design:ack", track="M", epic="KLC-077")
        _bootstrap(kd, "KLC-078", phase="intake:ack-needed", track="M", epic="KLC-077",
                   blocked_by=[{"on": "KLC-999", "phase": "build", "point": "integrated"}])
        r = _run(["board", "--epic", "KLC-077"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "dangling" in r.stdout, r.stdout
        assert "unknown ticket" in r.stdout, r.stdout


def test_epic_no_members():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "KLC-100", phase="design:work", track="M")  # no epic
        r = _run(["board", "--epic", "KLC-077"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "no epic KLC-077" in r.stdout, r.stdout


def test_epic_view_does_not_write_meta():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _seed_linear(kd)
        meta_p = kd / "tickets" / "KLC-078" / "meta.json"
        before = meta_p.read_bytes()
        _run(["board", "--epic", "KLC-077"], root)
        _run(["board", "--epic", "KLC-077", "--json"], root)
        assert meta_p.read_bytes() == before, "board --epic rewrote meta.json"


def test_empty_epic_json_is_valid():
    # codex P2: `--json` on an epic with no members must stay parseable JSON,
    # like the default board's empty `--json`.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "KLC-100", phase="design:work", track="M")  # no epic
        r = _run(["board", "--epic", "KLC-077", "--json"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        data = json.loads(r.stdout)  # must not raise
        assert data["root"] == "KLC-077"
        assert data["members"] == []
        assert data["ready"] == []


def test_cross_epic_upstream_not_dangling():
    # MEDIUM-1: an out-of-epic but existing+reached upstream -> member READY,
    # no false "dangling" (the whole repo is scanned for upstream resolution).
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "KLC-077", phase="design:ack", track="M", epic="KLC-077")
        _bootstrap(kd, "KLC-078", phase="intake:ack-needed", track="M",
                   epic="KLC-077",
                   blocked_by=[{"on": "KLC-500", "phase": "build",
                                "point": "integrated"}])
        _bootstrap(kd, "KLC-500", phase="integrate:ack", track="M",
                   epic="OTHER-EPIC")
        r = _run(["board", "--epic", "KLC-077", "--json"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        data = json.loads(r.stdout)
        assert "KLC-078" in data["ready"], data
        assert "KLC-078" not in data["blocked"]
        assert not any("dangling" in w for w in data["warnings"]), data["warnings"]


def test_non_dict_phase_history_not_fatal():
    # MEDIUM-3: a corrupt (non-dict) phase_history entry on an upstream must not
    # crash the whole board.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        tdir = kd / "tickets" / "KLC-077"
        tdir.mkdir(parents=True)
        (tdir / "meta.json").write_text(json.dumps({
            "ticket": "KLC-077", "phase": "integrate:ack", "track": "M",
            "epic": "KLC-077", "phase_history": ["oops-not-a-dict"],
        }), encoding="utf-8")
        _bootstrap(kd, "KLC-078", phase="intake:ack-needed", track="M",
                   epic="KLC-077",
                   blocked_by=[{"on": "KLC-077", "phase": "build",
                                "point": "integrated", "condition": "passed"}])
        r = _run(["board", "--epic", "KLC-077"], root)
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        assert "epic KLC-077" in r.stdout, r.stdout


def test_identity_absent_renders():
    # MEDIUM-2: identity.current() raises SystemExit when no git identity/$USER
    # is set; board must catch it (me=None fail-safe) and still render.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        _bootstrap(kd, "KLC-077", phase="design:ack", track="M", epic="KLC-077",
                   holder={"id": "alice", "machine": "box",
                           "since": "2026-01-01T00:00:00Z"})
        env = _env(root)
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        env["GIT_CONFIG_SYSTEM"] = "/dev/null"
        env["HOME"] = str(root)
        env.pop("USER", None)
        env.pop("LOGNAME", None)
        # cwd = a non-repo dir so `git config` finds no repo-local identity either.
        r = subprocess.run([sys.executable, str(KLC), "board", "--epic", "KLC-077"],
                           capture_output=True, text=True, env=env, cwd=str(root))
        assert r.returncode == 0, f"exit {r.returncode}; stderr={r.stderr}"
        assert "epic KLC-077" in r.stdout, r.stdout
        # me=None -> the holder counts as "someone else" -> occupied, still renders
        assert "held by alice" in r.stdout, r.stdout


def test_legacy_phase_upstream_resolves_not_malformed():
    # P2-B: an upstream carrying a LEGACY phase string ('observe', no colon) must
    # be normalized in-memory (like read_meta_ro) so its milestone resolves and
    # matches enforcement — not treated as malformed -> downstream falsely blocked.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); kd = root / ".klc"; kd.mkdir()
        # KLC-077 upstream at the LEGACY 'observe' (normalizes to observe:work,
        # which is past integrate:ack -> `integrated` reached).
        tdir = kd / "tickets" / "KLC-077"
        tdir.mkdir(parents=True)
        legacy = {"ticket": "KLC-077", "phase": "observe", "track": "M",
                  "epic": "KLC-077", "phase_history": []}
        meta_p = tdir / "meta.json"
        raw_before = json.dumps(legacy)
        meta_p.write_text(raw_before, encoding="utf-8")
        _bootstrap(kd, "KLC-078", phase="design:ack", track="M", epic="KLC-077",
                   blocked_by=[{"on": "KLC-077", "phase": "build",
                                "point": "integrated"}])
        r = _run(["board", "--epic", "KLC-077", "--json"], root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        data = json.loads(r.stdout)
        assert "KLC-078" in data["ready"], data
        assert "KLC-078" not in data["blocked"]
        # read-only: the legacy meta.json is NOT rewritten (normalization is
        # in-memory only).
        assert meta_p.read_text(encoding="utf-8") == raw_before, \
            "board rewrote a legacy meta.json"


def test_default_board_unchanged_with_epic_metas():
    # LOW-4: the default board output must be BYTE-IDENTICAL whether or not the
    # tickets carry epic/blocked_by/holder-irrelevant fields — the default view
    # ignores them entirely. Compare two repos differing only by epic fields.
    def _render(with_epic: bool) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); kd = root / ".klc"; kd.mkdir()
            if with_epic:
                _bootstrap(kd, "KLC-077", phase="design:work", track="M",
                           epic="KLC-077")
                _bootstrap(kd, "KLC-078", phase="design:ack", track="M",
                           epic="KLC-077",
                           blocked_by=[{"on": "KLC-077", "phase": "build",
                                        "point": "design-accepted"}])
            else:
                _bootstrap(kd, "KLC-077", phase="design:work", track="M")
                _bootstrap(kd, "KLC-078", phase="design:ack", track="M")
            r = _run(["board"], root)
            assert r.returncode == 0, f"stderr={r.stderr}"
            return r.stdout

    with_epic = _render(True)
    without_epic = _render(False)
    assert with_epic == without_epic, (
        f"default board diverged with epic fields:\n{with_epic!r}\n"
        f"vs\n{without_epic!r}")
    # and the grouping/holder shape is what we expect
    assert "== design:work (1) ==" in with_epic
    assert "== design:ack (1) ==" in with_epic
