"""KLC-108 — AC-8: a token-frequency artifact under `.klc/index/` is written
from the repository's own token frequencies over the file-roles signal; the
builder is pure with respect to its inputs, carries no timestamp, and a
re-run on an unchanged tree reproduces the artifact byte-for-byte.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
sys.path.insert(0, str(SKILLS))

import file_roles as fr  # noqa: E402


def _write_fixture_tree(root: Path) -> None:
    (root / "core" / "x").mkdir(parents=True, exist_ok=True)
    (root / "core" / "y").mkdir(parents=True, exist_ok=True)
    (root / "core" / "x" / "alpha.py").write_text(
        '"""Alpha module for widget catalog import."""\ndef one():\n    pass\n',
        encoding="utf-8")
    (root / "core" / "y" / "beta.py").write_text(
        '"""Beta module for widget catalog export."""\ndef two():\n    pass\n',
        encoding="utf-8")


def _fixture_views() -> tuple[dict, dict, dict]:
    inv = {"symbols": [
        {"name": "one", "kind": "function", "file": "core/x/alpha.py",
         "line": 2, "visibility": "public"},
        {"name": "two", "kind": "function", "file": "core/y/beta.py",
         "line": 2, "visibility": "public"},
    ]}
    modules = {"modules": [{"name": "x", "path": "core/x"},
                           {"name": "y", "path": "core/y"}]}
    structural = {"entry_points": []}
    return inv, modules, structural


def _run_main(root: Path, out_dir: Path, views: tuple[dict, dict, dict] | None = None
             ) -> tuple[Path, Path]:
    inv, modules, structural = views or _fixture_views()
    out_dir.mkdir(parents=True, exist_ok=True)
    in_inv = out_dir / "inventory.json"
    in_inv.write_text(json.dumps(inv), encoding="utf-8")
    in_mod = out_dir / "modules.json"
    in_mod.write_text(json.dumps(modules), encoding="utf-8")
    in_struct = out_dir / "structural.json"
    in_struct.write_text(json.dumps(structural), encoding="utf-8")
    out = out_dir / "file_roles.json"
    rc = fr.main(["--root", str(root), "--in-inventory", str(in_inv),
                 "--in-modules", str(in_mod), "--in-structural", str(in_struct),
                 "--out", str(out)])
    assert rc == 0
    return out, out.parent / "token_idf.json"


def test_idf_builder_reproducible_byte_for_byte(tmp_path):
    """AC-8: the builder is pure with respect to its inputs and a re-run on
    an unchanged tree reproduces the artifact byte-for-byte."""
    root = tmp_path / "repo"
    _write_fixture_tree(root)
    _, idf1 = _run_main(root, tmp_path / "run1")
    _, idf2 = _run_main(root, tmp_path / "run2")
    assert idf1.exists() and idf2.exists()
    assert idf1.read_bytes() == idf2.read_bytes()


def test_idf_artifact_carries_no_timestamp_field(tmp_path):
    """AC-8: the token-frequency artifact carries no timestamp."""
    root = tmp_path / "repo"
    _write_fixture_tree(root)
    _, idf = _run_main(root, tmp_path / "run1")
    data = json.loads(idf.read_text(encoding="utf-8"))
    for key in data:
        low = key.lower()
        assert "generated_at" not in low and "timestamp" not in low, key


def test_idf_artifact_absent_input_fails_closed(tmp_path):
    """AC-8: a missing/empty file_roles signal must not produce an artifact with
    fabricated frequencies — the CLI fails closed (exit 2, the same
    contract `--in-inventory` absence already carries) and writes nothing."""
    rc = fr.main(["--in-inventory", str(tmp_path / "nope.json"),
                 "--out", str(tmp_path / "roles.json")])
    assert rc == 2
    assert not (tmp_path / "token_idf.json").exists()
    assert not (tmp_path / "roles.json").exists()


def test_idf_weight_is_strictly_positive_for_a_token_in_every_file(tmp_path):
    """D-002: the smoothed weight `log((N+1)/(df+1)) + 1` is strictly
    positive even at `df == N` — a token in every file is down-weighted,
    never deleted."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text('"""shared token everywhere."""\n', encoding="utf-8")
    (root / "b.py").write_text('"""shared token everywhere too."""\n', encoding="utf-8")
    views = ({"symbols": []},
            {"modules": [{"name": "m", "path": ".", "files": ["a.py", "b.py"]}]},
            {"entry_points": []})
    _, idf_path = _run_main(root, tmp_path / "run1", views)
    idf = json.loads(idf_path.read_text(encoding="utf-8"))
    weight_shared = idf["tokens"].get("shared")
    assert weight_shared is not None
    assert weight_shared > 0
    assert weight_shared == min(idf["tokens"].values())
