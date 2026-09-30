## The one finding shape

Return ONE JSON object — your verdict, the last fenced block of your verdict file:

```json
{"findings": [{"id": "F-1", "rule_name": "RULE", "severity": "HIGH",
  "file": "spec.md", "line": 88, "title": "AC-3 has no observable outcome",
  "body": "AC-3 says the gate works correctly; nothing checkable follows.",
  "fix": "Name the rejected input and the exit code.", "ref": "AC-3"}],
 "decisions_to_confirm": [{"id": "D-1", "topic": "TOPIC", "question": "Is X in scope?",
  "recommended": "No: X belongs to another ticket.", "rationale": "", "ref": "AC-7"}]}
```

RULE is one value of your rule_name list below. With no such list,
`rule_name` is a lower-case kebab-case slug (e.g. `missing-test`, never
snake_case or `RULE` itself). TOPIC is one of your topics; none means
`decisions_to_confirm` must be `[]`.

- `id` unique in the object; `severity` is CRITICAL, HIGH, MEDIUM, LOW or INFO.
- `file` is the file the finding is about (a code file, else your artefact); `line`
  is its 1-based line, or null; never 0.
- `title` is one line; `body` is not empty; `fix` is a string or null.
- Do not add `reviewer` or `kind`: intake stamps them. `recommended` is required.
- Empty `findings` and `decisions_to_confirm` is a valid verdict.
