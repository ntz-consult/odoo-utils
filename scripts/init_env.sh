#!/bin/bash
# Create the repository-root .odoo runtime or an explicit worktree allocation.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: odoo-init-env [--conf-only]"
    echo "       odoo-init-env --worktree --db NAME [--http-port PORT] [--test-range-start PORT]"
    echo ""
    echo "With a port register (scripts/ports.py) --worktree takes the first free slot of"
    echo "the project's pool when --http-port is omitted, and refuses ports outside it."
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
mkdir -p "$ODOO_DIR"

if [[ "$WORKTREE" == true ]]; then
    [[ -f "$CONFIG_FILE" ]] || { echo "Error: missing $CONFIG_FILE." >&2; exit 1; }
    [[ -n "$WORKTREE_DB" ]] || { echo "Error: --worktree requires --db." >&2; exit 1; }
    PORTS_PY="$SCRIPT_DIR/ports.py"
    WORKTREE_GEVENT=""
    REGISTER_STATUS=0
    python3 "$PORTS_PY" active >/dev/null || REGISTER_STATUS=$?
    if ((REGISTER_STATUS != 0 && REGISTER_STATUS != 3)); then
        echo "Error: the port register could not be read." >&2
        exit 1
    fi
    if ((REGISTER_STATUS == 0)); then
        # Port register in use: ports come from (and must stay inside) the project's pool.
        POOL_PROJECT="$(python3 "$SCRIPT_DIR/config.py" json "$CONFIG_FILE" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("project") or {}).get("name") or "")')"
        POOL_PROJECT="${POOL_PROJECT:-$(basename "$PROJECT_ROOT")}"
        if [[ -n "$WORKTREE_HTTP" ]]; then
            SLOT="$(python3 "$PORTS_PY" slot "$POOL_PROJECT" --http "$WORKTREE_HTTP")" || exit 1
        else
            SLOT="$(python3 "$PORTS_PY" allocate "$POOL_PROJECT" --root "$PROJECT_ROOT")" || exit 1
        fi
        eval "$SLOT"
        if [[ -n "$WORKTREE_TEST" && "$WORKTREE_TEST" != "$test_start" ]]; then
            echo "Error: port $http uses test ports $test_start-$test_end in the register, not $WORKTREE_TEST." >&2
            exit 1
        fi
        WORKTREE_HTTP="$http"
        WORKTREE_GEVENT="$gevent"
        WORKTREE_TEST="$test_start"
        TEST_END="$test_end"
        python3 "$PORTS_PY" check "$POOL_PROJECT" --root "$PROJECT_ROOT" --http "$WORKTREE_HTTP" \
            --gevent "$WORKTREE_GEVENT" --test "$WORKTREE_TEST" "$TEST_END" || exit 1
    else
        [[ -n "$WORKTREE_HTTP" && -n "$WORKTREE_TEST" ]] || {
            echo "Error: without a port register --worktree requires --http-port and --test-range-start." >&2; exit 1;
        }
        TEST_END=$((WORKTREE_TEST + 101))
    fi
    TEST_GEVENT=$((WORKTREE_TEST + 1))
    {
        printf '[database]\nname = "%s"\n\n[ports]\nhttp = %s\n' "$WORKTREE_DB" "$WORKTREE_HTTP"
        [[ -n "$WORKTREE_GEVENT" ]] && printf 'gevent = %s\n' "$WORKTREE_GEVENT"
        printf 'test_http = %s\ntest_gevent = %s\ntest_range_start = %s\ntest_range_end = %s\n' \
            "$WORKTREE_TEST" "$TEST_GEVENT" "$WORKTREE_TEST" "$TEST_END"
    } > "$WORKTREE_FILE"
    cat >> "$WORKTREE_FILE" <<EOF

[targets.local]
url = "http://127.0.0.1:$WORKTREE_HTTP"
database = "$WORKTREE_DB"
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
