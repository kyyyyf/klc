#!/usr/bin/env bash
# validate-syntax.sh — generic asset validator.
#
# Contract: argv 1 = path to file with changed paths (one per line),
#           argv 2 = output JSON path.
#
# Rules: JSON and YAML files must parse. That's it. This hook is a
# baseline example — real projects replace it with a richer validator
# (OpenAPI via spectral, Terraform via tflint, dbt via dbt parse, etc.).

set -uo pipefail

FILES_IN="$1"
OUT_JSON="$2"

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"

findings='[]'
skipped='[]'
tools_missing='[]'
validated=0

add_finding() {
  findings=$(jq --arg f "$1" --arg s "$2" --arg t "$3" --arg m "$4" \
    '. + [{file: $f, line: null, severity: $s, tool: $t, message: $m}]' <<<"$findings")
}
add_skipped() { skipped=$(jq --arg f "$1" --arg r "$2" '. + [{file: $f, reason: $r}]' <<<"$skipped"); }

have() { command -v "$1" >/dev/null 2>&1; }

have jq || { echo "validate-syntax: jq required" >&2; exit 2; }
have python3 || tools_missing=$(jq '. + ["python3 (for yaml check)"]' <<<"$tools_missing")

while read -r rel; do
  [ -z "$rel" ] && continue
  path="$REPO_ROOT/$rel"
  [ -f "$path" ] || { add_skipped "$rel" "missing on disk"; continue; }

  case "$rel" in
    *.json)
      validated=$((validated + 1))
      if ! err=$(jq empty "$path" 2>&1); then
        add_finding "$rel" CRITICAL jq "invalid JSON: ${err//$'\n'/ }"
      fi
      ;;
    *.yml|*.yaml)
      validated=$((validated + 1))
      if have python3; then
        if ! err=$(python3 -c "import sys,yaml; yaml.safe_load(open(sys.argv[1]))" "$path" 2>&1); then
          add_finding "$rel" CRITICAL pyyaml "invalid YAML: ${err//$'\n'/ }"
        fi
      else
        add_skipped "$rel" "python3 not available; yaml check skipped"
      fi
      ;;
    *)
      add_skipped "$rel" "no validator registered for this extension"
      ;;
  esac
done < "$FILES_IN"

jq -n \
  --argjson f "$findings" \
  --argjson s "$skipped" \
  --argjson tm "$tools_missing" \
  --argjson v "$validated" \
  '{validated_files: $v, findings: $f, skipped: $s, tools_missing: $tm}' > "$OUT_JSON"
