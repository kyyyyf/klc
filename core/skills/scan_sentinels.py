#!/usr/bin/env python3
"""scan_sentinels.py — detect high-risk patterns in diffs.

Phase 3a: scans diff for sentinel patterns from config/sentinels.yml.
Sentinel matches force-escalate to CRITICAL and block merge regardless
of tier thresholds.

Usage:
    scan_sentinels.py --diff <path> [--format json|table]

Output (JSON):
    {
      "matches": [
        {
          "sentinel_id": "eval-exec",
          "file": "src/api/eval_endpoint.py",
          "line": 42,
          "matched_text": "result = eval(request.GET['expr'])",
          "description": "eval() on untrusted input → arbitrary code execution",
          "severity_override": "CRITICAL"
        }
      ],
      "summary": {"total": 1, "critical": 1, "high": 0}
    }

When matches exist, review.py injects synthetic CRITICAL findings and
forces verdict to CHANGES REQUESTED.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.shared.paths import framework_root  # noqa: E402
from core.shared.yaml import parse as load_yaml  # noqa: E402


def load_sentinels_config() -> dict:
    """Load config/sentinels.yml."""
    path = framework_root() / "config" / "sentinels.yml"
    if not path.exists():
        sys.stderr.write(f"scan_sentinels: {path} not found\n")
        sys.exit(1)
    return load_yaml(path)


def parse_diff_hunks(diff_path: Path) -> list[dict]:
    """Parse unified diff into hunks with file, line numbers, and added lines.
    Returns list of {file, line_start, lines: [str]}.
    """
    if not diff_path.exists():
        return []
    hunks: list[dict] = []
    current_file: str | None = None
    current_line: int = 0
    current_lines: list[str] = []

    try:
        for line in diff_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("+++ b/"):
                # New file
                if current_file and current_lines:
                    hunks.append({
                        "file": current_file,
                        "line_start": current_line,
                        "lines": current_lines,
                    })
                current_file = line[6:]  # strip "+++ b/"
                current_lines = []
                current_line = 0
            elif line.startswith("@@ "):
                # Hunk header: @@ -old_start,old_count +new_start,new_count @@
                # Extract new_start
                match = re.search(r'\+(\d+)', line)
                if match:
                    current_line = int(match.group(1))
            elif line.startswith("+") and not line.startswith("+++"):
                # Added line
                current_lines.append(line[1:])  # strip leading "+"
            elif not line.startswith("-"):
                # Context line (no change) or blank
                current_line += 1

        # Flush last hunk
        if current_file and current_lines:
            hunks.append({
                "file": current_file,
                "line_start": current_line,
                "lines": current_lines,
            })
    except OSError:
        pass

    return hunks


def file_extension(file_path: str) -> str:
    """Return file extension without dot (e.g., 'py', 'js')."""
    return Path(file_path).suffix.lstrip(".")


def scan_hunk(hunk: dict, sentinels: list[dict]) -> list[dict]:
    """Scan a single hunk for sentinel matches. Returns list of matches."""
    matches: list[dict] = []
    file_ext = file_extension(hunk["file"])

    for idx, line_text in enumerate(hunk["lines"]):
        line_num = hunk["line_start"] + idx
        for sentinel in sentinels:
            # Language filter
            allowed_langs = sentinel.get("languages", [])
            if allowed_langs and file_ext not in allowed_langs:
                continue

            # Pattern match
            pattern = sentinel.get("pattern", "")
            if not pattern:
                continue

            try:
                if re.search(pattern, line_text):
                    matches.append({
                        "sentinel_id": sentinel.get("id", "unknown"),
                        "file": hunk["file"],
                        "line": line_num,
                        "matched_text": line_text.strip(),
                        "description": sentinel.get("description", ""),
                        "severity_override": sentinel.get("severity_override", "CRITICAL"),
                    })
            except re.error:
                # Invalid regex in config — skip
                pass

    return matches


def scan_diff(diff_path: Path, sentinels_config: dict) -> dict:
    """Scan all hunks in diff for sentinels. Returns result dict."""
    hunks = parse_diff_hunks(diff_path)
    sentinels = sentinels_config.get("sentinels", [])
    all_matches: list[dict] = []

    for hunk in hunks:
        matches = scan_hunk(hunk, sentinels)
        all_matches.extend(matches)

    # Summary by severity
    summary = {"total": len(all_matches), "critical": 0, "high": 0, "medium": 0, "low": 0}
    for m in all_matches:
        sev = m.get("severity_override", "CRITICAL").lower()
        summary[sev] = summary.get(sev, 0) + 1

    return {"matches": all_matches, "summary": summary}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", required=True, help="Path to unified diff")
    ap.add_argument("--format", choices=["json", "table"], default="json")
    args = ap.parse_args()

    diff_path = Path(args.diff)
    if not diff_path.exists():
        sys.stderr.write(f"scan_sentinels: diff not found: {diff_path}\n")
        return 1

    sentinels_config = load_sentinels_config()
    result = scan_diff(diff_path, sentinels_config)

    if args.format == "json":
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        # Table format
        if not result["matches"]:
            print("No sentinel patterns detected.")
        else:
            print(f"{'Sentinel ID':<20} {'File:Line':<40} {'Severity':<10}")
            print("-" * 80)
            for m in result["matches"]:
                loc = f"{m['file']}:{m['line']}"
                print(f"{m['sentinel_id']:<20} {loc:<40} {m['severity_override']:<10}")
                print(f"  → {m['matched_text'][:60]}")
            print(f"\nTotal matches: {result['summary']['total']}")
            print(f"  CRITICAL: {result['summary']['critical']}")
            print(f"  HIGH: {result['summary']['high']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
