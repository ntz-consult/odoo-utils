#!/bin/bash

# Reset Odoo database from SQL dump
#
# Usage:
#   ./reset_db.sh                           # Reset using default db
#   ./reset_db.sh --db <database>            # Custom database name
#   ./reset_db.sh --dump <file.sql>         # Custom dump file
#   ./reset_db.sh --update                  # Also sync Odoo source, update modules, refresh dump
#
# Environment (see .env):
#   ODOO_ROOT    - Odoo source root
#   PROJECT_ROOT - Project addons root
#   PROJECT_NAME - Project db name

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [ $# -eq 0 ]; then
    echo "Usage: $0 [--db <database>] [--dump <file.sql>] [--update]"
    exit 0
fi

DB_NAME="$PROJECT_NAME"
DUMP_FILE="$SCRIPT_DIR/dump_${PROJECT_NAME}.sql"
UPDATE_MODE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)
            DB_NAME="$2"
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
            exit 1
            ;;
    esac
done

if [[ ! -f "$DUMP_FILE" ]]; then
    echo "Error: Dump file not found: $DUMP_FILE"
    echo "Use --dump <file.sql> to specify a different file"
    exit 1
fi

echo "Database: $DB_NAME"
echo "Dump file: $DUMP_FILE"
echo ""
echo "Tip: Use --update to also sync Odoo source, update all modules, and refresh the dump file."
sleep 3s

echo "Dropping database: $DB_NAME"
psql -c "drop database $DB_NAME;" 2>/dev/null || true
sleep 2s

echo "Creating database: $DB_NAME"
psql -c "create database $DB_NAME OWNER odoo;"
sleep 2s

echo "Restoring from dump..."
psql -d "$DB_NAME" < "$DUMP_FILE"

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
    pg_dump -d "$DB_NAME" > "$DUMP_FILE"
fi

echo ""
echo "Database reset complete!"