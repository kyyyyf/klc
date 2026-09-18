"""KLC-104 — module-writer must not clobber the root CLAUDE.md with a
per-module render of the `.`-path root-sentinel module (modules_build.py's
FIX-2 sentinel for repo-root files), must not mistake in-prose mentions of
the manual-block markers for the real markers, and `_verify()` must fail
closed on that exact clobber shape if it ever recurs.

Real-substrate style, consistent with tests/integration/test_pipeline_wiring.py:
throwaway repo + subprocess run of the actual script for the AC-1 case;
importlib-loaded module (hyphenated filename) for the AC-2/AC-3 unit-level
checks against `extract_manual_block()` and `_verify()` directly.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent      # worktree root
WRITER = REPO / "core" / "skills" / "module-writer.py"


def _load_writer():
    spec = importlib.util.spec_from_file_location("module_writer_klc104", WRITER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_with_dot_module_preserves_root(tmp_path):
    """AC-1: `module-writer.py --all` against a modules.json that carries both a
    `.` root-sentinel module and a normal `pkg` module must NOT render a per-module
    CLAUDE.md for `.` (that target IS the root CLAUDE.md — rendering it clobbers the
    real root content), must not list a `.` row in the root Modules table, and the
    root CLAUDE.md must keep the project-name heading `render_root()` always emits."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True)
    (idx / "modules.json").write_text(json.dumps({"modules": [
        {"name": "pkg", "path": "pkg/", "files": ["pkg/m.py"],
         "depends_on": [], "depended_by": []},
        {"name": ".", "path": ".", "files": ["main.py"],
         "depends_on": [], "depended_by": []},
    ]}), encoding="utf-8")
    (idx / "inventory.json").write_text(json.dumps({
        "structural": {"languages": {}, "total_lines": 0, "total_files": 2},
        "symbols": [], "notes": []}), encoding="utf-8")

    env = dict(os.environ, PROJECT_ROOT=str(root))
    r = subprocess.run([sys.executable, str(WRITER), "--all"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr

    root_doc = (root / "CLAUDE.md").read_text(encoding="utf-8")
    # The root doc must keep the project-name heading CLAUDE.md.j2 always emits,
    # never the module template's "# Module: ." heading.
    assert root_doc.startswith(f"# {root.name}"), (
        "root CLAUDE.md was clobbered by a per-module render of the '.' "
        f"sentinel: {root_doc[:80]!r}"
    )
    assert not root_doc.lstrip().startswith("# Module:")
    # No '.' row in the Modules table.
    assert "| `.` |" not in root_doc
    # The real code module still renders.
    assert (root / "pkg" / "CLAUDE.md").exists()


def test_extract_manual_block_ignores_prose_marker(tmp_path):
    """AC-2: a document whose header prose mentions the marker text inline
    (e.g. CLAUDE.md.j2's own "Manual notes go inside the `<!-- BEGIN: manual -->`
    block..." sentence) must not have that inline mention mistaken for the real
    marker. Only the genuine, own-line marker pair delimits the extracted block."""
    mod = _load_writer()
    doc = tmp_path / "CLAUDE.md"
    doc.write_text(
        "# proj\n\n"
        "> Manual notes go inside the `<!-- BEGIN: manual -->` block at the "
        "bottom of the file.\n\n"
        "## Overview\n\n"
        "some generated content that must NOT leak into the manual block\n\n"
        "<!-- BEGIN: manual -->\n"
        "the real manual note\n"
        "<!-- END: manual -->\n",
        encoding="utf-8",
    )
    extracted = mod.extract_manual_block(doc)
    assert extracted == "the real manual note"
    assert "generated content" not in extracted
    assert "Manual notes go inside" not in extracted


def test_verify_fails_on_module_prefixed_root(tmp_path, monkeypatch):
    """AC-3: `_verify()` must report an error when the root CLAUDE.md begins with
    `# Module:` instead of the project-name heading CLAUDE.md.j2 always emits --
    this is the exact clobber shape from AC-1, and the gate must catch it even if
    it recurs some other way (e.g. a hand-run `--module .`)."""
    mod = _load_writer()
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    (root / "CLAUDE.md").write_text(
        "# Module: .\n\n> Path: `.`\n> Language: -\n", encoding="utf-8"
    )
    errors = mod._verify([])
    assert any("# Module:" in e for e in errors), errors

    # And a normal, non-clobbered root must NOT false-positive.
    (root / "CLAUDE.md").write_text("# proj\n\n## Overview\n", encoding="utf-8")
    errors_ok = mod._verify([])
    assert not any("# Module:" in e for e in errors_ok), errors_ok

    # An absent root CLAUDE.md must not raise or false-positive either.
    (root / "CLAUDE.md").unlink()
    errors_missing = mod._verify([])
    assert not any("# Module:" in e for e in errors_missing), errors_missing


def test_extract_manual_block_tolerates_leading_whitespace_on_marker_line(tmp_path):
    """review-fix (MEDIUM, AC-2): a marker line with LEADING whitespace (e.g.
    the BEGIN/END lines indented inside a blockquote/list, or by an
    auto-indenting editor) must still be recognised as the real marker — the
    line-anchored regex introduced by this ticket only tolerated TRAILING
    whitespace, so an indented marker silently extracted '' instead of the
    real manual note. The prose-mention case (a marker mentioned inline,
    mid-sentence, never alone on its line) must still fail to match."""
    mod = _load_writer()
    doc = tmp_path / "CLAUDE.md"
    doc.write_text(
        "# proj\n\n"
        "> Manual notes go inside the `<!-- BEGIN: manual -->` block at the "
        "bottom of the file.\n\n"
        "## Overview\n\n"
        "some generated content that must NOT leak into the manual block\n\n"
        "    <!-- BEGIN: manual -->\n"
        "the real manual note, indented markers\n"
        "    <!-- END: manual -->\n",
        encoding="utf-8",
    )
    extracted = mod.extract_manual_block(doc)
    assert extracted == "the real manual note, indented markers"
    assert "generated content" not in extracted
    assert "Manual notes go inside" not in extracted


def _dot_module_fixture(tmp_path):
    """A repo whose modules.json carries both a real code module and the `.`
    root-sentinel module, mirroring test_all_with_dot_module_preserves_root."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True)
    (idx / "modules.json").write_text(json.dumps({"modules": [
        {"name": "pkg", "path": "pkg/", "files": ["pkg/m.py"],
         "depends_on": [], "depended_by": []},
        {"name": ".", "path": ".", "files": ["main.py"],
         "depends_on": [], "depended_by": []},
    ]}), encoding="utf-8")
    (idx / "inventory.json").write_text(json.dumps({
        "structural": {"languages": {}, "total_lines": 0, "total_files": 2},
        "symbols": [], "notes": []}), encoding="utf-8")
    return root


def test_module_dot_fails_closed_exit_1_never_touches_root(tmp_path):
    """review-fix (MEDIUM, AC-1): an explicit `--module .` request must fail
    closed — exit 1, a clear stderr message naming the sentinel, and the root
    CLAUDE.md left untouched (absent, since nothing renders it here)."""
    root = _dot_module_fixture(tmp_path)
    env = dict(os.environ, PROJECT_ROOT=str(root))
    r = subprocess.run([sys.executable, str(WRITER), "--module", "."],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "sentinel" in r.stderr, r.stderr
    assert not (root / "CLAUDE.md").exists(), (
        "the root CLAUDE.md must be left untouched by a failed --module . request")


def test_only_dot_skips_gracefully_exit_0_keeps_root_heading(tmp_path):
    """review-fix (MEDIUM, AC-1): an explicit `--only .` request must be
    skipped gracefully (exit 0, a 'skipping module' stderr line, nothing
    written for the sentinel) — symmetric with the existing non-code-module
    skip, never a silent no-op. The root CLAUDE.md still gets its
    project-name heading from render_root(), which --only always runs first.

    Uses a modules.json carrying ONLY the sentinel (no other code module) so
    the post-render `_verify()` gate — which always checks every code
    module's CLAUDE.md exists on disk, regardless of what --only asked for —
    has nothing else to fail on; that gate is orthogonal to this fix."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    idx = root / ".klc" / "index"
    idx.mkdir(parents=True)
    (idx / "modules.json").write_text(json.dumps({"modules": [
        {"name": ".", "path": ".", "files": ["main.py"],
         "depends_on": [], "depended_by": []},
    ]}), encoding="utf-8")
    (idx / "inventory.json").write_text(json.dumps({
        "structural": {"languages": {}, "total_lines": 0, "total_files": 1},
        "symbols": [], "notes": []}), encoding="utf-8")

    env = dict(os.environ, PROJECT_ROOT=str(root))
    r = subprocess.run([sys.executable, str(WRITER), "--only", "."],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "skipping module" in r.stderr, r.stderr

    root_doc = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert root_doc.startswith(f"# {root.name}"), (
        "root CLAUDE.md must keep the project-name heading, "
        f"got: {root_doc[:80]!r}")
    assert not root_doc.lstrip().startswith("# Module:")
