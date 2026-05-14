#!/usr/bin/env python3
"""validate_syntax.py — generic asset validator.

Port of validate-syntax.sh. Baseline example hook invoked via
core/skills/run-hook.py. Real projects should replace it with a
richer validator (spectral / tflint / dbt parse / ...).

Contract: argv[1] = file with changed paths (one per line),
          argv[2] = output JSON path.

Rules: JSON and YAML files must parse.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


# Paths in the files-list are relative to the project root (not the
# framework root). Honour $PROJECT_ROOT so the hook works regardless of
# where the framework checkout sits.
REPO_ROOT = Path(os.environ.get("PROJECT_ROOT") or
                  Path(__file__).resolve().parent.parent.parent.parent)


def _check_json(path: Path) -> str | None:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return None
    except json.JSONDecodeError as e:
        return f"invalid JSON: {e}"
    except OSError as e:
        return f"unreadable: {e}"


def _check_yaml(path: Path) -> tuple[str | None, str | None]:
    """Try PyYAML if installed, else our minimal parser. Returns
    (finding, tool_missing_note)."""
    text: str
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return (f"unreadable: {e}", None)
    try:
        import yaml  # type: ignore
    except ImportError:
        # Fall back to the bundled minimal parser; best-effort.
        sys.path.insert(0, str(REPO_ROOT / "core" / "skills"))
        try:
            from _yaml import parse as _yp  # noqa: E402
            _yp(text)
            return (None, None)
        except Exception as e:  # pragma: no cover — narrow case
            return (f"invalid YAML: {e}", "pyyaml")
    try:
        yaml.safe_load(text)
        return (None, None)
    except yaml.YAMLError as e:
        return (f"invalid YAML: {str(e).replace(chr(10), ' ')}", None)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: validate_syntax.py <files-list> <out-json>\n")
        return 2

    files_in, out_json = argv

    findings: list[dict] = []
    skipped:  list[dict] = []
    tools_missing: list[str] = []
    validated = 0

    try:
        lines = Path(files_in).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        sys.stderr.write(f"validate-syntax: cannot read {files_in}: {e}\n")
        return 2

    for rel in lines:
        rel = rel.strip()
        if not rel:
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            skipped.append({"file": rel, "reason": "missing on disk"})
            continue

        suffix = path.suffix.lower()
        if suffix == ".json":
            validated += 1
            msg = _check_json(path)
            if msg:
                findings.append({
                    "file": rel, "line": None, "severity": "CRITICAL",
                    "tool": "json", "message": msg,
                })
        elif suffix in (".yml", ".yaml"):
            validated += 1
            msg, tool_missing = _check_yaml(path)
            if msg:
                findings.append({
                    "file": rel, "line": None, "severity": "CRITICAL",
                    "tool": "pyyaml", "message": msg,
                })
            if tool_missing and tool_missing not in tools_missing:
                tools_missing.append(tool_missing)
        else:
            skipped.append({"file": rel,
                             "reason": "no validator registered for this extension"})

    Path(out_json).write_text(json.dumps({
        "validated_files": validated,
        "findings":        findings,
        "skipped":         skipped,
        "tools_missing":   tools_missing,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
