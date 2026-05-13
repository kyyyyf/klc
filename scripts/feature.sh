#!/usr/bin/env bash
# DEPRECATED: use `framework/scripts/klc` directly.
#
# This wrapper remains for one release so existing runbooks keep
# working. It forwards to `klc discover` and will be removed in the
# next release.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "DEPRECATED: feature.sh will be removed; use 'klc intake <jira-key> \"<desc>\" && klc discover <jira-key>' instead." >&2

if [ "$#" -lt 1 ]; then
  echo "usage: $0 '<feature description>' (deprecated)" >&2
  exit 2
fi

TMP_KEY="TMP-$(date -u +%s)"
"$SCRIPT_DIR/klc" intake "$TMP_KEY" --kind feature "$1"
"$SCRIPT_DIR/klc" discover "$TMP_KEY"
echo "Assigned temporary key $TMP_KEY. Rename the directory in .klc/tickets/ to the real Jira key." >&2
