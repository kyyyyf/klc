#!/usr/bin/env python3
"""KLC-118 step-1 — AC-7/AC-8: every card reader resolves the same path.

Cards move to a scratch root outside the ticket tree
(`<card root>/<KEY>/<phase>/_prompt.md`, default `.klc/scratch/`). This test
renders one phase card (via `klc jump`) and one build step card (via
`klc step`), then asserts `klc status`, `klc work --json`, the path `klc jump`
/ `klc step` print, and `resolve_phase(...).card_path` all agree on the
written file — first at the default root, then again with `KLC_CARD_ROOT`
pointed at an override directory.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

FW_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = FW_ROOT / "scripts"
KLC = SCRIPTS / "klc"
SKILLS_DIR = FW_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS_DIR))
sys.path.insert(0, str(FW_ROOT))


def _seed(tmp_path: Path, ticket: str, *, phase: str, track: str = "M",
          **extra) -> None:
    tdir = tmp_path / ".klc" / "tickets" / ticket
    tdir.mkdir(parents=True)
    meta = {
        "ticket": ticket, "kind": "tech", "kind_source": "user",
        "phase": phase, "phase_history": [], "track": track,
        "route_hint": track, "route_confidence": "high",
        "affected_modules": [], "estimate": None, "layer": "code",
        "jira_url": None, "created": "2026-01-01T00:00:00Z",
    }
    meta.update(extra)
    (tdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                    encoding="utf-8")


def _run(argv: list[str], env: dict) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(KLC), *argv],
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


_CAT_RE = re.compile(r"cat (\S+)")


def _card_from_cat_line(out: str) -> str:
    m = _CAT_RE.search(out)
    assert m, f"no `cat <path>` line found in:\n{out}"
    return m.group(1).rstrip("`")


def _check_parity(tmp_path: Path, env: dict) -> None:
    """One phase card (via `klc jump`) + one build step card (via `klc step`);
    assert every reader agrees on both."""
    # --- phase card: design (non-build), rendered via `klc jump` -----------
    _seed(tmp_path, "KLC-PAR1", phase="discovery:ack", track="M")
    rc, out = _run(["jump", "design", "KLC-PAR1", "--yes"], env)
    assert rc == 0, out
    jump_card = _card_from_cat_line(out)

    rc, status_out = _run(["status", "KLC-PAR1"], env)
    assert rc == 0, status_out
    status_card = _card_from_cat_line(status_out)

    rc, work_out = _run(["work", "KLC-PAR1", "--json"], env)
    assert rc == 0, work_out
    work_info = json.loads(work_out)
    work_card = str((tmp_path / work_info["prompt"]).resolve())

    import phase_resolver as pr
    resolved = pr.resolve_phase("KLC-PAR1", "design")

    assert str(Path(jump_card).resolve()) == str(Path(status_card).resolve()), \
        (jump_card, status_card)
    assert str(Path(jump_card).resolve()) == work_card, (jump_card, work_card)
    assert str(Path(jump_card).resolve()) == str(Path(resolved.card_path).resolve()), \
        (jump_card, resolved.card_path)

    # --- build step card, rendered via `klc step` ---------------------------
    _seed(tmp_path, "KLC-PAR2", phase="build:work", track="M", impl_step=1)
    (tmp_path / ".klc" / "tickets" / "KLC-PAR2" / "spec.md").write_text(
        "## Goals\nfake\n## Acceptance Criteria\n- AC-1\n", encoding="utf-8")
    (tmp_path / ".klc" / "tickets" / "KLC-PAR2" / "impl-plan.md").write_text(
        "## step-1 — fake\nGoal: fake\n", encoding="utf-8")
    rc, out = _run(["step", "KLC-PAR2", "1"], env)
    assert rc == 0, out
    step_card = _card_from_cat_line(out)

    rc, status_out = _run(["status", "KLC-PAR2"], env)
    assert rc == 0, status_out
    status_card2 = _card_from_cat_line(status_out)

    rc, work_out = _run(["work", "KLC-PAR2", "--json"], env)
    assert rc == 0, work_out
    work_info2 = json.loads(work_out)
    work_card2 = str((tmp_path / work_info2["prompt"]).resolve())

    resolved2 = pr.resolve_phase("KLC-PAR2", "build")

    assert str(Path(step_card).resolve()) == str(Path(status_card2).resolve()), \
        (step_card, status_card2)
    assert str(Path(step_card).resolve()) == work_card2, (step_card, work_card2)
    assert str(Path(step_card).resolve()) == str(Path(resolved2.card_path).resolve()), \
        (step_card, resolved2.card_path)


def test_all_card_readers_resolve_the_same_written_card_path(tmp_path,
                                                              monkeypatch):
    default_env = {**os.environ, "PROJECT_ROOT": str(tmp_path)}
    default_env.pop("KLC_CARD_ROOT", None)
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
    _check_parity(tmp_path, default_env)

    # Every card actually lives under the default card root, not the ticket
    # directory.
    scratch_root = tmp_path / ".klc" / "scratch"
    assert scratch_root.exists(), "cards were not written to the scratch root"

    # --- repeat once with the override, in a fresh ticket subtree ----------
    override_root = tmp_path / "override-cards"
    override_env = {**default_env, "KLC_CARD_ROOT": str(override_root)}
    monkeypatch.setenv("KLC_CARD_ROOT", str(override_root))
    tmp_path2 = tmp_path / "second"
    tmp_path2.mkdir()
    override_env["PROJECT_ROOT"] = str(tmp_path2)
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path2))
    _check_parity(tmp_path2, override_env)
    assert override_root.exists(), \
        "KLC_CARD_ROOT override was not honoured by the writer"


# --------------------------------------------------------------------------- #
# KLC-119 review-fix round 1, MEDIUM #3 (D-2119-1 / drift D-1): `_paths.py`
# (bare import, used by `token_journal.py`/`state_tx.py`/...) mirrors
# `core.shared.paths` (dotted import, used by `artefacts.py`)'s
# `klc_card_root`/`klc_card_path`/`CARD_ROOT_ENV` verbatim. The operator
# ruled (review-report.md D-1) to keep the mirror for this ticket rather than
# collapse the two path-helper modules, and to add a parity test so a future
# edit to one copy without the other fails fast instead of silently splitting
# journal storage (`token_journal.py`) from card storage (`artefacts.py`).
# --------------------------------------------------------------------------- #

def test_klc_card_root_and_klc_card_path_agree_between_shared_and_skills_path_modules(
        tmp_path, monkeypatch):
    """`core.shared.paths` and `core.skills._paths` must return byte-identical
    results for `klc_card_root()`/`klc_card_path()` across a matrix of
    `KLC_CARD_ROOT` values and project roots — the journal
    (`token_journal.journal_path`, via bare `_paths`) and the card writer
    (`artefacts.render_card`, via dotted `core.shared.paths`) must never
    disagree on where `.klc/scratch/` (or its override) lives."""
    import importlib
    sys.path.insert(0, str(SKILLS_DIR))
    _paths = importlib.import_module("_paths")
    import core.shared.paths as _shared_paths
    importlib.reload(_paths)
    importlib.reload(_shared_paths)

    assert _paths.CARD_ROOT_ENV == _shared_paths.CARD_ROOT_ENV

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    override = tmp_path / "elsewhere" / "cards"
    matrix = [
        None,                       # unset -> default .klc/scratch
        "",                         # blank -> treated as unset
        "   ",                      # whitespace-only -> treated as unset
        str(override),              # absolute override
        "relative-cards",           # relative override
        "~/klc-card-root-parity",   # ~-expansion
    ]
    for value in matrix:
        if value is None:
            monkeypatch.delenv("KLC_CARD_ROOT", raising=False)
        else:
            monkeypatch.setenv("KLC_CARD_ROOT", value)
        assert _paths.klc_card_root() == _shared_paths.klc_card_root(), \
            f"klc_card_root() disagreement for KLC_CARD_ROOT={value!r}"
        for ticket, phase, step in (
            ("KLC-PARITY1", "design", None),
            ("KLC-PARITY2", "build", 3),
        ):
            assert (_paths.klc_card_path(ticket, phase, step)
                   == _shared_paths.klc_card_path(ticket, phase, step)), \
                f"klc_card_path() disagreement for KLC_CARD_ROOT={value!r}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
