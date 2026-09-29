"""KLC-139 step-3 — `skeleton.py`: the Python outline, the renderer and the
limits (AC-3, AC-4, AC-5, plus the encoding assumption).

Every test points PROJECT_ROOT at a fresh tmp_path (C-006 hermetic tests) and
writes its own fixture as a string constant (D-210).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "core" / "skills"
for _p in (str(SKILLS), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import skeleton as sk  # noqa: E402

# The golden fixture (impl-plan step-3 code sketch): decorators, nested
# classes, async defs, private names, an annotation without a value, a
# try/except import-fallback pattern (a module-level function defined inside
# an except handler), and function-local defs/imports that must be excluded.
_GOLDEN_LINES = [
    "import os",                                    # 1
    "import os.path",                               # 2
    "from os import sep",                           # 3
    "import numpy as np",                            # 4
    "from a.b import c as d, e",                     # 5
    "from . import x",                               # 6
    "from ..u import y",                             # 7
    "",                                               # 8
    "LIMIT = 3",                                      # 9
    'name: str = "k"',                                # 10
    "",                                               # 11
    "try:",                                           # 12
    "    import json",                                # 13
    "except ImportError:",                            # 14
    "    json = None",                                # 15
    "",                                               # 16
    "    def loads(s):",                              # 17
    "        return s",                               # 18
    "",                                               # 19
    "",                                               # 20
    "@decorator",                                     # 21
    "@other(1)",                                      # 22
    "class Outer:",                                   # 23
    "    x: int",                                     # 24
    "    y: int = 1",                                 # 25
    "    z = 2",                                      # 26
    "",                                               # 27
    "    class Inner:",                               # 28
    "        w = 0",                                  # 29
    "",                                               # 30
    "    async def fetch(self, n: int) -> str:",      # 31
    '        return ""',                              # 32
    "",                                               # 33
    "    def _private(self):",                        # 34
    "        def local():",                           # 35
    "            pass",                               # 36
    "        class LocalClass:",                      # 37
    "            pass",                               # 38
    "        import sys",                             # 39
    "        return local",                           # 40
    "",                                               # 41
    "",                                               # 42
    "async def run(a, *, b=1):",                      # 43
    "    pass",                                       # 44
    "",                                               # 45
    "",                                               # 46
    "def _helper():",                                 # 47
    "    pass",                                       # 48
]
_GOLDEN_SOURCE = "\n".join(_GOLDEN_LINES) + "\n"

assert len(_GOLDEN_LINES) == 48


def _write(tmp_path: Path, name: str, source: str) -> Path:
    fixture = tmp_path / name
    fixture.write_text(source, encoding="utf-8")
    return fixture


def _section(text: str, header: str) -> list[str]:
    """Return the 2-space-indented entry lines directly under a section
    whose header line starts with *header*, up to the next 0-indent line."""
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines[1:]:               # skip the outline's own header line
        if not in_section:
            if line == header or line.startswith(header + " "):
                in_section = True
            continue
        if line and not line.startswith(" "):
            break
        out.append(line[2:])
    return out


def test_golden_classes_and_functions_match_ast_ranges(tmp_path, monkeypatch):
    """AC-3: the golden fixture's full text matches exactly, and every
    class/function range is cross-checked against `ast` (the first decorator
    line, or the def/class line, to `end_lineno`)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    golden = _write(tmp_path, "golden.py", _GOLDEN_SOURCE)

    result = sk.skeleton(str(golden))
    assert not result.refused

    expected = (
        f"{golden} (python, 48 lines)\n"
        "imports [1-13]\n"
        "  a.{b.c as d, b.e}\n"
        "  json\n"
        "  numpy as np\n"
        "  os.{self, path, sep}\n"
        "  ..u.y\n"
        "  .x\n"
        "variables\n"
        "  LIMIT [9]\n"
        "  name: str [10]\n"
        "  json [15]\n"
        "classes\n"
        "  Outer [21-40]\n"
        "    x: int [24]\n"
        "    y: int [25]\n"
        "    z [26]\n"
        "    Inner [28-29]\n"
        "      w [29]\n"
        "    async fetch(self, n: int) -> str [31-32]\n"
        "    _private(self) [34-40]\n"
        "functions\n"
        "  loads(s) [17-18]\n"
        "  async run(a, *, b=1) [43-44]\n"
        "  _helper() [47-48]\n"
    )
    assert result.text == expected

    # Cross-check every INCLUDED def/class range against ast directly.
    tree = ast.parse(_GOLDEN_SOURCE)
    included = {"Outer", "Inner", "fetch", "_private", "loads", "run", "_helper"}
    excluded = {"local", "LocalClass"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name not in included and node.name not in excluded:
                continue
            decorators = node.decorator_list
            start = min(d.lineno for d in decorators) if decorators else node.lineno
            rng = f"[{start}]" if start == node.end_lineno else f"[{start}-{node.end_lineno}]"
            if node.name in included:
                assert rng in result.text, f"{node.name} range {rng} missing"
            else:
                assert rng not in result.text, f"{node.name} range {rng} leaked"


def test_function_body_locals_excluded(tmp_path, monkeypatch):
    """AC-3: a function-local def, class and import never appear on any
    line of the outline."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    golden = _write(tmp_path, "golden.py", _GOLDEN_SOURCE)
    result = sk.skeleton(str(golden))
    body = "\n".join(result.text.splitlines()[1:])   # header line may embed "local" via tmp_path
    assert "local" not in body
    assert "LocalClass" not in body
    assert "sys" not in body


def test_module_level_if_definitions_included(tmp_path, monkeypatch):
    """AC-3 (review F-6): a def and a class inside a module-level `if`/`else`
    pair are listed, with their own ranges, both branches."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    source = (
        "if TYPE_CHECKING:\n"                # 1
        "    def when_true():\n"             # 2
        "        return 1\n"                 # 3
        "\n"                                 # 4
        "    class WhenTrue:\n"              # 5
        "        pass\n"                     # 6
        "else:\n"                            # 7
        "    def when_false():\n"            # 8
        "        return 2\n"                 # 9
        "\n"                                 # 10
        "    class WhenFalse:\n"             # 11
        "        pass\n"                     # 12
    )
    fixture = _write(tmp_path, "ifdefs.py", source)
    result = sk.skeleton(str(fixture))
    assert "when_true() [2-3]" in result.text
    assert "WhenTrue [5-6]" in result.text
    assert "when_false() [8-9]" in result.text
    assert "WhenFalse [11-12]" in result.text


