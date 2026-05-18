#!/usr/bin/env python3
"""validate_cbp.py — UE profile asset validator.

Port of validate-cbp.sh. Same contract:
  argv[1] = file with changed paths (one per line)
  argv[2] = output JSON path

See the original for the caveats about what this hook can / cannot do.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


REPO_ROOT = Path(os.environ.get("PROJECT_ROOT",
                                 Path(__file__).resolve().parent.parent.parent.parent))
INVENTORY = REPO_ROOT / ".klc" / "index" / "inventory.json"

_INI_SECTION_RE = re.compile(
    r"^\[/Script/([A-Za-z_]+)\.([A-Za-z_][A-Za-z_0-9]*)\]"
)


def _load_class_names() -> set[str]:
    if not INVENTORY.exists():
        return set()
    try:
        data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    out: set[str] = set()
    items = (data.get("symbols") or {}).get("cpp", {}).get("items") or []
    for item in items:
        kind = item.get("kind") or ""
        if re.search(r"UCLASS|class", kind):
            name = item.get("name")
            if name:
                out.add(name)
    return out


def _class_matches(cls: str, known: set[str]) -> bool:
    """UE conventionally strips a one-letter prefix (U/A/F/E); try
    both the literal name and any stripped-prefix variant."""
    if cls in known:
        return True
    for prefix in "AUFE":
        candidate = prefix + cls
        if candidate in known:
            return True
    # also: the ini may carry a prefix that was stripped in the inventory
    if len(cls) > 1 and cls[0] in "AUFE" and cls[1:] in known:
        return True
    return False


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: validate_cbp.py <files-list> <out-json>\n")
        return 2

    files_in, out_json = argv
    try:
        lines = Path(files_in).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        sys.stderr.write(f"validate-cbp: cannot read {files_in}: {e}\n")
        return 2

    findings: list[dict] = []
    skipped:  list[dict] = []
    tools_missing: list[str] = []
    validated = 0

    # Rule 2: remind on every CBP_*.uasset change.
    for rel in lines:
        rel = rel.strip()
        if not rel:
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            skipped.append({"file": rel, "reason": "missing on disk"})
            continue
        if not (Path(rel).name.startswith("CBP_") and rel.endswith(".uasset")):
            continue
        validated += 1
        findings.append({
            "file": rel, "line": None, "severity": "INFO", "tool": "validate-cbp",
            "message": (
                "CBP asset changed. Open it in the editor and confirm the "
                "Parts list; for GAS vehicles both "
                "CrushBehaviorPart_GASAttributeController_ForwardMaxSpeed and "
                "CrushBehaviorPart_GASAttributeController_AuxEnginePowerScale "
                "must be present (see CRUSH-3020)."
            ),
        })

    # Rule 1: stale [/Script/Module.ClassName] references in .ini.
    known = _load_class_names()
    if known:
        for rel in lines:
            rel = rel.strip()
            if not rel or not rel.endswith(".ini"):
                continue
            path = REPO_ROOT / rel
            if not path.is_file():
                continue
            validated += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line_num, line in enumerate(text.splitlines(), start=1):
                m = _INI_SECTION_RE.match(line.strip())
                if not m:
                    continue
                cls = m.group(2)
                if not _class_matches(cls, known):
                    findings.append({
                        "file": rel, "line": line_num, "severity": "MEDIUM",
                        "tool": "validate-cbp",
                        "message": (
                            f"ini section refers to class {cls!r} that is "
                            "not in the inventory; the class may have been "
                            "renamed or removed."
                        ),
                    })

    Path(out_json).write_text(json.dumps({
        "validated_files": validated,
        "findings":        findings,
        "skipped":         skipped,
        "tools_missing":   tools_missing,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
