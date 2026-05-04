#!/bin/bash
# common.sh — shared environment loader for Odoo project run-scripts
# Usage: source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

set -euo pipefail

# Resolve SCRIPT_DIR (docs/run-scrips)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
# Look for .env in script directory first, then fall back to current directory
CURRENT_DIR="$(pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    ENV_FILE="$SCRIPT_DIR/.env"
    ENV_DIR="$SCRIPT_DIR"
elif [[ -f "$CURRENT_DIR/.env" ]]; then
    ENV_FILE="$CURRENT_DIR/.env"
    ENV_DIR="$CURRENT_DIR"
else
    echo "Error: .env not found in current directory ($CURRENT_DIR) or script directory ($SCRIPT_DIR)."
    echo "Run: init_env.sh from your project directory to create .env"
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

# ---------------------------------------------------------------------------
# Resolve PROJECT_ROOT
# ---------------------------------------------------------------------------
# PROJECT_ROOT from .env takes priority, otherwise use directory containing .env
PROJECT_ROOT="${PROJECT_ROOT:-$ENV_DIR}"

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
    echo "Run: init_env.sh from your project directory to create odoo.conf"
    exit 1
fi
