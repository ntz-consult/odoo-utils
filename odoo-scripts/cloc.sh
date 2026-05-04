#!/bin/bash

# Count Lines of Code for Odoo modules using odoo-bin cloc
#
# Usage:
#   ./cloc.sh                      # Use default addons path
#   ./cloc.sh --path <directory>   # Custom addons path
#
# Environment (see .env):
#   ODOO_ROOT    - Odoo source root
#   PROJECT_ROOT - Project addons root

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [ $# -eq 0 ]; then
    echo "Usage: $0 [--path <directory>]"
    exit 0
fi

ADDONS_PATH="$PROJECT_ROOT"

if [[ "${1:-}" == "--path" ]]; then
    ADDONS_PATH="${2:-$PROJECT_ROOT}"
    shift 2
fi

MODULES=$(find "$ADDONS_PATH" -maxdepth 1 -type d ! -name ".*" ! -path "$ADDONS_PATH" | sort)

echo "================================================================================"
echo "Odoo CLOC - Modules Summary"
echo "================================================================================"
echo ""
echo "Scanning: $ADDONS_PATH"
echo ""

for module in $MODULES; do
    module_name=$(basename "$module")
    echo "Module: $module_name"
    echo "--------------------------------------------------------------------------------"
    "$ODOO_BIN" cloc --path="$module" 2>/dev/null
    echo ""
done

echo "================================================================================"
echo "TOTAL SUMMARY - All Modules"
echo "================================================================================"
"$ODOO_BIN" cloc --path="$ADDONS_PATH"