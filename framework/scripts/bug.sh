#!/usr/bin/env bash
# bug.sh — drive a bug-fix workflow. Mirrors feature.sh but wires the
# validator in --kind bug mode. All text is English.

set -uo pipefail

FRAMEWORK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 \"<bug description>\"" >&2
  exit 2
fi

DESC="$1"
PENDING="$FRAMEWORK_ROOT/index/pending-bug.md"
mkdir -p "$(dirname "$PENDING")"

cat > "$PENDING" <<EOF
# Pending bug

$DESC
EOF

echo "Wrote description to: $PENDING"
echo
echo "Step 1 — validator:"
cat <<EOF
  Prompt:
    Read framework/core/agents/validator.md and execute it with --kind bug.
    Input spec: $PENDING.
    Emit the JSON verdict. If complete=false, surface questions and stop.
EOF

echo
echo "Step 2 — task agent:"
cat <<EOF
  Prompt:
    Read framework/core/agents/task.md and execute it.
    Use the validated spec at $PENDING.
    Emit the three options (including a minimal-revert option when relevant)
    and the ADR_NEEDED signal.
EOF

echo
echo "Step 3 — ADR propose (only if task agent signalled ADR_NEEDED=yes):"
cat <<EOF
  Prompt:
    Read framework/core/agents/adr.md and execute it with --phase propose.
    Pass the chosen option label and the bug description at $PENDING.
EOF

echo
echo "Step 4 — test agent (regression test FIRST, must be RED):"
cat <<EOF
  Prompt:
    Read framework/core/agents/test.md and execute it with --type bug.
    Inputs: bug description at $PENDING, affected_modules from the task agent.

  Worker call (to be run by the test agent's LLM):
    python framework/core/skills/test-writer.py --spec "$PENDING" \\
           --modules "<affected_modules>" --type bug

  The first test must reproduce the bug and FAIL (RED) before the fix.
  Then call the review agent with focus=test-coverage on the new tests.
  Only proceed to code after 'APPROVED'.
EOF

echo
echo "Step 5 — implement the fix (GREEN), then full review:"
cat <<EOF
  Prompt:
    Write the fix. The regression test must go from RED to GREEN. Then run:
    ./framework/scripts/review.sh --diff HEAD --spec "$PENDING"
    Address blocking issues if VERDICT is CHANGES REQUESTED.
EOF

echo
echo "Step 6 — ADR accept (upgrade Proposed → Accepted):"
cat <<EOF
  Prompt:
    Read framework/core/agents/adr.md and execute it with --phase accept.
    Reconciles expected vs actual consequences; records lessons learned.
EOF
