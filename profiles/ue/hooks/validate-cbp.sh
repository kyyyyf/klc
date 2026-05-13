#!/usr/bin/env bash
# validate-cbp.sh — UE profile asset validator.
#
# Contract: receive a newline-separated list of changed file paths on
# stdin-filepath (argv 1) and write findings JSON to argv 2.
#
# What this hook can and cannot do
#
#   CAN   static sanity checks that do NOT require UE to run:
#           - ini sections referencing stale class names
#           - blatant corruption (file smaller than N bytes, truncated header)
#           - presence of expected substring markers
#
#   CANNOT   prove which parts a CBP (Crush Behaviour) actually instantiates.
#            uassets mention class names as soft references and in dependency
#            tables, even when the class is not inserted into the Parts list.
#            The CRUSH-3020-class bug (CBP ships without
#            GASAttributeController_* parts) can be mentioned as a reminder
#            but cannot be detected reliably from `strings`. A real check
#            needs headless UE (`-run=ValidateAssets`) or a uasset parser.
#
# Rules applied:
#
# 1. Any .ini with [/Script/Module.ClassName] section naming a class that
#    is not in .klc/index/inventory.json -> MEDIUM finding (class was
#    renamed or the ini is stale).
#
# 2. For each changed CBP_*.uasset we emit an INFO reminder that a full
#    asset audit requires the editor / headless UE, and point at the
#    CRUSH-3020 class of bug. This is a deliberate prompt for the human
#    reviewer rather than an automated decision.

set -uo pipefail

FILES_IN="$1"
OUT_JSON="$2"

REPO_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")/../../../.." && pwd)}"
INVENTORY="$REPO_ROOT/.klc/index/inventory.json"

findings='[]'
skipped='[]'
tools_missing='[]'
validated=0

add_finding() {
  local file="$1" line="$2" severity="$3" tool="$4" message="$5"
  findings=$(jq --arg f "$file" --arg l "$line" --arg s "$severity" \
                --arg t "$tool"  --arg m "$message" \
    '. + [{file: $f, line: (if $l == "" then null else ($l|tonumber) end), severity: $s, tool: $t, message: $m}]' <<<"$findings")
}

add_skipped() {
  local file="$1" reason="$2"
  skipped=$(jq --arg f "$file" --arg r "$reason" '. + [{file: $f, reason: $r}]' <<<"$skipped")
}

have() { command -v "$1" >/dev/null 2>&1; }

have strings || {
  tools_missing=$(jq '. + ["binutils (strings)"]' <<<"$tools_missing")
}
have jq || {
  echo "validate-cbp: jq required" >&2; exit 2;
}

# --- Rule 2: remind on every CBP_*.uasset change (manual check required) -----
# We cannot prove Parts-list contents from `strings` alone (see header).
# Emit an INFO to prompt a manual check in the editor.
while read -r rel; do
  [ -z "$rel" ] && continue
  path="$REPO_ROOT/$rel"
  [ -f "$path" ] || { add_skipped "$rel" "missing on disk"; continue; }

  case "$(basename "$rel")" in
    CBP_*.uasset) ;;
    *)            continue ;;
  esac
  validated=$((validated + 1))

  add_finding "$rel" "" INFO validate-cbp \
    "CBP asset changed. Open it in the editor and confirm the Parts list; for GAS vehicles both CrushBehaviorPart_GASAttributeController_ForwardMaxSpeed and CrushBehaviorPart_GASAttributeController_AuxEnginePowerScale must be present (see CRUSH-3020)."
done < "$FILES_IN"

# --- Rule 1: stale [/Script/...] references in .ini --------------------------
# Only runs when inventory.json exists and lists class symbols we can check
# against. Missed classes are MEDIUM — the ini may just name an engine
# class we didn't index.
if [ -s "$INVENTORY" ]; then
  classes_file="$(mktemp)"
  trap 'rm -f "$classes_file"' EXIT
  jq -r '.symbols.cpp.items[]? | select(.kind|test("UCLASS|class")) | .name' "$INVENTORY" 2>/dev/null \
    | sort -u > "$classes_file" || true

  while read -r rel; do
    [ -z "$rel" ] && continue
    case "$rel" in
      *.ini) ;;
      *)     continue ;;
    esac
    path="$REPO_ROOT/$rel"
    [ -f "$path" ] || continue
    validated=$((validated + 1))

    # Each "[/Script/Module.ClassName]" header — extract ClassName and look it up.
    grep -nE '^\[\/Script\/[A-Za-z_]+\.[A-Za-z_][A-Za-z_0-9]*\]' "$path" \
      | while IFS=: read -r linenum header; do
          cls="$(echo "$header" | sed -E 's@.*\.([A-Za-z_][A-Za-z_0-9]*)\].*@\1@')"
          # Match with or without the typical U/A/F/E prefix UE strips.
          if ! grep -qxE "^[AUFE]?${cls}$" "$classes_file"; then
            add_finding "$rel" "$linenum" MEDIUM validate-cbp \
              "ini section refers to class '$cls' that is not in the inventory; the class may have been renamed or removed."
          fi
        done
  done < "$FILES_IN"
fi

jq -n \
  --argjson f "$findings" \
  --argjson s "$skipped" \
  --argjson tm "$tools_missing" \
  --argjson v "$validated" \
  '{validated_files: $v, findings: $f, skipped: $s, tools_missing: $tm}' > "$OUT_JSON"
