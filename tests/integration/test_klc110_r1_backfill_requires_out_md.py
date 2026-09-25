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
