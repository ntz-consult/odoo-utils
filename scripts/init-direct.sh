#!/bin/bash
# Store the API key for a target already declared in .odoo/config.toml.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ODOO_RUNTIME_MODE=project
source "$SCRIPT_DIR/common.sh"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -ne 1 ]]; then
    echo "Usage: odoo-direct-init TARGET"
    exit $(( $# == 1 ? 0 : 1 ))
fi

TARGET="$1"
CONFIG_JSON="$(python3 "$SCRIPT_DIR/config.py" json "$ODOO_CONFIG_FILE" "$ODOO_WORKTREE_FILE")"
if ! python3 -c 'import json,sys; data=json.load(sys.stdin); raise SystemExit(0 if sys.argv[1] in data.get("targets", {}) else 1)' "$TARGET" <<<"$CONFIG_JSON"; then
    echo "Error: target '$TARGET' is not declared in $ODOO_CONFIG_FILE." >&2
    exit 1
fi

TOKEN="$(printf '%s' "$TARGET" | tr '[:lower:]-' '[:upper:]_' | tr -c 'A-Z0-9_' '_')"
VARIABLE="ODOO_DIRECT_${TOKEN}_API_KEY"
read -r -s -p "API key for $TARGET: " API_KEY
echo
[[ -n "$API_KEY" ]] || { echo "Error: API key cannot be empty." >&2; exit 1; }

mkdir -p "$ODOO_CONFIG_DIR"
TEMP_FILE="$(mktemp "$ODOO_CONFIG_DIR/.secrets.XXXXXX")"
chmod 600 "$TEMP_FILE"
if [[ -f "$ODOO_SECRETS_FILE" ]]; then
    grep -v "^${VARIABLE}=" "$ODOO_SECRETS_FILE" > "$TEMP_FILE" || true
fi
printf '%s=%s\n' "$VARIABLE" "$API_KEY" >> "$TEMP_FILE"
mv -f "$TEMP_FILE" "$ODOO_SECRETS_FILE"
echo "Configured credentials for target '$TARGET'."
