#!/bin/bash
# Create the repository-root .odoo runtime or an explicit worktree allocation.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: odoo-init-env [--conf-only]"
    echo "       odoo-init-env --worktree --db NAME --http-port PORT --test-range-start PORT"
}

CONF_ONLY=false
WORKTREE=false
WORKTREE_DB=""
WORKTREE_HTTP=""
WORKTREE_TEST=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --conf-only) CONF_ONLY=true; shift ;;
        --worktree) WORKTREE=true; shift ;;
        --db) WORKTREE_DB="$2"; shift 2 ;;
        --http-port) WORKTREE_HTTP="$2"; shift 2 ;;
        --test-range-start) WORKTREE_TEST="$2"; shift 2 ;;
        *) echo "Error: unknown option '$1'." >&2; usage; exit 1 ;;
    esac
done

PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "Error: run inside a Git worktree." >&2; exit 1; }
ODOO_DIR="$PROJECT_ROOT/.odoo"
CONFIG_FILE="$ODOO_DIR/config.yaml"
SECRETS_FILE="$ODOO_DIR/secrets.env"
WORKTREE_FILE="$ODOO_DIR/worktree.yaml"
mkdir -p "$ODOO_DIR"

if [[ "$WORKTREE" == true ]]; then
    [[ -f "$CONFIG_FILE" ]] || { echo "Error: missing $CONFIG_FILE." >&2; exit 1; }
    [[ -n "$WORKTREE_DB" && -n "$WORKTREE_HTTP" && -n "$WORKTREE_TEST" ]] || {
        echo "Error: --worktree requires --db, --http-port, and --test-range-start." >&2; exit 1;
    }
    TEST_GEVENT=$((WORKTREE_TEST + 1))
    TEST_END=$((WORKTREE_TEST + 101))
    cat > "$WORKTREE_FILE" <<EOF
database:
  name: $WORKTREE_DB
ports:
  http: $WORKTREE_HTTP
  test_http: $WORKTREE_TEST
  test_gevent: $TEST_GEVENT
  test_range_start: $WORKTREE_TEST
  test_range_end: $TEST_END
targets:
  local:
    url: http://127.0.0.1:$WORKTREE_HTTP
    database: $WORKTREE_DB
EOF
    MAIN_WORKTREE="$(git worktree list --porcelain | awk '/^worktree / {print substr($0, 10); exit}')"
    if [[ "$MAIN_WORKTREE" != "$PROJECT_ROOT" && -f "$MAIN_WORKTREE/.odoo/secrets.env" ]]; then
        ln -sfn "$MAIN_WORKTREE/.odoo/secrets.env" "$SECRETS_FILE"
    fi
    echo "Created explicit worktree allocation: $WORKTREE_FILE"
    exit 0
fi

if [[ "$CONF_ONLY" != true && ! -f "$CONFIG_FILE" ]]; then
    NAME="$(basename "$PROJECT_ROOT")"
    cat > "$CONFIG_FILE" <<EOF
version: 1

# Policy values: allow runs, ask previews for approval, deny refuses.
project:
  name: $NAME
odoo:
  root: /home/gdt/Odoo/V19
  data_dir: $ODOO_DIR/data
database:
  name: $NAME
  port: 5432
  user: odoo
ports:
  http: 8096
  test_http: 9096
  test_gevent: 9097
  test_range_start: 9096
  test_range_end: 9197
tags:
  develop:
    read: allow
    create: allow
    write: allow
    unlink: ask
    exec: ask
targets:
  local:
    odoo_version: 19
    url: http://127.0.0.1:8096
    database: $NAME
    tags: [develop]
EOF
fi

touch "$SECRETS_FILE"
chmod 600 "$SECRETS_FILE"
EXCLUDE_FILE="$(git rev-parse --git-path info/exclude)"
for pattern in /.odoo/secrets.env /.odoo/worktree.yaml /.odoo/dump.sql /.odoo/odoo.conf '/.odoo/*.log' /.odoo/data/; do
    grep -Fxq "$pattern" "$EXCLUDE_FILE" 2>/dev/null || printf '%s\n' "$pattern" >> "$EXCLUDE_FILE"
done

cd "$PROJECT_ROOT"
source "$SCRIPT_DIR/common.sh"
echo "Odoo configuration ready: $CONFIG_FILE"
