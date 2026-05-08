#!/usr/bin/env bash
# review-runner-claude.sh — fulfil a sub-agent job card by invoking the
# Claude Code CLI in non-interactive mode.
#
# Usage:
#   review-runner-claude.sh <job-card-path> <partial-output-path>
#
# Contract with review.sh:
#   - `review.sh --diff ... --spec ...` is launched with
#     RUN_LOCAL_SUBAGENTS=1 and REVIEW_RUNNER=<this script>.
#   - review.sh spawns one process per reviewer, passing the job-card path
#     and target partial file as arguments.
#   - This script reads the job card (which names the prompt file + inputs),
#     invokes `claude --print` with the concatenated prompt, and writes the
#     answer to the partial file.
#   - The script MUST NOT print anything to stdout besides fatal errors —
#     review.sh aggregates partials from disk, not from stdout.
#
# The runner assumes the `claude` CLI is on PATH. Override with the
# CLAUDE_CLI env var if you need a specific binary or wrapper:
#   CLAUDE_CLI=~/bin/claude-sonnet ./review-runner-claude.sh ...
#
# All text is English.

set -uo pipefail

JOB_CARD="${1:-}"
PARTIAL_OUT="${2:-}"

if [ -z "$JOB_CARD" ] || [ -z "$PARTIAL_OUT" ]; then
  echo "usage: $0 <job-card> <partial-output>" >&2
  exit 2
fi
[ -f "$JOB_CARD" ] || { echo "review-runner: job card not found: $JOB_CARD" >&2; exit 2; }

CLAUDE_BIN="${CLAUDE_CLI:-claude}"
if ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  echo "review-runner: '$CLAUDE_BIN' not on PATH — install Claude Code CLI or set CLAUDE_CLI" >&2
  exit 2
fi

# Parse job card for the referenced input paths. The cards produced by
# review.sh look like:
#
#   Prompt file: framework/core/agents/review/<name>.md
#   Inputs:
#   - diff:              <path>
#   - spec:              <path>
#   - claude_md_context: <path>
#   Write the sub-agent's output to: <path>

PROMPT_FILE="$(grep -m1 '^Prompt file:' "$JOB_CARD" | awk '{print $3}')"
DIFF_FILE="$(grep -m1 '^- diff:' "$JOB_CARD" | awk '{print $3}')"
SPEC_FILE="$(grep -m1 '^- spec:' "$JOB_CARD" | awk '{print $3}')"
CTX_FILE="$(grep -m1 '^- claude_md_context:' "$JOB_CARD" | awk '{print $3}')"

for f in "$PROMPT_FILE" "$DIFF_FILE" "$SPEC_FILE" "$CTX_FILE"; do
  if [ ! -f "$f" ]; then
    echo "review-runner: input file missing: $f" >&2
    exit 2
  fi
done

# Compose the full prompt: system instruction = the reviewer role file;
# user message = concatenated diff + spec + claude_md_context, with clear
# section markers so the LLM can address each.
WORK_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t review-runner)"
trap 'rm -rf "$WORK_DIR"' EXIT

PROMPT="$WORK_DIR/prompt.md"
{
  cat "$PROMPT_FILE"
  echo
  echo "---"
  echo
  echo "## Inputs for this review"
  echo
  echo "### diff"
  echo '```diff'
  cat "$DIFF_FILE"
  echo '```'
  echo
  echo "### spec"
  echo '```'
  cat "$SPEC_FILE"
  echo '```'
  echo
  echo "### claude_md_context"
  echo '```'
  cat "$CTX_FILE"
  echo '```'
  echo
  echo "---"
  echo
  echo "Produce the reviewer's markdown output and trailer exactly as the"
  echo "prompt file specifies. Do not emit anything else."
} > "$PROMPT"

# Invoke Claude Code in non-interactive mode. `--print` streams the
# assistant message to stdout and exits; no tools run unless the prompt
# asks for them, and this prompt is pure analysis — no tool use required.
#
# If your installation expects `-p`/`--prompt` instead of `--print`,
# override with CLAUDE_ARGS env var.
CLAUDE_ARGS="${CLAUDE_ARGS:---print --no-conversation}"
if ! "$CLAUDE_BIN" $CLAUDE_ARGS < "$PROMPT" > "$PARTIAL_OUT" 2> "$WORK_DIR/err"; then
  echo "review-runner: '$CLAUDE_BIN' failed (exit $?). stderr:" >&2
  cat "$WORK_DIR/err" >&2
  # Synthesize a CRITICAL partial so review.sh aggregation still runs.
  {
    echo "## Reviewer crashed"
    echo
    echo "### [CRITICAL] review-runner-claude.sh failure"
    echo "**Issue**: \`$CLAUDE_BIN\` did not complete successfully for \`$PROMPT_FILE\`."
    echo "**Fix**: inspect the stderr above, re-run manually, or switch REVIEW_RUNNER to a different backend."
    echo
    echo "ISSUES_TOTAL=1 ISSUES_BLOCKING=1"
  } > "$PARTIAL_OUT"
  exit 1
fi

exit 0
