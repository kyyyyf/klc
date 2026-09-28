# External Review Agent

## Role
Send the same diff/spec/CLAUDE.md bundle that internal reviewers saw to
an external LLM provider and merge its verdict into the final report.
Provider-agnostic; pick one of openai / anthropic / google / ollama.

## Inputs (from the review orchestrator)
- `diff`              — unified diff.
- `spec`              — feature spec or bug description.
- `claude_md_context` — root + module `CLAUDE.md` bundle.

## Configuration
Read `config/reviewers.yml` → `external_reviewer` (`enabled`, `min_track`,
`focus`, `output_format`, `report_path`). The provider and model resolve
through `config/models.yml`'s `review-external` pseudo-phase
(`core/skills/review_plan.py::external_route`) unless the block sets its
own `provider`/`model` (legacy override, still honoured).

## Hard rules
- If `enabled: false` and the orchestrator did not pass `--external`, exit
  silently with status 0. Print nothing.
- Never hardcode API keys or tokens. For `openai`/`google` always read the
  key from `os.environ[api_key_env]`; if unset, log a warning and exit 0
  (so the internal review still counts). The `anthropic` route reads no
  key — it shells out to the `claude` CLI.
- Never include secrets, `.env` contents, or local file paths outside the
  repo in the prompt.
- Timeout the provider call at 120 s; on timeout log a warning and exit 0.

## Steps

### 1. Build the prompt
Render `core/templates/external-review-prompt.j2` with:
- `spec`               — from input
- `diff`               — from input
- `claude_md_context`  — from input
- `focus_areas`        — list from `external_reviewer.focus`

Keep the rendered string in memory. Do **not** write it to disk (may
contain source under review).

### 2. Dispatch by provider

#### openai
- Endpoint: `https://api.openai.com/v1/chat/completions`
- Auth: `Authorization: Bearer $OPENAI_API_KEY` (env var name from config).
- Payload:
  ```json
  {
    "model": "<model>",
    "messages": [
      {"role": "system", "content": "You are a senior code reviewer."},
      {"role": "user",   "content": "<rendered prompt>"}
    ],
    "temperature": 0.2
  }
  ```
- Response text: `choices[0].message.content`.

#### anthropic
Run the rendered prompt through the `claude` CLI on the resolved model
(`core/skills/runner.py`'s anthropic dispatcher) — no API key read.

#### google (Gemini)
- Endpoint:
  `https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent?key=$GOOGLE_API_KEY`
- Payload:
  ```json
  {"contents":[{"parts":[{"text":"<rendered prompt>"}]}]}
  ```
- Response text: `candidates[0].content.parts[0].text`.

#### ollama
- Endpoint: `http://localhost:11434/v1/chat/completions`
- No API key required; ignore `api_key_env`.
- Same payload shape as the openai provider.

### 3. Parse and count
- Extract issues from the provider's markdown using the same convention as
  internal sub-agents (`### [SEVERITY] ...`).
- Count total issues and blocking issues (severity in
  `review.blocking_severity`).

### 4. Save the report
- Resolve `report_path`: substitute `{timestamp}` with
  `YYYY-MM-DD-HH-MM` (UTC).
- Write the provider's markdown verbatim to that path (create directories
  as needed).

### 5. Return result
Stdout must end with a single JSON line that the orchestrator merges:

```json
{
  "provider": "<resolved>",
  "model":    "<resolved>",
  "total":    7,
  "blocking": 2,
  "notes":    "<one-sentence summary>",
  "path":     ".klc/reports/external-review-2026-05-04-10-15.md"
}
```

Final signal line:

```
EXTERNAL_REVIEW_OK
```

or, on skip:

```
EXTERNAL_REVIEW_SKIPPED <reason>
```

{{include:completion-signal}}
