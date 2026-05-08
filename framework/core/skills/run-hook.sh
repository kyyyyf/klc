#!/usr/bin/env bash
# run-hook.sh — invoke a profile hook with a standard file-list input and
# JSON output.
#
# Usage:   run-hook.sh <hook-name> <files-list-file> <out-json-file>
#
# The active profile's manifest.yml must have:
#
#   hooks:
#     <hook-name>: profiles/<profile>/hooks/<script>
#
# If the hook is not declared, the skill writes an empty-findings JSON and
# exits 0 (no-op). Callers don't need to special-case missing hooks.

set -uo pipefail

HOOK_NAME="${1:-}"
FILES_IN="${2:-}"
OUT_JSON="${3:-}"

if [ -z "$HOOK_NAME" ] || [ -z "$FILES_IN" ] || [ -z "$OUT_JSON" ]; then
  echo "usage: run-hook.sh <hook-name> <files-list> <out-json>" >&2
  exit 2
fi

FWROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO_ROOT="$(cd "$FWROOT/.." && pwd)"

# Resolve the hook path from the active profile manifest.
HOOKS_JSON="$(python3 "$FWROOT/core/skills/profile-resolve.py" --field hooks 2>/dev/null || echo '{}')"
HOOK_REL="$(python3 -c "
import json, sys
h = json.loads(sys.argv[1] or '{}')
print(h.get(sys.argv[2], ''))
" "$HOOKS_JSON" "$HOOK_NAME")"

if [ -z "$HOOK_REL" ]; then
  # No hook declared — emit empty findings.
  cat > "$OUT_JSON" <<EOF
{
  "validated_files": 0,
  "findings": [],
  "skipped": [],
  "tools_missing": [],
  "note": "hook '$HOOK_NAME' not declared in active profile"
}
EOF
  exit 0
fi

HOOK_PATH="$REPO_ROOT/framework/$HOOK_REL"
if [ ! -x "$HOOK_PATH" ]; then
  if [ -f "$HOOK_PATH" ]; then
    echo "run-hook: $HOOK_PATH exists but is not executable; chmod +x it" >&2
  else
    echo "run-hook: $HOOK_PATH not found" >&2
  fi
  exit 1
fi

exec "$HOOK_PATH" "$FILES_IN" "$OUT_JSON"
