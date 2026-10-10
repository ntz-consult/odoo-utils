#!/bin/bash
# Shared runtime resolver for the global Odoo commands.

set -euo pipefail

ODOO_MANAGED_CONF_KEYS=(
    addons_path bin_path data_dir db_host db_name db_password db_port db_user
    gevent_port http_interface http_port list_db log_level proxy_mode
)

odoo_help_requested() {
    local arg
    for arg in "$@"; do
        [[ "$arg" == "-h" || "$arg" == "--help" ]] && return 0
    done
    return 1
}

odoo_resolve_project() {
    local start_dir="${1:-$PWD}"
    if ! PROJECT_ROOT="$(git -C "$start_dir" rev-parse --show-toplevel 2>/dev/null)"; then
        echo "Error: run this command inside a Git worktree." >&2
        return 1
    fi
    ODOO_CONFIG_DIR="$PROJECT_ROOT/.odoo"
    ODOO_CONFIG_FILE="$ODOO_CONFIG_DIR/config.toml"
    ODOO_SECRETS_FILE="$ODOO_CONFIG_DIR/secrets.env"
    ODOO_WORKTREE_FILE="$ODOO_CONFIG_DIR/worktree.toml"
    ENV_DIR="$ODOO_CONFIG_DIR"
    ENV_FILE="$ODOO_SECRETS_FILE"
    CONF_FILE="$ODOO_CONFIG_DIR/odoo.conf"
    CONF_LOCAL_FILE="$ODOO_CONFIG_DIR/odoo.conf.local"
    export PROJECT_ROOT ODOO_CONFIG_DIR ODOO_CONFIG_FILE ODOO_SECRETS_FILE
    export ODOO_WORKTREE_FILE ENV_DIR ENV_FILE CONF_FILE CONF_LOCAL_FILE
}

odoo_load_env() {
    local required="${1:-true}"
    local resolved_root="$PROJECT_ROOT" loader
    loader="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.py"
    if [[ ! -f "$ODOO_CONFIG_FILE" ]]; then
        if [[ -f "$ODOO_CONFIG_DIR/config.yaml" ]]; then
            echo "Error: found $ODOO_CONFIG_DIR/config.yaml; rename it to config.toml. Odoo commands now read TOML, not YAML." >&2
            return 1
        fi
        if [[ "$required" == true ]]; then
            echo "Error: project runtime configuration not found: $ODOO_CONFIG_FILE" >&2
            echo "Run 'odoo-init-env' anywhere in this worktree." >&2
            return 1
        fi
        return 0
    fi

    # The TOML is portable and committed. The optional worktree file contains
    # explicit local database and port overrides. Credentials stay ignored.
    eval "$(python3 "$loader" shell "$ODOO_CONFIG_FILE" "$ODOO_WORKTREE_FILE")"
    if [[ -f "$ODOO_SECRETS_FILE" ]]; then
        set -a
        # shellcheck disable=SC1090
        source "$ODOO_SECRETS_FILE"
        set +a
    fi

    # Repository identity is derived and cannot be overridden by .env.
    PROJECT_ROOT="$resolved_root"
    ODOO_CONFIG_DIR="$PROJECT_ROOT/.odoo"
    ODOO_CONFIG_FILE="$ODOO_CONFIG_DIR/config.toml"
    ODOO_SECRETS_FILE="$ODOO_CONFIG_DIR/secrets.env"
    ODOO_WORKTREE_FILE="$ODOO_CONFIG_DIR/worktree.toml"
    ENV_DIR="$ODOO_CONFIG_DIR"
    ENV_FILE="$ODOO_SECRETS_FILE"
    CONF_FILE="$ODOO_CONFIG_DIR/odoo.conf"
    CONF_LOCAL_FILE="$ODOO_CONFIG_DIR/odoo.conf.local"

    PYTHON_PATH="${PYTHON_PATH:-$PROJECT_ROOT/.venv/bin}"
    HTTP_PORT="${HTTP_PORT:-8096}"
    TEST_HTTP_PORT="${TEST_HTTP_PORT:-$((HTTP_PORT + 1000))}"
    TEST_GEVENT_PORT="${TEST_GEVENT_PORT:-$((TEST_HTTP_PORT + 1))}"
    TEST_PORT_RANGE_START="${TEST_PORT_RANGE_START:-$TEST_HTTP_PORT}"
    TEST_PORT_RANGE_END="${TEST_PORT_RANGE_END:-$((TEST_PORT_RANGE_START + 101))}"
    BIN_PATH="${BIN_PATH:-/usr/local/bin}"
    ODOO_DATA_DIR="${ODOO_DATA_DIR:-$ENV_DIR/odoo-data}"
    ODOO_HTTP_INTERFACE="${ODOO_HTTP_INTERFACE:-0.0.0.0}"
    ODOO_LIST_DB="${ODOO_LIST_DB:-False}"
    ODOO_PROXY_MODE="${ODOO_PROXY_MODE:-False}"
    ODOO_LOG_LEVEL="${ODOO_LOG_LEVEL:-info}"
    LOG_FILE="${LOG_FILE:-$ENV_DIR/${DB_NAME:-$(basename "$PROJECT_ROOT")}.log}"
    # Port pools (scripts/ports.py): the project name selects the pool, and the
    # second (gevent/websocket) port follows from the http port when a register exists.
    ODOO_PORTS_PROJECT="${PROJECT_NAME:-$(basename "$PROJECT_ROOT")}"
    if [[ -z "${GEVENT_PORT:-}" ]]; then
        GEVENT_PORT="$(python3 "$(dirname "$loader")/ports.py" gevent "$ODOO_PORTS_PROJECT" --http "$HTTP_PORT" 2>/dev/null || true)"
    fi

    export PROJECT_ROOT ODOO_CONFIG_DIR ODOO_CONFIG_FILE ODOO_SECRETS_FILE
    export ODOO_WORKTREE_FILE ENV_DIR ENV_FILE CONF_FILE CONF_LOCAL_FILE
    export PYTHON_PATH HTTP_PORT TEST_HTTP_PORT TEST_GEVENT_PORT
    export TEST_PORT_RANGE_START TEST_PORT_RANGE_END BIN_PATH ODOO_DATA_DIR
    export ODOO_HTTP_INTERFACE ODOO_LIST_DB ODOO_PROXY_MODE ODOO_LOG_LEVEL
    export LOG_FILE ODOO_PORTS_PROJECT GEVENT_PORT
    export PATH="$PYTHON_PATH:$PATH"
}

