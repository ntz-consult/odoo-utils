#!/bin/bash
# odoo-upgrade MODULE[,MODULE...] [-- extra odoo-bin args]
# Updates modules in this project's dev DB (-u ... --stop-after-init) and FAILS
# (non-zero) if odoo-bin exits non-zero OR the log shows ERROR/CRITICAL,
# a DB connection loss, or a registry load failure. Log: .odoo/upgrade-<ts>.log
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
[[ $# -ge 1 && "$1" != -* ]] || { echo "Usage: odoo-upgrade MODULE[,MODULE...] [-- ODOO_ARGS...]" >&2; exit 2; }
MODS="$1"; shift; [[ "${1:-}" == "--" ]] && shift
LOG="$ENV_DIR/upgrade-$(date +%Y%m%d-%H%M%S).log"
echo "Updating $MODS in $DB_NAME ($DB_HOST:$DB_PORT); log: $LOG"
start=$(date +%s); set +e
"$PYTHON_PATH/python" "$ODOO_BIN" -c "$CONF_FILE" -u "$MODS" --stop-after-init --http-port=0 "$@" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}; set -e
bad=$(grep -cE ' (ERROR|CRITICAL) |OperationalError|InterfaceError|server closed the connection|Failed to load registry' "$LOG" || true)
echo "odoo-bin exit=$rc, error lines=$bad, $(( $(date +%s)-start ))s"
if [[ $rc -ne 0 || $bad -gt 0 ]]; then echo "UPGRADE FAILED" >&2; exit $(( rc ? rc : 1 )); fi
echo "UPGRADE OK"
