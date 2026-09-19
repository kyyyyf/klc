"""KLC-106 step-8 — `klc init` and `klc update` print one summary line per
builder on every deterministic run (AC-14).

`_build_planning_views` is tested directly (loaded by path — both scripts
are invoked as `klc init`/`klc update`, not imported by name) with
`subprocess.run` stubbed to a trivial success, so the assertion is purely
about the NEW summary-printing behaviour reading the index artifacts this
test writes itself — not about any real builder actually running.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_FW_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, str(_FW_ROOT / relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeCompleted:
    returncode = 0
    stdout = ""
    stderr = ""


def _stub_subprocess(monkeypatch, mod) -> None:
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **kw: _FakeCompleted())


def _write_degraded_verdict(index_dir: Path) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "inventory.json").write_text(json.dumps({"errors": [
        {"builder": "inventory:python", "artifact": "inventory.json",
         "metric": "files-with-symbols", "observed": 1, "universe": 20,
         "ratio": 0.05, "threshold": 0.25, "degraded": True,
         "reason": "files-with-symbols 0.05 below threshold 0.25 (1/20)"},
    ]}), encoding="utf-8")


def test_init_prints_per_builder_summary_line_on_deterministic_run(tmp_path, monkeypatch, capsys):
    init_mod = _load("klc106_init", "scripts/init.py")
    _stub_subprocess(monkeypatch, init_mod)
    index_dir = tmp_path / ".klc" / "index"
    _write_degraded_verdict(index_dir)
    init_mod._build_planning_views(index_dir, include_inventory=False)
    out = capsys.readouterr().out
    assert "index coverage" in out
    assert "inventory:python" in out
    assert "degraded=true" in out


def test_update_prints_per_builder_summary_line_on_deterministic_run(tmp_path, monkeypatch, capsys):
    update_mod = _load("klc106_update", "scripts/update.py")
    _stub_subprocess(monkeypatch, update_mod)
    index_dir = tmp_path / ".klc" / "index"
    _write_degraded_verdict(index_dir)
    update_mod._build_planning_views(index_dir)
    out = capsys.readouterr().out
    assert "index coverage" in out
    assert "inventory:python" in out
    assert "degraded=true" in out
