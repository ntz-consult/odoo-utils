#!/bin/bash
# common.sh — shared environment loader for Odoo project run-scripts
# Usage: source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
#
# IMPORTANT: .env and odoo.conf are ALWAYS read from the CURRENT DIRECTORY ($PWD).
# They are NEVER looked for in the script directory.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve ENV_DIR (current working directory ONLY)
# ---------------------------------------------------------------------------
ENV_DIR="$(pwd)"

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
ENV_FILE="$ENV_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env not found in current directory ($ENV_DIR)."
    echo "Run: odoo-init-env from this directory to create .env"
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

# ---------------------------------------------------------------------------
# Validate required variables
# ---------------------------------------------------------------------------
: "${ODOO_ROOT:?Missing ODOO_ROOT in $ENV_FILE}"
: "${PROJECT_NAME:?Missing PROJECT_NAME in $ENV_FILE}"
: "${DB_NAME:?Missing DB_NAME in $ENV_FILE}"
: "${PYTHON_PATH:?Missing PYTHON_PATH in $ENV_FILE}"

# ---------------------------------------------------------------------------
# Derived paths
# ---------------------------------------------------------------------------
export PATH="$PYTHON_PATH:$PATH"
ODOO_BIN="${ODOO_ROOT}/odoo/odoo-bin"
CONF_FILE="$ENV_DIR/odoo.conf"

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------
if [[ ! -f "$ODOO_BIN" ]]; then
    echo "Error: odoo-bin not found: $ODOO_BIN"
    echo "Check ODOO_ROOT in $ENV_FILE"
    exit 1
fi

if [[ ! -f "$CONF_FILE" ]]; then
    echo "Error: $CONF_FILE not found."
    echo "Run: odoo-init-env from this directory to create odoo.conf"
    exit 1
fi
