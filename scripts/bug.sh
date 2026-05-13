#!/usr/bin/env bash
# DEPRECATED: use `framework/scripts/klc` directly.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "DEPRECATED: bug.sh will be removed; use 'klc intake <jira-key> --kind bug \"<desc>\" && klc discover <jira-key>' instead." >&2

if [ "$#" -lt 1 ]; then
  echo "usage: $0 '<bug description>' (deprecated)" >&2
  exit 2
fi

TMP_KEY="TMP-$(date -u +%s)"
"$SCRIPT_DIR/klc" intake "$TMP_KEY" --kind bug "$1"
"$SCRIPT_DIR/klc" discover "$TMP_KEY"
echo "Assigned temporary key $TMP_KEY. Rename the directory in .klc/tickets/ to the real Jira key." >&2