odoo_conf_key_is_managed() {
    local candidate="${1,,}" key
    for key in "${ODOO_MANAGED_CONF_KEYS[@]}"; do
        [[ "$candidate" == "$key" ]] && return 0
    done
    return 1
}

odoo_append_local_conf() {
    local destination="$1" line key value section_seen=false line_number=0
    [[ -f "$CONF_LOCAL_FILE" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line_number=$((line_number + 1))
        line="${line%$'\r'}"
        [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*[\;#] ]] && continue
        if [[ "$line" =~ ^[[:space:]]*\[options\][[:space:]]*$ ]]; then
            section_seen=true
            continue
        fi
        if [[ "$line" =~ ^[[:space:]]*\[.*\][[:space:]]*$ ]]; then
            echo "Error: $CONF_LOCAL_FILE supports only an [options] section (line $line_number)." >&2
            return 1
        fi
        if [[ "$section_seen" != true || "$line" != *"="* ]]; then
            echo "Error: invalid entry in $CONF_LOCAL_FILE at line $line_number." >&2
            return 1
        fi
        key="${line%%=*}"
        value="${line#*=}"
        key="$(printf '%s' "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        if odoo_conf_key_is_managed "$key"; then
            echo "Error: $CONF_LOCAL_FILE may not override managed key '$key'." >&2
            return 1
        fi
        printf '%s =%s\n' "$key" "$value" >> "$destination"
    done < "$CONF_LOCAL_FILE"
    if [[ "$section_seen" != true ]]; then
        echo "Error: $CONF_LOCAL_FILE must contain an [options] section." >&2
        return 1
    fi
}

odoo_render_conf() {
    local temp_conf previous_umask
    mkdir -p -- "$ENV_DIR"
    previous_umask="$(umask)"
    umask 077
    temp_conf="$(mktemp "$ENV_DIR/.odoo.conf.XXXXXX")"
    {
        printf '[options]\n'
        printf 'http_interface = %s\n' "$ODOO_HTTP_INTERFACE"
        printf 'http_port = %s\n' "$HTTP_PORT"
        [[ -n "${GEVENT_PORT:-}" ]] && printf 'gevent_port = %s\n' "$GEVENT_PORT"
        [[ -n "${DB_HOST:-}" ]] && printf 'db_host = %s\n' "$DB_HOST"
        [[ -n "${DB_PORT:-}" ]] && printf 'db_port = %s\n' "$DB_PORT"
        [[ -n "${DB_USER:-}" ]] && printf 'db_user = %s\n' "$DB_USER"
        [[ -n "${DB_PASSWORD:-}" ]] && printf 'db_password = %s\n' "$DB_PASSWORD"
        printf 'db_name = %s\n' "$DB_NAME"
        printf 'addons_path = %s/odoo/addons,%s/enterprise,%s/themes,%s\n' \
            "$ODOO_ROOT" "$ODOO_ROOT" "$ODOO_ROOT" "$PROJECT_ROOT"
        printf 'data_dir = %s\n' "$ODOO_DATA_DIR"
        printf 'list_db = %s\n' "$ODOO_LIST_DB"
        printf 'proxy_mode = %s\n' "$ODOO_PROXY_MODE"
        printf 'log_level = %s\n' "$ODOO_LOG_LEVEL"
        printf 'bin_path = %s\n' "$BIN_PATH"
    } > "$temp_conf"
    if ! odoo_append_local_conf "$temp_conf"; then
        rm -f -- "$temp_conf"
        umask "$previous_umask"
        return 1
    fi
    chmod 600 "$temp_conf"
    mv -f -- "$temp_conf" "$CONF_FILE"
    umask "$previous_umask"
}

odoo_require_local_runtime() {
    : "${ODOO_ROOT:?Missing odoo.root in $ODOO_CONFIG_FILE}"
    : "${DB_NAME:?Missing database.name in $ODOO_CONFIG_FILE}"
    ODOO_BIN="${ODOO_ROOT}/odoo/odoo-bin"
    export ODOO_BIN
    if [[ ! -f "$ODOO_BIN" ]]; then
        echo "Error: odoo-bin not found: $ODOO_BIN" >&2
        echo "Check odoo.root in $ODOO_CONFIG_FILE." >&2
        return 1
    fi
    odoo_render_conf
}

# Refuse ports outside this project's pool in the port register (scripts/ports.py).
# Usage: odoo_enforce_port_pool HTTP [GEVENT] [TEST_START TEST_END]
# Does nothing when no register is in use.
odoo_enforce_port_pool() {
    local http="$1" gevent="${2:-}" test_start="${3:-}" test_end="${4:-}" args
    args=(check "$ODOO_PORTS_PROJECT" --root "$PROJECT_ROOT" --http "$http")
    [[ -n "$gevent" ]] && args+=(--gevent "$gevent")
    [[ -n "$test_start" && -n "$test_end" ]] && args+=(--test "$test_start" "$test_end")
    if ! python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ports.py" "${args[@]}"; then
        echo "Refusing to start Odoo for project '$ODOO_PORTS_PROJECT' in $PROJECT_ROOT." >&2
        return 1
    fi
}

odoo_bootstrap() {
    local mode="${1:-local}"
    odoo_resolve_project "$PWD"
    case "$mode" in
        init) mkdir -p -- "$ENV_DIR" ;;
        project) odoo_load_env false ;;
        remote) odoo_load_env true ;;
        local) odoo_load_env true; odoo_require_local_runtime ;;
        *) echo "Error: unknown Odoo runtime mode '$mode'." >&2; return 1 ;;
    esac
}

