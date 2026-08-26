#!/bin/bash
# Compatibility bridge for odoo-direct wrappers; project resolution is shared.

ODOO_RUNTIME_MODE=project
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

odoo_direct_resolve_project() {
    odoo_resolve_project "${1:-$PWD}"
    ODOO_DIRECT_PROJECT_ROOT="$PROJECT_ROOT"
    ODOO_DIRECT_ENV_DIR="$ENV_DIR"
    ODOO_DIRECT_ENV_FILE="$ENV_FILE"
    ODOO_DIRECT_CONF_FILE="$CONF_FILE"
    ODOO_DIRECT_CONFIG_FILE="$ODOO_CONFIG_FILE"
    ODOO_DIRECT_WORKTREE_FILE="$ODOO_WORKTREE_FILE"
    export ODOO_DIRECT_PROJECT_ROOT ODOO_DIRECT_ENV_DIR
    export ODOO_DIRECT_ENV_FILE ODOO_DIRECT_CONF_FILE ODOO_DIRECT_CONFIG_FILE
    export ODOO_DIRECT_WORKTREE_FILE
}
