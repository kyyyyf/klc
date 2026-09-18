"""rule_test_executor.py — KLC-103 AC-3: execute the declared `tests:` block
of every ast-grep rule file through the PRODUCTION scan path.

KLC semantics, which are the INVERSE of `ast-grep test` (F-101): a `valid`
case must MATCH the rule, an `invalid` case must NOT match, and a rule file
that declares no cases at all is itself a failure (a coverage gap cannot
reopen silently). `ast-grep test`'s own convention is the opposite (`valid`
means "must NOT match"), so this is a harness, not a shell-out to that
command (A-5).

Each case is scanned in isolation: the snippet is written to a temp file
carrying the extension the rule file declares (`metadata.extensions`), a
temp sgconfig lists that one rule file's directory plus the caller-supplied
`languageGlobs`, and `ast-grep scan` runs over it — the same mechanism
`deterministic_inventory._run_astgrep()` uses in production, so a case that
passes here is guaranteed to behave the same way in a real scan.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

# KLC-103: import yaml LOCALLY inside each function (not at module level).
# Several test files in this suite put `core/shared` on sys.path at their
# own MODULE level (collection time, before any fixture runs), which shadows
# a bare `import yaml` with klc's own core/shared/yaml.py (parse()/load(),
# no safe_load()) instead of real PyYAML. tests/conftest.py's autouse
# `_restore_real_pyyaml` fixture repairs sys.modules['yaml'] before every
# TEST FUNCTION body runs, but a MODULE-LEVEL `import yaml` here would bind
# the name once at COLLECTION time — before that fixture ever runs — and
# stay bound to the shadow for the rest of the process. A local import
# inside each function re-resolves sys.modules['yaml'] at CALL time
# (after the fixture already ran), matching the same pattern
# core/skills/deterministic_inventory.py's _run_astgrep() already uses for
# exactly this reason.


def _scan_one(rule_file: Path, snippet: str, ext: str,
             language_globs: dict) -> int:
    """One isolated ast-grep scan of *snippet* (written with extension *ext*)
    against *rule_file* alone. Returns the match count."""
    import yaml
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        rules_dir = td_path / "rules"
        case_dir = td_path / "case"
        rules_dir.mkdir()
        case_dir.mkdir()
        (rules_dir / rule_file.name).write_text(
            rule_file.read_text(encoding="utf-8"), encoding="utf-8")
        cfg: dict = {"ruleDirs": ["rules"]}
        if language_globs:
            cfg["languageGlobs"] = language_globs
        (td_path / "sg.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
        (case_dir / f"case{ext}").write_text(snippet, encoding="utf-8")
        proc = subprocess.run(
            ["ast-grep", "scan", "-c", "sg.yml", "--json", "case"],
            cwd=td_path, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"ast-grep scan failed for {rule_file} (exit {proc.returncode}): "
                f"{proc.stderr.strip()}")
        return len(json.loads(proc.stdout or "[]"))


def run_rule_tests(rule_dirs: list[Path], language_globs: dict) -> list[str]:
    """Execute every rule file's declared `tests:` cases. Returns one
    human-readable failure string per offending case or missing-cases rule
    file — empty when the gate is green.

    A rule file with no `tests:` block, or one whose `valid`/`invalid` keys
    are both empty, is itself a failure (AC-3: "fails when a rule file
    carries no test cases")."""
    import yaml
    failures: list[str] = []
    rule_files = sorted(
        p for d in rule_dirs for p in Path(d).rglob("*.yaml")
    )
    for rule_file in rule_files:
        doc = yaml.safe_load(rule_file.read_text(encoding="utf-8")) or {}
        cases = doc.get("tests") or {}
        valid_cases = cases.get("valid") or []
        invalid_cases = cases.get("invalid") or []
        if not valid_cases and not invalid_cases:
            failures.append(f"{rule_file}: declares no test cases")
            continue
        exts = (doc.get("metadata") or {}).get("extensions") or []
        ext = exts[0] if exts else ".txt"
        for bucket, snippets, must_match in (
            ("valid", valid_cases, True),
            ("invalid", invalid_cases, False),
        ):
            for i, snippet in enumerate(snippets):
                n = _scan_one(rule_file, snippet, ext, language_globs)
                matched = n > 0
                if matched is not must_match:
                    outcome = "no match" if must_match else f"matched ({n})"
                    failures.append(f"{rule_file} [{bucket} #{i}]: {outcome}")
    return failures
