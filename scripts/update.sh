#!/usr/bin/env bash
# update.sh — incremental refresh. Cron-friendly.
#
# Calls the periodic agent (LLM) with enough context to decide what to
# refresh. Prepares the diff inputs as files so the agent does not have to
# call git itself.
#
# Per-project state lives in $PROJECT_ROOT/.klc/ (see MIGRATION.md).

set -uo pipefail

FRAMEWORK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$FRAMEWORK_ROOT/.." && pwd)}"
cd "$PROJECT_ROOT"

KLC_DIR="$PROJECT_ROOT/.klc"
INDEX_DIR="$KLC_DIR/index"
LOGS_DIR="$KLC_DIR/logs"
mkdir -p "$INDEX_DIR" "$LOGS_DIR"

log()  { echo "[update] $*"; }
die()  { echo "[update][err] $*" >&2; exit 1; }

[ -f "$INDEX_DIR/.last-run" ] || \
  die ".klc/index/.last-run missing; run .klc/bin/klc init.sh first"

LAST="$(tr -d '[:space:]' < "$INDEX_DIR/.last-run")"
HEAD_SHA="$(git rev-parse HEAD)"

if [ "$LAST" = "$HEAD_SHA" ]; then
  echo "PERIODIC_NOOP"
  exit 0
fi

log "Change window: $LAST..$HEAD_SHA"

# Persist the diff for the agent to consume.
git diff --name-only --diff-filter=ACMRD "$LAST" "$HEAD_SHA" \
  > "$INDEX_DIR/changed-files.txt" \
  || die "git diff failed"

log "Changed files -> .klc/index/changed-files.txt"
log "Now run the periodic agent inside Claude Code:"
cat <<EOF
  Prompt:
    Read core/agents/periodic.md and execute it.
    Inputs:
      - .klc/index/.last-run (SHA: $LAST)
      - .klc/index/changed-files.txt
      - .klc/index/inventory.json
      - .klc/index/modules.json
    Current HEAD: $HEAD_SHA
    On success, print PERIODIC_OK and overwrite .klc/index/.last-run with $HEAD_SHA.
    On no-op, print PERIODIC_NOOP.
EOF

log "After the agent finishes:"
log "  echo $HEAD_SHA > .klc/index/.last-run"
