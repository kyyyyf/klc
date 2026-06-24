#!/usr/bin/env python3
"""findings.py — structured finding schema and aggregation helpers for review pipeline.

Phase 1.2 of the review overhaul plan. Provides:
- Finding dataclass (JSON-serializable)
- aggregate(partials_dir) → list[Finding]
- dedupe(findings, line_window) → list[Finding]
- sort_for_report(findings) → list[Finding]

Used by scripts/review.py (aggregator) and core/agents/review/*.md output spec.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Finding:
    """Structured code review finding.

    Fields match Phase 1.2 JSON schema. `issue_id` is computed from
    (rule_name, file, line) to enable stable cross-run deduplication.
    """
    rule_name: str
    severity: str  # CRITICAL | HIGH | MEDIUM | LOW | INFO
    file: str
    line: int
    title: str
    body: str
    fix: Optional[str]
    reviewer: str
    issue_id: str = field(init=False, default="")

    def __post_init__(self):
        """Compute deterministic issue_id."""
        if not self.issue_id:  # allow explicit override for testing
            payload = f"{self.rule_name}|{self.file}|{self.line}"
            self.issue_id = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def from_dict(cls, d: dict) -> Finding:
        """Deserialize from JSON dict."""
        # issue_id may or may not be in the dict; __post_init__ recomputes if missing
        return cls(
            rule_name=d["rule_name"],
            severity=d["severity"],
            file=d["file"],
            line=int(d["line"]),
            title=d["title"],
            body=d["body"],
            fix=d.get("fix"),
            reviewer=d["reviewer"],
        )

    def to_dict(self) -> dict:
        """Serialize to JSON dict."""
        return asdict(self)


def aggregate(partials_dir: Path) -> list[Finding]:
    """Load all findings.json from partials_dir/**/findings.json.

    Each reviewer's partial directory contains findings.json. The sentinel
    pass (Phase 3a) also writes partials_dir/sentinels/findings.json.

    Returns deduplicated, unsorted list. Caller should sort via
    sort_for_report() before rendering.

    Warnings on malformed JSON are printed to stderr; malformed entries are
    skipped, not fatal.
    """
    findings: list[Finding] = []

    if not partials_dir.exists():
        return findings

    for findings_file in partials_dir.rglob("findings.json"):
        try:
            with findings_file.open("r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, list):
                print(f"WARN: {findings_file} is not a JSON list; skipping", file=__import__("sys").stderr)
                continue

            for item in data:
                try:
                    findings.append(Finding.from_dict(item))
                except (KeyError, TypeError, ValueError) as e:
                    print(f"WARN: {findings_file} has malformed entry: {e}", file=__import__("sys").stderr)

        except (OSError, json.JSONDecodeError) as e:
            print(f"WARN: cannot read {findings_file}: {e}", file=__import__("sys").stderr)

    return findings


def dedupe(findings: list[Finding], line_window: int = 3) -> list[Finding]:
    """Collapse findings from multiple reviewers on the same location.

    Two findings match if:
      - Same file
      - Lines within `line_window` of each other
      - Same rule_name

    When a match occurs, keep the first finding and append all other
    reviewers to a comma-separated `reviewer` field. The `body` is
    concatenated with "---" separators.

    Returns a new list; does not mutate input.
    """
    if not findings:
        return []

    # Group by (file, rule_name) for fast lookup
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        key = (f.file, f.rule_name)
        groups.setdefault(key, []).append(f)

    result: list[Finding] = []
    seen: set[str] = set()  # issue_id's already merged

    for (file, rule_name), group in groups.items():
        # Sort by line to make window logic deterministic
        group.sort(key=lambda x: x.line)

        for candidate in group:
            if candidate.issue_id in seen:
                continue

            # Find all findings within line_window of this candidate
            matches = [candidate]
            for other in group:
                if other.issue_id in seen or other is candidate:
                    continue
                if abs(other.line - candidate.line) <= line_window:
                    matches.append(other)
                    seen.add(other.issue_id)

            # Merge if multiple matches
            if len(matches) == 1:
                result.append(candidate)
                seen.add(candidate.issue_id)
            else:
                # Build merged finding
                reviewers = ", ".join(sorted(set(m.reviewer for m in matches)))
                bodies = [f"[{m.reviewer}] {m.body}" for m in matches]
                merged_body = "\n\n---\n\n".join(bodies)

                # Use first match as template, override multi-reviewer fields
                merged = Finding(
                    rule_name=candidate.rule_name,
                    severity=candidate.severity,  # all should be same by rule_name
                    file=candidate.file,
                    line=candidate.line,  # earliest line
                    title=candidate.title,
                    body=merged_body,
                    fix=candidate.fix,  # first fix wins
                    reviewer=reviewers,
                )
                result.append(merged)
                seen.add(merged.issue_id)

    return result


def sort_for_report(findings: list[Finding]) -> list[Finding]:
    """Sort findings for diff-friendly, human-readable reports.

    Order:
      1. File (lexicographic)
      2. Line (numeric ascending)
      3. Severity (CRITICAL > HIGH > MEDIUM > LOW > INFO)

    Returns a new sorted list; does not mutate input.
    """
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

    def sort_key(f: Finding) -> tuple:
        return (f.file, f.line, severity_order.get(f.severity, 99))

    return sorted(findings, key=sort_key)


def main():
    """CLI for testing / debugging. Usage: findings.py <partials-dir>"""
    import sys
    if len(sys.argv) < 2:
        print("Usage: findings.py <partials-dir>", file=sys.stderr)
        sys.exit(1)

    partials = Path(sys.argv[1])
    findings_list = aggregate(partials)
    findings_list = dedupe(findings_list)
    findings_list = sort_for_report(findings_list)

    print(json.dumps([f.to_dict() for f in findings_list], indent=2))


if __name__ == "__main__":
    main()
