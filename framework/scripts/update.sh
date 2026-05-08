#!/usr/bin/env bash
# update.sh — incremental refresh. Cron-friendly.
#
# Calls the periodic agent (LLM) with enough context to decide what to
# refresh. Prepares the diff inputs as files so the agent does not have to
# call git itself. All text is English.

set -uo pipefail

FRAMEWORK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$FRAMEWORK_ROOT/.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p "$FRAMEWORK_ROOT/logs" "$FRAMEWORK_ROOT/index"

log()  { echo "[update] $*"; }
die()  { echo "[update][err] $*" >&2; exit 1; }

[ -f "$FRAMEWORK_ROOT/.last-run" ] || \
  die "framework/.last-run missing; run ./framework/scripts/init.sh first"

LAST="$(cat "$FRAMEWORK_ROOT/.last-run" | tr -d '[:space:]')"
HEAD_SHA="$(git rev-parse HEAD)"

if [ "$LAST" = "$HEAD_SHA" ]; then
  echo "PERIODIC_NOOP"
  exit 0
fi

log "Change window: $LAST..$HEAD_SHA"

# Persist the diff for the agent to consume.
git diff --name-only --diff-filter=ACMRD "$LAST" "$HEAD_SHA" \
  > "$FRAMEWORK_ROOT/index/changed-files.txt" \
  || die "git diff failed"

log "Changed files -> framework/index/changed-files.txt"
log "Now run the periodic agent inside Claude Code:"
cat <<EOF
  Prompt:
    Read framework/core/agents/periodic.md and execute it.
    Inputs:
      - framework/.last-run (SHA: $LAST)
      - framework/index/changed-files.txt
      - framework/index/inventory.json
      - framework/index/modules.json
    Current HEAD: $HEAD_SHA
    On success, print PERIODIC_OK and overwrite framework/.last-run with $HEAD_SHA.
    On no-op, print PERIODIC_NOOP.
EOF

log "After the agent finishes:"
log "  echo $HEAD_SHA > framework/.last-run"
