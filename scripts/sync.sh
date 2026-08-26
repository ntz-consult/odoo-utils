#!/bin/bash

# Sync XML data files with database records
#
# Usage:
#   odoo-sync --module MODULE_NAME [options]
#
# Options:
#   --module MODULE     Module name to check (required)
#   --detail            Show full discrepancy details (default is summary only)
#   --update [N]        Update XML after confirmation; with N, stop after N successful changes
#   --model MODEL       Filter discrepancies to a single model
#   --img               Include image/binary fields in comparison
#   --debug             Print raw XML vs DB field comparisons
#   --models            List models found in the module's XML data files and exit
#   --out PATH          Also write the report to a Markdown file
#
# Configuration comes from <git-root>/.odoo/.
#   ODOO_ROOT    - Odoo source root
#   PROJECT_ROOT - Project addons root
#   DB_NAME      - Database name
#   PYTHON_PATH  - Python venv bin directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: odoo-sync --module MODULE [--detail] [--models] [--update [N]] [--out PATH]"
    exit 0
fi

# Export variables for Python script
export PROJECT_ROOT
export ENV_DIR
export ODOO_ROOT
export DB_NAME
export CONF_FILE

# Pass through all arguments to Python script
exec python3 "$SCRIPT_DIR/sync.py" "$@"
