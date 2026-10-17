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

# Ports given on the command line win over the configuration; check what Odoo will bind.
RUN_HTTP_PORT="$HTTP_PORT"
RUN_GEVENT_PORT="${GEVENT_PORT:-}"
for ((i = 0; i < ${#ODOO_ARGS[@]}; i++)); do
    case "${ODOO_ARGS[$i]}" in
        -p|--http-port) RUN_HTTP_PORT="${ODOO_ARGS[$((i + 1))]:-}" ;;
        --http-port=*) RUN_HTTP_PORT="${ODOO_ARGS[$i]#*=}" ;;
        --gevent-port|--longpolling-port) RUN_GEVENT_PORT="${ODOO_ARGS[$((i + 1))]:-}" ;;
        --gevent-port=*|--longpolling-port=*) RUN_GEVENT_PORT="${ODOO_ARGS[$i]#*=}" ;;
    esac
done
if [[ -n "$CUSTOM_CONF" && "$RUN_HTTP_PORT" == "$HTTP_PORT" ]]; then
    conf_port="$(sed -n 's/^[[:space:]]*http_port[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$CONF_FILE" | tail -1)"
    [[ -n "$conf_port" ]] && RUN_HTTP_PORT="$conf_port"
fi
if ! [[ "$RUN_HTTP_PORT" =~ ^[0-9]+$ ]]; then
    echo "Error: invalid http port '$RUN_HTTP_PORT'." >&2
    exit 2
fi
odoo_enforce_port_pool "$RUN_HTTP_PORT" "$RUN_GEVENT_PORT" || exit 1

# Record the ports Odoo will bind in the shared reservation register. The gevent
# port is bound only with workers > 0, so it is recorded only when workers are requested.
RESERVE_PORTS=("$RUN_HTTP_PORT")
for ((i = 0; i < ${#ODOO_ARGS[@]}; i++)); do
    case "${ODOO_ARGS[$i]}" in
        --workers) [[ "${ODOO_ARGS[$((i + 1))]:-0}" != 0 && -n "$RUN_GEVENT_PORT" ]] && RESERVE_PORTS+=("$RUN_GEVENT_PORT") ;;
        --workers=*) [[ "${ODOO_ARGS[$i]#*=}" != 0 && -n "$RUN_GEVENT_PORT" ]] && RESERVE_PORTS+=("$RUN_GEVENT_PORT") ;;
    esac
done
odoo_reserve_ports "Odoo server for ${DB_NAME} (odoo-run)" "${ODOO_PORT_OWNER:-odoo-${DB_NAME}}" "${RESERVE_PORTS[@]}" || exit 1

# Worktrees use the primary checkout's filestore through a symlink (never a copy); check/repair it.
source "$SCRIPT_DIR/filestore_link.sh"
odoo_link_main_filestore "$PROJECT_ROOT" || echo "Warning: could not link the primary filestore; images/assets may break." >&2

LOG_FILE="${LOG_FILE:-$ENV_DIR/${DB_NAME}.log}"
echo "Test URL (give Gerhard this, never a local port): http://solomon:${RUN_HTTP_PORT} (fallback http://100.105.180.75:${RUN_HTTP_PORT}); stop it when done" >&2

if [ "$USE_LOGFILE" = "true" ]; then
    rm -f "$LOG_FILE"
    "$ODOO_BIN" -c "$CONF_FILE" --logfile="$LOG_FILE" "${ODOO_ARGS[@]}"
else
    "$ODOO_BIN" -c "$CONF_FILE" "${ODOO_ARGS[@]}"
fi
