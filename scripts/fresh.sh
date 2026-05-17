#!/bin/bash

# Quick database refresh from SQL dump
#
# Usage:
#   odoo-fresh                           # Quick refresh (default DB, default dump)
#   odoo-fresh --db <database>           # Custom database name
#   odoo-fresh --dump <file.sql>         # Custom dump file
#   odoo-fresh --update                  # Also sync Odoo source, update modules, refresh dump
#
# Environment (see .env in current directory):
#   DB_NAME      - Default database name
#   PROJECT_NAME - Project name (used for default dump file)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Defaults
DB_NAME_ARG="$DB_NAME"
DUMP_FILE="$ENV_DIR/dump_${PROJECT_NAME}.sql"
UPDATE_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)
            DB_NAME_ARG="$2"
            shift 2
            ;;
        --dump)
            DUMP_FILE="$2"
            shift 2
            ;;
        --update)
            UPDATE_MODE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--db <database>] [--dump <file.sql>] [--update]"
            exit 1
            ;;
    esac
done

# Validate dump file exists
if [[ ! -f "$DUMP_FILE" ]]; then
    echo "Error: Dump file not found: $DUMP_FILE"
    echo "Use --dump <file.sql> to specify a different file"
    exit 1
fi

clear

echo "Database: $DB_NAME_ARG"
echo "Dump file: $DUMP_FILE"
echo ""

if [[ "$UPDATE_MODE" == false ]]; then
    echo "Tip: Use --update to also sync Odoo source, update all modules, and refresh the dump file."
    sleep 3s
fi

echo "Dropping database: $DB_NAME_ARG"
psql -c "drop database $DB_NAME_ARG;" 2>/dev/null || true
sleep 2s

echo "Creating database: $DB_NAME_ARG"
psql -c "create database $DB_NAME_ARG OWNER odoo;"
sleep 2s

echo "Restoring from dump..."
psql -d "$DB_NAME_ARG" < "$DUMP_FILE"

if [[ "$UPDATE_MODE" == true ]]; then
    sleep 2s

    if [[ -n "${ODOO_SYNC_SCRIPT:-}" && -x "$ODOO_SYNC_SCRIPT" ]]; then
        echo "Syncing Odoo source ($ODOO_SYNC_SCRIPT)..."
        "$ODOO_SYNC_SCRIPT"
    fi

    sleep 2s

    echo "Updating all modules..."
    "$ODOO_BIN" -c "$CONF_FILE" -u all --stop-after-init

    sleep 2s

    echo "Refreshing dump file..."
    pg_dump -d "$DB_NAME_ARG" > "$DUMP_FILE"
fi

echo ""
echo "Database refresh complete!"
