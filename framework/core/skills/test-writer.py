#!/usr/bin/env python3
"""test-writer.py — test generation + mutation testing orchestrator.

Usage:
    test-writer.py --spec <path> --modules <m1,m2> [--type feature|bug]

The skill:
- Reads framework/index/test-framework.json (produced by the test agent).
- Reads framework/index/modules.json for module path resolution.
- Samples existing tests in the affected modules (via ast-grep if present)
  so a caller LLM can match the project's style.
- Runs the detected mutation-testing tool scoped to the affected tests.
- Returns a single JSON document on stdout in the exact shape documented in
  framework/core/agents/test.md.

The skill does NOT invoke an LLM. It is a deterministic worker: it prepares
inputs, runs mutation commands, parses results, and reports. The test agent
calls it and, if `tests_written == 0` or new tests are required, uses the
reports to steer the LLM that actually edits files.

Errors: printed to stderr; exits non-zero only when the inputs are malformed
or essential files are missing. A failing mutation run is reported as a
warning, not an error.

All text is English.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def framework_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def project_root() -> Path:
    return framework_root().parent


def load_json(p: Path) -> Any:
    if not p.exists():
        sys.stderr.write(f"test-writer: missing file {p}\n")
        sys.exit(1)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_yaml_min(path: Path) -> dict:
    """Tiny YAML reader for reviewers.yml (no external dependency).

    Only supports the subset this repo uses: scalars, nested maps, and
    simple '- item' lists under a key. Returns a dict. On parse trouble,
    returns an empty dict and logs to stderr."""
    if not path.exists():
        return {}
    try:
        out: dict = {}
        stack = [(0, out)]
        current_list: list | None = None
        last_key: str | None = None
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            line = raw.strip()
            # pop to matching indent
            while stack and stack[-1][0] > indent:
                stack.pop()
                current_list = None
            parent_indent, container = stack[-1]
            if line.startswith("- ") and isinstance(container, dict) and last_key:
                lst = container.setdefault(last_key, [])
                lst.append(line[2:].strip().strip('"'))
                current_list = lst
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if value == "":
                    new_map: dict = {}
                    container[key] = new_map
                    stack.append((indent + 2, new_map))
                    last_key = None
                elif value == "[]":
                    container[key] = []
                    last_key = key
                else:
                    # coerce obvious types
                    if value.lower() == "true":
                        container[key] = True
                    elif value.lower() == "false":
                        container[key] = False
                    elif value.isdigit():
                        container[key] = int(value)
                    else:
                        container[key] = value.strip('"')
                    last_key = key
        return out
    except Exception as exc:  # pragma: no cover - best-effort parser
        sys.stderr.write(f"test-writer: reviewers.yml parse warning: {exc}\n")
        return {}


def _detect_unreal() -> dict | None:
    """Detect Unreal Engine projects (*.uproject at root or one level down).

    Distinguishes three sub-cases the test agent must surface to the user:
    - Automation tests found (`IMPLEMENT_SIMPLE_AUTOMATION_TEST(...)` in source).
    - LLTest found (a `LowLevelTests/` directory or a `.Target.cs` with
      `LaunchType.Program`).
    - Neither — test agent must ask the user which framework to use before
      writing tests.

    Mutation testing is reported as disabled for UE per reviewers.yml
    `per_language.cpp-unreal.mutation_enabled: false`.
    """
    pr = project_root()
    uprojects = list(pr.glob("*.uproject")) + list(pr.glob("*/*.uproject"))
    if not uprojects:
        return None

    uproject = uprojects[0]
    root = uproject.parent

    # Grep for Automation macros inside the Source tree.
    automation_hits = 0
    lltest_seen = False
    source_dir = root / "Source"
    if source_dir.exists():
        for p in source_dir.rglob("*.cpp"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "IMPLEMENT_SIMPLE_AUTOMATION_TEST" in text \
               or "IMPLEMENT_COMPLEX_AUTOMATION_TEST" in text \
               or "IMPLEMENT_CUSTOM_SIMPLE_AUTOMATION_TEST" in text:
                automation_hits += 1
            if automation_hits > 5:
                break
        for tcs in source_dir.rglob("*.Target.cs"):
            try:
                t = tcs.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "LaunchType.Program" in t and "LowLevelTests" in t:
                lltest_seen = True
                break
    if (root / "LowLevelTests").exists():
        lltest_seen = True

    sub_kind = []
    if automation_hits > 0:
        sub_kind.append("automation")
    if lltest_seen:
        sub_kind.append("lltest")
    if not sub_kind:
        sub_kind = ["unknown"]

    return {
        "detected_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "language":      "cpp-unreal",
        "framework":     "ue-automation" if "automation" in sub_kind else (
                         "lltest" if "lltest" in sub_kind else "unreal-unknown"),
        "framework_variants": sub_kind,  # {automation, lltest, unknown}
        "mutation_tool":  None,
        "mutation_enabled": False,
        "mutation_reason": "UBT + mull are not compatible; mutation testing "
                           "is disabled for UE projects.",
        "test_glob":      "Source/**/*Tests/**/*.cpp",
        "run_command":    "UnrealEditor-Cmd.exe <uproject> -ExecCmds=\"Automation RunTests <FilterName>; Quit\" -Unattended -NoPause",
        "mutation_cmd":   None,
        "uproject":       str(uproject.relative_to(pr)),
        "fallback":       True,
    }


def detect_framework_if_missing() -> dict:
    """If test-framework.json is missing, produce a best-effort guess so the
    skill can still return a useful report. The test agent is expected to
    generate this file properly; this is only a fallback."""
    pr = project_root()
    # UE check comes first: a project may also have a CMakeLists.txt inside
    # Source/ for native LLTest, but the .uproject is authoritative.
    ue = _detect_unreal()
    if ue:
        return ue

    candidates = [
        ("pyproject.toml", "python",    "pytest",     "mutmut",        "mutmut run"),
        ("package.json",   "typescript","vitest",     "stryker",       "npx stryker run"),
        ("Cargo.toml",     "rust",      "cargo test", "cargo-mutants", "cargo mutants"),
        ("CMakeLists.txt", "cpp",       "ctest",      "mull",          "mull-runner"),
    ]
    for marker, lang, run, mtool, mcmd in candidates:
        if (pr / marker).exists():
            return {
                "detected_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "language":      lang,
                "framework":     run.split()[0],
                "mutation_tool": mtool,
                "test_glob":     "",
                "run_command":   run,
                "mutation_cmd":  mcmd,
                "fallback":      True,
            }
    return {}


def sample_existing_tests(module_paths: list[Path]) -> list[str]:
    """List paths of existing tests inside the affected modules. Uses ast-grep
    if available; falls back to glob heuristics."""
    found: list[str] = []
    patterns = [
        "**/test_*.py",
        "**/*_test.py",
        "**/*.test.ts",
        "**/*.test.tsx",
        "**/*.test.js",
        "**/*.spec.ts",
        "**/*.spec.js",
        "**/tests/**/*.rs",
        "**/test_*.cpp",
        "**/*Test.cpp",
        # UE Automation tests live under Source/<Module>Tests/ or
        # <Module>/Tests/. Match both to pick up whichever layout the team uses.
        "**/Tests/*.cpp",
        "**/*Tests/*.cpp",
        "**/LowLevelTests/**/*.cpp",
    ]
    for mp in module_paths:
        if not mp.exists():
            continue
        for pat in patterns:
            for f in mp.glob(pat):
                if f.is_file():
                    found.append(str(f.relative_to(project_root())))
    # dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for f in found:
        if f not in seen:
            out.append(f)
            seen.add(f)
    return out


def resolve_modules(names: list[str]) -> list[dict]:
    mods_doc = load_json(framework_root() / "index" / "modules.json")
    by_name = {m["name"]: m for m in mods_doc.get("modules", [])}
    out = []
    for n in names:
        if n in by_name:
            out.append(by_name[n])
        else:
            sys.stderr.write(f"test-writer: unknown module '{n}'\n")
    return out


def run_mutation(cmd: str, cwd: Path) -> tuple[int | None, str, str]:
    """Run the configured mutation command. Return (score, stdout, stderr).
    The score is extracted heuristically from the tool's output; if it cannot
    be parsed, returns (None, stdout, stderr)."""
    if not cmd:
        return None, "", "no mutation_cmd configured"
    parts = cmd.split()
    if not shutil.which(parts[0]):
        return None, "", f"mutation tool '{parts[0]}' not on PATH"
    try:
        proc = subprocess.run(
            parts,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        return None, exc.stdout or "", "timeout after 600s"
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    score = None
    for line in combined.splitlines():
        ll = line.lower()
        # crude score extraction; each tool uses its own wording
        if "mutation score" in ll or "score:" in ll or "mutants killed" in ll:
            for token in ll.replace(":", " ").replace("%", " ").split():
                try:
                    val = float(token)
                except ValueError:
                    continue
                if 0 <= val <= 100:
                    score = int(round(val))
                    break
            if score is not None:
                break
    return score, proc.stdout, proc.stderr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--modules", required=True,
                    help="comma-separated module names")
    ap.add_argument("--type", choices=["feature", "bug"], default="feature")
    args = ap.parse_args()

    spec_path = Path(args.spec)
    if not spec_path.exists():
        sys.stderr.write(f"test-writer: spec file not found: {spec_path}\n")
        return 1

    fw_index = framework_root() / "index" / "test-framework.json"
    if fw_index.exists():
        fw = load_json(fw_index)
    else:
        fw = detect_framework_if_missing()
        if not fw:
            sys.stderr.write(
                "test-writer: no test-framework.json and no project manifest "
                "recognised; run the test agent first\n"
            )
            return 1
        sys.stderr.write(
            "test-writer: test-framework.json missing; using fallback detection\n"
        )

    requested = [s.strip() for s in args.modules.split(",") if s.strip()]
    modules = resolve_modules(requested)
    if not modules:
        sys.stderr.write("test-writer: no valid modules resolved\n")
        return 1

    module_paths = [project_root() / m["path"] for m in modules]

    reviewers_cfg = load_yaml_min(framework_root() / "config" / "reviewers.yml")
    test_cfg = reviewers_cfg.get("test") or {}
    threshold = int(test_cfg.get("mutation_score_threshold", 80))

    # Per-language overrides (improvement 10). If the detected language has
    # mutation_enabled: false, skip the mutation run entirely and record the
    # reason so reviewers know the gate is intentionally off.
    per_lang = (test_cfg.get("per_language") or {}).get(fw.get("language", ""), {})
    mutation_enabled = per_lang.get("mutation_enabled", True) and (
        fw.get("mutation_enabled", True) is not False
    )
    mutation_reason = per_lang.get("reason") or fw.get("mutation_reason", "")

    existing = sample_existing_tests(module_paths)

    spec_text = spec_path.read_text(encoding="utf-8", errors="replace")

    # Acceptance-criterion extraction is lexical: count lines that look like
    # acceptance bullets. The test agent's LLM is expected to refine this,
    # but a skill-level estimate is still useful for the report.
    ac_lines = [
        ln for ln in spec_text.splitlines()
        if any(tag in ln.lower() for tag in ("acceptance", "ac:", "- [ ]", "- [x]"))
    ]
    ac_count = max(1, len(ac_lines))

    # The skill does not write test files itself — the test agent owns the
    # file edits. Report what the skill prepared so the agent can proceed.
    if mutation_enabled:
        score, stdout, stderr = run_mutation(fw.get("mutation_cmd", ""), project_root())
    else:
        score, stdout, stderr = None, "", f"mutation disabled: {mutation_reason}"

    report = {
        "framework":                   fw.get("framework", "unknown"),
        "language":                    fw.get("language", "unknown"),
        "mutation_tool":               fw.get("mutation_tool", "unknown"),
        "tests_written":               0,
        "existing_tests_sampled":      existing,
        "acceptance_criteria_covered": f"0/{ac_count}",
        "mutation_score":              score,
        "mutation_threshold":          threshold,
        "missing_coverage":            [] if score is None or score >= threshold
                                       else ["mutation_score_below_threshold"],
        "ready_for_review":            False,
        "type":                        args.type,
        "modules":                     [m["name"] for m in modules],
        "spec":                        str(spec_path),
        "notes": [
            "test-writer prepares inputs only; the test agent edits files",
            stderr.strip()[:500] if stderr else "",
        ],
    }
    if os.environ.get("TEST_WRITER_DEBUG"):
        report["mutation_stdout_tail"] = stdout[-2000:]

    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
