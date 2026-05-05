#!/bin/bash

# Run Odoo server with configurable project
#
# Usage:
#   odoo-run                           # Start server with default config
#   odoo-run --conf <file.conf>        # Use custom config file
#   odoo-run --log                     # Log to file
#   odoo-run --                        # Pass args to odoo-bin
#
# Environment (see .env in current directory):
#   ODOO_ROOT    - Odoo source root
#   PROJECT_ROOT - Project addons root
#   PROJECT_NAME - Project db name
#   PYTHON_PATH  - Python venv bin directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

USE_LOGFILE=false
CUSTOM_CONF=""
ODOO_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --conf)
            CUSTOM_CONF="$2"
            shift 2
            ;;
        --log)
            USE_LOGFILE=true
            shift
            ;;
        --)
            shift
            ODOO_ARGS+=("$@")
            break
            ;;
        *)
            ODOO_ARGS+=("$arg")
            shift
            ;;
    esac
done

if [ -n "$CUSTOM_CONF" ]; then
    CONF_FILE="$CUSTOM_CONF"
fi

if [ ! -f "$CONF_FILE" ]; then
    echo "Error: Config file not found: $CONF_FILE"
    echo "Create one or specify with --conf <file.conf>"
    exit 1
fi

if [ ! -f "$ODOO_BIN" ]; then
    echo "Error: odoo-bin not found: $ODOO_BIN"
    exit 1
fi

LOG_FILE="${LOG_FILE:-$ENV_DIR/${PROJECT_NAME}.log}"

if [ "$USE_LOGFILE" = "true" ]; then
    rm -f "$LOG_FILE"
    "$ODOO_BIN" -c "$CONF_FILE" --logfile="$LOG_FILE" "${ODOO_ARGS[@]}"
else
    "$ODOO_BIN" -c "$CONF_FILE" "${ODOO_ARGS[@]}"
fi
