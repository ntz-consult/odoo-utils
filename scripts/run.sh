#!/bin/bash

# Run Odoo server with configurable project
#
# Usage:
#   odoo-run                           # Start server with default config
#   odoo-run --conf <file.conf>        # Use custom config file
#   odoo-run --log                     # Log to file
#   odoo-run --                        # Pass args to odoo-bin
#
# Configuration comes from <git-root>/.odoo/.
#   ODOO_ROOT    - Odoo source root
#   DB_NAME      - Project database name
#   PYTHON_PATH  - Python venv bin directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

for arg in "$@"; do
    if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
        echo "Usage: odoo-run [--log] [--conf FILE] [-- ODOO_ARGS...]"
        exit 0
    fi
done

USE_LOGFILE=false
CUSTOM_CONF=""
ODOO_ARGS=()

while (($#)); do
    case "$1" in
        --conf)
            if (($# < 2)); then
                echo "Error: --conf requires a file path." >&2
                exit 2
            fi
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
            ODOO_ARGS+=("$1")
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

LOG_FILE="${LOG_FILE:-$ENV_DIR/${DB_NAME}.log}"

if [ "$USE_LOGFILE" = "true" ]; then
    rm -f "$LOG_FILE"
    "$ODOO_BIN" -c "$CONF_FILE" --logfile="$LOG_FILE" "${ODOO_ARGS[@]}"
else
    "$ODOO_BIN" -c "$CONF_FILE" "${ODOO_ARGS[@]}"
fi
