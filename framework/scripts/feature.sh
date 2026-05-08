#!/usr/bin/env bash
# feature.sh — drive a new-feature workflow.
#
# Usage: ./framework/scripts/feature.sh "<short feature description>"
#
# The script captures the description to framework/index/pending-feature.md and
# prints the prompts to run inside Claude Code in order: validator -> task ->
# (optional) adr. All text is English.

set -uo pipefail

FRAMEWORK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 \"<feature description>\"" >&2
  exit 2
fi

DESC="$1"
PENDING="$FRAMEWORK_ROOT/index/pending-feature.md"
mkdir -p "$(dirname "$PENDING")"

cat > "$PENDING" <<EOF
# Pending feature

$DESC
EOF

echo "Wrote description to: $PENDING"
echo
echo "Step 1 — validator:"
cat <<EOF
  Prompt:
    Read framework/core/agents/validator.md and execute it with --kind feature.
    Input spec: $PENDING.
    Emit the JSON verdict. If complete=false, surface questions and stop.
EOF

echo
echo "Step 2 — task agent (only if validator returned complete=true):"
cat <<EOF
  Prompt:
    Read framework/core/agents/task.md and execute it.
    Use the validated spec at $PENDING and the affected_modules from the
    validator output. Emit the three options and the ADR_NEEDED signal.
EOF

echo
echo "Step 3 — ADR propose (only if task agent signalled ADR_NEEDED=yes):"
cat <<EOF
  Prompt:
    Read framework/core/agents/adr.md and execute it with --phase propose.
    Pass the chosen option label and the validated spec at $PENDING.
    Writes docs/adr/ADR-NNN-*.md with status: Proposed, linked from each
    affected CLAUDE.md.
EOF

echo
echo "Step 4 — test agent (TDD; runs after ADR propose):"
cat <<EOF
  Prompt:
    Read framework/core/agents/test.md and execute it.
    Inputs: spec at $PENDING, affected_modules from the task agent.

  Worker call (to be run by the test agent's LLM):
    python framework/core/skills/test-writer.py --spec "$PENDING" \\
           --modules "<affected_modules>"

  Then call the review agent with focus=test-coverage on the newly-written
  tests. Only proceed to code after 'APPROVED'.
EOF

echo
echo "Step 5 — implement code, then full review:"
cat <<EOF
  Prompt:
    Write the implementation. Then run:
    ./framework/scripts/review.sh --diff HEAD --spec "$PENDING"
    Address blocking issues if VERDICT is CHANGES REQUESTED.
EOF

echo
echo "Step 6 — ADR accept (upgrade Proposed → Accepted):"
cat <<EOF
  Prompt:
    Read framework/core/agents/adr.md and execute it with --phase accept.
    Pass --adr docs/adr/ADR-NNN-*.md and the final review report.
    Reconciles expected vs actual consequences; records lessons learned.
EOF