def test_module_variables_section(tmp_path, monkeypatch):
    """AC-3 (Q-002/D-213): plain-name and annotated module assignments are
    listed with their whole-statement range; a tuple target is not; the
    section is uncapped (12 variables, 12 lines)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    var_lines = [f"v{i} = {i}" for i in range(1, 13)]
    source = "\n".join(var_lines) + "\n(tx, ty) = (1, 2)\n"
    fixture = _write(tmp_path, "vars.py", source)
    result = sk.skeleton(str(fixture))
    for i in range(1, 13):
        assert f"v{i} [{i}]" in result.text
    assert "tx" not in result.text
    assert "ty" not in result.text


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import os\n", ["os"]),
        ("import os.path\nfrom os import sep\n", ["os.{path, sep}"]),
        ("import os\nfrom os import path\n", ["os.{self, path}"]),
        ("import numpy as np\n", ["numpy as np"]),
        ("from a.b import c as d, e\n", ["a.{b.c as d, b.e}"]),
        ("from . import x\n", [".x"]),
        ("from ..u import y\n", ["..u.y"]),
    ],
)
def test_import_collapsing_table(tmp_path, monkeypatch, source, expected):
    """AC-4: each row of spec §"Output format" produces the exact collapsed
    line(s), one case per parametrized fixture."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = _write(tmp_path, "imp.py", source)
    result = sk.skeleton(str(fixture))
    imports = _section(result.text, "imports")
    assert imports == expected


def test_module_level_if_try_imports_included_function_local_excluded(tmp_path, monkeypatch):
    """AC-4: imports inside module-level `if`/`try` are included; a
    function-local import is not."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    source = (
        "if COND:\n"
        "    import a\n"
        "else:\n"
        "    from . import b\n"
        "\n"
        "try:\n"
        "    import c\n"
        "except ImportError:\n"
        "    import d\n"
        "\n"
        "\n"
        "def f():\n"
        "    import local_only\n"
    )
    fixture = _write(tmp_path, "mixed_imports.py", source)
    result = sk.skeleton(str(fixture))
    imports = _section(result.text, "imports")
    assert imports == ["a", "c", "d", ".b"]
    assert "local_only" not in result.text


def test_imports_header_range_spans_first_to_last_import_line(tmp_path, monkeypatch):
    """AC-4: the golden fixture's imports header is `imports [1-13]`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    golden = _write(tmp_path, "golden.py", _GOLDEN_SOURCE)
    result = sk.skeleton(str(golden))
    assert "imports [1-13]" in result.text


