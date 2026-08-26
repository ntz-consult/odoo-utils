#!/bin/bash
# direct.sh — Global wrapper for deterministic Odoo 19 JSON-2 access
#
# Usage:
#   odoo-direct local test
#   odoo-direct production search-read res.company "[]" "['name']"
#
# Targets come from <Git repository root>/.odoo/config.yaml.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    DIRECT_DIR="$(cd "$SCRIPT_DIR/../direct" && pwd)"
    export PYTHONPATH="${DIRECT_DIR}${PYTHONPATH:+:$PYTHONPATH}"
    exec python3 "$SCRIPT_DIR/direct.py" "$@"
fi

source "$SCRIPT_DIR/direct-common.sh"
odoo_direct_resolve_project "$PWD"

# ---------------------------------------------------------------------------
# Load the repository-local runtime and optional remote credentials
# ---------------------------------------------------------------------------
if [[ -f "$ODOO_DIRECT_CONFIG_FILE" ]]; then
    if [[ -n "${PYTHON_PATH:-}" ]]; then
        export PATH="$PYTHON_PATH:$PATH"
    fi
else
    echo "Error: repository Odoo configuration not found: $ODOO_DIRECT_CONFIG_FILE" >&2
    echo "Run odoo-init-env inside the repository." >&2
    exit 1
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
