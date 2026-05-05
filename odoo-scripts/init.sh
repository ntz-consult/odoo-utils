#!/bin/bash
#
# Initialize a fresh Odoo database with -i base.
#
# Usage:
#   ./init.sh                           # Use default db name and modules
#   ./init.sh --db <database_name>      # Use specific database name
#   ./init.sh --modules <mod1,mod2>     # Specify modules to install (default: base)
#
# Environment (see .env):
#   ODOO_ROOT    - Odoo source root
#   PROJECT_ROOT - Project addons root
#   PROJECT_NAME - Default project db name
#   PYTHON_PATH  - Python venv bin directory
#   INIT_MODULES - Default modules to install (overridden by --modules)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

DB_NAME="$PROJECT_NAME"
MODULES="${INIT_MODULES:-base}"
MODULES_FROM_CLI=false

SUGGESTED_MODULES=("web_studio" "stock" "purchase" "mrp" "sale_management" "accountant")

show_usage() {
    echo "Usage: odoo-init [--db <database_name>] [--modules <mod1,mod2,...>]"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)
            DB_NAME="$2"
            shift 2
            ;;
        --modules)
            MODULES="$2"
            MODULES_FROM_CLI=true
            shift 2
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

if [ ! -f "$ODOO_BIN" ]; then
    echo "Error: odoo-bin not found: $ODOO_BIN"
    exit 1
fi

if [ ! -f "$CONF_FILE" ]; then
    echo "Error: Config file not found: $CONF_FILE"
    exit 1
fi

# Interactive module selection
if [ "$MODULES_FROM_CLI" = false ] && [ -t 0 ]; then
    echo "Initializing database: $DB_NAME"
    echo "The 'base' module will be installed automatically."
    echo "Select additional modules to install:"
    ADDITIONAL_MODULES=()
    for mod in "${SUGGESTED_MODULES[@]}"; do
        read -r -p "  Install $mod? [y/N]: " choice
        if [[ "$choice" =~ ^[Yy]$ ]]; then
            ADDITIONAL_MODULES+=("$mod")
        fi
    done

    if [ ${#ADDITIONAL_MODULES[@]} -gt 0 ]; then
        MODULES="base,$(IFS=,; echo "${ADDITIONAL_MODULES[*]}")"
    else
        MODULES="base"
    fi
    echo ""
fi

# Drop and recreate database
echo "Dropping database: $DB_NAME"
psql -c "drop database if exists $DB_NAME;"

echo "Creating database: $DB_NAME"
psql -c "create database $DB_NAME OWNER odoo;"

# Initialize Odoo with requested modules
echo "Initializing Odoo database with -i $MODULES..."
"$ODOO_BIN" -c "$CONF_FILE" -d "$DB_NAME" -i "$MODULES" --stop-after-init

# Create backup in $PWD
DUMP_FILE="$PWD/dump_${DB_NAME}.sql"
echo "Creating backup: $DUMP_FILE"
pg_dump -d "$DB_NAME" > "$DUMP_FILE"

echo "Done!"