def test_data_member_cap_truncates_at_default_8(tmp_path, monkeypatch):
    """AC-5: a 12-attribute class shows 8 then `[4 more truncated]`; a class
    with 30 methods and 12 attributes shows all 30 methods, 8 attributes and
    `[4 more truncated]` (Q-001's example)."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    attrs_only = "class C:\n" + "\n".join(f"    attr{i} = {i}" for i in range(1, 13)) + "\n"
    fixture_a = _write(tmp_path, "capA.py", attrs_only)
    result_a = sk.skeleton(str(fixture_a))
    for i in range(1, 9):
        assert f"attr{i} [{i + 1}]" in result_a.text
    for i in range(9, 13):
        assert f"attr{i} " not in result_a.text
    assert "[4 more truncated]" in result_a.text

    attrs = [f"    attr{i} = {i}" for i in range(1, 13)]
    methods = [f"    def m{i}(self): pass" for i in range(1, 31)]
    mixed = "class D:\n" + "\n".join(attrs + methods) + "\n"
    fixture_b = _write(tmp_path, "capB.py", mixed)
    result_b = sk.skeleton(str(fixture_b))
    for i in range(1, 31):
        assert f"m{i}(self)" in result_b.text
    for i in range(1, 9):
        assert f"attr{i} [{i + 1}]" in result_b.text
    for i in range(9, 13):
        assert f"attr{i} " not in result_b.text
    assert "[4 more truncated]" in result_b.text


def test_data_member_cap_boundary_exactly_8_not_truncated(tmp_path, monkeypatch):
    """AC-5: 8 members give no marker; 9 give `[1 more truncated]`."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    eight = "class E:\n" + "\n".join(f"    a{i} = {i}" for i in range(1, 9)) + "\n"
    fixture_8 = _write(tmp_path, "cap8.py", eight)
    result_8 = sk.skeleton(str(fixture_8))
    assert "truncated" not in result_8.text
    for i in range(1, 9):
        assert f"a{i} [{i + 1}]" in result_8.text

    nine = "class F:\n" + "\n".join(f"    a{i} = {i}" for i in range(1, 10)) + "\n"
    fixture_9 = _write(tmp_path, "cap9.py", nine)
    result_9 = sk.skeleton(str(fixture_9))
    assert "[1 more truncated]" in result_9.text


def test_line_length_cut_keeps_range(tmp_path, monkeypatch):
    """AC-5: a 200-character signature and a 150-character path header are
    each at most 120 characters, `[truncated]` sits directly before the
    range (the entry) or before the protected `(python, N lines)` suffix
    (the header, D-208), and both stay intact."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    long_name = "a" * 200
    source = f"def {long_name}():\n    pass\n"
    fixture = _write(tmp_path, "longsig.py", source)
    result = sk.skeleton(str(fixture))
    entry_line = [l for l in result.text.splitlines() if "[truncated]" in l and "[1-2]" in l][0]
    assert len(entry_line) <= 120
    assert " [truncated] [1-2]" in entry_line or " [truncated][1-2]" in entry_line

    long_stem = "f" * 200
    long_fixture = _write(tmp_path, f"{long_stem}.py", "x = 1\n")
    result_long = sk.skeleton(str(long_fixture))
    header_line = result_long.text.splitlines()[0]
    assert len(header_line) <= 120
    assert "[truncated]" in header_line
    assert header_line.endswith("(python, 1 lines)")


def test_settings_override_changes_cap_and_line_limit(tmp_path, monkeypatch):
    """AC-5: a tmp `.klc/config/settings.yml` with `max_fields: 2` and
    `max_line: 60` changes the marker to `[10 more truncated]` and the cut
    length to 60."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    cfg_dir = tmp_path / ".klc" / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "settings.yml").write_text(
        "skeleton:\n  max_fields: 2\n  max_line: 60\n", encoding="utf-8"
    )
    twelve = "class G:\n" + "\n".join(f"    b{i} = {i}" for i in range(1, 13)) + "\n"
    fixture = _write(tmp_path, "override.py", twelve)
    result = sk.skeleton(str(fixture))
    assert "[10 more truncated]" in result.text
    for line in result.text.splitlines():
        assert len(line) <= 60


def test_non_utf8_file_decoded_with_replace(tmp_path, monkeypatch):
    """AC-3 (assumption encoding): a latin-1 byte in a comment still yields
    the outline, exit 0."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    fixture = tmp_path / "latin1.py"
    fixture.write_bytes(b"# caf\xe9 comment\ndef f():\n    pass\n")
    result = sk.skeleton(str(fixture))
    assert result.exit_code == 0
    assert "f() [2-3]" in result.text
