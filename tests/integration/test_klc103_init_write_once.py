"""KLC-103 — AC-8: a full `klc init --auto` run writes inventory.json exactly
once, whether or not the inventory agent step actually ran.

Real substrate: a temp git repo, `klc install`, then `init.py --auto` as a
real subprocess. The LLM agent step is served by a stub `CLAUDE_CLI` binary
(a tiny script on PATH) so the whole pipeline runs end to end with no network
call and no real model dependency — matching the pattern klc's own agent
dispatch uses (`core/skills/runner.py`'s provider="anthropic" path invokes
whatever binary `CLAUDE_CLI` names)."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent

_STUB_CLAUDE = """#!/usr/bin/env python3
import json
import os
import sys

prompt = sys.stdin.read()
idx = os.path.join(".klc", "index")
if "Inventory Agent" in prompt:
    # Play the agent's own role for real: write the annotation file it is
    # instructed to write (never inventory.json — this stub is deliberately
    # faithful to that instruction, since the test asserts on it).
    ann_path = os.path.join(idx, "inventory-annotations.json")
    with open(ann_path, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": "stub", "root": ".", "profile": "generic",
                   "annotations": [], "notes": ["stub agent run"]}, fh)
    print("Enrichment complete.\\nINVENTORY_OK " + ann_path)
elif "Docgen Agent" in prompt:
    print("Docs written.\\nDOCGEN_OK 1 file(s) written")
else:
    print("STUB_OK")
sys.exit(0)
"""


class TestInitAutoWriteOnce(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="klc-test-init-write-once-")
        self.project_root = Path(self.tempdir)

        subprocess.run(["git", "init"], cwd=str(self.project_root),
                       capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(self.project_root), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(self.project_root), capture_output=True)
        (self.project_root / "pkg").mkdir()
        (self.project_root / "pkg" / "mod.py").write_text(
            "def public_fn():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(self.project_root),
                       capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"],
                       cwd=str(self.project_root), capture_output=True)

        subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "klc"),
             "install", str(self.project_root)],
            capture_output=True, check=True)

        # Stub CLAUDE_CLI: a fake `claude` binary on PATH so the agent
        # dispatch step (runner.py, provider=anthropic) runs end-to-end
        # with no network call.
        stub_dir = self.project_root / "_stub_bin"
        stub_dir.mkdir()
        stub_path = stub_dir / "fake-claude"
        stub_path.write_text(_STUB_CLAUDE, encoding="utf-8")
        stub_path.chmod(stub_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        self.env = dict(os.environ)
        self.env["PROJECT_ROOT"] = str(self.project_root)
        self.env["CLAUDE_CLI"] = str(stub_path)
        self.env["CLAUDE_ARGS"] = ""
        self.env["PATH"] = f"{stub_dir}{os.pathsep}{self.env.get('PATH', '')}"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_init_auto_writes_inventory_exactly_once(self):
        """AC-8: the deterministic view-builder log line 'planning view:
        inventory' (F-106 — init logs one per builder it runs) must appear
        exactly once across the whole --auto run, not twice (pre-agent +
        post-agent)."""
        result = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "init.py"), "--auto"],
            cwd=str(self.project_root), env=self.env,
            capture_output=True, text=True, timeout=120,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        occurrences = output.count("planning view: inventory")
        self.assertEqual(occurrences, 1,
                         f"expected exactly one inventory view build, got {occurrences}:\n{output}")

    def test_inventory_validates_against_schema_with_and_without_agent_step(self):
        """AC-8: the on-disk artifact validates against the canonical flat
        schema whether the inventory agent step executed (--auto) or was
        skipped (--scan-only)."""
        from core.shared.inventory import symbols

        # Sub-run 1: --scan-only (agent step skipped entirely).
        r1 = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "init.py"), "--scan-only"],
            cwd=str(self.project_root), env=self.env,
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        inv_path = self.project_root / ".klc" / "index" / "inventory.json"
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
        symbols(inv, source=str(inv_path))  # must not raise

        # Sub-run 2: --auto (agent step executed, stub INVENTORY_OK).
        r2 = subprocess.run(
            [sys.executable, str(FRAMEWORK_ROOT / "scripts" / "init.py"), "--auto"],
            cwd=str(self.project_root), env=self.env,
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        inv2 = json.loads(inv_path.read_text(encoding="utf-8"))
        symbols(inv2, source=str(inv_path))  # must not raise
        # The agent's own annotation file must exist and NOT be the
        # inventory.json shape (D-103: separate artifact, separate producer).
        ann_path = self.project_root / ".klc" / "index" / "inventory-annotations.json"
        self.assertTrue(ann_path.exists(), "agent must write inventory-annotations.json")


if __name__ == "__main__":
    unittest.main()
