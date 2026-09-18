"""KLC-103 — the shared inventory accessor (core/shared/inventory.py).

Real-substrate tests: no mocks. The accessor is the single reader every
consumer of `.klc/index/inventory.json` routes through (AC-6); it must raise a
named, path-carrying error for a retired/wrong-shaped artifact (AC-7) while
still degrading cleanly on a genuinely ABSENT or unreadable one when the
caller says the input is optional (C-005 / D-2).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.shared.inventory import InventorySchemaError, load, symbols

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"

# AC-6's seven named consumers. Filenames as they live on disk (public-api-filter.py
# and planning-retriever.py use dashes, not underscores — not importable as plain
# modules, so the static-scan test below reads them as text rather than importing).
_SEVEN_CONSUMERS = [
    SKILLS / "file_roles.py",
    SKILLS / "symbol_usage.py",
    SKILLS / "planning_validate.py",
    SKILLS / "public-api-filter.py",
    SKILLS / "context-loader.py",
    SKILLS / "module-writer.py",
    SKILLS / "planning-retriever.py",
]

# The exact raw-iteration patterns spec.md's Defect 2 cited at each site, before
# KLC-103 routed them through the accessor. Presence of any of these in a
# consumer's source is the AC-6 violation this test guards against.
_RETIRED_RAW_PATTERNS = (
    'inventory.get("symbols") or []',
    '(inventory or {}).get("symbols") or []',
    'inv.get("symbols", {}).items()',
    'inventory.get("symbols", {}).items()',
    'inv.get("symbols", {})',
)


def test_accessor_raises_named_error_on_retired_mapping_shape():
    """AC-7: the retired per-language mapping shape must raise, not degrade."""
    retired = {
        "root": "/proj",
        "symbols": {
            "python": [{"name": "f", "kind": "function"}],
        },
    }
    with pytest.raises(InventorySchemaError) as exc_info:
        symbols(retired, source="/proj/.klc/index/inventory.json")
    msg = str(exc_info.value)
    assert "/proj/.klc/index/inventory.json" in msg
    assert "mapping" in msg.lower()


def test_accessor_raises_named_error_on_missing_symbols_key():
    """AC-7: no 'symbols' key at all must raise, not silently return []."""
    no_symbols = {"root": "/proj", "profile": "generic"}
    with pytest.raises(InventorySchemaError) as exc_info:
        symbols(no_symbols, source="/proj/.klc/index/inventory.json")
    msg = str(exc_info.value)
    assert "/proj/.klc/index/inventory.json" in msg
    assert "symbols" in msg.lower()


def test_accessor_load_degrades_on_present_but_corrupt_json_when_not_required(tmp_path):
    """D-2 / F-2: a PRESENT but unparseable file degrades to None when the
    caller marks the input optional (required=False) — matching today's
    behaviour of planning_validate._opt() and planning-retriever._load() for
    every optional artifact, inventory included."""
    bad = tmp_path / "inventory.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert load(bad, required=False) is None


def test_accessor_load_raises_on_present_but_corrupt_json_when_required(tmp_path):
    """The same present-but-corrupt input raises when the caller marks the
    input required (the default)."""
    bad = tmp_path / "inventory.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(InventorySchemaError):
        load(bad, required=True)


def test_accessor_load_raises_on_wrong_shape_regardless_of_required(tmp_path):
    """AC-7 / D-2: a present, READABLE, but WRONG-SHAPED artifact always
    raises — that check does not depend on `required`, because it is a schema
    mismatch, not a missing input."""
    wrong_shape = tmp_path / "inventory.json"
    wrong_shape.write_text(
        json.dumps({"root": "/proj", "symbols": {"python": []}}), encoding="utf-8")
    with pytest.raises(InventorySchemaError):
        load(wrong_shape, required=False)
    with pytest.raises(InventorySchemaError):
        load(wrong_shape, required=True)


def test_accessor_load_absent_degrades_only_when_not_required(tmp_path):
    """Baseline C-005 behaviour: a genuinely absent path raises when required,
    degrades to None when not."""
    absent = tmp_path / "does-not-exist.json"
    with pytest.raises(InventorySchemaError):
        load(absent, required=True)
    assert load(absent, required=False) is None


def _import_skill(module_name: str, filename: str):
    """Import a core/skills/<filename> module whose on-disk name is not a
    valid Python identifier (dashes), the same pattern already used across
    this suite (e.g. tests/integration/test_modules_v2.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(module_name, str(SKILLS / filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seven_consumers_use_shared_accessor_not_raw_iteration():
    """AC-6: none of the seven named consumers may iterate the raw `symbols`
    value directly any more — every retired raw-iteration pattern spec.md
    cited at each site must be gone, and each file must import the shared
    accessor."""
    for path in _SEVEN_CONSUMERS:
        text = path.read_text(encoding="utf-8")
        for pattern in _RETIRED_RAW_PATTERNS:
            assert pattern not in text, f"{path.name} still has raw pattern: {pattern!r}"
        assert "core.shared.inventory" in text, (
            f"{path.name} does not import the shared accessor (core.shared.inventory)")


def test_all_seven_consumers_agree_on_symbol_count_via_accessor(tmp_path):
    """AC-6 (functional): one canonical flat inventory.json fixture fed through
    each of the 7 consumers' real functions; every one derives the same
    symbol count via the shared accessor — no consumer silently sees fewer
    symbols than another."""
    n = 5
    inv = {"symbols": [
        {"name": f"sym{i}", "kind": "function", "file": "pkg/mod.py", "line": i,
         "signature": "def f(): pass", "visibility": "public",
         "source_of_truth": "ast_grep", "lang": "python", "rule": "r"}
        for i in range(n)
    ]}
    mods = {"modules": [{"name": "pkg", "path": "pkg/", "files": []}]}

    fr = _import_skill("klc103_file_roles", "file_roles.py")
    su = _import_skill("klc103_symbol_usage", "symbol_usage.py")
    paf = _import_skill("klc103_public_api_filter", "public-api-filter.py")
    cl = _import_skill("klc103_context_loader", "context-loader.py")

    # file_roles: every symbol lands in exactly one file bucket.
    by_file = fr._symbols_by_file(inv)
    assert sum(len(v) for v in by_file.values()) == n

    # symbol_usage: one output entry per input symbol (no structural filter,
    # no callgraph — a plain 1:1 pass).
    result = su.build_symbol_usage(inv, mods, callgraph=None, depgraph=None,
                                   structural=None)
    assert len(result["symbols"]) == n

    # public-api-filter: trim_modules' by-file index sees every symbol.
    _, _, sbm = paf.trim_modules(inv, mods, cap=999)
    assert sum(len(v) for v in sbm.values()) == n

    # context-loader: total_project_symbols() is the flat count.
    assert cl.total_project_symbols(inv) == n
    idx = cl._build_symbols_by_module_from_inventory(inv, mods)
    assert sum(len(v) for v in idx.values()) == n


def test_consumer_cli_exits_nonzero_on_retired_shape(tmp_path):
    """AC-7: fail-closed at the public entry point. file_roles.py invoked as a
    subprocess against a mapping-shaped (retired) inventory.json must exit
    non-zero with the error on stderr, not a zero-count success."""
    inv_path = tmp_path / "inventory.json"
    inv_path.write_text(json.dumps({"symbols": {"python": []}}), encoding="utf-8")
    modules_path = tmp_path / "modules.json"
    modules_path.write_text(json.dumps({"modules": []}), encoding="utf-8")
    out_path = tmp_path / "file_roles.json"

    proc = subprocess.run(
        [sys.executable, str(SKILLS / "file_roles.py"),
         "--in-inventory", str(inv_path),
         "--in-modules", str(modules_path),
         "--out", str(out_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 2, proc.stderr
    # A CONTROLLED, named failure (AC-7: "message names the offending path and
    # the expected schema") — not an uncaught AttributeError/Traceback crash.
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "mapping" in proc.stderr.lower()
    assert str(inv_path) in proc.stderr


def test_planning_validate_degrades_on_present_but_corrupt_inventory(tmp_path):
    """D-2 / F-2: planning_validate.py is ADVISORY — a present-but-corrupt
    --in-inventory must degrade (not crash), matching today's behaviour for
    every other optional input."""
    sys.path.insert(0, str(SKILLS))
    import importlib
    if "planning_validate" in sys.modules:
        importlib.reload(sys.modules["planning_validate"])
    import planning_validate as pv  # noqa: E402

    modules_path = tmp_path / "modules.json"
    modules_path.write_text(json.dumps({"modules": []}), encoding="utf-8")
    bad_inv = tmp_path / "inventory.json"
    bad_inv.write_text("{not valid json", encoding="utf-8")
    out_path = tmp_path / "report.json"

    rc = pv.main(["--in-modules", str(modules_path),
                 "--in-inventory", str(bad_inv), "--out", str(out_path)])
    assert rc == 0  # degrade-not-fail: a corrupt optional input is not fatal


def test_planning_retriever_degrades_on_present_but_corrupt_inventory(tmp_path):
    """D-2 / F-2: planning-retriever.py's inventory input is optional (its
    build_trace() docstring: accepted but currently ignored) — a
    present-but-corrupt inventory.json must not crash the retriever."""
    pr = _import_skill("klc103_planning_retriever", "planning-retriever.py")
    bad_inv = tmp_path / "inventory.json"
    bad_inv.write_text("{not valid json", encoding="utf-8")
    data = pr._load_inventory(bad_inv)
    assert data == {}
