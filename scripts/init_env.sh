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
    [[ -f "$CONFIG_FILE" || -L "$ODOO_DIR" ]] || { echo "Error: missing $CONFIG_FILE." >&2; exit 1; }
    MAIN_WORKTREE="$(git worktree list --porcelain | awk '/^worktree / {print substr($0, 10); exit}')"
    POOL_PROJECT="$(python3 "$SCRIPT_DIR/config.py" json "$MAIN_WORKTREE/.odoo/config.toml" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("project") or {}).get("name") or "")')"
    POOL_PROJECT="${POOL_PROJECT:-$(basename "$MAIN_WORKTREE")}"
    # IBCorr worktrees use the primary checkout's .odoo. The database name comes from the
    # folder. Other projects still get a private worktree.toml and their own ports.
    if [[ "$POOL_PROJECT" == "ibcorr" || -L "$ODOO_DIR" ]]; then
        [[ "$MAIN_WORKTREE" != "$PROJECT_ROOT" ]] || { echo "Error: --worktree is for a linked worktree." >&2; exit 1; }
        if [[ -d "$ODOO_DIR" && ! -L "$ODOO_DIR" ]]; then
            extras="$(find "$ODOO_DIR" -mindepth 1 ! -name config.toml -print -quit)"
            if [[ -n "$extras" ]]; then
                echo "Error: $ODOO_DIR has local files besides config.toml ($extras)." >&2
                echo "Refusing to replace that folder. It must be a symlink to $MAIN_WORKTREE/.odoo." >&2
                exit 1
            fi
            git -C "$PROJECT_ROOT" update-index --skip-worktree .odoo/config.toml
            rm -rf "$ODOO_DIR"
        fi
        if [[ ! -e "$ODOO_DIR" ]]; then
            ln -s "$MAIN_WORKTREE/.odoo" "$ODOO_DIR"
        elif [[ -L "$ODOO_DIR" ]]; then
            [[ "$(readlink -f "$ODOO_DIR")" == "$(readlink -f "$MAIN_WORKTREE/.odoo")" ]] \
                || { echo "Error: $ODOO_DIR does not point at $MAIN_WORKTREE/.odoo." >&2; exit 1; }
        else
            echo "Error: $ODOO_DIR is not a symlink to $MAIN_WORKTREE/.odoo." >&2
            exit 1
        fi
        git -C "$PROJECT_ROOT" update-index --skip-worktree .odoo/config.toml || true
        if [[ -n "$WORKTREE_DB" ]]; then
            derived="$(python3 "$SCRIPT_DIR/config.py" shared-db "$PROJECT_ROOT")" || exit 1
            [[ "$WORKTREE_DB" == "$derived" ]] \
                || { echo "Error: this folder's database is $derived. Refusing --db $WORKTREE_DB." >&2; exit 1; }
        fi
        python3 "$SCRIPT_DIR/config.py" shared-db "$PROJECT_ROOT" >/dev/null || exit 1
        EXCLUDE_FILE="$(git rev-parse --git-path info/exclude)"
        grep -Fxq '/.odoo' "$EXCLUDE_FILE" 2>/dev/null || printf '%s\n' '/.odoo' >> "$EXCLUDE_FILE"
        if [[ -f "$MAIN_WORKTREE/PROJECT_RULES.md" ]]; then
            if [[ -e "$PROJECT_ROOT/PROJECT_RULES.md" && ! -L "$PROJECT_ROOT/PROJECT_RULES.md" ]]; then
                rm -f "$PROJECT_ROOT/PROJECT_RULES.md"
            fi
            if [[ ! -L "$PROJECT_ROOT/PROJECT_RULES.md" ]]; then
                ln -s "$MAIN_WORKTREE/PROJECT_RULES.md" "$PROJECT_ROOT/PROJECT_RULES.md"
            fi
        fi
        LINKER="$MAIN_WORKTREE/.odoo-sh-rules/scripts/link-repository"
        if [[ -x "$LINKER" ]]; then
            "$LINKER" "$PROJECT_ROOT" >/dev/null \
                || echo "Warning: could not link the agent rules into $PROJECT_ROOT; run: $LINKER $PROJECT_ROOT" >&2
            [[ -e "$PROJECT_ROOT/CLAUDE.md" || ! -e "$PROJECT_ROOT/AGENTS.md" ]] || ln -s AGENTS.md "$PROJECT_ROOT/CLAUDE.md"
        fi
        "$SCRIPT_DIR/filestore_link.sh" "$PROJECT_ROOT" \
            || echo "Warning: could not link the primary filestore; run: $SCRIPT_DIR/filestore_link.sh $PROJECT_ROOT" >&2
        echo "Worktree .odoo points at $MAIN_WORKTREE/.odoo"
        exit 0
    fi
    [[ -n "$WORKTREE_DB" ]] || { echo "Error: --worktree requires --db." >&2; exit 1; }
    # The project name selects the pool. assign takes the first free slot (or checks the given
    # one), refuses anything another checkout claims, and writes worktree.toml under the lock.
    ASSIGN_ARGS=(assign "$POOL_PROJECT" --root "$PROJECT_ROOT" --db "$WORKTREE_DB")
    if [[ -n "$WORKTREE_HTTP" ]]; then ASSIGN_ARGS+=(--http "$WORKTREE_HTTP"); fi
    if [[ -n "$WORKTREE_TEST" ]]; then ASSIGN_ARGS+=(--test-start "$WORKTREE_TEST"); fi
    python3 "$PORTS_PY" "${ASSIGN_ARGS[@]}" >/dev/null || exit 1
    if [[ "$MAIN_WORKTREE" != "$PROJECT_ROOT" && -f "$MAIN_WORKTREE/.odoo/secrets.env" ]]; then
        ln -sfn "$MAIN_WORKTREE/.odoo/secrets.env" "$SECRETS_FILE"
    fi
    # The agent-rules overlay (AGENTS.md, PROJECT_RULES.md, .odoo-sh-rules) is untracked and
    # ignored, so `git worktree add` does not bring it. Install it from the primary checkout.
    # PROJECT_RULES.md is a symlink to the primary file. The worktree does not get a copy.
    LINKER="$MAIN_WORKTREE/.odoo-sh-rules/scripts/link-repository"
    if [[ "$MAIN_WORKTREE" != "$PROJECT_ROOT" && -x "$LINKER" && -f "$MAIN_WORKTREE/PROJECT_RULES.md" ]]; then
        if [[ ! -e "$PROJECT_ROOT/PROJECT_RULES.md" ]]; then
            ln -s "$MAIN_WORKTREE/PROJECT_RULES.md" "$PROJECT_ROOT/PROJECT_RULES.md"
        fi
        "$LINKER" "$PROJECT_ROOT" >/dev/null \
            || echo "Warning: could not link the agent rules into $PROJECT_ROOT; run: $LINKER $PROJECT_ROOT" >&2
        [[ -e "$PROJECT_ROOT/CLAUDE.md" || ! -e "$PROJECT_ROOT/AGENTS.md" ]] || ln -s AGENTS.md "$PROJECT_ROOT/CLAUDE.md"
    fi
    # Share the primary checkout's filestore by symlink; never copy it.
    "$SCRIPT_DIR/filestore_link.sh" "$PROJECT_ROOT" \
        || echo "Warning: could not link the primary filestore; run: $SCRIPT_DIR/filestore_link.sh $PROJECT_ROOT" >&2
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
