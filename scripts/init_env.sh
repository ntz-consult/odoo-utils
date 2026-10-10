#!/bin/bash
# Create the repository-root .odoo runtime or an explicit worktree allocation.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: odoo-init-env [--conf-only]"
    echo "       odoo-init-env --worktree --db NAME [--http-port PORT] [--test-range-start PORT]"
    echo ""
    echo "A linked worktree (git worktree add) must be allocated with --worktree; plain"
    echo "odoo-init-env refuses it so that it never inherits the primary checkout's ports."
    echo "With a port register (scripts/ports.py) --worktree takes the first free slot of"
    echo "the project's pool when --http-port is omitted, and refuses ports outside it."
    echo "Allocation runs under the port lock, so two worktrees never receive the same port."
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
CONFIG_FILE="$ODOO_DIR/config.toml"
SECRETS_FILE="$ODOO_DIR/secrets.env"
WORKTREE_FILE="$ODOO_DIR/worktree.toml"
PORTS_PY="$SCRIPT_DIR/ports.py"

# A linked worktree without its own ports must not get a config.toml that falls back to the
# primary checkout's ports. Allocate it first: odoo-init-env --worktree --db NAME.
if [[ "$WORKTREE" != true ]] && ! python3 "$PORTS_PY" guard --root "$PROJECT_ROOT"; then
    echo "Refusing to write Odoo configuration in linked worktree $PROJECT_ROOT." >&2
    exit 1
fi
mkdir -p "$ODOO_DIR"

if [[ "$WORKTREE" == true ]]; then
    [[ -f "$CONFIG_FILE" ]] || { echo "Error: missing $CONFIG_FILE." >&2; exit 1; }
    [[ -n "$WORKTREE_DB" ]] || { echo "Error: --worktree requires --db." >&2; exit 1; }
    # The project name selects the pool. assign takes the first free slot (or checks the given
    # one), refuses anything another checkout claims, and writes worktree.toml under the lock.
    POOL_PROJECT="$(python3 "$SCRIPT_DIR/config.py" json "$CONFIG_FILE" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("project") or {}).get("name") or "")')"
    POOL_PROJECT="${POOL_PROJECT:-$(basename "$PROJECT_ROOT")}"
    ASSIGN_ARGS=(assign "$POOL_PROJECT" --root "$PROJECT_ROOT" --db "$WORKTREE_DB")
    if [[ -n "$WORKTREE_HTTP" ]]; then ASSIGN_ARGS+=(--http "$WORKTREE_HTTP"); fi
    if [[ -n "$WORKTREE_TEST" ]]; then ASSIGN_ARGS+=(--test-start "$WORKTREE_TEST"); fi
    python3 "$PORTS_PY" "${ASSIGN_ARGS[@]}" >/dev/null || exit 1
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
version = 1

# Policy values: allow runs, ask previews for approval, deny refuses.

[project]
name = "$NAME"

[odoo]
root = "$HOME/Odoo/V19"
data_dir = "$ODOO_DIR/data"

[database]
name = "$NAME"
port = 5432
user = "odoo"

[ports]
http = 8096
test_http = 9096
test_gevent = 9097
test_range_start = 9096
test_range_end = 9197

[tags.develop]
read = "allow"
create = "allow"
write = "allow"
unlink = "ask"
exec = "ask"

[targets.local]
odoo_version = 19
url = "http://127.0.0.1:8096"
database = "$NAME"
tags = ["develop"]
EOF
fi

touch "$SECRETS_FILE"
chmod 600 "$SECRETS_FILE"
EXCLUDE_FILE="$(git rev-parse --git-path info/exclude)"
for pattern in /.odoo/secrets.env /.odoo/worktree.toml /.odoo/dump.sql /.odoo/odoo.conf '/.odoo/*.log' /.odoo/data/; do
    grep -Fxq "$pattern" "$EXCLUDE_FILE" 2>/dev/null || printf '%s\n' "$pattern" >> "$EXCLUDE_FILE"
done

cd "$PROJECT_ROOT"
source "$SCRIPT_DIR/common.sh"
echo "Odoo configuration ready: $CONFIG_FILE"
