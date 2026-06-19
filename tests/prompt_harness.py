from __future__ import annotations
import re

PLACEHOLDER_TOKENS = ("TODO", "TBD", "write tests", "<...>", "...")
REQUIRED_STEP_FIELDS = ("Goal", "VERIFY", "COMMIT", "Affected")


def parse_impl_plan_steps(text: str) -> list[dict]:
    """Split an impl-plan markdown into steps keyed by '## step-N — title'."""
    pattern = re.compile(r"(?m)^##\s+(step-\d+)\s*[—-]\s*(.+)$")
    matches = list(pattern.finditer(text))
    steps = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        steps.append({
            "id": m.group(1),
            "title": m.group(2).strip(),
            "body": text[start:end],
        })
    return steps


def impl_plan_violations(text: str) -> list[str]:
    """Return human-readable violations in an impl-plan."""
    steps = parse_impl_plan_steps(text)
    if not steps:
        return ["no steps found in impl-plan"]

    violations: list[str] = []
    for step in steps:
        body = step["body"]
        sid = step["id"]

        for field in REQUIRED_STEP_FIELDS:
            pattern = re.compile(
                rf"(?im)(?:\*\*{re.escape(field)}\b|\b{re.escape(field)}:)"
            )
            if not pattern.search(body):
                violations.append(f"{sid}: missing required field '{field}'")

        for token in PLACEHOLDER_TOKENS:
            if token == "...":
                if re.search(r"(?<![\w.])\.\.\.(?![\w.])", body):
                    violations.append(f"{sid}: contains placeholder token '...'")
            else:
                if token in body:
                    violations.append(f"{sid}: contains placeholder token '{token}'")

        if re.search(r"```[a-z]*\s*```", body):
            violations.append(f"{sid}: contains empty code fence")

    return violations


def has_min_approaches(text: str, n: int = 2) -> bool:
    """True iff the text proposes >= n distinct approaches."""
    line_pattern = re.compile(
        r"(?im)^(\s*(?:[-*]|\d+\.|#{2,3})\s*(?:option|approach|approach\s+\d|alternative)\b[^\n]*)"
    )
    matches = line_pattern.findall(text)
    normalized = {m.strip().lower() for m in matches}
    return len(normalized) >= n