# Existing wrappers source common.sh and expect a ready runtime. Commands that
# need another mode set ODOO_RUNTIME_MODE before sourcing it.
if odoo_help_requested "$@"; then
    PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
    ODOO_CONFIG_DIR="${ODOO_CONFIG_DIR:-$PROJECT_ROOT/.odoo}"
    ODOO_CONFIG_FILE="${ODOO_CONFIG_FILE:-$ODOO_CONFIG_DIR/config.toml}"
    ODOO_SECRETS_FILE="${ODOO_SECRETS_FILE:-$ODOO_CONFIG_DIR/secrets.env}"
    ODOO_WORKTREE_FILE="${ODOO_WORKTREE_FILE:-$ODOO_CONFIG_DIR/worktree.toml}"
    ENV_DIR="${ENV_DIR:-$ODOO_CONFIG_DIR}"
    ENV_FILE="${ENV_FILE:-$ODOO_SECRETS_FILE}"
    CONF_FILE="${CONF_FILE:-$ODOO_CONFIG_DIR/odoo.conf}"
    DB_NAME="${DB_NAME:-database}"
    ODOO_ROOT="${ODOO_ROOT:-}"
    PYTHON_PATH="${PYTHON_PATH:-$PROJECT_ROOT/.venv/bin}"
    HTTP_PORT="${HTTP_PORT:-8096}"
    TEST_HTTP_PORT="${TEST_HTTP_PORT:-9096}"
    TEST_GEVENT_PORT="${TEST_GEVENT_PORT:-9097}"
else
    odoo_bootstrap "${ODOO_RUNTIME_MODE:-local}"
fi
