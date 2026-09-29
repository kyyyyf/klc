"""tests/integration/test_klc110_r1_backfill_requires_out_md.py — KLC-110
review round 1, step-11b (LOW/INFO, D-110-13): `--backfill` without
`--out-md` used to default the rendered table into the LIVE
`.klc/index/planning/` (the `--out` default's own directory with a `.md`
suffix) — a build session must never write into the live index. `--backfill`
now REQUIRES `--out-md` explicitly, an argparse error otherwise."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FW_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_FW_ROOT), str(_FW_ROOT / "core" / "skills")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import retrieval_eval as _reval  # noqa: E402

_pe = _reval.load_planning_eval()

# KLC-136 AC-2 (F-012 group (a)): every test in this file runs against an
# EMPTY, per-test `PROJECT_ROOT` — `planning-eval` never needs a real index
# for either the backfill-argparse check or the corpus-report path, so
# redirecting unconditionally is both hermetic and, by construction,
# verdict-unchanged whatever a stand-in `live_index_state` claims to hold
# (see `test_backfill_check_verdict_unchanged_by_live_index_state` below,
# whose `live_index_state` param is instantiated first and then overridden
# by this same `hermetic_project_root`, per that fixture's own contract).
pytestmark = pytest.mark.usefixtures("hermetic_project_root")


def test_backfill_without_out_md_is_an_argparse_error(tmp_path, capsys):
    tickets_root = tmp_path / "tickets"
    tickets_root.mkdir()
    with pytest.raises(SystemExit) as exc:
        _pe.main(["--backfill", "--tickets", str(tickets_root),
                 "--out", str(tmp_path / "out.json")])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--out-md" in err


def test_backfill_with_out_md_succeeds(tmp_path):
    tickets_root = tmp_path / "tickets"
    tickets_root.mkdir()
    out_json = tmp_path / "out.json"
    out_md = tmp_path / "out.md"
    rc = _pe.main(["--backfill", "--tickets", str(tickets_root),
                  "--out", str(out_json), "--out-md", str(out_md)])
    assert rc == 0
    assert out_md.exists()


def test_non_backfill_mode_does_not_require_out_md(tmp_path):
    """Regression: the existing corpus-report path is unaffected — it never
    took `--out-md` and still doesn't need it."""
    tickets_root = tmp_path / "tickets"
    tickets_root.mkdir()
    rc = _pe.main(["--tickets", str(tickets_root), "--out", "-"])
    assert rc == 0


@pytest.mark.parametrize("live_index_state", ["absent", "stale", "current"], indirect=True)
def test_backfill_check_verdict_unchanged_by_live_index_state(
        live_index_state, no_index_reads, tmp_path):
    """AC-2: the corpus-report call returns the same code whatever the live
    index holds, and never reads it — the module-wide `hermetic_project_root`
    pytestmark redirects `PROJECT_ROOT` to an empty project regardless of
    what `live_index_state`'s stand-in contains."""
    tickets_root = tmp_path / "tickets"
    tickets_root.mkdir()
    rc = _pe.main(["--tickets", str(tickets_root), "--out", "-"])
    assert rc == 0
    assert no_index_reads() == []
