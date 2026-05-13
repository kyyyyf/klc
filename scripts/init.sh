#!/usr/bin/env bash
# init.sh — first-time bootstrap.
#
# Runs the full pipeline:
#   1. install-deps check
#   2. file-scanner          (structural snapshot)
#   3. Serena start hint     (user-managed MCP; we only prepare inputs)
#   4. dep-graph             (per-language)
#   5. inventory agent       (LLM step, invoked from Claude Code)
#   6. decompose agent       (LLM)
#   7. docgen agent          (LLM)
#   8. store HEAD sha in $PROJECT_ROOT/.klc/index/.last-run
#
# Per-project state lives in $PROJECT_ROOT/.klc/ (see MIGRATION.md). The
# framework directory itself stays pristine.
#
# This script is a *driver*: steps 5-7 are LLM agents and are not executed
# directly from bash. The script prepares their inputs and prints the exact
# prompt to run inside Claude Code. All text is English.

set -uo pipefail

FRAMEWORK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$FRAMEWORK_ROOT/.." && pwd)}"
cd "$PROJECT_ROOT"

KLC_DIR="$PROJECT_ROOT/.klc"
INDEX_DIR="$KLC_DIR/index"
LOGS_DIR="$KLC_DIR/logs"
mkdir -p "$INDEX_DIR" "$LOGS_DIR"

log()  { echo "[init] $*"; }
die()  { echo "[init][err] $*" >&2; exit 1; }

log "Project root:   $PROJECT_ROOT"
log "Framework root: $FRAMEWORK_ROOT"
log "State dir:      $KLC_DIR"

# 1. Dependencies ------------------------------------------------------------
#log "Step 1/8: checking dependencies"
#if ! bash "$FRAMEWORK_ROOT/scripts/install-deps.sh"; then
#  die "dependencies missing — resolve the suggestions above and rerun ./framework/scripts/init.sh"
#fi

# 2. Structural scan --------------------------------------------------------
log "Step 2/8: structural scan (file-scanner.sh)"
bash "$FRAMEWORK_ROOT/core/skills/file-scanner.sh" "$PROJECT_ROOT" \
  > "$INDEX_DIR/structural.json" \
  || die "file-scanner.sh failed"
log "  -> .klc/index/structural.json"

# 3. MCP bootstrap hint -----------------------------------------------------
# init is deterministic — Serena is NOT required here. The ast-grep MCP
# is useful for inventory's structural rules, but even that has a CLI
# fallback. Serena becomes relevant later, on the first M/L ticket that
# reaches design/impl/build (gated by serena-call.py).
log "Step 3/8: MCP configuration (advisory)"
if [ -f "$PROJECT_ROOT/.mcp.json" ]; then
  log "  .mcp.json already present; assuming ast-grep (and optionally Serena) are configured."
else
  log "  No project-level .mcp.json found — init will still work without it."
  log "  When you're ready for ticket work, copy framework/profiles/<profile>/mcp.json"
  log "  to .mcp.json (gives you ast-grep + Serena)."
fi

# 4. Dependency graph -------------------------------------------------------
log "Step 4/8: dependency graph (dep-graph.sh)"
bash "$FRAMEWORK_ROOT/core/skills/dep-graph.sh" "$PROJECT_ROOT" \
  > "$INDEX_DIR/depgraph.json" \
  || log "  WARN: dep-graph.sh returned non-zero; inventory will note this"
log "  -> .klc/index/depgraph.json"

# 5-7. LLM agents (prepare instructions) ------------------------------------
log "Step 5/8: run the inventory agent from Claude Code"
cat <<EOF
  Prompt:
    Read framework/core/agents/inventory.md and execute it.
    Inputs are .klc/index/structural.json and .klc/index/depgraph.json.
    Produce .klc/index/inventory.json and print INVENTORY_OK.
EOF

log "Step 6/8: run the decompose agent"
cat <<EOF
  Prompt:
    Read framework/core/agents/decompose.md and execute it.
    Input is .klc/index/inventory.json.
    Produce .klc/index/modules.json and print DECOMPOSE_OK.
EOF

log "Step 7/8: run the docgen agent"
cat <<EOF
  Prompt:
    Read framework/core/agents/docgen.md and execute it.
    Inputs are .klc/index/inventory.json and .klc/index/modules.json.
    Produce the root CLAUDE.md plus a CLAUDE.md for each module. Print DOCGEN_OK.
EOF

# 8. Baseline sha ----------------------------------------------------------
log "Step 8/8: record baseline git sha (after agents finish, rerun this script"
log "          with --finalize, or execute the command below manually)"
if [ "${1:-}" = "--finalize" ]; then
  head_sha="$(git rev-parse HEAD)"
  echo "$head_sha" > "$INDEX_DIR/.last-run"
  log "  Recorded $head_sha in .klc/index/.last-run"
else
  echo "  git rev-parse HEAD > $INDEX_DIR/.last-run"
fi

log "init done. Next: run the three agents listed above inside Claude Code."
