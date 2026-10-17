#!/bin/bash
# odoo-url: print this project's/worktree's test URL on the solomon machine (fallback: tailnet IP).
ODOO_RUNTIME_MODE=project
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
echo "http://solomon:${HTTP_PORT}"
echo "fallback: http://100.105.180.75:${HTTP_PORT}"
