#!/bin/bash

# Quick database refresh from SQL dump
#
# Usage:
#   odoo-fresh                           # Quick refresh
#   odoo-fresh --update                  # Also sync Odoo source, update modules, refresh dump
#
# Environment (see .env in current directory):
#   PROJECT_NAME - Project db name

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [ $# -eq 0 ]; then
    echo "Usage: $0 [--update]"
    exit 0
fi

DUMP_FILE="$ENV_DIR/dump_${PROJECT_NAME}.sql"

clear

# Check if --update argument is provided
if [[ "${1:-}" == "--update" ]]; then
    UPDATE_MODE=true
else
    UPDATE_MODE=false
    echo "Tip: Use --update to also sync Odoo source, update all modules, and refresh the dump file."
    sleep 5s
fi

echo "Dropping database: $PROJECT_NAME"
psql -c "drop database $PROJECT_NAME;"
sleep 5s

echo "Creating database: $PROJECT_NAME"
psql -c "create database $PROJECT_NAME OWNER odoo;"
sleep 5s

echo "Restoring from dump..."
psql -d "$PROJECT_NAME" < "$DUMP_FILE"

if [[ "$UPDATE_MODE" == true ]]; then
    sleep 5s
    if [[ -n "${ODOO_SYNC_SCRIPT:-}" && -x "$ODOO_SYNC_SCRIPT" ]]; then
        echo "Syncing Odoo source ($ODOO_SYNC_SCRIPT)..."
        "$ODOO_SYNC_SCRIPT"
    fi
    sleep 5s
    echo "Updating all modules..."
    "$ODOO_BIN" -c "$CONF_FILE" -u all --stop-after-init
    sleep 5s
    echo "Refreshing dump file..."
    pg_dump -d "$PROJECT_NAME" > "$DUMP_FILE"
fi

echo "Done!"
