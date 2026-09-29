"""KLC-137 step-2 — reader compatibility with the new `line_end` field
(AC-4, AC-14).

Real-substrate: the three inventory shapes compared here (int-valued,
absent-key, null-valued) are all derived from ONE real `build_inventory()`
output (C-005) — never a hand-shaped inventory dict.
"""
import datetime as _real_dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klc137_fixtures import (  # noqa: E402
    null_line_end, real_inventory, strip_line_end, write_python_fixture,
)

pytestmark = pytest.mark.usefixtures("hermetic_project_root")

_FIXED_CLOCK = _real_dt.datetime(2026, 1, 1, tzinfo=_real_dt.timezone.utc)


class _FixedDatetime(_real_dt.datetime):
    """impl-plan-review F-2: the only normalisation this file applies —
    `module-writer.py`'s two `generated_at` timestamps (lines 243, 604) are
    the current second, so both functions run under this fixed clock."""

    @classmethod
    def now(cls, tz=None):
        return _FIXED_CLOCK


def _import_skill(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, str(SKILLS / filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _modules_doc() -> dict:
    return {"modules": [
        {"name": "pkg", "path": "pkg/", "language": "python", "symbol_count": 1,
         "public_api": [], "depends_on": [], "depended_by": []},
    ]}


def _reader_file_roles(inv, modules, tmp_path, monkeypatch):
    fr = _import_skill("klc137_file_roles", "file_roles.py")
    return fr.build_file_roles(inv, modules, {})


def _reader_symbol_usage(inv, modules, tmp_path, monkeypatch):
    su = _import_skill("klc137_symbol_usage", "symbol_usage.py")
    return su.build_symbol_usage(inv, modules, callgraph=None, depgraph=None, structural=None)


def _reader_planning_validate(inv, modules, tmp_path, monkeypatch):
    pv = _import_skill("klc137_planning_validate", "planning_validate.py")
    return pv.validate(modules, inventory=inv)


def _reader_module_writer(inv, modules, tmp_path, monkeypatch):
    idx = tmp_path / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    (idx / "modules.json").write_text(json.dumps(modules), encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    mw = _import_skill("klc137_module_writer", "module-writer.py")
    monkeypatch.setattr(mw._dt, "datetime", _FixedDatetime)
    payload = mw._inventory_hash_payload()
    out = tmp_path / "CLAUDE.md"
    mw.render_root(out)
    return {"hash_payload": payload, "root_md": out.read_text(encoding="utf-8")}


def _reader_callgraph(filename: str):
    def _run(inv, modules, tmp_path, monkeypatch):
        mod = _import_skill(f"klc137_{filename}", f"{filename}.py")
        return mod.coverage_verdict({"symbols": []}, inv)
    return _run


_READERS = {
    "file_roles": _reader_file_roles,
    "symbol_usage": _reader_symbol_usage,
    "planning_validate": _reader_planning_validate,
    "module_writer": _reader_module_writer,
    "callgraph_python": _reader_callgraph("callgraph_python"),
    "callgraph_cpp": _reader_callgraph("callgraph_cpp"),
    "callgraph_rust_async": _reader_callgraph("callgraph_rust_async"),
}


def _bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, default=str).encode("utf-8")


@pytest.fixture
def _shapes(tmp_path):
    root = tmp_path / "src"
    write_python_fixture(root)
    inv_int = real_inventory(root, astgrep=True)
    assert any(isinstance(s.get("line_end"), int) for s in inv_int["symbols"]), (
        "fixture must yield at least one real int line_end — this cannot "
        "pass vacuously")
    return inv_int, strip_line_end(inv_int), null_line_end(inv_int)


@pytest.mark.parametrize("reader_name", sorted(_READERS))
def test_name_count_file_readers_byte_identical_with_and_without_line_end(
    reader_name, _shapes, tmp_path, monkeypatch
):
    """AC-4/AC-14: a reader that uses only names, counts or files produces
    byte-identical output whether the inventory's symbols carry a real int
    `line_end` or lack the key entirely (the true pre-KLC-137 shape)."""
    inv_int, inv_absent, _inv_null = _shapes
    modules = _modules_doc()
    reader = _READERS[reader_name]
    # Same LEAF directory name ("proj") for both calls — module-writer's
    # render_root() infers project_name from project_root().name, and a
    # differing tmp_path basename would introduce a spurious byte diff that
    # has nothing to do with line_end.
    out_int = reader(inv_int, modules, tmp_path / "int" / "proj", monkeypatch)
    out_absent = reader(inv_absent, modules, tmp_path / "absent" / "proj", monkeypatch)
    assert _bytes(out_int) == _bytes(out_absent)


@pytest.mark.parametrize("reader_name", sorted(_READERS))
def test_readers_do_not_raise_when_line_end_key_is_entirely_absent(
    reader_name, _shapes, tmp_path, monkeypatch
):
    """AC-4/AC-14: the absent-key shape and the null-valued (AC-2 regex)
    shape produce byte-identical output too — a reader tolerates both
    uniformly, and neither call raises."""
    _inv_int, inv_absent, inv_null = _shapes
    modules = _modules_doc()
    reader = _READERS[reader_name]
    out_absent = reader(inv_absent, modules, tmp_path / "absent2" / "proj", monkeypatch)
    out_null = reader(inv_null, modules, tmp_path / "null" / "proj", monkeypatch)
    assert _bytes(out_absent) == _bytes(out_null)


def _run_context_loader(project_root: Path, fmt: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PROJECT_ROOT": str(project_root)}
    return subprocess.run(
        [sys.executable, "-B", str(SKILLS / "context-loader.py"),
         "--modules", "pkg", "--format", fmt],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), timeout=30,
    )


def _write_index(project_root: Path, inv: dict, modules: dict) -> None:
    idx = project_root / ".klc" / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    (idx / "modules.json").write_text(json.dumps(modules), encoding="utf-8")


def test_public_api_filter_and_context_loader_pass_through_line_end_unchanged_otherwise(
    _shapes, tmp_path
):
    """AC-14: `public-api-filter.py`'s `symbols_by_module.json` output and
    `context-loader.py`'s JSON `public_api` output are each compared between
    the int-valued and absent-key shapes — the only difference anywhere is
    the added `line_end` key on every echoed item."""
    inv_int, inv_absent, _inv_null = _shapes
    modules = _modules_doc()

    paf = _import_skill("klc137_public_api_filter", "public-api-filter.py")
    _t1, _r1, sbm_int = paf.trim_modules(inv_int, modules, cap=999)
    _t2, _r2, sbm_absent = paf.trim_modules(inv_absent, modules, cap=999)
    assert sbm_int["pkg"], "fixture must produce at least one authored symbol"
    for with_end, without_end in zip(sbm_int["pkg"], sbm_absent["pkg"]):
        only_diff = set(with_end) - set(without_end)
        assert only_diff == {"line_end"}, only_diff
        stripped = dict(with_end)
        stripped.pop("line_end")
        assert stripped == without_end

    proj_int = tmp_path / "cl_int"
    _write_index(proj_int, inv_int, modules)
    proj_absent = tmp_path / "cl_absent"
    _write_index(proj_absent, inv_absent, modules)

    r_int = _run_context_loader(proj_int, "json")
    r_absent = _run_context_loader(proj_absent, "json")
    assert r_int.returncode == 0, r_int.stderr
    assert r_absent.returncode == 0, r_absent.stderr
    data_int = json.loads(r_int.stdout)
    data_absent = json.loads(r_absent.stdout)
    # `public_api` and the flattened `referenced_symbols` (D-071: built from
    # the same public_api values, core/skills/context-loader.py:571-572) BOTH
    # echo whole symbol dicts, so both carry the line_end diff.
    for field in ("public_api", "referenced_symbols"):
        items_int = (data_int[field]["pkg"] if field == "public_api"
                     else data_int[field])
        items_absent = (data_absent[field]["pkg"] if field == "public_api"
                        else data_absent[field])
        assert items_int, f"fixture must produce at least one {field} item"
        for with_end, without_end in zip(items_int, items_absent):
            only_diff = set(with_end) - set(without_end)
            assert only_diff == {"line_end"}, (field, only_diff)
            stripped = dict(with_end)
            stripped.pop("line_end")
            assert stripped == without_end

    # the rest of the payload (everything but the two echoed-symbol fields)
    # is untouched.
    data_int["public_api"] = data_absent["public_api"] = None
    data_int["referenced_symbols"] = data_absent["referenced_symbols"] = None
    assert data_int == data_absent


def test_context_loader_markdown_rendering_is_byte_identical_with_line_end_present(
    _shapes, tmp_path
):
    """AC-14 non-goal boundary: `context-loader.py`'s markdown rendering
    (the human-facing view) is byte-identical whether or not the underlying
    symbols carry `line_end` — the field passes through JSON only."""
    inv_int, inv_absent, _inv_null = _shapes
    modules = _modules_doc()

    proj_int = tmp_path / "md_int"
    _write_index(proj_int, inv_int, modules)
    proj_absent = tmp_path / "md_absent"
    _write_index(proj_absent, inv_absent, modules)

    r_int = _run_context_loader(proj_int, "markdown")
    r_absent = _run_context_loader(proj_absent, "markdown")
    assert r_int.returncode == 0, r_int.stderr
    assert r_absent.returncode == 0, r_absent.stderr
    assert r_int.stdout == r_absent.stdout
