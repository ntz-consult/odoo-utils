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

# Validate Python environment has required dependencies
PYTHON_EXE="$PYTHON_PATH/python"
if [ ! -x "$PYTHON_EXE" ]; then
    echo "Error: Python executable not found: $PYTHON_EXE"
    echo "Check PYTHON_PATH in $ENV_FILE"
    exit 1
fi

# Check for key Odoo dependencies
REQUIRED_MODULES=("babel" "lxml" "psycopg2" "werkzeug")
MISSING_MODULES=()
for mod in "${REQUIRED_MODULES[@]}"; do
    if ! "$PYTHON_EXE" -c "import $mod" 2>/dev/null; then
        MISSING_MODULES+=("$mod")
    fi
done

if [ ${#MISSING_MODULES[@]} -gt 0 ]; then
    echo "Error: Python environment is missing required dependencies:"
    printf '  - %s\n' "${MISSING_MODULES[@]}"
    echo ""
    echo "The virtual environment may have been created with a different directory path."
    echo "To fix this, recreate the venv:"
    echo "  odoo-init-env --venv-recreate"
    echo ""
    echo "Or manually install dependencies:"
    echo "  $PYTHON_PATH/pip install -r \$ODOO_ROOT/odoo/requirements.txt"
    exit 1
fi

# Interactive module selection
if [ "$MODULES_FROM_CLI" = false ] && [ -t 0 ]; then
    echo "Initializing database: $DB_NAME"
    echo "The 'base' module will be installed automatically."
    echo "Select additional modules to install:"
    ADDITIONAL_MODULES=()
    for mod in "${SUGGESTED_MODULES[@]}"; do
        read -r -p "  Install $mod? [Y/n]: " choice
        if [[ ! "$choice" =~ ^[Nn]$ ]]; then
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

# Configure settings for installed modules
CONFIGURE_ARGS=(--db "$DB_NAME" --modules "$MODULES")
if [ "$MODULES_FROM_CLI" = true ]; then
    CONFIGURE_ARGS+=(--non-interactive)
fi
"$SCRIPT_DIR/configure_settings.sh" "${CONFIGURE_ARGS[@]}"

# Delete preconfigured default product attributes
echo "Deleting default product attributes..."
DELETE_ATTRS_SCRIPT="attr_ids = env['product.attribute'].search([]).ids
for attr_id in attr_ids:
    attr = env['product.attribute'].browse(attr_id)
    try:
        attr_name = attr.name
        attr.unlink()
        print(f'Deleted attribute: {attr_name}')
    except Exception as e:
        print(f'Could not delete attribute {attr.name}: {e}')
env.cr.commit()
print('Default product attributes cleanup complete.')
"
"$ODOO_BIN" shell -c "$CONF_FILE" -d "$DB_NAME" --no-http <<< "$DELETE_ATTRS_SCRIPT"

# Create backup in $PWD
DUMP_FILE="$PWD/dump_${DB_NAME}.sql"
echo "Creating backup: $DUMP_FILE"
pg_dump -d "$DB_NAME" > "$DUMP_FILE"

echo "Done!"
