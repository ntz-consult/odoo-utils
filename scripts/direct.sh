#!/bin/bash
# direct.sh — Global wrapper for odoo-direct Python tool
#
# Usage:
#   odoo-direct --test    # Test connection using credentials from .env
#
# Environment (from .env in current directory):
#   ODOO_DIRECT_URL      - Odoo instance URL
#   ODOO_DIRECT_DB       - Database name
#   ODOO_DIRECT_USER     - Username (email)
#   ODOO_DIRECT_API_KEY  - API key

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$(pwd)"
ENV_FILE="$ENV_DIR/.env"

# ---------------------------------------------------------------------------
# Load .env if present (soft fail if missing)
# ---------------------------------------------------------------------------
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "Warning: .env not found in current directory ($ENV_DIR)."
    echo "Run 'odoo-direct-init' to configure odoo-direct credentials."
fi

# ---------------------------------------------------------------------------
# Ensure direct/ package is on PYTHONPATH
# ---------------------------------------------------------------------------
DIRECT_DIR="$(cd "$SCRIPT_DIR/../direct" && pwd)"
export PYTHONPATH="${DIRECT_DIR}${PYTHONPATH:+:$PYTHONPATH}"

# ---------------------------------------------------------------------------
# Delegate to Python CLI
# ---------------------------------------------------------------------------
exec python3 "$SCRIPT_DIR/direct.py" "$@"
