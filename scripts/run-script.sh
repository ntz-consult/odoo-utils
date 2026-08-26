#!/bin/bash

# Run a Python script inside odoo-bin shell with the project's Odoo environment
#
# Usage:
#   odoo-run-script <script.py>
#
# Uses odoo-bin shell's stdin-script mode (non-TTY). The script receives:
#   env   – api.Environment(cr, SUPERUSER_ID, ctx)
#   self  – env.user (the SUPERUSER)
#   odoo  – the odoo module
#
# The shell auto-rollbacks at exit. Call env.cr.commit() to persist changes.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [[ $# -eq 0 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: odoo-run-script <script.py>"
    [[ $# -eq 0 ]] && exit 1 || exit 0
fi

SCRIPT_PATH="$1"

if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: Script not found: $SCRIPT_PATH"
    exit 1
fi

"$ODOO_BIN" shell -c "$CONF_FILE" -d "$DB_NAME" < "$SCRIPT_PATH"
